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

import asyncio
import logging
import math
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

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

# ── Auto-redirect thresholds (chats-v1 auto-classify) ───────────────
#
# Conservative defaults. The auto-router only fires when the chat is in
# one of the "pending" buckets (kora:inbox:* OR plain kora:<platform>),
# has enough content to be meaningful, AND the top suggestion is a
# clear winner. Anything ambiguous stays put for manual triage.
AUTO_MIN_TURNS = 4  # need ≥4 turns of real exchange
AUTO_MIN_CHARS = 600  # body must total ≥600 chars (skips trivials)
AUTO_MOVE_THRESHOLD = 0.55  # top suggestion cosine must clear this
AUTO_MOVE_GAP = 0.08  # top must beat #2 by this margin (clear winner)
# When NO existing namespace clears the threshold, we may auto-create a
# fresh one from the chat title — but only when the title is meaningful
# (skips generic "claude conversation" / "untitled" etc.).
AUTO_TITLE_MIN_CHARS = 8
_GENERIC_TITLE_RE = re.compile(
    r"^(untitled|new chat|new conversation|"
    r"(chatgpt|claude|gemini|manus) (chat|conversation)|"
    r"\(no title\)|\(untitled\)|"
    r"chat \d+|conversation \d+)$",
    re.IGNORECASE,
)


def is_pending_namespace(namespace: str | None) -> bool:
    """True when a chat is still in a holding bucket awaiting classification.

    Covers BOTH the new `kora:inbox:<platform>` inboxes AND the plain
    `kora:<platform>` buckets that pre-v3.32.0 captures landed in. We
    treat the latter as pending so old chats get retroactively rescued
    by the auto-classifier (and aren't trapped in their original default).
    """
    if not namespace:
        return False
    if namespace.startswith(INBOX_PREFIX):
        return True
    # `kora:<platform>` with no further `:` — bare per-platform bucket.
    parts = namespace.split(":")
    if len(parts) == 2 and parts[0] == "kora":
        return True
    return False


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
        (
            await db.execute(
                select(AIChatTurn)
                .where(AIChatTurn.chat_id == chat.chat_id)
                .order_by(AIChatTurn.sequence.asc())
                .limit(MAX_TURNS)
            )
        )
        .scalars()
        .all()
    )

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


# ─── Auto-redirect (fire-and-forget on chat upsert) ──────────────────


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug_from_title(title: str) -> str:
    slug = _SLUG_RE.sub("-", title.strip().lower()).strip("-")
    return slug[:48]


def _is_generic_title(title: str | None) -> bool:
    if not title:
        return True
    t = title.strip()
    if len(t) < AUTO_TITLE_MIN_CHARS:
        return True
    return bool(_GENERIC_TITLE_RE.match(t))


