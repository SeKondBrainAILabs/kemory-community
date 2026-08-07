"""Rolling session context assembly (S9N-6291).

This service keeps the latest exchanges readable while compacting older
session context into a token-budgeted digest. The digest is a prompt-facing
representation, so it deliberately avoids AAAK; AAAK remains a storage and
transport/export dialect.
"""

from __future__ import annotations

import math
import os
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from backend.config.settings import settings
from backend.core.tenancy import current_org_id
from backend.models.ai_chat import AIChat, AIChatTurn
from backend.models.memory import Memory
from backend.models.namespace_policy import NamespacePolicy
from backend.models.session_digest import SessionDigest
from backend.models.session_summary import SessionSummary
from backend.services.compression_pipeline import L3_SUMMARY_GROQ_MODEL
from backend.services.memory_service import MemorySearchRequest, search_memories

logger = structlog.get_logger(__name__)

RAW_TAIL_EXCHANGES = 3
DEFAULT_TOKEN_BUDGET = 900
MAX_TOKEN_BUDGET = 4000
DEFAULT_RELEVANT_MEMORIES = 5
MAX_RELEVANT_MEMORIES = 20
DEFAULT_REHYDRATION_TOKEN_BUDGET = 700
MAX_REHYDRATION_TOKEN_BUDGET = 3000
DEFAULT_REHYDRATION_ITEMS = 3
MAX_REHYDRATION_ITEMS = 20
COMPACTION_BATCH_SIZE = 3
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "session_digest_v1.txt"
FALLBACK_TOKEN_METHOD = "fallback_chars_per_token_3"
DETAIL_REQUEST_RE = re.compile(
    r"\b(exact|verbatim|raw|source|sources|cite|citation|evidence|quote|detail|details|drill|expand)\b",
    re.I,
)
SOURCE_EXCHANGE_RE = re.compile(
    r"\b(?P<prefix>memory|turn):(?P<id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
)
DIGEST_SECTION_NAMES = (
    "Current objective",
    "Decisions made",
    "Constraints and preferences",
    "Open loops",
    "Files/services/entities touched",
    "Retrieval hooks",
)


@dataclass(frozen=True)
class TokenCount:
    count: int
    model: str
    tokenizer_name: str | None
    method: str


@dataclass(frozen=True)
class _ChatExchange:
    anchor_turn_id: uuid.UUID
    content: str


def _pair_chat_turns(turns: Sequence[AIChatTurn]) -> list[_ChatExchange]:
    ordered = sorted(
        (turn for turn in turns if turn.role in ("user", "assistant")),
        key=lambda turn: turn.sequence if turn.sequence is not None else 0,
    )
    exchanges: list[_ChatExchange] = []
    pending_user: AIChatTurn | None = None

    def text(turn: AIChatTurn) -> str:
        return (turn.content or "").strip()

    def flush_user() -> None:
        nonlocal pending_user
        if pending_user is not None:
            exchanges.append(
                _ChatExchange(
                    anchor_turn_id=pending_user.turn_id,
                    content=f"User: {text(pending_user)}",
                )
            )
            pending_user = None

    for turn in ordered:
        if turn.role == "user":
            if not text(turn):
                continue
            flush_user()
            pending_user = turn
            continue

        assistant_text = text(turn)
        if pending_user is not None and assistant_text:
            exchanges.append(
                _ChatExchange(
                    anchor_turn_id=turn.turn_id,
                    content=f"User: {text(pending_user)}\nAssistant: {assistant_text}",
                )
            )
            pending_user = None
        elif pending_user is None and assistant_text:
            exchanges.append(
                _ChatExchange(
                    anchor_turn_id=turn.turn_id,
                    content=f"Assistant: {assistant_text}",
                )
            )

    flush_user()
    return exchanges


def _render_chat_exchange(chat: AIChat, exchange: _ChatExchange) -> str:
    title = (chat.title or "").strip() or "Untitled conversation"
    return f"[{chat.platform} chat - {title}]\n{exchange.content}"


@dataclass(frozen=True)
class SourceExchange:
    source_exchange_id: str
    content: str
    created_at: datetime | None
    source: str
    memory_id: str | None = None
    source_turn_id: str | None = None

    def to_context_dict(self) -> dict[str, Any]:
        return {
            "source_exchange_id": self.source_exchange_id,
            "source": self.source,
            "memory_id": self.memory_id,
            "source_turn_id": self.source_turn_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "content": self.content,
        }


@dataclass(frozen=True)
class RehydratedSource:
    source_exchange_id: str
    source: str
    content: str
    created_at: datetime | None
    memory_id: str | None = None
    source_turn_id: str | None = None
    content_type: str | None = None
    role: str | None = None
    title: str | None = None

    def to_context_dict(self, *, token_count: int | None = None) -> dict[str, Any]:
        data = {
            "source_exchange_id": self.source_exchange_id,
            "source": self.source,
            "memory_id": self.memory_id,
            "source_turn_id": self.source_turn_id,
            "content_type": self.content_type,
            "role": self.role,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "content": self.content,
        }
        if token_count is not None:
            data["token_count"] = token_count
        return data


@dataclass(frozen=True)
class DigestGeneration:
    text: str
    tier: str


