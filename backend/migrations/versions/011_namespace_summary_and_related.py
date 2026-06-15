"""Add consolidated_summary, consolidated_summary_tier,
consolidated_summary_updated_at, and related_namespaces columns to
kemory_namespace_policies.

Supports the Namespaces tab + L3/L3.1 cross-session rollup + related-namespace
detection.

Revision ID: 011
"""
from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


TABLE = "kemory_namespace_policies"


_NEW_COLUMNS = [
    ("consolidated_summary", sa.Text(), True),
    ("consolidated_summary_tier", sa.String(length=8), True),
    ("consolidated_summary_updated_at", sa.DateTime(timezone=True), True),
    ("related_namespaces", sa.JSON(), True),
]


def _has_column(conn, table: str, column: str) -> bool:
    inspector = sa.inspect(conn)
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    conn = op.get_bind()
    for name, coltype, nullable in _NEW_COLUMNS:
        if not _has_column(conn, TABLE, name):
            op.add_column(TABLE, sa.Column(name, coltype, nullable=nullable))


def downgrade() -> None:
    conn = op.get_bind()
    for name, _coltype, _nullable in reversed(_NEW_COLUMNS):
        if _has_column(conn, TABLE, name):
            op.drop_column(TABLE, name)
