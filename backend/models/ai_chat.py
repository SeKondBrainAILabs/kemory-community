"""
Kemory — AI Chats module models (chats-v1).

Stores raw conversations pushed by the Kanvas Chrome Extension (and any
future ingest source). Memory extraction from these chats is intentionally
out of scope for v1 — the ``source_chat_id`` / ``source_turn_id`` columns
on :class:`backend.models.memory.Memory` are the forward-compat hooks that
phase 2 will populate.

Four tables:
  * ``kemory_ai_chats``                  — one row per source conversation
  * ``kemory_ai_chat_turns``             — one row per message turn
  * ``kemory_ai_chat_artifacts``         — code/file/image artifacts per turn
  * ``kemory_chat_namespace_mappings``   — explicit project→namespace overrides

Every table carries ``org_id NOT NULL`` and is registered in
``backend/core/tenancy.py::TENANT_SCOPED_MODEL_NAMES`` so the global
``do_orm_execute`` filter scopes SELECTs to the caller's org automatically.

Idempotency primitives:
  * ``AIChat`` is unique by ``(user_id, platform, platform_conversation_id)``
    so re-pushes from the extension update in place instead of duplicating.
  * ``AIChat.content_hash`` is the SHA-256 of the canonicalised turn list;
    a re-push that hashes identically is a no-op (handled in
    ``ai_chat_service.upsert_chat``).
  * ``AIChatTurn`` is unique by ``(chat_id, source_turn_id)`` when
    ``source_turn_id`` is set — lets the extension append turn-by-turn
    without bookkeeping its own id space.

Migration: ``backend/migrations/versions/015_ai_chats_module.py``.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from backend.core.database import Base
from backend.core.types import GUID, JSONType


class AIChat(Base):
    """A raw conversation captured from an external LLM tool.

    One row per (user, platform, external conversation id). Re-pushes from
    the extension are idempotent: the upsert path matches on the unique
    constraint and updates ``updated_at`` only when ``content_hash``
    differs.
    """

    __tablename__ = "kemory_ai_chats"

    chat_id = Column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Internal chat id.",
    )
    user_id = Column(GUID(), nullable=False, index=True)
    org_id = Column(
        String(64),
        nullable=False,
        comment="Tenant id. Always read from AuthContext, never request headers.",
    )

    platform = Column(
        String(32),
        nullable=False,
        comment="chatgpt | claude | gemini | manus | other",
    )
    platform_conversation_id = Column(
        String(255),
        nullable=False,
        comment="External conversation id reported by the source tool.",
    )
    source_project_id = Column(
        String(255),
        nullable=True,
        comment="ChatGPT Project / Claude Project id when present.",
    )
    source_project_name = Column(
        String(500),
        nullable=True,
        comment="Human-readable project name (used by mapping fallback / debug).",
    )

    namespace = Column(
        String(100),
        nullable=False,
        comment="Resolved Kemory namespace (post mapping/matcher).",
    )
    requested_namespace = Column(
        String(100),
        nullable=True,
        comment="Caller-supplied namespace when the matcher auto-redirected.",
    )

    title = Column(String(500), nullable=True)
    model = Column(String(100), nullable=True)
    chat_metadata = Column(JSONType(), nullable=True)

    content_hash = Column(
        String(64),
        nullable=False,
        comment="SHA-256 of canonicalised turn list. Skip noop updates.",
    )

    captured_at = Column(DateTime(timezone=True), nullable=True)

    source_type = Column(
        String(32),
        nullable=False,
        default="extension",
        comment="extension | import | manual",
    )
    installation_id = Column(
        GUID(),
        nullable=True,
        comment="Which extension install pushed this chat (per-device revoke).",
    )

    invalid_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Soft-delete timestamp. NULL = active.",
    )

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
            "platform",
            "platform_conversation_id",
            name="uq_ai_chats_user_platform_convid",
        ),
        Index("idx_ai_chats_org_user", "org_id", "user_id"),
        Index("idx_ai_chats_namespace", "namespace"),
        Index("idx_ai_chats_captured", "user_id", "captured_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<AIChat(chat_id={self.chat_id}, platform={self.platform}, "
            f"namespace={self.namespace}, turns?)>"
        )


class AIChatTurn(Base):
    """One message turn within an :class:`AIChat`.

    The extension may push turns in a single batch with the parent chat,
    or stream them as the user reads the conversation. Both paths use the
    same upsert: when ``source_turn_id`` is set, the unique constraint
    ``(chat_id, source_turn_id)`` makes the write idempotent.
    """

    __tablename__ = "kemory_ai_chat_turns"

    turn_id = Column(GUID(), primary_key=True, default=uuid.uuid4, nullable=False)
    chat_id = Column(
        GUID(),
        ForeignKey("kemory_ai_chats.chat_id", ondelete="CASCADE"),
        nullable=False,
    )
    # Denormalised so the tenant filter doesn't have to traverse a join.
    user_id = Column(GUID(), nullable=False, index=True)
    org_id = Column(String(64), nullable=False)

    source_turn_id = Column(
        String(255),
        nullable=True,
        comment="External per-turn id (data-message-id etc.).",
    )
    parent_turn_id = Column(
        GUID(),
        nullable=True,
        comment="For ChatGPT branching trees. v1 reads turns as a flat sequence.",
    )

    role = Column(
        String(20),
        nullable=False,
        comment="user | assistant | system | tool",
    )
    content = Column(Text(), nullable=False)
    content_html = Column(Text(), nullable=True)
    thinking_content = Column(Text(), nullable=True)
    tool_calls = Column(JSONType(), nullable=True)
    turn_metadata = Column(JSONType(), nullable=True)
    sequence = Column(Integer(), nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "source_turn_id",
            name="uq_ai_chat_turns_chat_sourceid",
        ),
        Index("idx_ai_chat_turns_chat_seq", "chat_id", "sequence"),
        Index("idx_ai_chat_turns_org_user", "org_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<AIChatTurn(turn_id={self.turn_id}, role={self.role}, seq={self.sequence})>"


class AIChatArtifact(Base):
    """A code block / file / image / Claude Artifact.

    v3.35.0 generalisation: artifacts can now live at three granularities:

      1. **Chat-turn** (existing) — both ``chat_id`` and ``turn_id`` set.
      2. **Memory-attached** — ``memory_id`` set; ``chat_id`` / ``turn_id`` NULL.
      3. **Namespace-level** (standalone project file) — only ``namespace``
         set; ``chat_id`` / ``turn_id`` / ``memory_id`` all NULL.

    ``namespace`` is always NOT NULL (back-filled from the parent chat for
    rows written before v3.35.0).

    For text artifacts the payload is stored inline in ``content`` (capped at
    ~1 MB at the service layer).  Binary artifacts (images, audio, video,
    arbitrary files) are stored in object storage and the key is held in
    ``artifact_metadata['storage_key']``.  ``content_url`` is either a
    short-lived HMAC-signed URL regenerated on read, or a legacy external URL
    passed through as-is.

    Migration: ``backend/migrations/versions/016_namespace_artifacts.py``.
    """

    __tablename__ = "kemory_ai_chat_artifacts"

    artifact_id = Column(GUID(), primary_key=True, default=uuid.uuid4, nullable=False)
    # Nullable since v3.35.0 — NULL for namespace/memory artifacts.
    turn_id = Column(
        GUID(),
        ForeignKey("kemory_ai_chat_turns.turn_id", ondelete="CASCADE"),
        nullable=True,
        comment="FK to kemory_ai_chat_turns. NULL for namespace/memory artifacts.",
    )
    chat_id = Column(
        GUID(),
        ForeignKey("kemory_ai_chats.chat_id", ondelete="CASCADE"),
        nullable=True,
        comment="FK to kemory_ai_chats. NULL for namespace/memory artifacts.",
    )
    user_id = Column(GUID(), nullable=False, index=True)
    org_id = Column(String(64), nullable=False)

    # Always set (backfilled from parent chat for pre-v3.35.0 rows).
    namespace = Column(
        String(100),
        nullable=False,
        comment="Kemory namespace this artifact belongs to.",
    )

    # Optional FK for memory-attached artifacts (v3.35.0).
    memory_id = Column(
        GUID(),
        ForeignKey("kemory_memories.memory_id", ondelete="CASCADE"),
        nullable=True,
        comment="FK to kemory_memories. Set for memory-attached artifacts.",
    )

    # Source project provenance — mirrors kemory_ai_chats columns (v3.35.0).
    source_project_id = Column(String(255), nullable=True)
    source_project_name = Column(String(500), nullable=True)
    source_platform = Column(String(50), nullable=True)

    artifact_type = Column(
        String(32),
        nullable=False,
        comment="code | image | file | react | html | svg | audio | video",
    )
    language = Column(String(50), nullable=True)
    content = Column(Text(), nullable=True)
    content_url = Column(String(1000), nullable=True)
    content_sha256 = Column(String(64), nullable=False)
    artifact_metadata = Column(JSONType(), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("idx_ai_chat_artifacts_turn", "turn_id"),
        Index("idx_ai_chat_artifacts_chat", "chat_id"),
        Index("idx_ai_chat_artifacts_org_user", "org_id", "user_id"),
        # v3.35.0 indices (also created by migration 016)
        Index("ix_artifacts_user_namespace", "user_id", "namespace"),
    )

    def __repr__(self) -> str:
        return (
            f"<AIChatArtifact(artifact_id={self.artifact_id}, "
            f"type={self.artifact_type}, namespace={self.namespace})>"
        )


class ChatNamespaceMapping(Base):
    """User-defined ``(platform, project) → namespace`` override.

    When an :class:`AIChat` ingest matches one of these rows the resolved
    namespace is the mapping's ``target_namespace`` and the namespace
    matcher is skipped. Many source projects can collapse onto one Kemory
    namespace simply by inserting multiple rows pointing at the same
    ``target_namespace``.

    Precedence (low → high priority numbers evaluated first):
      1. Exact ``(platform, source_project_id)`` match
      2. ``platform`` match + case-insensitive substring match on
         ``source_project_name_pattern``
    """

    __tablename__ = "kemory_chat_namespace_mappings"

    mapping_id = Column(GUID(), primary_key=True, default=uuid.uuid4, nullable=False)
    user_id = Column(GUID(), nullable=False, index=True)
    org_id = Column(String(64), nullable=False)

    platform = Column(String(32), nullable=False)
    source_project_id = Column(String(255), nullable=True)
    source_project_name_pattern = Column(String(500), nullable=True)

    target_namespace = Column(String(100), nullable=False)
    priority = Column(Integer(), nullable=False, default=100)
    enabled = Column(Boolean(), nullable=False, default=True)

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
        Index("idx_chat_ns_mappings_user_platform", "user_id", "platform"),
        Index("idx_chat_ns_mappings_org_user", "org_id", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ChatNamespaceMapping(platform={self.platform}, "
            f"project_id={self.source_project_id!r}, "
            f"target_namespace={self.target_namespace})>"
        )
