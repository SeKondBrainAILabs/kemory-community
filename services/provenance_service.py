"""
S9N Memory Vault — Provenance Service (MV2-E02)

Records every memory state change as an append-only event.
Provides query API for memory history.

Stories: MV2-S02.1 through S02.5
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.memory_event import MemoryEvent

logger = structlog.get_logger(__name__)


async def emit_event(
    db: AsyncSession,
    memory_id: uuid.UUID | str,
    event_type: str,
    *,
    actor_type: str = "system",
    actor_id: str | None = None,
    reason: str | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """
    Record a provenance event for a memory.

    Story: MV2-S02.2, MV2-S02.3

    Parameters
    ----------
    db: Database session
    memory_id: Memory this event relates to
    event_type: created, updated, deleted, accessed, demoted, promoted,
                consolidated, ttl_set, conflict_resolved, enriched, decayed
    actor_type: agent, user, system, enrichment, scheduler
    actor_id: Who performed the action
    reason: Why the change happened
    before_state: Partial state snapshot before change
    after_state: Partial state snapshot after change
    metadata: Additional context

    Returns
    -------
    str: Event ID
    """
    event = MemoryEvent(
        memory_id=uuid.UUID(str(memory_id)) if isinstance(memory_id, str) else memory_id,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        reason=reason,
        before_state=before_state,
        after_state=after_state,
        meta=metadata or {},
    )
    db.add(event)
    await db.flush()

    logger.debug(
        "provenance.event_emitted",
        event_id=str(event.event_id),
        memory_id=str(memory_id),
        event_type=event_type,
    )
    return str(event.event_id)


async def get_memory_history(
    db: AsyncSession,
    memory_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """
    Get provenance history for a memory, newest-first.

    Story: MV2-S02.4
    """
    result = await db.execute(
        select(MemoryEvent)
        .where(MemoryEvent.memory_id == memory_id)
        .order_by(desc(MemoryEvent.created_at))
        .limit(limit)
        .offset(offset)
    )
    events = result.scalars().all()

    return [
        {
            "event_id": str(e.event_id),
            "memory_id": str(e.memory_id),
            "event_type": e.event_type,
            "actor_type": e.actor_type,
            "actor_id": e.actor_id,
            "reason": e.reason,
            "before_state": e.before_state,
            "after_state": e.after_state,
            "metadata": e.meta,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]


async def get_last_event(
    db: AsyncSession,
    memory_id: uuid.UUID,
) -> dict[str, Any] | None:
    """
    Get the most recent provenance event for a memory.

    Story: MV2-S02.5
    """
    result = await db.execute(
        select(MemoryEvent)
        .where(MemoryEvent.memory_id == memory_id)
        .order_by(desc(MemoryEvent.created_at))
        .limit(1)
    )
    event = result.scalar_one_or_none()
    if not event:
        return None

    return {
        "event_type": event.event_type,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "reason": event.reason,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
