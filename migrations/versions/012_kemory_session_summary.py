"""Create kemory_session_summary — per-session L3 rollup table.

Each row pairs a (user, namespace, session) tuple with two summaries:

  * session_summary    — L3 Groq narrative over memories IN this session only.
                         Useful for "what happened in this session" resume UX.
  * cumulative_summary — L3 Groq narrative over all namespace memories with
                         created_at ≤ up_to_ts. A point-in-time snapshot of
                         the namespace state as of this session's boundary.

up_to_ts is the created_at of the latest memory at the time of the last
pipeline run. For active sessions it advances on every write; once a session
stops receiving memories the cumulative summary freezes, giving an answer
to "what was the namespace state when this session ended?"

Story: F12 v2 (session-aware L3 rollup)
Revision ID: 012
"""
from alembic import op
import sqlalchemy as sa


revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


TABLE = "kemory_session_summary"


def _has_table(conn, table: str) -> bool:
    inspector = sa.inspect(conn)
    return table in inspector.get_table_names()


def upgrade() -> None:
    conn = op.get_bind()
    if _has_table(conn, TABLE):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("namespace", sa.String(length=100), nullable=False),
        sa.Column("session_id", sa.String(length=200), nullable=False),

        # L3 over memories in this session only
        sa.Column("session_summary", sa.Text(), nullable=True),
        sa.Column("session_summary_tier", sa.String(length=8), nullable=True),
        sa.Column("session_memory_count", sa.Integer(), nullable=False, server_default="0"),

        # L3 over all namespace memories with created_at ≤ up_to_ts
        sa.Column("cumulative_summary", sa.Text(), nullable=True),
        sa.Column("cumulative_summary_tier", sa.String(length=8), nullable=True),
        sa.Column("cumulative_memory_count", sa.Integer(), nullable=False, server_default="0"),

        # Anchor: max(created_at) of memories reflected in the cumulative summary
        sa.Column("up_to_ts", sa.DateTime(timezone=True), nullable=True),

        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),

        sa.UniqueConstraint(
            "user_id", "namespace", "session_id",
            name="uq_session_summary_user_ns_session",
        ),
    )
    op.create_index(
        "ix_session_summary_user_ns",
        TABLE,
        ["user_id", "namespace"],
    )
    op.create_index(
        "ix_session_summary_session",
        TABLE,
        ["user_id", "session_id"],
    )
    op.create_index(
        "ix_session_summary_updated_at",
        TABLE,
        ["updated_at"],
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, TABLE):
        return
    op.drop_index("ix_session_summary_updated_at", table_name=TABLE)
    op.drop_index("ix_session_summary_session", table_name=TABLE)
    op.drop_index("ix_session_summary_user_ns", table_name=TABLE)
    op.drop_table(TABLE)
