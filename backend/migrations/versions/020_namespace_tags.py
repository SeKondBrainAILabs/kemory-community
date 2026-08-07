"""Namespace second-tier tags — profiles table + namespace_tag columns (S9N-6612).

A namespace can collapse several real-world contexts that merely share
vocabulary (canonical repro: ``project:ai-expansion-strategy`` mixing
Builder.ai's Insight-deal chats, EY and Al Ansari client work with
SeKondBrain's sovereign-AI strategy). Instead of destructive reassignment,
items get an automatic second tier — ``namespace:tag`` — that segments the
timeline/explorer view while search continues to span the parent namespace.

- ``kemory_namespace_tags``: one row per tag profile within (user, namespace)
  — entity anchor terms, running embedding centroid, observed era window
  (S9N-6613 ``occurred_at``), member count. Tenant-scoped (org_id).
- ``kemory_ai_chats.namespace_tag`` / ``kemory_memories.namespace_tag``:
  nullable slug stamped by the resolver / backfill script. NULL = untagged.

No data backfill here — tags are seeded by ``scripts/backfill_namespace_tags.py``
(dry-run default) and assigned automatically on new ingests.

Community Docker bootstraps create fresh PostgreSQL tables from model metadata
and stamp Alembic at head; upgrades from existing installs run this migration.

Revision ID: 020
Revises: 019
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # GUID / JSON column types per house rule: branch on dialect.
    if dialect == "postgresql":
        guid = sa.dialects.postgresql.UUID(as_uuid=True)
        json_type = sa.dialects.postgresql.JSONB()
    else:
        guid = sa.CHAR(36)
        json_type = sa.Text()

    op.create_table(
        "kemory_namespace_tags",
        sa.Column("tag_id", guid, primary_key=True, nullable=False),
        sa.Column("user_id", guid, nullable=False),
        sa.Column("org_id", sa.String(64), nullable=False),
        sa.Column("namespace", sa.String(100), nullable=False),
        sa.Column("tag", sa.String(120), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entity_terms", json_type, nullable=True),
        sa.Column("centroid", json_type, nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("occurred_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurred_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default=sa.text("'auto'")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "namespace", "tag", name="uq_namespace_tags_user_ns_tag"),
    )
    op.create_index("ix_kemory_namespace_tags_user_id", "kemory_namespace_tags", ["user_id"])
    op.create_index("idx_namespace_tags_user_ns", "kemory_namespace_tags", ["user_id", "namespace"])
    op.create_index("idx_namespace_tags_org_user", "kemory_namespace_tags", ["org_id", "user_id"])

    op.add_column(
        "kemory_ai_chats",
        sa.Column(
            "namespace_tag",
            sa.String(120),
            nullable=True,
            comment="S9N-6612: automatic second-tier segment (namespace:tag). View-only.",
        ),
    )
    op.add_column(
        "kemory_memories",
        sa.Column(
            "namespace_tag",
            sa.String(120),
            nullable=True,
            comment="S9N-6612: automatic second-tier segment (namespace:tag). View-only.",
        ),
    )
    # Tag-filtered views scan per (user, namespace, tag).
    op.create_index("idx_ai_chats_ns_tag", "kemory_ai_chats", ["user_id", "namespace", "namespace_tag"])
    op.create_index("idx_memories_ns_tag", "kemory_memories", ["user_id", "namespace", "namespace_tag"])


def downgrade() -> None:
    op.drop_index("idx_memories_ns_tag", table_name="kemory_memories")
    op.drop_index("idx_ai_chats_ns_tag", table_name="kemory_ai_chats")
    op.drop_column("kemory_memories", "namespace_tag")
    op.drop_column("kemory_ai_chats", "namespace_tag")
    op.drop_index("idx_namespace_tags_org_user", table_name="kemory_namespace_tags")
    op.drop_index("idx_namespace_tags_user_ns", table_name="kemory_namespace_tags")
    op.drop_index("ix_kemory_namespace_tags_user_id", table_name="kemory_namespace_tags")
    op.drop_table("kemory_namespace_tags")
