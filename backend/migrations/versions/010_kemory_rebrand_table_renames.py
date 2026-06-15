"""Rename s9nmv_ tables to kemory_ as part of the Kemory rebrand.

All six s9nmv_-prefixed tables are renamed to use the kemory_ prefix.
This is a non-destructive DDL operation — PostgreSQL ALTER TABLE RENAME
keeps all data, indexes, constraints, and sequences intact.

This migration runs after 009 (waitlist drop), which is why waitlist and
referral_events are no longer in the list.

Revision ID: 010
"""
from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


_RENAMES = [
    ("s9nmv_memories",            "kemory_memories"),
    ("s9nmv_agent_registry",      "kemory_agent_registry"),
    ("s9nmv_audit_log",           "kemory_audit_log"),
    ("s9nmv_permission_rules",    "kemory_permission_rules"),
    ("s9nmv_consent_requests",    "kemory_consent_requests"),
    ("s9nmv_namespace_policies",  "kemory_namespace_policies"),
]


_CHECK_SQL = sa.text(
    "SELECT to_regclass(:old) IS NOT NULL AS old_exists, "
    "to_regclass(:new) IS NOT NULL AS new_exists"
)


def upgrade() -> None:
    conn = op.get_bind()
    for old, new in _RENAMES:
        # Idempotent: only rename if the old table exists and the new one
        # does not — this makes the migration safe to re-run on envs where
        # it was partially applied.
        old_exists, new_exists = conn.execute(_CHECK_SQL, {"old": old, "new": new}).one()
        if old_exists and not new_exists:
            op.rename_table(old, new)


def downgrade() -> None:
    conn = op.get_bind()
    for old, new in _RENAMES:
        old_exists, new_exists = conn.execute(_CHECK_SQL, {"old": old, "new": new}).one()
        if new_exists and not old_exists:
            op.rename_table(new, old)
