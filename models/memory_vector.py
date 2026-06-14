"""Tenant-scoped vector index rows for pluggable vector backends."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Index, String

from backend.core.database import Base
from backend.core.types import GUID, JSONType, VectorEmbedding


class MemoryVector(Base):
    """Embedding payload keyed by memory, user, and tenant."""

    __tablename__ = "kemory_memory_vectors"

    memory_id = Column(GUID(), primary_key=True, default=uuid.uuid4, nullable=False)
    user_id = Column(GUID(), primary_key=True, nullable=False, index=True)
    org_id = Column(String(64), primary_key=True, nullable=False, index=True)
    namespace = Column(String(100), nullable=False, index=True)
    embedding = Column(VectorEmbedding(dimension=384), nullable=True)
    meta = Column("metadata", JSONType(), nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("idx_memory_vectors_org_user_namespace", "org_id", "user_id", "namespace"),
    )
