"""Namespace-level artifacts (project files — v3.35.0).

Generalises ``kemory_ai_chat_artifacts`` so files can live at three
granularities instead of only being tied to a chat turn:

  1. **Namespace-level** — standalone project document / image, no parent
     chat or memory.  ``namespace`` is always populated; ``chat_id`` and
     ``turn_id`` are NULL.
  2. **Memory-attached** — a document or image linked to a ``kemory_memories``
     row.  ``memory_id`` is set; ``chat_id`` / ``turn_id`` remain NULL.
  3. **Chat-attached** (existing behaviour) — both ``chat_id`` and ``turn_id``
     are set, same as before this migration.

What this migration does
────────────────────────
  * Makes ``chat_id`` and ``turn_id`` nullable (they were NOT NULL).
  * Adds ``namespace VARCHAR(100) NOT NULL`` — back-filled from the parent
    chat's namespace for all existing rows before the NOT NULL constraint is
    applied.
  * Adds ``memory_id UUID NULLABLE`` FK → ``kemory_memories.memory_id``
    with ON DELETE CASCADE.
  * Adds three cosmetic columns: ``source_project_id``,
    ``source_project_name``, ``source_platform`` — mirror of the
    ``kemory_ai_chats`` equivalents; let us group / filter artifacts by
    their origin project across platforms.
  * Drops the partial constraint that required chat_id/turn_id (namespace
    NOT NULL is the only required parent).
  * Adds two new indices:
      ix_artifacts_user_namespace    (user_id, namespace)
      ix_artifacts_memory_id         (memory_id) WHERE memory_id IS NOT NULL

Rollback (downgrade)
────────────────────
  * Drop the new indices and the new columns.
  * Restore NOT NULL on ``chat_id`` and ``turn_id``.  Any artifact rows
    that were inserted without a chat_id / turn_id (i.e. namespace-only or
    memory-only artifacts) will prevent the downgrade — those rows must be
    deleted first.
"""

import sqlalchemy as sa
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Make chat_id / turn_id nullable ──────────────────────────
    op.alter_column(
        "kemory_ai_chat_artifacts",
        "chat_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
        comment="FK to kemory_ai_chats. NULL for namespace-level / memory-level artifacts.",
    )
    op.alter_column(
        "kemory_ai_chat_artifacts",
        "turn_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
        comment="FK to kemory_ai_chat_turns. NULL for namespace-level / memory-level artifacts.",
    )

    # ── 2. Add new columns (all nullable first) ──────────────────────
    op.add_column(
        "kemory_ai_chat_artifacts",
        sa.Column(
            "namespace",
            sa.String(100),
            nullable=True,  # set NOT NULL after backfill
            comment="Kemory namespace this artifact belongs to (always set).",
        ),
    )
    op.add_column(
        "kemory_ai_chat_artifacts",
        sa.Column(
            "memory_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "kemory_memories.memory_id",
                ondelete="CASCADE",
                name="fk_artifacts_memory_id",
            ),
            nullable=True,
            comment="FK to kemory_memories — set for memory-attached artifacts.",
        ),
    )
    op.add_column(
        "kemory_ai_chat_artifacts",
        sa.Column(
            "source_project_id",
            sa.String(255),
            nullable=True,
            comment="Source project id (mirrors kemory_ai_chats.source_project_id).",
        ),
    )
    op.add_column(
        "kemory_ai_chat_artifacts",
        sa.Column(
            "source_project_name",
            sa.String(500),
            nullable=True,
            comment="Human-readable project name for this artifact's origin.",
        ),
    )
    op.add_column(
        "kemory_ai_chat_artifacts",
        sa.Column(
            "source_platform",
            sa.String(50),
            nullable=True,
            comment="Platform for direct artifact uploads (chatgpt | claude | etc.).",
        ),
    )

    # ── 3. Backfill namespace from parent chat ───────────────────────
    # All existing rows have chat_id set; the JOIN is always defined.
    op.execute(
        """
        UPDATE kemory_ai_chat_artifacts AS a
        SET namespace = c.namespace
        FROM kemory_ai_chats AS c
        WHERE c.chat_id = a.chat_id
        """
    )

    # ── 4. Make namespace NOT NULL now that every row has a value ────
    op.alter_column(
        "kemory_ai_chat_artifacts",
        "namespace",
        nullable=False,
        existing_type=sa.String(100),
    )

    # ── 5. Add indices ───────────────────────────────────────────────
    op.create_index(
        "ix_artifacts_user_namespace",
        "kemory_ai_chat_artifacts",
        ["user_id", "namespace"],
    )
    op.create_index(
        "ix_artifacts_memory_id",
        "kemory_ai_chat_artifacts",
        ["memory_id"],
        postgresql_where=sa.text("memory_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Drop indices first.
    op.drop_index("ix_artifacts_memory_id", table_name="kemory_ai_chat_artifacts")
    op.drop_index("ix_artifacts_user_namespace", table_name="kemory_ai_chat_artifacts")

    # Drop added columns.
    for col in (
        "source_platform",
        "source_project_name",
        "source_project_id",
        "memory_id",
        "namespace",
    ):
        op.drop_column("kemory_ai_chat_artifacts", col)

    # Restore NOT NULL on chat_id / turn_id.
    # NOTE: if any namespace-only or memory-only artifacts were written after
    # the upgrade those rows will violate this constraint.  Delete them first.
    op.alter_column(
        "kemory_ai_chat_artifacts",
        "turn_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.alter_column(
        "kemory_ai_chat_artifacts",
        "chat_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=False,
    )
