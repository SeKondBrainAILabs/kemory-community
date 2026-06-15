"""MV3: Visibility model, teams, and team_members tables

Adds visibility column to kora_memories and creates teams/team_members tables.

Revision ID: 004
Revises: 003
Create Date: 2026-04-05
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def _add_column_safe(table: str, column: sa.Column) -> None:
    try:
        op.add_column(table, column)
    except Exception:
        pass


def upgrade() -> None:
    # MV3-E01: Visibility on kora_memories
    _add_column_safe("kora_memories", sa.Column("visibility", sa.String(20), nullable=False, server_default="user-private"))
    _add_column_safe("kora_memories", sa.Column("team_id", UUID(as_uuid=True), nullable=True))
    _add_column_safe("kora_memories", sa.Column("tier", sa.String(20), nullable=False, server_default="active"))
    _add_column_safe("kora_memories", sa.Column("access_count", sa.Integer, nullable=False, server_default="0"))
    try:
        op.create_index("idx_memories_visibility", "kora_memories", ["visibility"])
    except Exception:
        pass

    # MV3-E02: Teams table
    op.create_table(
        "teams",
        sa.Column("team_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(1000), nullable=True),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="team"),
        sa.Column("settings", sa.JSON, nullable=True),
        sa.Column("created_by", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default="false"),
    )
    op.create_index("idx_teams_org", "teams", ["org_id"])

    # MV3-E02: Team members table
    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("team_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("can_write", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_member"),
    )
    op.create_index("idx_team_members_user", "team_members", ["user_id"])
    op.create_index("idx_team_members_team", "team_members", ["team_id"])


def downgrade() -> None:
    op.drop_table("team_members")
    op.drop_table("teams")
    for col in ["visibility", "team_id", "tier", "access_count"]:
        try:
            op.drop_column("kora_memories", col)
        except Exception:
            pass
