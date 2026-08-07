"""Rolling session digest model (S9N-6291).

Stores the compacted, readable context tail for one
``(org_id, user_id, namespace, session_id)``. It is intentionally separate
from ``SessionSummary``: that table is an L3 historical/session rollup,
while this table is a rolling prompt-budget control surface.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, UniqueConstraint

from backend.core.database import Base
from backend.core.types import GUID, JSONType


class SessionDigest(Base):
    """Readable digest of older exchanges while the latest tail stays raw."""

    __tablename__ = "kemory_session_digests"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4, nullable=False)
    org_id = Column(String(64), nullable=False)
    user_id = Column(GUID(), nullable=False)
    namespace = Column(String(100), nullable=False)
    session_id = Column(String(200), nullable=False)

    digest = Column(Text, nullable=True)
    digest_tier = Column(String(20), nullable=False, default="L2.1")
    source_exchange_ids = Column(JSONType(), nullable=False, default=list)
    source_turn_ids = Column(JSONType(), nullable=False, default=list)
    source_memory_ids = Column(JSONType(), nullable=False, default=list)
    compacted_exchange_count = Column(Integer, nullable=False, default=0)
    raw_tail_count = Column(Integer, nullable=False, default=3)

    token_budget = Column(Integer, nullable=False, default=900)
    token_count = Column(Integer, nullable=False, default=0)
    tokenizer_model = Column(String(100), nullable=True)
    tokenizer_name = Column(String(100), nullable=True)
    token_count_method = Column(String(100), nullable=False, default="fallback_chars_per_token_3")

    last_source_created_at = Column(DateTime(timezone=True), nullable=True)
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
            "org_id",
            "user_id",
            "namespace",
            "session_id",
            name="uq_session_digest_org_user_ns_session",
        ),
        Index("ix_session_digest_org_user_ns", "org_id", "user_id", "namespace"),
        Index("ix_session_digest_org_session", "org_id", "session_id"),
        Index("ix_session_digest_updated_at", "updated_at"),
    )
