"""S9N-6291 rolling session digest table.

Adds ``kemory_session_digests`` for the additive session-context tool:
the latest N exchanges stay readable/raw, older exchanges are folded into
a rolling, token-budgeted digest. AAAK remains a byte-oriented L2 storage
and export dialect, not the context injection representation.

Revision ID: 018
Revises: 017
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def _uuid_type(bind):
    """Dialect-aware UUID type. Mirrors backend.core.types.GUID."""
    if bind.dialect.name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.CHAR(36)


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _has_index(table_name: str, index_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    uuid_t = _uuid_type(bind)

    if not _has_table("kemory_session_digests"):
        op.create_table(
            "kemory_session_digests",
            sa.Column("id", uuid_t, primary_key=True),
            sa.Column("org_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", uuid_t, nullable=False),
            sa.Column("namespace", sa.String(length=100), nullable=False),
            sa.Column("session_id", sa.String(length=200), nullable=False),
            sa.Column("digest", sa.Text(), nullable=True),
            sa.Column("digest_tier", sa.String(length=20), nullable=False, server_default="L2.1"),
            sa.Column("source_exchange_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("source_turn_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("source_memory_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("compacted_exchange_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("raw_tail_count", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("token_budget", sa.Integer(), nullable=False, server_default="900"),
            sa.Column("token_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tokenizer_model", sa.String(length=100), nullable=True),
            sa.Column("tokenizer_name", sa.String(length=100), nullable=True),
            sa.Column(
                "token_count_method",
                sa.String(length=100),
                nullable=False,
                server_default="fallback_chars_per_token_3",
            ),
            sa.Column("last_source_created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "org_id",
                "user_id",
                "namespace",
                "session_id",
                name="uq_session_digest_org_user_ns_session",
            ),
        )

    if not _has_index("kemory_session_digests", "ix_session_digest_org_user_ns"):
        op.create_index(
            "ix_session_digest_org_user_ns",
            "kemory_session_digests",
            ["org_id", "user_id", "namespace"],
            unique=False,
        )
    if not _has_index("kemory_session_digests", "ix_session_digest_org_session"):
        op.create_index(
            "ix_session_digest_org_session",
            "kemory_session_digests",
            ["org_id", "session_id"],
            unique=False,
        )
    if not _has_index("kemory_session_digests", "ix_session_digest_updated_at"):
        op.create_index(
            "ix_session_digest_updated_at",
            "kemory_session_digests",
            ["updated_at"],
            unique=False,
        )


def downgrade() -> None:
    if not _has_table("kemory_session_digests"):
        return
    if _has_index("kemory_session_digests", "ix_session_digest_updated_at"):
        op.drop_index("ix_session_digest_updated_at", table_name="kemory_session_digests")
    if _has_index("kemory_session_digests", "ix_session_digest_org_session"):
        op.drop_index("ix_session_digest_org_session", table_name="kemory_session_digests")
    if _has_index("kemory_session_digests", "ix_session_digest_org_user_ns"):
        op.drop_index("ix_session_digest_org_user_ns", table_name="kemory_session_digests")
    op.drop_table("kemory_session_digests")
