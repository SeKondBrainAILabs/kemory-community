"""
S9N Memory Vault — Memory Event Model (MV2-S02.1)

Records every state change on a memory for full provenance:
who changed what, when, and why.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Index, String, Text

from backend.core.database import Base
from backend.core.types import GUID, JSONType


class MemoryEvent(Base):
    """
    A single provenance event for a memory.

    Events are append-only — never updated or deleted.
    They form a complete audit trail of every memory lifecycle transition.
    """

    __tablename__ = "memory_events"

    event_id = Column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Unique event identifier",
    )
    memory_id = Column(
        GUID(),
        nullable=False,
        index=True,
        comment="Memory this event relates to (FK to kora_memories)",
    )

    # Event classification
    event_type = Column(
        String(50),
        nullable=False,
        comment="created, updated, deleted, accessed, demoted, promoted, "
        "consolidated, ttl_set, conflict_resolved, enriched, decayed",
    )

    # Actor
    actor_type = Column(
        String(20),
        nullable=False,
        default="system",
        comment="agent, user, system, enrichment, scheduler",
    )
    actor_id = Column(
        String(200),
        nullable=True,
        comment="Agent ID, user ID, or system component name",
    )

    # Context
    reason = Column(
        Text,
        nullable=True,
        comment="Why this change happened (e.g. 'decay_score fell to 0.32')",
    )

    # State snapshots (JSONB in Postgres, TEXT JSON in SQLite)
    before_state = Column(
        JSONType(),
        nullable=True,
        comment="Memory state before the change (partial snapshot)",
    )
    after_state = Column(
        JSONType(),
        nullable=True,
        comment="Memory state after the change (partial snapshot)",
    )

    # Extra metadata
    meta = Column(
        "metadata",
        JSONType(),
        nullable=True,
        default=dict,
        comment="Additional event context",
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("idx_events_memory_id", "memory_id"),
        Index("idx_events_type", "event_type"),
        Index("idx_events_created", "created_at"),
    )

    def __repr__(self):
        return f"<MemoryEvent(event_id={self.event_id}, memory_id={self.memory_id}, type={self.event_type})>"