async def get_session_context(
    user_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    namespace: str,
    session_id: str,
    db: AsyncSession,
    *,
    chat_id: str | None = None,
    topic: str | None = None,
    raw_tail_count: int = RAW_TAIL_EXCHANGES,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    max_relevant_memories: int = DEFAULT_RELEVANT_MEMORIES,
    model: str | None = None,
    include_expansion_hooks: bool = False,
) -> dict[str, Any]:
    """Return an optimized context block for a session.

    The returned ``context.text`` is intended for LLM prompt injection:
    namespace/session summaries first, rolling digest next, relevant recalled
    memories after that, and the latest raw exchanges last. The caller should
    append the current user message after this block.
    """

    if not namespace:
        raise ValueError("namespace is required")
    if not session_id:
        raise ValueError("session_id is required")

    raw_tail_count = min(max(int(raw_tail_count or RAW_TAIL_EXCHANGES), 1), 10)
    token_budget = min(max(int(token_budget or DEFAULT_TOKEN_BUDGET), 128), MAX_TOKEN_BUDGET)
    max_relevant_memories = min(max(int(max_relevant_memories or 0), 0), MAX_RELEVANT_MEMORIES)
    model = model or L3_SUMMARY_GROQ_MODEL

    exchanges = await load_session_exchanges(
        user_id,
        namespace,
        session_id,
        db,
        chat_id=chat_id,
    )
    background = await load_background_context(user_id, namespace, session_id, db)

    digest_state = await refresh_session_digest(
        user_id,
        namespace,
        session_id,
        exchanges,
        db,
        background_context=background["text"],
        raw_tail_count=raw_tail_count,
        token_budget=token_budget,
        model=model,
    )

    raw_tail = exchanges[-raw_tail_count:] if exchanges else []
    exclude_memory_ids = {ex.memory_id for ex in exchanges if ex.memory_id}
    relevant_memories = await load_relevant_memories(
        user_id,
        agent_id,
        namespace,
        db,
        topic=topic,
        limit=max_relevant_memories,
        exclude_memory_ids=exclude_memory_ids,
    )

    context_text = format_session_context(
        namespace=namespace,
        session_id=session_id,
        background=background,
        digest_state=digest_state,
        relevant_memories=relevant_memories,
        raw_tail=raw_tail,
    )
    context_tokens = count_tokens(context_text, model)
    expansion_hooks = build_expansion_hooks(digest_state) if include_expansion_hooks else None
    rehydration = detect_rehydration_trigger(
        topic=topic,
        digest_state=digest_state,
        explicit=False,
    )

    return {
        "namespace": namespace,
        "session_id": session_id,
        "chat_id": chat_id,
        "source_exchange_count": len(exchanges),
        "generated_at": datetime.now(UTC).isoformat(),
        "background": background,
        "digest": digest_state,
        "expansion_hooks": expansion_hooks,
        "rehydration": rehydration,
        "relevant_memories": relevant_memories,
        "raw_tail": [ex.to_context_dict() for ex in raw_tail],
        "context": {
            "text": context_text,
            "token_count": context_tokens.count,
            "tokenizer_model": context_tokens.model,
            "tokenizer_name": context_tokens.tokenizer_name,
            "token_count_method": context_tokens.method,
        },
    }


async def rehydrate_session_sources(
    user_id: uuid.UUID,
    namespace: str,
    session_id: str,
    db: AsyncSession,
    *,
    source_memory_ids: Sequence[str] | None = None,
    source_turn_ids: Sequence[str] | None = None,
    source_exchange_ids: Sequence[str] | None = None,
    query: str | None = None,
    token_budget: int = DEFAULT_REHYDRATION_TOKEN_BUDGET,
    max_items: int = DEFAULT_REHYDRATION_ITEMS,
    model: str | None = None,
    trigger: str = "explicit",
) -> dict[str, Any]:
    """Read-only drill-to-raw expansion for a stored session digest.

    The function expands selected source IDs to exact raw L1 memories and/or
    raw chat turns. It never slices a source item to fit budget: whole items
    are included or omitted with a reason so callers do not pay for lossy
    syntactic fragments.
    """

    if not namespace:
        raise ValueError("namespace is required")
    if not session_id:
        raise ValueError("session_id is required")
    if trigger not in {"explicit", "heuristic"}:
        raise ValueError("trigger must be 'explicit' or 'heuristic'")

    token_budget = min(
        max(int(token_budget or DEFAULT_REHYDRATION_TOKEN_BUDGET), 32),
        MAX_REHYDRATION_TOKEN_BUDGET,
    )
    max_items = min(max(int(max_items or DEFAULT_REHYDRATION_ITEMS), 1), MAX_REHYDRATION_ITEMS)
    model = model or L3_SUMMARY_GROQ_MODEL
    org_id = current_org_id() or settings.tenant_legacy_sentinel

    row = await _load_digest_row(user_id, org_id, namespace, session_id, db)
    if row is None:
        raise ValueError("session digest not found")

    requested_memory_ids, requested_turn_ids = _requested_raw_ids(
        source_memory_ids=source_memory_ids,
        source_turn_ids=source_turn_ids,
        source_exchange_ids=source_exchange_ids,
    )
    explicit_ids_supplied = bool(requested_memory_ids or requested_turn_ids)
    if trigger == "explicit" and not explicit_ids_supplied:
        raise ValueError(
            "explicit rehydration requires source_memory_ids, source_turn_ids, or source_exchange_ids"
        )

    if trigger == "heuristic" and not explicit_ids_supplied:
        requested_memory_ids = list(row.source_memory_ids or [])
        requested_turn_ids = list(row.source_turn_ids or [])

    sources = await _load_rehydration_sources(
        user_id,
        namespace,
        db,
        memory_ids=requested_memory_ids,
        turn_ids=requested_turn_ids,
    )
    order = _source_order(row, requested_memory_ids, requested_turn_ids, source_exchange_ids)
    sources = sorted(sources, key=lambda item: order.get(item.source_exchange_id, len(order)))
    if trigger == "heuristic":
        sources = _rank_rehydration_sources(sources, query)

    selected, omitted, text, token_meta = _fit_rehydrated_sources_to_budget(
        sources,
        token_budget=token_budget,
        max_items=max_items,
        model=model,
    )
    digest_state = _digest_state(
        digest=row.digest or "",
        tier=row.digest_tier or "L2.1",
        row=row,
        token_meta=count_tokens(row.digest or "", model),
        token_budget=row.token_budget,
        raw_tail_count=row.raw_tail_count,
        pending_source_count=0,
    )

    missing_source_ids = _missing_source_ids(
        requested_memory_ids=requested_memory_ids,
        requested_turn_ids=requested_turn_ids,
        found=sources,
    )

    return {
        "namespace": namespace,
        "session_id": session_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "trigger": {
            "mode": trigger,
            "query": query,
            "explicit_ids_supplied": explicit_ids_supplied,
            "reason": _rehydration_reason(trigger, query, explicit_ids_supplied),
        },
        "token_budget": token_budget,
        "token_count": token_meta.count,
        "tokenizer_model": token_meta.model,
        "tokenizer_name": token_meta.tokenizer_name,
        "token_count_method": token_meta.method,
        "expanded_count": len(selected),
        "omitted_count": len(omitted),
        "missing_source_ids": missing_source_ids,
        "items": selected,
        "omitted_items": omitted,
        "expansion_hooks": build_expansion_hooks(digest_state),
        "text": text,
    }


