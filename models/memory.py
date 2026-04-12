"""
S9N Memory Vault — Unified Memory Model (MV2-S01.2)

Single storage table that supports both REST API and core library operations.
Merges s9nmv_memories (REST) and episodes (core library) schemas.

Bi-temporal model: valid_at (when fact became true) + invalid_at (soft delete).
Replaces the legacy is_deleted/deleted_at pattern.

Spec reference: docs/mv2-schema-audit.md
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, DateTime, Integer, Float, Text, Index, text
)
from sqlalchemy.dialects.postgresql import ARRAY as _PG_ARRAY
from backend.core.database import Base
from backend.core.types import GUID, JSONType


class Memory(Base):
    """
    Unified memory record — serves both REST API and core library.

    Every memory:
    - Belongs to a user (user_id) and a namespace
    - Has text content with optional structured metadata
    - Supports bi-temporal validity (valid_at / invalid_at)
    - Tracks provenance (source agent, session, round)
    - Has enrichment pipeline integration (quality score, status)
    - Supports TTL, versioning, and decay-based forgetting
    """
    __tablename__ = "s9nmv_memories"

    # ── Identity ──────────────────────────────────────────────────
    memory_id = Column(
        GUID(), primary_key=True, default=uuid.uuid4, nullable=False,
        comment="Unique identifier (UUID v4)",
    )
    user_id = Column(
        GUID(), nullable=False, index=True,
        comment="Owner user ID (maps to org_id in core library)",
    )

    # ── Content ───────────────────────────────────────────────────
    namespace = Column(
        String(100), nullable=False,
        comment="Namespace: 'shared', 'user:preferences', 'agent:name:private'",
    )
    content = Column(
        Text, nullable=False,
        comment="Memory content (text, up to 100k chars)",
    )
    content_type = Column(
        String(50), nullable=False, default="text",
        comment="text, structured, conversation, fact, preference, embedding",
    )
    content_hash = Column(
        String(64), nullable=False,
        comment="SHA-256 hex digest of normalised content for deduplication (S9N-DEDUP)",
    )
    meta = Column(
        "metadata", JSONType(), nullable=True, default=dict,
        comment="Structured metadata: tags, categories, custom fields",
    )

    # ── Provenance ────────────────────────────────────────────────
    source_agent_id = Column(
        GUID(), nullable=True,
        comment="Agent that created this memory (NULL if user-created)",
    )
    source_type = Column(
        String(50), nullable=False, default="agent",
        comment="How created: agent, user, import, enrichment",
    )
    session_id = Column(
        String(200), nullable=True,
        comment="Session context identifier (from core library)",
    )
    round_id = Column(
        String(200), nullable=True,
        comment="Round/turn identifier within a session (V2-E07)",
    )

    # ── Enrichment ────────────────────────────────────────────────
    quality_score = Column(
        Float, nullable=True,
        comment="Quality score from enrichment pipeline (0.0-1.0)",
    )
    enrichment_status = Column(
        String(20), nullable=False, default="pending",
        comment="pending, processing, completed, failed, skipped",
    )
    facts = Column(
        Text, nullable=True, default="[]",
        comment="JSON array of extracted facts for FTS5 key expansion (V2-E07)",
    )
    temporal_anchor = Column(
        String(20), nullable=True,
        comment="ISO date YYYY-MM-DD extracted from content (V2-E08)",
    )

    # ── Versioning & TTL ──────────────────────────────────────────
    version = Column(
        Integer, nullable=False, default=1,
        comment="Version number, incremented on each update",
    )
    ttl_seconds = Column(
        Integer, nullable=True,
        comment="Time-to-live in seconds. NULL = no expiry.",
    )
    expires_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="Computed expiry time (created_at + ttl_seconds)",
    )

    # ── Bi-temporal + Forgetting ──────────────────────────────────
    # ── Lifecycle Tier (MV2-E03) ────────────────────────────────
    tier = Column(
        String(20), nullable=False, default="active",
        comment="Lifecycle tier: active, demoted, deleted (MV2-E03)",
    )

    # ── Visibility (MV3-E01) ──────────────────────────────────
    visibility = Column(
        String(20), nullable=False, default="user-private",
        comment="Visibility tier: agent-private, user-private, team, org-public (MV3-E01)",
    )
    team_id = Column(
        GUID(), nullable=True,
        comment="Team this memory belongs to (when visibility='team')",
    )

    valid_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="When the fact became true (bi-temporal model)",
    )
    invalid_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="When soft-deleted or invalidated (NULL = active)",
    )
    decay_score = Column(
        Float, nullable=True, default=1.0,
        comment="Relevance decay score (0.0-1.0), 30-day half-life (V2-E04)",
    )
    last_accessed_at = Column(
        DateTime(timezone=True), nullable=True,
        comment="Last access timestamp for utility salience (V2-E07)",
    )
    access_count = Column(
        Integer, nullable=False, default=0,
        comment="Number of times this memory was accessed (MV2-E07)",
    )

    # ── Hybrid Search (S9N-3074) ──────────────────────────────────
    embedding = Column(
        _PG_ARRAY(Float),
        nullable=True,
        comment=(
            "384-dim L2-normalised embedding vector "
            "(sentence-transformers/all-MiniLM-L6-v2). "
            "NULL until enrichment worker backfills. Story: S9N-3074-SUB1"
        ),
    )
    embedding_model = Column(
        String(100),
        nullable=True,
        server_default="all-MiniLM-L6-v2",
        comment="Model ID used to generate the embedding. Story: S9N-3074-SUB1",
    )

    # ── Timestamps ────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # ── Backward compatibility ────────────────────────────────────
    @property
    def is_deleted(self) -> bool:
        """Backward compat: True when invalid_at is set."""
        return self.invalid_at is not None

    @property
    def deleted_at(self) -> datetime | None:
        """Backward compat: returns invalid_at."""
        return self.invalid_at

    __table_args__ = (
        Index("idx_memories_user_namespace", "user_id", "namespace"),
        Index("idx_memories_user_type", "user_id", "content_type"),
        Index("idx_memories_enrichment", "enrichment_status"),
        Index("idx_memories_session", "session_id"),
        Index("idx_memories_round", "round_id"),
        Index("idx_memories_temporal", "temporal_anchor"),
        Index("idx_memories_decay", "decay_score"),
        Index(
            "uq_memories_user_ns_hash",
            "user_id", "namespace", "content_hash",
            unique=True,
            postgresql_where=text("invalid_at IS NULL"),
        ),
    )

    def __repr__(self):
        return f"<Memory(memory_id={self.memory_id}, namespace={self.namespace}, v={self.version})>"
