"""MV2-S01.5: Unified memory schema migration

Adds columns from the core library (episodes table) to kora_memories,
creating a single unified storage model. Also migrates is_deleted/deleted_at
to invalid_at (bi-temporal model).

Idempotent: safe to run on existing deployments (uses ADD COLUMN IF NOT EXISTS
via exception handling).

Revision ID: 002
Revises: 001
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def _add_column_safe(table: str, column: sa.Column) -> None:
    """Add a column, ignoring if it already exists (idempotent)."""
    try:
        op.add_column(table, column)
    except Exception:
        pass  # Column already exists


def upgrade() -> None:
    # ── New columns from core library ─────────────────────────────
    _add_column_safe("kora_memories", sa.Column("session_id", sa.String(200), nullable=True))
    _add_column_safe("kora_memories", sa.Column("round_id", sa.String(200), nullable=True))
    _add_column_safe("kora_memories", sa.Column("valid_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_safe("kora_memories", sa.Column("invalid_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_safe("kora_memories", sa.Column("decay_score", sa.Float, nullable=True, server_default="1.0"))
    _add_column_safe("kora_memories", sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True))
    _add_column_safe("kora_memories", sa.Column("facts", sa.Text, nullable=True, server_default="[]"))
    _add_column_safe("kora_memories", sa.Column("temporal_anchor", sa.String(20), nullable=True))
    _add_column_safe("kora_memories", sa.Column("access_count", sa.Integer, nullable=False, server_default="0"))

    # ── Indexes for new columns ───────────────────────────────────
    try:
        op.create_index("idx_memories_session", "kora_memories", ["session_id"])
    except Exception:
        pass
    try:
        op.create_index("idx_memories_round", "kora_memories", ["round_id"])
    except Exception:
        pass
    try:
        op.create_index("idx_memories_temporal", "kora_memories", ["temporal_anchor"])
    except Exception:
        pass
    try:
        op.create_index("idx_memories_decay", "kora_memories", ["decay_score"])
    except Exception:
        pass

    # ── Migrate is_deleted → invalid_at ───────────────────────────
    # Set invalid_at = deleted_at for all soft-deleted records
    op.execute("""
        UPDATE kora_memories
        SET invalid_at = deleted_at
        WHERE is_deleted = true AND deleted_at IS NOT NULL AND invalid_at IS NULL
    """)
    # For is_deleted=true but deleted_at is NULL (edge case), use updated_at
    op.execute("""
        UPDATE kora_memories
        SET invalid_at = updated_at
        WHERE is_deleted = true AND deleted_at IS NULL AND invalid_at IS NULL
    """)

    # ── Relax legacy NOT NULL on is_deleted ───────────────────────
    # The unified MV2 model no longer writes is_deleted (uses invalid_at
    # instead), so INSERTs from the new ORM would fail the NOT NULL
    # constraint that the v1 schema put on this column. We keep the
    # column around for downgrade compatibility but make it nullable
    # and default to FALSE so the old and new models can coexist.
    try:
        op.execute("""
            ALTER TABLE kora_memories
            ALTER COLUMN is_deleted SET DEFAULT FALSE
        """)
    except Exception:
        pass
    try:
        op.execute("""
            ALTER TABLE kora_memories
            ALTER COLUMN is_deleted DROP NOT NULL
        """)
    except Exception:
        pass


def downgrade() -> None:
    # Reverse: copy invalid_at back to deleted_at/is_deleted
    op.execute("""
        UPDATE kora_memories
        SET is_deleted = true, deleted_at = invalid_at
        WHERE invalid_at IS NOT NULL
    """)

    # Drop new columns
    for col in ["session_id", "round_id", "valid_at", "invalid_at",
                "decay_score", "last_accessed_at", "facts", "temporal_anchor"]:
        try:
            op.drop_column("kora_memories", col)
        except Exception:
            pass

    # Drop new indexes
    for idx in ["idx_memories_session", "idx_memories_round",
                "idx_memories_temporal", "idx_memories_decay"]:
        try:
            op.drop_index(idx, "kora_memories")
        except Exception:
            pass
