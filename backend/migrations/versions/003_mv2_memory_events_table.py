"""MV2-S02.1: Create memory_events provenance table

Append-only table recording every memory state change.
Idempotent: safe to run on existing deployments.

Revision ID: 003
Revises: 002
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_events",
        sa.Column("event_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("memory_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False, server_default="system"),
        sa.Column("actor_id", sa.String(200), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("before_state", sa.JSON, nullable=True),
        sa.Column("after_state", sa.JSON, nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_events_memory_id", "memory_events", ["memory_id"])
    op.create_index("idx_events_type", "memory_events", ["event_type"])
    op.create_index("idx_events_created", "memory_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("memory_events")
