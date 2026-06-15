"""AI Chats module (chats-v1): raw conversation ingest from the Kanvas
Chrome Extension, plus namespace mapping overrides and extension-kind
agents.

This migration stands up the storage backing for the AI Chats module.
The extension scrapes conversations + turns + artifacts from
ChatGPT / Claude / Gemini etc. and pushes them to Kemory. Memory
extraction from those chats is an explicit non-goal for v1; the
``source_chat_id`` / ``source_turn_id`` columns on ``kemory_memories``
are forward-compat so the next phase needs no schema change.

What this migration does:
  * Adds ``agent_kind`` column to ``kemory_agent_registry`` so we can
    distinguish extension keys ('extension') from regular agent keys
    ('agent') without forking the auth path. Extension installs are
    just agents — same AgentRegistry row, same X-API-Key flow, same
    Gatekeeper checks, same tenancy.
  * Creates ``kemory_ai_chats`` — one row per source conversation
    (unique by user + platform + platform_conversation_id).
  * Creates ``kemory_ai_chat_turns`` — one row per message turn
    (unique by chat + source_turn_id when supplied).
  * Creates ``kemory_ai_chat_artifacts`` — code blocks, files,
    images attached to a turn. Inline ``content`` for text; the
    ``content_url`` column is reserved for an S3 backend later (v1
    keeps everything in Postgres).
  * Creates ``kemory_chat_namespace_mappings`` — explicit
    (platform, source_project_id) → target_namespace overrides that
    bypass the namespace matcher. Many source projects can map to
    one namespace (just multiple rows).
  * Adds ``source_chat_id`` + ``source_turn_id`` nullable FK columns
    to ``kemory_memories`` (forward-compat, no backfill).

Tenancy: every new table carries ``org_id NOT NULL VARCHAR(64)`` and
is registered in ``TENANT_SCOPED_MODEL_NAMES`` (backend/core/tenancy.py)
so the global ``do_orm_execute`` listener filters reads automatically.

Revision ID: 015
"""

import sqlalchemy as sa
from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def _uuid_type(bind):
    """Dialect-aware UUID type. Mirrors backend.core.types.GUID."""
    if bind.dialect.name == "postgresql":
        return sa.dialects.postgresql.UUID(as_uuid=True)
    return sa.CHAR(36)


def _json_type(bind):
    """Dialect-aware JSON type. Mirrors backend.core.types.JSONType."""
    if bind.dialect.name == "postgresql":
        return sa.dialects.postgresql.JSONB()
    return sa.Text()


