"""
S9N Memory Vault — Session Summary Model (F12 v2)

Per-session L3 rollup. Each row pairs a (user, namespace, session) with two
LLM summaries:

  * session_summary    — L3 Groq narrative over memories IN this session only.
                         Useful for "what happened in this session" resume UX.
  * cumulative_summary — L3 Groq narrative over all namespace memories with
                         created_at ≤ up_to_ts. A point-in-time snapshot of
                         the namespace state as of this session's boundary.

Architectural note:
  This complements NamespacePolicy.consolidated_summary (which is always the
  "live" namespace-wide summary). The session table is an append-over-time
  log of per-session rollups — each row freezes once the session stops
  receiving new memories, giving agents an answer to "what was the world
  like when that session ended?"

Story: F12 v2 — session-aware L3
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from backend.core.database import Base
from backend.core.types import GUID


class SessionSummary(Base):
    """Per-(user, namespace, session) L3 summary pair.

    Primary key: `id` (UUID).
    Unique:      (user_id, namespace, session_id).

    session_summary     — rollup over memories where session_id matches
                          (exactly this session, regardless of recency).
    cumulative_summary  — rollup over all active memories in the namespace
                          with created_at ≤ up_to_ts (point-in-time snapshot).
    """

    __tablename__ = "kemory_session_summary"

    # ── Identity ──────────────────────────────────────────────────
    id = Column(GUID(), primary_key=True, default=uuid.uuid4, nullable=False)
    user_id = Column(GUID(), nullable=False)
    namespace = Column(String(100), nullable=False)
    session_id = Column(String(200), nullable=False)

    # ── Session-only rollup ───────────────────────────────────────
    session_summary = Column(Text, nullable=True)
    session_summary_tier = Column(String(8), nullable=True)  # "L3" today
    session_memory_count = Column(Integer, nullable=False, default=0)

    # ── Cumulative (namespace up to up_to_ts) rollup ──────────────
    cumulative_summary = Column(Text, nullable=True)
    cumulative_summary_tier = Column(String(8), nullable=True)  # "L3"
    cumulative_memory_count = Column(Integer, nullable=False, default=0)

    # Anchor: max(created_at) of memories reflected in cumulative summary.
    # For active sessions this advances; for past sessions it freezes.
    up_to_ts = Column(DateTime(timezone=True), nullable=True)

    # ── Timestamps ────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "namespace",
            "session_id",
            name="uq_session_summary_user_ns_session",
        ),
        Index("ix_session_summary_user_ns", "user_id", "namespace"),
        Index("ix_session_summary_session", "user_id", "session_id"),
        Index("ix_session_summary_updated_at", "updated_at"),
    )
