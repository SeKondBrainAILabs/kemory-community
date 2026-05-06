"""add waitlist and referral_events tables

Revision ID: 001
Revises:
Create Date: 2026-03-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kora_waitlist",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("service", sa.String(50), nullable=False, server_default="kemory"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("position", sa.BigInteger, nullable=False),
        sa.Column("referral_code", sa.String(20), nullable=False, unique=True),
        sa.Column("referred_by_code", sa.String(20), nullable=True),
        sa.Column("referral_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(50), nullable=True, server_default="organic"),
        sa.UniqueConstraint("user_id", "service", name="uq_waitlist_user_service"),
    )
    op.create_index("ix_waitlist_status", "kora_waitlist", ["status"])
    op.create_index("ix_waitlist_service", "kora_waitlist", ["service"])
    op.create_index("ix_waitlist_position", "kora_waitlist", ["position"])

    op.create_table(
        "kora_referral_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("referrer_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("referred_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("referral_code", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("referrer_user_id", "referred_user_id", name="uq_referral_pair"),
    )
    op.create_index("ix_referral_referrer", "kora_referral_events", ["referrer_user_id"])


def downgrade() -> None:
    op.drop_table("kora_referral_events")
    op.drop_table("kora_waitlist")