def schedule_auto_classify(chat_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Fire-and-forget background task triggered from ai_chat_service.upsert_chat.

    Matches the compression_pipeline pattern: never blocks the write
    path, failures logged and swallowed. The task opens its OWN session
    via _get_session_factory() (asyncio.create_task runs outside the
    request's contextvars Context, so the request's session would be
    torn down before we get to act on it).
    """
    asyncio.create_task(
        _run_auto_classify(str(chat_id), str(user_id)),
        name=f"auto-classify:{chat_id}",
    )


async def _run_auto_classify(chat_id_str: str, user_id_str: str) -> None:
    """Inspect the chat; if it's pending + content-rich + top suggestion
    is a clear winner, silently redirect to the chosen namespace.

    Decision tree:
      1. Chat must be in a "pending" namespace (kora:inbox:* or kora:<plat>).
      2. Chat must have ≥ AUTO_MIN_TURNS turns AND ≥ AUTO_MIN_CHARS of body.
      3. Run classify_chat() — get top-N suggestions.
      4. If top.similarity ≥ AUTO_MOVE_THRESHOLD AND
         (top.similarity − second.similarity) ≥ AUTO_MOVE_GAP →
         silently move to top.namespace.
      5. Else if title is meaningful (not generic) →
         derive `project:<slug>` and move there (creates the namespace).
      6. Else: do nothing — leave for manual triage.

    Every auto-move records itself in chat_metadata.auto_classified so
    the dashboard can label it. Idempotent: if the chat has already
    been auto-classified in this lifecycle we still re-evaluate (a
    later turn may swing the decision toward a new destination), but
    we only act when the new choice is materially different.
    """
    chat_id = uuid.UUID(chat_id_str)
    user_id = uuid.UUID(user_id_str)

    # Lazy imports to keep this module light + dodge any import cycles
    # between chat_classifier ↔ ai_chat_service ↔ namespace_matcher.
    from backend.core.database import _get_session_factory
    from backend.core.tenancy import bypass_tenant_filter

    try:
        async with _get_session_factory()() as db:
            async with db.begin():
                # Background tasks run outside the request's tenant scope;
                # bypass the filter so our SELECT actually returns the row
                # (the filter would emit an always-false predicate against
                # the empty scope and we'd see "Chat not found" on a chat
                # we just wrote two milliseconds ago).
                with bypass_tenant_filter():
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
                        return

                    if not is_pending_namespace(chat.namespace):
                        return

                    # Substantive-content gate.
                    turn_count = (
                        (
                            await db.execute(
                                select(AIChatTurn)
                                .where(AIChatTurn.chat_id == chat.chat_id)
                                .order_by(AIChatTurn.sequence.asc())
                            )
                        )
                        .scalars()
                        .all()
                    )
                    if len(turn_count) < AUTO_MIN_TURNS:
                        return
                    total_chars = sum(len(t.content or "") for t in turn_count)
                    if total_chars < AUTO_MIN_CHARS:
                        return

                    # Re-use the same classifier the manual endpoint uses
                    # so the dashboard's "Suggested namespaces" and the
                    # auto-router stay in lockstep on ranking logic.
                    result = await classify_chat(user_id, chat_id, db, limit=5)
                    target_ns: str | None = None
                    decision_signal = "none"
                    decision_sim: float | None = None

                    if result.suggestions:
                        top = result.suggestions[0]
                        second_sim = result.suggestions[1].similarity if len(result.suggestions) > 1 else 0.0
                        if (
                            top.similarity >= AUTO_MOVE_THRESHOLD
                            and (top.similarity - second_sim) >= AUTO_MOVE_GAP
                            and top.namespace != chat.namespace
                        ):
                            target_ns = top.namespace
                            decision_signal = f"existing:{top.signal}"
                            decision_sim = top.similarity

                    if target_ns is None and not _is_generic_title(chat.title):
                        slug = _slug_from_title(chat.title or "")
                        if slug:
                            candidate = f"project:{slug}"
                            if candidate != chat.namespace:
                                target_ns = candidate
                                decision_signal = "title"

                    if target_ns is None:
                        return

                    # Apply via the namespace matcher so a typo on the
                    # title-derived slug auto-redirects to a similar
                    # existing namespace instead of fragmenting.
                    try:
                        from backend.services.namespace_matcher import (
                            ResolutionAction,
                            apply_resolution,
                            resolve_namespace,
                        )

                        resolution = await resolve_namespace(user_id, target_ns, None, db)
                        if resolution.action != ResolutionAction.SUGGEST:
                            await apply_resolution(resolution, None, db, user_id)
                            target_ns = resolution.namespace
                        # SUGGEST → ambiguous, don't auto-act; leave for triage.
                        elif resolution.action == ResolutionAction.SUGGEST:
                            return
                    except Exception as exc:
                        logger.debug(
                            "chat_classifier.matcher_skipped",
                            extra={"reason": str(exc), "chat_id": chat_id_str},
                        )

                    previous_namespace = chat.namespace
                    chat.namespace = target_ns
                    chat.requested_namespace = None
                    chat.updated_at = datetime.now(UTC)
                    # Stash classification provenance so the UI can show
                    # "Auto-classified by Kemory · 87% confidence" and the
                    # user can audit / undo manually.
                    meta = dict(chat.chat_metadata or {})
                    meta["auto_classified"] = {
                        "at": datetime.now(UTC).isoformat(),
                        "from": previous_namespace,
                        "to": target_ns,
                        "signal": decision_signal,
                        "similarity": (round(decision_sim, 4) if decision_sim is not None else None),
                    }
                    chat.chat_metadata = meta
                    logger.info(
                        "chat_classifier.auto_redirected",
                        extra={
                            "chat_id": chat_id_str,
                            "from": previous_namespace,
                            "to": target_ns,
                            "signal": decision_signal,
                            "similarity": decision_sim,
                        },
                    )
    except Exception as exc:
        # Auto-classify is advisory; never let it surface to the user.
        logger.warning(
            "chat_classifier.auto_classify_failed",
            extra={"chat_id": chat_id_str, "error": str(exc)},
        )
