"""
Kemory — Chat content classifier (chats-v1 inbox).

Given a chat sitting in ``kora:inbox:<platform>`` (or any other holding
area), suggest which existing namespace it belongs to based on the
chat's CONTENT — embeddings over the first N turns vs each known
namespace's representative text.

This is intentionally a *suggester*, not an auto-router. The user (or
a future background task) decides whether to act on suggestions.
Auto-classification would risk silently misfiling chats; the user
explicitly asked for "a temp location until we know where to put it"
which implies explicit movement.

Algorithm:
  1. Fetch up to ``MAX_TURNS`` of the chat ordered by sequence; cap
     concatenated text at ``MAX_CHARS`` (cheap embed, ~few k tokens).
  2. Embed it via the shared bge-small-en-v1.5 encoder.
  3. Build candidate namespaces for this user (memory + chat namespaces),
     skipping the chat's own current namespace and any ``kora:inbox:*``.
  4. For each candidate, build a representative text:
       * NamespacePolicy.consolidated_summary if non-empty (best signal)
       * else NamespacePolicy.description
       * else the namespace name itself
  5. Embed each, compute cosine, sort, return top-N along with the
     signal source so the caller can show "based on summary" vs
     "based on name" badges in the UI.

If the encoder is unavailable (model not loaded, no candidates with
text), we fall back to returning all candidate namespaces with
similarity=0 so the dashboard can still surface the list for manual
selection.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass

from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.ai_chat import AIChat, AIChatTurn
from backend.models.memory import Memory
from backend.models.namespace_policy import NamespacePolicy

logger = logging.getLogger(__name__)

# Soft caps. Picked to keep a typical encoder pass under ~50ms on CPU.
MAX_TURNS = 12
MAX_CHARS = 4_000

INBOX_PREFIX = "kora:inbox:"


# ─── Response shapes ─────────────────────────────────────────────────


class NamespaceSuggestion(BaseModel):
    """One candidate destination namespace for a chat."""

    namespace: str
    similarity: float = Field(..., description="Cosine similarity (0..1). 0 when no signal.")
    signal: str = Field(
        ...,
        description=(
            "What we compared against: 'summary' (NamespacePolicy.consolidated_summary), "
            "'description' (NamespacePolicy.description), or 'name' (the namespace string)."
        ),
    )
    memory_count: int = Field(default=0, description="Active memories in that namespace.")
    chat_count: int = Field(default=0, description="Active chats currently in that namespace.")


class ChatClassifyResponse(BaseModel):
    """Top-N namespace suggestions for a chat."""

    chat_id: str
    current_namespace: str
    in_inbox: bool
    sample_chars: int = Field(..., description="Bytes of chat content actually fed to the embedder.")
    suggestions: list[NamespaceSuggestion]
    fallback: bool = Field(
        default=False,
        description="True when the encoder was unavailable; suggestions are unranked.",
    )


# ─── Internals ──────────────────────────────────────────────────────


@dataclass
class _Candidate:
    namespace: str
    representative_text: str
    signal: str  # 'summary' | 'description' | 'name'
    memory_count: int = 0
    chat_count: int = 0


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _embed(text: str):
    """Lazy import to keep this module light when the encoder is unused."""
    from kemory.embeddings.encoder import encode

    return encode(text)


async def _load_chat_sample(
    chat: AIChat,
    db: AsyncSession,
) -> str:
    """Return a single string with the first MAX_TURNS turns concatenated,
    capped at MAX_CHARS. Includes role hints so the encoder sees structure."""
    rows = (
        await db.execute(
            select(AIChatTurn)
            .where(AIChatTurn.chat_id == chat.chat_id)
            .order_by(AIChatTurn.sequence.asc())
            .limit(MAX_TURNS)
        )
    ).scalars().all()

    pieces: list[str] = []
    used = 0
    title = (chat.title or "").strip()
    if title:
        pieces.append(f"Title: {title}")
        used += len(title) + 7
    for t in rows:
        snippet = (t.content or "").strip()
        if not snippet:
            continue
        line = f"{t.role}: {snippet}"
        # Respect MAX_CHARS — truncate mid-turn rather than overshoot the
        # encoder's input window.
        remaining = MAX_CHARS - used
        if remaining <= 0:
            break
        if len(line) > remaining:
            line = line[:remaining]
        pieces.append(line)
        used += len(line) + 1
    return "\n".join(pieces)


async def _gather_candidates(
    user_id: uuid.UUID,
    exclude_namespace: str,
    db: AsyncSession,
) -> list[_Candidate]:
    """Build the list of destination candidates the suggester ranks.

    Pulled from:
      * NamespacePolicy rows owned by this user (best signals)
      * Memory.namespace distinct values for this user (fallback to name)
      * AIChat.namespace distinct values for this user (fallback to name)

    Skips the chat's current namespace and any ``kora:inbox:*`` bucket —
    suggesting "move to your inbox" or "move to the bucket you're in"
    would be useless.
    """
    # Per-user namespace policies (carry summary/description).
    policy_rows = (
        await db.execute(
            select(
                NamespacePolicy.namespace,
                NamespacePolicy.description,
                NamespacePolicy.consolidated_summary,
            ).where(
                or_(
                    NamespacePolicy.created_by == user_id,
                    NamespacePolicy.created_by.is_(None),
                )
            )
        )
    ).all()

    # Distinct namespaces from memories + chats for this user (some won't
    # have a NamespacePolicy yet; we still want them as candidates).
    mem_rows = (
        await db.execute(
            select(Memory.namespace)
            .where(Memory.user_id == user_id, Memory.invalid_at.is_(None))
            .group_by(Memory.namespace)
        )
    ).all()
    chat_rows = (
        await db.execute(
            select(AIChat.namespace)
            .where(AIChat.user_id == user_id, AIChat.invalid_at.is_(None))
            .group_by(AIChat.namespace)
        )
    ).all()

    # Build a single dict keyed by namespace name; later sources don't
    # overwrite earlier (policy data is best).
    by_ns: dict[str, _Candidate] = {}
    for ns, desc, summary in policy_rows:
        if not ns or ns == exclude_namespace or ns.startswith(INBOX_PREFIX):
            continue
        if summary:
            by_ns[ns] = _Candidate(ns, summary, "summary")
        elif desc:
            by_ns[ns] = _Candidate(ns, desc, "description")
        else:
            by_ns[ns] = _Candidate(ns, ns, "name")

    for (ns,) in mem_rows + chat_rows:
        if not ns or ns == exclude_namespace or ns.startswith(INBOX_PREFIX):
            continue
        if ns not in by_ns:
            by_ns[ns] = _Candidate(ns, ns, "name")

    # Counts (cheap aggregate per-namespace via the rows we already fetched).
    mem_counts: dict[str, int] = {}
    for (ns,) in mem_rows:
        if not ns:
            continue
        mem_counts[ns] = mem_counts.get(ns, 0) + 1
    chat_counts: dict[str, int] = {}
    for (ns,) in chat_rows:
        if not ns:
            continue
        chat_counts[ns] = chat_counts.get(ns, 0) + 1
    for ns, cand in by_ns.items():
        cand.memory_count = mem_counts.get(ns, 0)
        cand.chat_count = chat_counts.get(ns, 0)

    return list(by_ns.values())


# ─── Public API ─────────────────────────────────────────────────────


async def classify_chat(
    user_id: uuid.UUID,
    chat_id: uuid.UUID,
    db: AsyncSession,
    limit: int = 5,
) -> ChatClassifyResponse:
    """Suggest top-N namespaces for the given chat.

    Pure read-only — does NOT move the chat. Caller (UI or background
    task) decides whether to apply a suggestion via
    :func:`backend.services.ai_chat_service.move_chat`.
    """
    chat = (
        await db.execute(
            select(AIChat).where(
                AIChat.chat_id == chat_id,
                AIChat.user_id == user_id,
                AIChat.invalid_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if chat is None:
        raise ValueError("Chat not found")

    sample = await _load_chat_sample(chat, db)
    in_inbox = chat.namespace.startswith(INBOX_PREFIX)

    candidates = await _gather_candidates(user_id, chat.namespace, db)

    if not candidates:
        return ChatClassifyResponse(
            chat_id=str(chat.chat_id),
            current_namespace=chat.namespace,
            in_inbox=in_inbox,
            sample_chars=len(sample),
            suggestions=[],
        )

    # Try to embed; fall back to unranked candidate list when the encoder
    # is unavailable so the UI still has something to display.
    try:
        chat_vec = _embed(sample) if sample.strip() else None
    except Exception as exc:
        logger.debug("chat_classifier.embed_chat_failed", reason=str(exc))
        chat_vec = None

    if chat_vec is None:
        ranked = [
            NamespaceSuggestion(
                namespace=c.namespace,
                similarity=0.0,
                signal=c.signal,
                memory_count=c.memory_count,
                chat_count=c.chat_count,
            )
            for c in candidates[:limit]
        ]
        return ChatClassifyResponse(
            chat_id=str(chat.chat_id),
            current_namespace=chat.namespace,
            in_inbox=in_inbox,
            sample_chars=len(sample),
            suggestions=ranked,
            fallback=True,
        )

    scored: list[NamespaceSuggestion] = []
    for c in candidates:
        try:
            cand_vec = _embed(c.representative_text)
            sim = _cosine(chat_vec, cand_vec)
        except Exception as exc:
            logger.debug("chat_classifier.embed_cand_failed", ns=c.namespace, reason=str(exc))
            sim = 0.0
        scored.append(
            NamespaceSuggestion(
                namespace=c.namespace,
                similarity=round(sim, 4),
                signal=c.signal,
                memory_count=c.memory_count,
                chat_count=c.chat_count,
            )
        )

    scored.sort(key=lambda s: s.similarity, reverse=True)
    return ChatClassifyResponse(
        chat_id=str(chat.chat_id),
        current_namespace=chat.namespace,
        in_inbox=in_inbox,
        sample_chars=len(sample),
        suggestions=scored[:limit],
    )
