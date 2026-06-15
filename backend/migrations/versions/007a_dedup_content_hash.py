"""Add content_hash column for memory deduplication.

Agents frequently store identical or near-identical memories across sessions.
A SHA-256 hash of normalised content enables O(1) exact-duplicate detection
at the database level via a partial unique index, scoped to (user_id, namespace)
and excluding soft-deleted rows.

Layer 1 (this migration): deterministic hash — catches exact duplicates.
Layer 2 (application code): semantic similarity via embeddings — catches
near-duplicates at write time.

Story: S9N-DEDUP
Revision ID: 007a
"""
from alembic import op
import sqlalchemy as sa


revision = "007a"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add nullable content_hash column
    op.add_column(
        "kora_memories",
        sa.Column(
            "content_hash",
            sa.String(64),
            nullable=True,
            comment="SHA-256 hex digest of normalised content for deduplication",
        ),
    )

    # 2. Backfill existing rows using PostgreSQL built-in SHA-256
    op.execute(
        """
        UPDATE kora_memories
        SET content_hash = encode(
            sha256(convert_to(content, 'UTF8')),
            'hex'
        )
        WHERE content_hash IS NULL
        """
    )

    # 3. Set NOT NULL after backfill
    op.alter_column("kora_memories", "content_hash", nullable=False)

    # 4. Partial unique index: only active (non-deleted) memories participate
    op.execute(
        """
        CREATE UNIQUE INDEX uq_memories_user_ns_hash
        ON kora_memories (user_id, namespace, content_hash)
        WHERE invalid_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_memories_user_ns_hash")
    op.drop_column("kora_memories", "content_hash")