async def load_session_exchanges(
    user_id: uuid.UUID,
    namespace: str,
    session_id: str,
    db: AsyncSession,
    *,
    chat_id: str | None = None,
) -> list[SourceExchange]:
    """Load source exchanges from L1 memories, with raw chat turns as fallback."""

    memory_exchanges = await _load_memory_exchanges(user_id, namespace, session_id, db)

    chat_uuid = _coerce_uuid(chat_id) or _coerce_uuid(session_id)
    chat_exchanges = (
        await _load_chat_exchanges(user_id, namespace, chat_uuid, db) if chat_uuid is not None else []
    )
    if not memory_exchanges:
        return chat_exchanges

    # If both are present, keep the memory rows as canonical and add only
    # chat-turn exchanges not already represented by source_turn_id.
    existing_turn_ids = {ex.source_turn_id for ex in memory_exchanges if ex.source_turn_id}
    merged = list(memory_exchanges)
    merged.extend(
        ex for ex in chat_exchanges if ex.source_turn_id and ex.source_turn_id not in existing_turn_ids
    )
    return sorted(merged, key=lambda ex: (_datetime_sort_key(ex.created_at), ex.source_exchange_id))


async def load_background_context(
    user_id: uuid.UUID,
    namespace: str,
    session_id: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Load long-term namespace and session summaries as non-source background."""

    policy = (
        await db.execute(
            select(NamespacePolicy).where(
                NamespacePolicy.namespace == namespace,
            )
        )
    ).scalar_one_or_none()
    session_summary = (
        await db.execute(
            select(SessionSummary).where(
                SessionSummary.user_id == user_id,
                SessionSummary.namespace == namespace,
                SessionSummary.session_id == session_id,
            )
        )
    ).scalar_one_or_none()

    namespace_summary = {
        "summary": getattr(policy, "consolidated_summary", None) if policy else None,
        "tier": getattr(policy, "consolidated_summary_tier", None) if policy else None,
        "updated_at": (
            policy.consolidated_summary_updated_at.isoformat()
            if policy and policy.consolidated_summary_updated_at
            else None
        ),
    }
    session_summary_out = {
        "session_summary": getattr(session_summary, "session_summary", None),
        "session_summary_tier": getattr(session_summary, "session_summary_tier", None),
        "cumulative_summary": getattr(session_summary, "cumulative_summary", None),
        "cumulative_summary_tier": getattr(session_summary, "cumulative_summary_tier", None),
        "updated_at": (
            session_summary.updated_at.isoformat()
            if session_summary is not None and session_summary.updated_at
            else None
        ),
    }

    text = _format_background_context(namespace, namespace_summary, session_summary_out)
    return {
        "namespace": namespace_summary,
        "session": session_summary_out,
        "text": text,
    }


async def refresh_session_digest(
    user_id: uuid.UUID,
    namespace: str,
    session_id: str,
    exchanges: list[SourceExchange],
    db: AsyncSession,
    *,
    background_context: str,
    raw_tail_count: int = RAW_TAIL_EXCHANGES,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    model: str | None = None,
) -> dict[str, Any]:
    """Update the stored digest for exchanges older than the raw tail."""

    model = model or L3_SUMMARY_GROQ_MODEL
    org_id = current_org_id() or settings.tenant_legacy_sentinel
    compactable = exchanges[:-raw_tail_count] if raw_tail_count else list(exchanges)

    row = await _load_digest_row(user_id, org_id, namespace, session_id, db)
    if row is None and not compactable:
        token_meta = count_tokens("", model)
        return _digest_state(
            digest="",
            tier="L2.1",
            row=None,
            token_meta=token_meta,
            token_budget=token_budget,
            raw_tail_count=raw_tail_count,
            pending_source_count=0,
        )

    if row is None:
        row = SessionDigest(
            org_id=org_id,
            user_id=user_id,
            namespace=namespace,
            session_id=session_id,
            digest="",
            digest_tier="L2.1",
            source_exchange_ids=[],
            source_turn_ids=[],
            source_memory_ids=[],
            raw_tail_count=raw_tail_count,
            token_budget=token_budget,
            token_count=0,
            tokenizer_model=model,
            tokenizer_name=None,
            token_count_method=FALLBACK_TOKEN_METHOD,
        )
        db.add(row)

    processed_exchange_ids = list(row.source_exchange_ids or [])
    processed_set = set(processed_exchange_ids)
    pending = [ex for ex in compactable if ex.source_exchange_id not in processed_set]
    digest_text = row.digest or ""
    tier = row.digest_tier or "L2.1"

    for batch in _chunks(pending, COMPACTION_BATCH_SIZE):
        generation = await generate_digest_update(
            previous_digest=digest_text,
            background_context=background_context,
            batch=batch,
            namespace=namespace,
            session_id=session_id,
            token_budget=token_budget,
            model=model,
        )
        digest_text = generation.text
        tier = generation.tier
        processed_exchange_ids.extend(ex.source_exchange_id for ex in batch)

    token_meta = count_tokens(digest_text, model)
    digest_text, token_meta = fit_text_to_budget(digest_text, token_budget, model)

    row.digest = digest_text
    row.digest_tier = tier
    row.source_exchange_ids = processed_exchange_ids
    row.source_memory_ids = _unique(
        [*(row.source_memory_ids or []), *(ex.memory_id for ex in pending if ex.memory_id)]
    )
    row.source_turn_ids = _unique(
        [*(row.source_turn_ids or []), *(ex.source_turn_id for ex in pending if ex.source_turn_id)]
    )
    row.compacted_exchange_count = len(processed_exchange_ids)
    row.raw_tail_count = raw_tail_count
    row.token_budget = token_budget
    row.token_count = token_meta.count
    row.tokenizer_model = token_meta.model
    row.tokenizer_name = token_meta.tokenizer_name
    row.token_count_method = token_meta.method
    row.last_source_created_at = compactable[-1].created_at if compactable else row.last_source_created_at
    row.updated_at = datetime.now(UTC)

    return _digest_state(
        digest=digest_text,
        tier=tier,
        row=row,
        token_meta=token_meta,
        token_budget=token_budget,
        raw_tail_count=raw_tail_count,
        pending_source_count=len(pending),
    )


async def generate_digest_update(
    *,
    previous_digest: str,
    background_context: str,
    batch: list[SourceExchange],
    namespace: str,
    session_id: str,
    token_budget: int,
    model: str,
) -> DigestGeneration:
    """Use core-ai-backend when available, otherwise deterministic fallback."""

    source_exchanges = _format_source_exchanges(batch)
    prompt = _render_prompt(
        namespace=namespace,
        session_id=session_id,
        token_budget=token_budget,
        previous_digest=previous_digest,
        background_context=background_context,
        source_exchanges=source_exchanges,
    )
    base_url = (os.environ.get("CORE_AI_BACKEND_URL") or os.environ.get("AI_BACKEND_URL", "")).rstrip("/")
    if not base_url:
        return DigestGeneration(
            text=_extractive_digest(previous_digest, batch, token_budget, model),
            tier="L2.1-extractive",
        )

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": min(max(token_budget, 128), MAX_TOKEN_BUDGET),
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    token = os.environ.get("CORE_AI_BACKEND_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
            text = (data["choices"][0]["message"]["content"] or "").strip()
            if text:
                fitted, _ = fit_text_to_budget(text, token_budget, model)
                return DigestGeneration(text=fitted, tier="L2.1")
    except Exception as exc:
        logger.warning(
            "session_digest.llm_failed", namespace=namespace, session_id=session_id, error=str(exc)
        )

    return DigestGeneration(
        text=_extractive_digest(previous_digest, batch, token_budget, model),
        tier="L2.1-extractive",
    )


async def load_relevant_memories(
    user_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    namespace: str,
    db: AsyncSession,
    *,
    topic: str | None,
    limit: int,
    exclude_memory_ids: set[str | None],
) -> list[dict[str, Any]]:
    if not topic or limit <= 0:
        return []

    request = MemorySearchRequest(
        query=topic,
        namespace=namespace,
        limit=limit,
        offset=0,
        search_mode="hybrid",
    )
    try:
        result = await search_memories(user_id, agent_id, request, db, skip_gatekeeper=True)
    except Exception as exc:
        logger.debug("session_digest.relevant_memories_failed", namespace=namespace, error=str(exc))
        return []

    relevant: list[dict[str, Any]] = []
    for item in result.items:
        if item.memory_id in exclude_memory_ids:
            continue
        relevant.append(
            {
                "memory_id": item.memory_id,
                "namespace": item.namespace,
                "content_type": item.content_type,
                "created_at": item.created_at,
                "similarity_score": item.similarity_score,
                "content": item.content,
            }
        )
        if len(relevant) >= limit:
            break
    return relevant


def format_session_context(
    *,
    namespace: str,
    session_id: str,
    background: dict[str, Any],
    digest_state: dict[str, Any],
    relevant_memories: list[dict[str, Any]],
    raw_tail: list[SourceExchange],
) -> str:
    """Format the prompt-facing context block."""

    lines = [
        "Kemory session context",
        f"namespace: {namespace}",
        f"session_id: {session_id}",
        "",
    ]

    background_text = background.get("text") or ""
    if background_text:
        lines.extend(["Namespace/session summary", background_text, ""])

    digest = (digest_state.get("text") or "").strip()
    if digest:
        lines.extend(
            [
                "Rolling session digest",
                f"tier: {digest_state.get('tier') or 'L2.1'}",
                f"compacted_exchanges: {digest_state.get('compacted_exchange_count', 0)}",
                digest,
                "",
            ]
        )

    if relevant_memories:
        lines.append("Relevant recalled raw memories")
        for idx, mem in enumerate(relevant_memories, start=1):
            lines.append(
                f"[{idx}] {mem['memory_id']} ({mem['content_type']}, score={mem.get('similarity_score')})"
            )
            lines.append(_collapse_blank_lines(mem["content"]).strip())
        lines.append("")

    if raw_tail:
        lines.append(f"Latest {len(raw_tail)} raw exchange(s)")
        for idx, ex in enumerate(raw_tail, start=1):
            lines.append(f"[{idx}] {ex.source_exchange_id}")
            lines.append(_collapse_blank_lines(ex.content).strip())
        lines.append("")

    lines.append("Caller should append the current user message after this context block.")
    return "\n".join(lines).strip()


def count_tokens(text: str, model: str | None = None) -> TokenCount:
    """Count tokens exactly when a tokenizer is available, otherwise overestimate.

    Groq/Llama model IDs used by the backend are not mapped by ``tiktoken``.
    In that case the service uses a conservative chars/3 estimate and records
    that method explicitly; it never uses AAAK byte compression ratio as a
    token proxy.
    """

    model_name = model or L3_SUMMARY_GROQ_MODEL
    try:
        import tiktoken  # type: ignore[import-not-found]

        encoding = tiktoken.encoding_for_model(model_name)
        return TokenCount(
            count=len(encoding.encode(text or "")),
            model=model_name,
            tokenizer_name=getattr(encoding, "name", None),
            method="tiktoken_encoding_for_model",
        )
    except Exception:
        return TokenCount(
            count=math.ceil(len(text or "") / 3),
            model=model_name,
            tokenizer_name=None,
            method=FALLBACK_TOKEN_METHOD,
        )


def fit_text_to_budget(text: str, token_budget: int, model: str) -> tuple[str, TokenCount]:
    """Fit text to budget without slicing words or source items."""

    text = (text or "").strip()
    token_meta = count_tokens(text, model)
    if token_meta.count <= token_budget:
        return text, token_meta

    marker = "[additional semantic digest lines omitted to fit token budget]"
    marker_tokens = count_tokens(marker, model)
    if marker_tokens.count > token_budget:
        return "", count_tokens("", model)

    kept: list[str] = []
    for line in text.splitlines():
        candidate_lines = [*kept, line]
        candidate = "\n".join(candidate_lines + [marker]).strip()
        if count_tokens(candidate, model).count <= token_budget:
            kept.append(line)

    fitted = "\n".join([*kept, marker]).strip() if kept else marker
    return fitted, count_tokens(fitted, model)


async def _load_memory_exchanges(
    user_id: uuid.UUID,
    namespace: str,
    session_id: str,
    db: AsyncSession,
) -> list[SourceExchange]:
    stmt = (
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.namespace == namespace,
            Memory.session_id == session_id,
            Memory.invalid_at.is_(None),
            Memory.content_type != "concept",
        )
        .options(defer(Memory.embedding))
        .order_by(Memory.created_at.asc(), Memory.updated_at.asc())
    )
    rows = list((await db.execute(stmt)).scalars().all())
    return [
        SourceExchange(
            source_exchange_id=f"memory:{memory.memory_id}",
            memory_id=str(memory.memory_id),
            source_turn_id=str(memory.source_turn_id) if memory.source_turn_id else None,
            source="memory",
            content=memory.content,
            created_at=memory.created_at,
        )
        for memory in rows
        if (memory.content or "").strip()
    ]


async def _load_chat_exchanges(
    user_id: uuid.UUID,
    namespace: str,
    chat_id: uuid.UUID,
    db: AsyncSession,
) -> list[SourceExchange]:
    chat = (
        await db.execute(
            select(AIChat).where(
                AIChat.chat_id == chat_id,
                AIChat.user_id == user_id,
                AIChat.namespace == namespace,
                AIChat.invalid_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if chat is None:
        return []

    turns = list(
        (
            await db.execute(
                select(AIChatTurn).where(AIChatTurn.chat_id == chat_id).order_by(AIChatTurn.sequence.asc())
            )
        ).scalars()
    )
    turns_by_id = {turn.turn_id: turn for turn in turns}
    exchanges: list[SourceExchange] = []
    for exchange in _pair_chat_turns(turns):
        anchor = turns_by_id.get(exchange.anchor_turn_id)
        exchanges.append(
            SourceExchange(
                source_exchange_id=f"turn:{exchange.anchor_turn_id}",
                source_turn_id=str(exchange.anchor_turn_id),
                memory_id=None,
                source="chat_turn",
                content=_render_chat_exchange(chat, exchange),
                created_at=anchor.created_at if anchor else chat.created_at,
            )
        )
    return exchanges


async def _load_digest_row(
    user_id: uuid.UUID,
    org_id: str,
    namespace: str,
    session_id: str,
    db: AsyncSession,
) -> SessionDigest | None:
    return (
        await db.execute(
            select(SessionDigest).where(
                SessionDigest.org_id == org_id,
                SessionDigest.user_id == user_id,
                SessionDigest.namespace == namespace,
                SessionDigest.session_id == session_id,
            )
        )
    ).scalar_one_or_none()


def _digest_state(
    *,
    digest: str,
    tier: str,
    row: SessionDigest | None,
    token_meta: TokenCount,
    token_budget: int,
    raw_tail_count: int,
    pending_source_count: int,
) -> dict[str, Any]:
    return {
        "text": digest,
        "tier": tier,
        "source_exchange_ids": list(row.source_exchange_ids or []) if row is not None else [],
        "source_turn_ids": list(row.source_turn_ids or []) if row is not None else [],
        "source_memory_ids": list(row.source_memory_ids or []) if row is not None else [],
        "compacted_exchange_count": row.compacted_exchange_count if row is not None else 0,
        "pending_source_count": pending_source_count,
        "raw_tail_count": raw_tail_count,
        "token_budget": token_budget,
        "token_count": token_meta.count,
        "tokenizer_model": token_meta.model,
        "tokenizer_name": token_meta.tokenizer_name,
        "token_count_method": token_meta.method,
        "updated_at": row.updated_at.isoformat() if row is not None and row.updated_at else None,
    }


def _render_prompt(
    *,
    namespace: str,
    session_id: str,
    token_budget: int,
    previous_digest: str,
    background_context: str,
    source_exchanges: str,
) -> str:
    try:
        template = PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        template = (
            "Update the rolling session digest under {{token_budget}} tokens.\n"
            "Use only previous_digest and source_exchanges as source facts.\n"
            "Background is orientation only.\n\n"
            "namespace: {{namespace}}\n"
            "session_id: {{session_id}}\n"
            "previous_digest:\n{{previous_digest}}\n\n"
            "background_context:\n{{background_context}}\n\n"
            "source_exchanges:\n{{source_exchanges}}\n"
        )
    values = {
        "namespace": namespace,
        "session_id": session_id,
        "token_budget": str(token_budget),
        "previous_digest": previous_digest or "(none)",
        "background_context": background_context or "(none)",
        "source_exchanges": source_exchanges or "(none)",
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    return template


def _format_background_context(
    namespace: str,
    namespace_summary: dict[str, Any],
    session_summary: dict[str, Any],
) -> str:
    lines: list[str] = []
    ns_summary = (namespace_summary.get("summary") or "").strip()
    if ns_summary:
        lines.extend(
            [
                f"[namespace:{namespace}] tier={namespace_summary.get('tier') or 'unknown'}",
                ns_summary,
            ]
        )
    sess_summary = (session_summary.get("session_summary") or "").strip()
    if sess_summary:
        lines.extend(
            [
                f"[session:{namespace}] tier={session_summary.get('session_summary_tier') or 'unknown'}",
                sess_summary,
            ]
        )
    cumulative = (session_summary.get("cumulative_summary") or "").strip()
    if cumulative:
        lines.extend(
            [
                f"[cumulative:{namespace}] tier={session_summary.get('cumulative_summary_tier') or 'unknown'}",
                cumulative,
            ]
        )
    return "\n".join(lines).strip()


def _format_source_exchanges(batch: list[SourceExchange]) -> str:
    blocks: list[str] = []
    for idx, ex in enumerate(batch, start=1):
        created = ex.created_at.isoformat() if ex.created_at else "unknown"
        memory = f" memory_id={ex.memory_id}" if ex.memory_id else ""
        turn = f" source_turn_id={ex.source_turn_id}" if ex.source_turn_id else ""
        blocks.append(
            f"[{idx}] id={ex.source_exchange_id} source={ex.source}{memory}{turn} created_at={created}\n"
            f"{_collapse_blank_lines(ex.content).strip()}"
        )
    return "\n\n".join(blocks)


def _extractive_digest(
    previous_digest: str,
    batch: list[SourceExchange],
    token_budget: int,
    model: str,
) -> str:
    lines: list[str] = []
    previous = (previous_digest or "").strip()
    if previous:
        lines.append(previous)
        lines.append("")
    lines.append("Open loops")
    for ex in batch:
        content = _collapse_blank_lines(ex.content)
        lines.append(f"- source={ex.source_exchange_id}")
        for line in content.splitlines():
            lines.append(f"  {line}")
    text, _ = fit_text_to_budget("\n".join(lines), token_budget, model)
    return text


def _collapse_blank_lines(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _coerce_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _chunks(items: list[SourceExchange], size: int) -> list[list[SourceExchange]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _unique(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def detect_rehydration_trigger(
    *,
    topic: str | None,
    digest_state: dict[str, Any],
    explicit: bool,
) -> dict[str, Any]:
    source_count = len(digest_state.get("source_exchange_ids") or []) or (
        len(digest_state.get("source_memory_ids") or []) + len(digest_state.get("source_turn_ids") or [])
    )
    if explicit:
        return {
            "suggested": True,
            "trigger": "explicit",
            "reason": "caller requested drill-to-raw expansion",
            "tool": "kemory_rehydrate_session_sources",
        }
    if source_count and topic and DETAIL_REQUEST_RE.search(topic):
        return {
            "suggested": True,
            "trigger": "heuristic",
            "reason": "topic asks for detail/source evidence while the digest has compacted sources",
            "tool": "kemory_rehydrate_session_sources",
        }
    return {
        "suggested": False,
        "trigger": None,
        "reason": "no detail/source-evidence request detected for compacted digest sources",
        "tool": "kemory_rehydrate_session_sources",
    }


def build_expansion_hooks(digest_state: dict[str, Any]) -> dict[str, Any]:
    source_exchange_ids = list(digest_state.get("source_exchange_ids") or [])
    source_memory_ids = list(digest_state.get("source_memory_ids") or [])
    source_turn_ids = list(digest_state.get("source_turn_ids") or [])
    if not source_exchange_ids:
        source_exchange_ids = _combined_source_exchange_ids(source_memory_ids, source_turn_ids)

    sections: list[dict[str, Any]] = []
    for section, body in _digest_section_blocks(digest_state.get("text") or "").items():
        refs = _extract_source_exchange_ids(body)
        mem_ids, turn_ids = _ids_from_source_exchange_ids(refs)
        sections.append(
            {
                "section": section,
                "source_exchange_ids": refs,
                "source_memory_ids": mem_ids,
                "source_turn_ids": turn_ids,
                "fallback_source_scope": "digest" if not refs and source_exchange_ids else None,
            }
        )

    return {
        "tool": "kemory_rehydrate_session_sources",
        "digest": {
            "source_exchange_ids": source_exchange_ids,
            "source_memory_ids": source_memory_ids,
            "source_turn_ids": source_turn_ids,
        },
        "sections": sections,
    }


async def _load_rehydration_sources(
    user_id: uuid.UUID,
    namespace: str,
    db: AsyncSession,
    *,
    memory_ids: Sequence[str],
    turn_ids: Sequence[str],
) -> list[RehydratedSource]:
    out: list[RehydratedSource] = []
    memory_uuids = _coerce_uuid_list(memory_ids)
    if memory_uuids:
        stmt = (
            select(Memory)
            .where(
                Memory.user_id == user_id,
                Memory.namespace == namespace,
                Memory.memory_id.in_(memory_uuids),
                Memory.invalid_at.is_(None),
            )
            .options(defer(Memory.embedding))
        )
        for memory in (await db.execute(stmt)).scalars().all():
            out.append(
                RehydratedSource(
                    source_exchange_id=f"memory:{memory.memory_id}",
                    source="memory",
                    memory_id=str(memory.memory_id),
                    source_turn_id=str(memory.source_turn_id) if memory.source_turn_id else None,
                    content_type=memory.content_type,
                    content=memory.content,
                    created_at=memory.created_at,
                )
            )

    turn_uuids = _coerce_uuid_list(turn_ids)
    if turn_uuids:
        stmt = (
            select(AIChatTurn, AIChat)
            .join(AIChat, AIChatTurn.chat_id == AIChat.chat_id)
            .where(
                AIChatTurn.user_id == user_id,
                AIChatTurn.turn_id.in_(turn_uuids),
                AIChatTurn.invalid_at.is_(None),
                AIChat.user_id == user_id,
                AIChat.namespace == namespace,
                AIChat.invalid_at.is_(None),
            )
            .order_by(AIChatTurn.created_at.asc(), AIChatTurn.sequence.asc())
        )
        for turn, chat in (await db.execute(stmt)).all():
            out.append(
                RehydratedSource(
                    source_exchange_id=f"turn:{turn.turn_id}",
                    source="chat_turn",
                    source_turn_id=str(turn.turn_id),
                    role=turn.role,
                    title=chat.title,
                    content=turn.content,
                    created_at=turn.created_at,
                )
            )
    return out


def _fit_rehydrated_sources_to_budget(
    sources: list[RehydratedSource],
    *,
    token_budget: int,
    max_items: int,
    model: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, TokenCount]:
    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    text_blocks: list[str] = []

    for source in sources:
        if len(selected) >= max_items:
            omitted.append(
                {
                    "source_exchange_id": source.source_exchange_id,
                    "memory_id": source.memory_id,
                    "source_turn_id": source.source_turn_id,
                    "reason": "over_max_items",
                    "token_count": count_tokens(_format_rehydrated_source(source), model).count,
                }
            )
            continue

        block = _format_rehydrated_source(source)
        item_tokens = count_tokens(block, model)
        candidate_text = "\n\n".join([*text_blocks, block]).strip()
        candidate_tokens = count_tokens(candidate_text, model)
        if candidate_tokens.count <= token_budget:
            selected.append(source.to_context_dict(token_count=item_tokens.count))
            text_blocks.append(block)
        else:
            omitted.append(
                {
                    "source_exchange_id": source.source_exchange_id,
                    "memory_id": source.memory_id,
                    "source_turn_id": source.source_turn_id,
                    "reason": "over_token_budget_whole_item_not_sliced",
                    "token_count": item_tokens.count,
                }
            )

    text = "\n\n".join(text_blocks).strip()
    return selected, omitted, text, count_tokens(text, model)


def _format_rehydrated_source(source: RehydratedSource) -> str:
    header = [f"[{source.source_exchange_id}]", f"source={source.source}"]
    if source.memory_id:
        header.append(f"memory_id={source.memory_id}")
    if source.source_turn_id:
        header.append(f"source_turn_id={source.source_turn_id}")
    if source.content_type:
        header.append(f"content_type={source.content_type}")
    if source.role:
        header.append(f"role={source.role}")
    if source.created_at:
        header.append(f"created_at={source.created_at.isoformat()}")
    title = f"title={source.title}\n" if source.title else ""
    return " ".join(header) + "\n" + title + _collapse_blank_lines(source.content)


def _requested_raw_ids(
    *,
    source_memory_ids: Sequence[str] | None,
    source_turn_ids: Sequence[str] | None,
    source_exchange_ids: Sequence[str] | None,
) -> tuple[list[str], list[str]]:
    memory_ids = [str(value) for value in (source_memory_ids or []) if value]
    turn_ids = [str(value) for value in (source_turn_ids or []) if value]
    ex_memory_ids, ex_turn_ids = _ids_from_source_exchange_ids(source_exchange_ids or [])
    return _unique([*memory_ids, *ex_memory_ids]), _unique([*turn_ids, *ex_turn_ids])


def _source_order(
    row: SessionDigest,
    memory_ids: Sequence[str],
    turn_ids: Sequence[str],
    source_exchange_ids: Sequence[str] | None,
) -> dict[str, int]:
    ordered = list(source_exchange_ids or [])
    if not ordered:
        ordered = _combined_source_exchange_ids(memory_ids, turn_ids)
    if not ordered:
        ordered = list(row.source_exchange_ids or [])
    if not ordered:
        ordered = _combined_source_exchange_ids(row.source_memory_ids or [], row.source_turn_ids or [])
    return {source_id: idx for idx, source_id in enumerate(ordered)}


def _rank_rehydration_sources(
    sources: list[RehydratedSource],
    query: str | None,
) -> list[RehydratedSource]:
    query_terms = _query_terms(query or "")
    if not query_terms:
        return sources[:DEFAULT_REHYDRATION_ITEMS]

    def score(source: RehydratedSource) -> tuple[int, str]:
        body = source.content.lower()
        overlap = sum(1 for term in query_terms if term in body)
        created = _datetime_sort_key(source.created_at).isoformat() if source.created_at else ""
        return (overlap, created)

    ranked = sorted(sources, key=score, reverse=True)
    return [source for source in ranked if score(source)[0] > 0] or ranked[:1]


def _query_terms(query: str) -> set[str]:
    return {term for term in re.findall(r"[a-zA-Z0-9_/-]{3,}", query.lower()) if term}


def _missing_source_ids(
    *,
    requested_memory_ids: Sequence[str],
    requested_turn_ids: Sequence[str],
    found: Sequence[RehydratedSource],
) -> list[str]:
    found_memory = {source.memory_id for source in found if source.memory_id}
    found_turn = {source.source_turn_id for source in found if source.source_turn_id}
    missing = [f"memory:{mid}" for mid in requested_memory_ids if mid not in found_memory]
    missing.extend(f"turn:{tid}" for tid in requested_turn_ids if tid not in found_turn)
    return missing


def _rehydration_reason(trigger: str, query: str | None, explicit_ids_supplied: bool) -> str:
    if trigger == "explicit":
        return "caller supplied source IDs for drill-to-raw expansion"
    if explicit_ids_supplied:
        return "heuristic expansion constrained to caller-supplied source IDs"
    if query:
        return "heuristic expansion ranked compacted sources by query overlap"
    return "heuristic expansion used digest provenance with no query terms"


def _digest_section_blocks(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if line in DIGEST_SECTION_NAMES:
            current = line
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(raw_line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}


def _extract_source_exchange_ids(text: str) -> list[str]:
    return _unique(
        [f"{match.group('prefix')}:{match.group('id')}" for match in SOURCE_EXCHANGE_RE.finditer(text or "")]
    )


def _ids_from_source_exchange_ids(source_exchange_ids: Sequence[str]) -> tuple[list[str], list[str]]:
    memory_ids: list[str | None] = []
    turn_ids: list[str | None] = []
    for value in source_exchange_ids:
        value = str(value or "")
        if value.startswith("memory:"):
            memory_ids.append(value.split(":", 1)[1])
        elif value.startswith("turn:"):
            turn_ids.append(value.split(":", 1)[1])
    return _unique(memory_ids), _unique(turn_ids)


def _combined_source_exchange_ids(
    source_memory_ids: Sequence[str],
    source_turn_ids: Sequence[str],
) -> list[str]:
    return [
        *(f"memory:{mid}" for mid in source_memory_ids if mid),
        *(f"turn:{tid}" for tid in source_turn_ids if tid),
    ]


def _coerce_uuid_list(values: Sequence[str]) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    for value in values:
        coerced = _coerce_uuid(str(value))
        if coerced is not None:
            out.append(coerced)
    return out


def _datetime_sort_key(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