def upgrade() -> None:
    bind = op.get_bind()
    uuid_t = _uuid_type(bind)
    json_t = _json_type(bind)

    # ── 1) Extend kemory_agent_registry with agent_kind ────────────────
    op.add_column(
        "kemory_agent_registry",
        sa.Column(
            "agent_kind",
            sa.String(length=20),
            nullable=False,
            server_default="agent",
            comment=(
                "Distinguishes regular MCP/agent keys ('agent') from Chrome "
                "Extension installs ('extension'). Auth path is identical; "
                "kind only affects which mint/list endpoints surface the row."
            ),
        ),
    )
    op.create_index(
        "idx_agent_registry_kind",
        "kemory_agent_registry",
        ["user_id", "agent_kind"],
    )

    # ── 2) kemory_ai_chats ─────────────────────────────────────────────
    op.create_table(
        "kemory_ai_chats",
        sa.Column("chat_id", uuid_t, primary_key=True),
        sa.Column("user_id", uuid_t, nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column(
            "platform",
            sa.String(length=32),
            nullable=False,
            comment="chatgpt | claude | gemini | manus | other",
        ),
        sa.Column(
            "platform_conversation_id",
            sa.String(length=255),
            nullable=False,
            comment="External conversation id reported by the source tool.",
        ),
        sa.Column(
            "source_project_id",
            sa.String(length=255),
            nullable=True,
            comment="ChatGPT Project / Claude Project id when known.",
        ),
        sa.Column(
            "source_project_name",
            sa.String(length=500),
            nullable=True,
            comment="Human-readable project name (used by mapping fallback).",
        ),
        sa.Column(
            "namespace",
            sa.String(length=100),
            nullable=False,
            comment="Resolved Kemory namespace (post mapping/matcher).",
        ),
        sa.Column(
            "requested_namespace",
            sa.String(length=100),
            nullable=True,
            comment="Original namespace the extension asked for. Set when matcher redirected.",
        ),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("chat_metadata", json_t, nullable=True),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
            comment="SHA-256 of canonicalised turn array. Skip writes when unchanged.",
        ),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_type",
            sa.String(length=32),
            nullable=False,
            server_default="extension",
            comment="extension | import | manual",
        ),
        sa.Column(
            "installation_id",
            uuid_t,
            nullable=True,
            comment="Which extension install pushed this. NULL for manual/import.",
        ),
        sa.Column(
            "invalid_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Soft-delete timestamp. NULL = active.",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "user_id",
            "platform",
            "platform_conversation_id",
            name="uq_ai_chats_user_platform_convid",
        ),
    )
    op.create_index(
        "idx_ai_chats_org_user",
        "kemory_ai_chats",
        ["org_id", "user_id"],
    )
    op.create_index("idx_ai_chats_namespace", "kemory_ai_chats", ["namespace"])
    op.create_index(
        "idx_ai_chats_captured",
        "kemory_ai_chats",
        ["user_id", "captured_at"],
    )

    # ── 3) kemory_ai_chat_turns ────────────────────────────────────────
    op.create_table(
        "kemory_ai_chat_turns",
        sa.Column("turn_id", uuid_t, primary_key=True),
        sa.Column(
            "chat_id",
            uuid_t,
            sa.ForeignKey("kemory_ai_chats.chat_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            uuid_t,
            nullable=False,
            comment="Denormalised so the tenant filter doesn't need a join.",
        ),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column(
            "source_turn_id",
            sa.String(length=255),
            nullable=True,
            comment="data-message-id or equivalent per-turn id from the source UI.",
        ),
        sa.Column(
            "parent_turn_id",
            uuid_t,
            nullable=True,
            comment="For ChatGPT branching conversation trees.",
        ),
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            comment="user | assistant | system | tool",
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "content_html",
            sa.Text(),
            nullable=True,
            comment="Optional rich HTML when source provides it.",
        ),
        sa.Column(
            "thinking_content",
            sa.Text(),
            nullable=True,
            comment="Claude/o1 thinking blocks.",
        ),
        sa.Column("tool_calls", json_t, nullable=True),
        sa.Column("turn_metadata", json_t, nullable=True),
        sa.Column(
            "sequence",
            sa.Integer(),
            nullable=False,
            comment="Position within the chat (0-indexed).",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # SQLite + Postgres both accept this partial unique index pattern via
        # SQLAlchemy: the constraint applies only when source_turn_id is set.
        sa.UniqueConstraint(
            "chat_id",
            "source_turn_id",
            name="uq_ai_chat_turns_chat_sourceid",
        ),
    )
    op.create_index(
        "idx_ai_chat_turns_chat_seq",
        "kemory_ai_chat_turns",
        ["chat_id", "sequence"],
    )
    op.create_index(
        "idx_ai_chat_turns_org_user",
        "kemory_ai_chat_turns",
        ["org_id", "user_id"],
    )

    # ── 4) kemory_ai_chat_artifacts ────────────────────────────────────
    op.create_table(
        "kemory_ai_chat_artifacts",
        sa.Column("artifact_id", uuid_t, primary_key=True),
        sa.Column(
            "turn_id",
            uuid_t,
            sa.ForeignKey("kemory_ai_chat_turns.turn_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chat_id",
            uuid_t,
            sa.ForeignKey("kemory_ai_chats.chat_id", ondelete="CASCADE"),
            nullable=False,
            comment="Denormalised so artifacts can be queried per chat without joining turns.",
        ),
        sa.Column("user_id", uuid_t, nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column(
            "artifact_type",
            sa.String(length=32),
            nullable=False,
            comment="code | image | file | react | html | svg",
        ),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column(
            "content",
            sa.Text(),
            nullable=True,
            comment="Inline content for text-shaped artifacts. Capped at ~1MB.",
        ),
        sa.Column(
            "content_url",
            sa.String(length=1000),
            nullable=True,
            comment="Reserved for object-storage migration. NULL in v1.",
        ),
        sa.Column(
            "content_sha256",
            sa.String(length=64),
            nullable=False,
            comment="SHA-256 of content (or content_url payload).",
        ),
        sa.Column("artifact_metadata", json_t, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_ai_chat_artifacts_turn",
        "kemory_ai_chat_artifacts",
        ["turn_id"],
    )
    op.create_index(
        "idx_ai_chat_artifacts_chat",
        "kemory_ai_chat_artifacts",
        ["chat_id"],
    )
    op.create_index(
        "idx_ai_chat_artifacts_org_user",
        "kemory_ai_chat_artifacts",
        ["org_id", "user_id"],
    )

    # ── 5) kemory_chat_namespace_mappings ──────────────────────────────
    op.create_table(
        "kemory_chat_namespace_mappings",
        sa.Column("mapping_id", uuid_t, primary_key=True),
        sa.Column("user_id", uuid_t, nullable=False),
        sa.Column("org_id", sa.String(length=64), nullable=False),
        sa.Column(
            "platform",
            sa.String(length=32),
            nullable=False,
            comment="chatgpt | claude | gemini | manus | other",
        ),
        sa.Column(
            "source_project_id",
            sa.String(length=255),
            nullable=True,
            comment="Exact project id match. NULL = pattern fallback.",
        ),
        sa.Column(
            "source_project_name_pattern",
            sa.String(length=500),
            nullable=True,
            comment="Case-insensitive substring match applied when source_project_id is NULL.",
        ),
        sa.Column(
            "target_namespace",
            sa.String(length=100),
            nullable=False,
            comment="Always wins over the namespace matcher.",
        ),
        sa.Column(
            "priority",
            sa.Integer(),
            nullable=False,
            server_default="100",
            comment="Lower priority is evaluated first. Defaults to 100.",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_chat_ns_mappings_user_platform",
        "kemory_chat_namespace_mappings",
        ["user_id", "platform"],
    )
    op.create_index(
        "idx_chat_ns_mappings_org_user",
        "kemory_chat_namespace_mappings",
        ["org_id", "user_id"],
    )

    # ── 6) Forward-compat columns on kemory_memories ───────────────────
    # Nullable + no FK on SQLite (cross-dialect simplicity); a partial FK
    # on Postgres would still allow chat deletion without breaking memory
    # rows. v1 leaves these NULL — phase 2 (chat → memory extraction)
    # populates them when it materialises a memory from a turn.
    op.add_column(
        "kemory_memories",
        sa.Column(
            "source_chat_id",
            uuid_t,
            nullable=True,
            comment="Links a memory back to the kemory_ai_chats row it was extracted from (phase 2).",
        ),
    )
    op.add_column(
        "kemory_memories",
        sa.Column(
            "source_turn_id",
            uuid_t,
            nullable=True,
            comment="Specific turn within the source chat (phase 2).",
        ),
    )
    op.create_index(
        "idx_memories_source_chat",
        "kemory_memories",
        ["source_chat_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_memories_source_chat", table_name="kemory_memories")
    op.drop_column("kemory_memories", "source_turn_id")
    op.drop_column("kemory_memories", "source_chat_id")

    op.drop_index(
        "idx_chat_ns_mappings_org_user",
        table_name="kemory_chat_namespace_mappings",
    )
    op.drop_index(
        "idx_chat_ns_mappings_user_platform",
        table_name="kemory_chat_namespace_mappings",
    )
    op.drop_table("kemory_chat_namespace_mappings")

    op.drop_index("idx_ai_chat_artifacts_org_user", table_name="kemory_ai_chat_artifacts")
    op.drop_index("idx_ai_chat_artifacts_chat", table_name="kemory_ai_chat_artifacts")
    op.drop_index("idx_ai_chat_artifacts_turn", table_name="kemory_ai_chat_artifacts")
    op.drop_table("kemory_ai_chat_artifacts")

    op.drop_index("idx_ai_chat_turns_org_user", table_name="kemory_ai_chat_turns")
    op.drop_index("idx_ai_chat_turns_chat_seq", table_name="kemory_ai_chat_turns")
    op.drop_table("kemory_ai_chat_turns")

    op.drop_index("idx_ai_chats_captured", table_name="kemory_ai_chats")
    op.drop_index("idx_ai_chats_namespace", table_name="kemory_ai_chats")
    op.drop_index("idx_ai_chats_org_user", table_name="kemory_ai_chats")
    op.drop_table("kemory_ai_chats")

    op.drop_index("idx_agent_registry_kind", table_name="kemory_agent_registry")
    op.drop_column("kemory_agent_registry", "agent_kind")
