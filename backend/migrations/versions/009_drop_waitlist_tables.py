"""Drop waitlist + referral_events tables.

Kemory no longer owns the waitlist flow — the marketing-site waitlist now lives
in `core-ai-backend`. Existing rows on this deployment are already mirrored
there; if they were not, the dashboard operator should export them before
applying this migration.

This migration is deliberately destructive. Downgrade re-creates empty tables
with the original schema so that older application code can boot, but it does
not restore data.

Revision ID: 009
"""
from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS s9nmv_referral_events CASCADE")
    op.execute("DROP TABLE IF EXISTS s9nmv_waitlist CASCADE")
    # Older deployments may still carry the pre-rebrand names if 008 was
    # skipped; drop those too so the migration is idempotent across envs.
    op.execute("DROP TABLE IF EXISTS kora_referral_events CASCADE")
    op.execute("DROP TABLE IF EXISTS kora_waitlist CASCADE")


def downgrade() -> None:
    op.create_table(
        "s9nmv_waitlist",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("referral_code", sa.String(64), nullable=True, unique=True),
        sa.Column("referred_by", sa.String(64), nullable=True),
        sa.Column("metadata", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "s9nmv_referral_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("referrer_email", sa.String(255), nullable=False),
        sa.Column("referee_email", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
