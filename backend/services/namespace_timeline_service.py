"""Unified, source-ordered timeline for one community namespace."""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import String, and_, cast, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from backend.models.agent import AgentRegistry
from backend.models.ai_chat import AIChat, AIChatArtifact, AIChatTurn
from backend.models.memory import Memory

PREVIEW_CHARS = 240
DEFAULT_LIMIT = 40
MAX_LIMIT = 100
VALID_KINDS = frozenset({"chat", "memory"})


class TimelineEntry(BaseModel):
    kind: str
    id: str
    occurred_at: str
    namespace: str
    platform: str
    namespace_tag: str | None = None

    title: str | None = None
    turn_count: int | None = None
    artifact_count: int | None = None
    memory_count: int | None = None

    preview: str | None = None
    memory_type: str | None = None
    source_chat_id: str | None = None
    source_turn_id: str | None = None


class TimelineResponse(BaseModel):
    namespace: str
    items: list[TimelineEntry]
    limit: int
    has_more: bool = False
    next_cursor: str | None = None


def _encode_cursor(occurred_at: datetime | str, kind: str, entry_id: str) -> str:
    timestamp = occurred_at.isoformat() if isinstance(occurred_at, datetime) else str(occurred_at)
    value = f"{timestamp}|{kind}|{entry_id}".encode()
    return base64.urlsafe_b64encode(value).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, str, str] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        timestamp, kind, entry_id = raw.split("|", 2)
        if kind not in VALID_KINDS:
            return None
        return datetime.fromisoformat(timestamp), kind, entry_id
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return None


def _parse_types(types: str | None) -> set[str]:
    if not types:
        return set(VALID_KINDS)
    requested = {value.strip().lower() for value in types.split(",") if value.strip()}
    return requested & VALID_KINDS


def _platform_from_agent(agent_name: str | None) -> str:
    value = (agent_name or "").lower()
    if "claude" in value:
        return "claude"
    if any(name in value for name in ("codex", "chatgpt", "openai", "gpt")):
        return "chatgpt"
    if "gemini" in value or "google" in value:
        return "gemini"
    if "manus" in value:
        return "manus"
    if "cursor" in value:
        return "cursor"
    return "other"


async def get_namespace_timeline(
    user_id: uuid.UUID,
    namespace: str,
    db: AsyncSession,
    *,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
    types: str | None = None,
) -> TimelineResponse:
    """Return chats and memories on one newest-first source-time axis."""
    limit = max(1, min(limit, MAX_LIMIT))
    kinds = _parse_types(types)
    if not kinds:
        return TimelineResponse(namespace=namespace, items=[], limit=limit)

    legs = []
    if "chat" in kinds:
        legs.append(
            select(
                literal("chat").label("kind"),
                cast(AIChat.chat_id, String).label("id"),
                func.coalesce(AIChat.captured_at, AIChat.created_at).label("occurred_at"),
            ).where(
                AIChat.user_id == user_id,
                AIChat.invalid_at.is_(None),
                AIChat.namespace == namespace,
            )
        )
    if "memory" in kinds:
        source_chat = aliased(AIChat)
        legs.append(
            select(
                literal("memory").label("kind"),
                cast(Memory.memory_id, String).label("id"),
                func.coalesce(
                    Memory.occurred_at,
                    source_chat.captured_at,
                    source_chat.created_at,
                    Memory.created_at,
                ).label("occurred_at"),
            )
            .select_from(Memory)
            .outerjoin(
                source_chat,
                and_(
                    source_chat.chat_id == Memory.source_chat_id,
                    source_chat.user_id == user_id,
                ),
            )
            .where(
                Memory.user_id == user_id,
                Memory.invalid_at.is_(None),
                Memory.namespace == namespace,
            )
        )

    unified = (legs[0] if len(legs) == 1 else union_all(*legs)).subquery("timeline")
    kind_col, id_col, time_col = unified.c.kind, unified.c.id, unified.c.occurred_at
    query = select(kind_col, id_col, time_col)
    decoded = _decode_cursor(cursor) if cursor else None
    if decoded is not None:
        cursor_time, cursor_kind, cursor_id = decoded
        query = query.where(
            or_(
                time_col < cursor_time,
                and_(time_col == cursor_time, id_col < cursor_id),
                and_(
                    time_col == cursor_time,
                    id_col == cursor_id,
                    kind_col < cursor_kind,
                ),
            )
        )
    query = query.order_by(time_col.desc(), id_col.desc(), kind_col.desc()).limit(limit + 1)

    # The global tenancy listener cannot safely rewrite a UNION containing an
    # aliased outer join: its source-chat predicate turns direct memories into
    # non-matches. This service already scopes both legs by the authenticated
    # user, and hydration only receives IDs from those scoped legs.
    from backend.core.tenancy import bypass_tenant_filter

    with bypass_tenant_filter():
        rows = (await db.execute(query)).all()
        has_more = len(rows) > limit
        page = rows[:limit]
        chat_ids = [uuid.UUID(row.id) for row in page if row.kind == "chat"]
        memory_ids = [uuid.UUID(row.id) for row in page if row.kind == "memory"]
        chats = await _hydrate_chats(db, chat_ids)
        memories = await _hydrate_memories(db, memory_ids, user_id)

    items: list[TimelineEntry] = []
    for row in page:
        occurred_at = (
            row.occurred_at.isoformat() if isinstance(row.occurred_at, datetime) else str(row.occurred_at)
        )
        if row.kind == "chat":
            chat = chats.get(row.id)
            if chat is None:
                continue
            items.append(
                TimelineEntry(
                    kind="chat",
                    id=row.id,
                    occurred_at=occurred_at,
                    namespace=namespace,
                    **chat,
                )
            )
        else:
            memory = memories.get(row.id)
            if memory is None:
                continue
            items.append(
                TimelineEntry(
                    kind="memory",
                    id=row.id,
                    occurred_at=occurred_at,
                    namespace=namespace,
                    **memory,
                )
            )

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor(last.occurred_at, last.kind, last.id)
    return TimelineResponse(
        namespace=namespace,
        items=items,
        limit=limit,
        has_more=has_more,
        next_cursor=next_cursor,
    )


