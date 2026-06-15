"""Add vector-store adapter table.

Revision ID: 017
Revises: 016
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            """
            CREATE TABLE IF NOT EXISTS kemory_memory_vectors (
                memory_id uuid NOT NULL,
                user_id uuid NOT NULL,
                org_id varchar(64) NOT NULL,
                namespace varchar(100) NOT NULL,
                embedding vector(384),
                metadata jsonb,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now(),
                CONSTRAINT pk_memory_vectors PRIMARY KEY (memory_id, user_id, org_id)
            )
            """
        )
        op.create_index(
            "idx_memory_vectors_org_user_namespace",
            "kemory_memory_vectors",
            ["org_id", "user_id", "namespace"],
        )
        op.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_memory_vectors_embedding_hnsw
            ON kemory_memory_vectors USING hnsw (embedding vector_cosine_ops)
            WHERE embedding IS NOT NULL
            """
        )
        return

    op.create_table(
        "kemory_memory_vectors",
        sa.Column("memory_id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("namespace", sa.String(100), nullable=False),
        sa.Column("embedding", sa.LargeBinary(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("memory_id", "user_id", "org_id", name="pk_memory_vectors"),
    )
    op.create_index(
        "idx_memory_vectors_org_user_namespace",
        "kemory_memory_vectors",
        ["org_id", "user_id", "namespace"],
    )


def downgrade() -> None:
    op.drop_index("idx_memory_vectors_org_user_namespace", table_name="kemory_memory_vectors")
    if op.get_bind().dialect.name == "postgresql":
        op.drop_index("idx_memory_vectors_embedding_hnsw", table_name="kemory_memory_vectors")
    op.drop_table("kemory_memory_vectors")
