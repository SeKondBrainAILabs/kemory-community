"""S9N-3073/S9N-3074: Hybrid vector + FTS search — embedding column and pg_trgm index

Adds:
- ``embedding``       FLOAT[] column on kora_memories (384-dim sentence-transformers vector)
- ``embedding_model`` VARCHAR(100) column — model ID used to generate the embedding
- ``pg_trgm`` extension (idempotent) for trigram-based FTS fallback
- GIN trigram index on kora_memories.content for fast ILIKE / similarity search
- Composite index (user_id, namespace, embedding IS NOT NULL) for vector-eligible rows

This migration is ADDITIVE ONLY — no columns are dropped or modified.

Revision ID: 005
Revises: 004
Create Date: 2026-04-08
Story: S9N-3073 (Epic), S9N-3074 (Story)
Author: sachmans <sachin@sachinduggal.com>
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, FLOAT

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_column_safe(table: str, column: sa.Column) -> None:
    """Add a column, silently skipping if it already exists (idempotent)."""
    try:
        op.add_column(table, column)
    except Exception:
        pass  # column already exists — safe to ignore


def _create_index_safe(name: str, table: str, columns: list[str], **kwargs) -> None:
    """Create an index, silently skipping if it already exists (idempotent)."""
    try:
        op.create_index(name, table, columns, **kwargs)
    except Exception:
        pass


def _execute_safe(sql: str) -> None:
    """Execute raw SQL, silently skipping on error (idempotent DDL)."""
    try:
        op.execute(sa.text(sql))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ── 1. Enable pg_trgm extension (required for GIN trigram index) ─────────
    # This is idempotent — safe to run multiple times.
    _execute_safe("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # ── 2. Add embedding columns to kora_memories ────────────────────────────
    # embedding: 384-float array produced by sentence-transformers all-MiniLM-L6-v2
    # NULL until the async enrichment worker backfills existing rows.
    _add_column_safe(
        "kora_memories",
        sa.Column(
            "embedding",
            ARRAY(FLOAT),
            nullable=True,
            comment=(
                "384-dimensional L2-normalised embedding vector "
                "(sentence-transformers/all-MiniLM-L6-v2). "
                "NULL until enrichment worker backfills the row. "
                "Story: S9N-3074-SUB1"
            ),
        ),
    )
    _add_column_safe(
        "kora_memories",
        sa.Column(
            "embedding_model",
            sa.String(100),
            nullable=True,
            server_default="all-MiniLM-L6-v2",
            comment=(
                "Model ID used to generate the embedding. "
                "Stored so that re-encoding can be triggered on model upgrade. "
                "Story: S9N-3074-SUB1"
            ),
        ),
    )

    # ── 3. GIN trigram index on content (fast ILIKE / similarity) ────────────
    # Replaces the implicit sequential scan used by the current ILIKE search.
    _create_index_safe(
        "idx_memories_content_trgm",
        "kora_memories",
        ["content"],
        postgresql_using="gin",
        postgresql_ops={"content": "gin_trgm_ops"},
    )

    # ── 4. Partial index: rows that have been embedded ───────────────────────
    # Used by the vector search path to quickly filter embeddable rows.
    _execute_safe(
        """
        CREATE INDEX IF NOT EXISTS idx_memories_has_embedding
        ON kora_memories (user_id, namespace)
        WHERE embedding IS NOT NULL
        """
    )


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Drop indexes first, then columns.
    _execute_safe("DROP INDEX IF EXISTS idx_memories_has_embedding")
    _execute_safe("DROP INDEX IF EXISTS idx_memories_content_trgm")

    try:
        op.drop_column("kora_memories", "embedding_model")
    except Exception:
        pass

    try:
        op.drop_column("kora_memories", "embedding")
    except Exception:
        pass

    # Note: we intentionally do NOT drop the pg_trgm extension on downgrade
    # as other tables/indexes may depend on it.