async def _hydrate_chats(db: AsyncSession, chat_ids: list[uuid.UUID]) -> dict[str, dict]:
    if not chat_ids:
        return {}

    rows = (await db.execute(select(AIChat).where(AIChat.chat_id.in_(chat_ids)))).scalars().all()
    turn_counts = dict(
        (
            await db.execute(
                select(AIChatTurn.chat_id, func.count())
                .where(AIChatTurn.chat_id.in_(chat_ids))
                .group_by(AIChatTurn.chat_id)
            )
        ).all()
    )
    artifact_counts = dict(
        (
            await db.execute(
                select(AIChatArtifact.chat_id, func.count())
                .where(AIChatArtifact.chat_id.in_(chat_ids))
                .group_by(AIChatArtifact.chat_id)
            )
        ).all()
    )
    memory_counts = dict(
        (
            await db.execute(
                select(Memory.source_chat_id, func.count())
                .where(Memory.source_chat_id.in_(chat_ids), Memory.invalid_at.is_(None))
                .group_by(Memory.source_chat_id)
            )
        ).all()
    )

    return {
        str(chat.chat_id): {
            "platform": chat.platform,
            "title": chat.title,
            "turn_count": int(turn_counts.get(chat.chat_id, 0)),
            "artifact_count": int(artifact_counts.get(chat.chat_id, 0)),
            "memory_count": int(memory_counts.get(chat.chat_id, 0)),
            "namespace_tag": chat.namespace_tag,
        }
        for chat in rows
    }


async def _hydrate_memories(
    db: AsyncSession,
    memory_ids: list[uuid.UUID],
    user_id: uuid.UUID,
) -> dict[str, dict]:
    if not memory_ids:
        return {}

    rows = (
        await db.execute(
            select(
                Memory.memory_id,
                Memory.content,
                Memory.content_type,
                Memory.source_chat_id,
                Memory.source_turn_id,
                Memory.namespace_tag,
                AgentRegistry.agent_name,
                AIChat.platform.label("source_chat_platform"),
            )
            .outerjoin(
                AgentRegistry,
                and_(
                    AgentRegistry.agent_id == Memory.source_agent_id,
                    AgentRegistry.user_id == user_id,
                ),
            )
            .outerjoin(
                AIChat,
                and_(AIChat.chat_id == Memory.source_chat_id, AIChat.user_id == user_id),
            )
            .where(Memory.memory_id.in_(memory_ids))
        )
    ).all()

    output: dict[str, dict] = {}
    for row in rows:
        content = row.content or ""
        preview = content[:PREVIEW_CHARS] + ("..." if len(content) > PREVIEW_CHARS else "")
        output[str(row.memory_id)] = {
            "platform": row.source_chat_platform or _platform_from_agent(row.agent_name),
            "preview": preview,
            "memory_type": row.content_type,
            "source_chat_id": str(row.source_chat_id) if row.source_chat_id else None,
            "source_turn_id": str(row.source_turn_id) if row.source_turn_id else None,
            "namespace_tag": row.namespace_tag,
        }
    return output
