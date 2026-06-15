"""Rename kora_ tables to s9nmv_ as part of S9N Memory Vault rebrand.

All seven kora_-prefixed tables are renamed to use the s9nmv_ prefix.
This is a non-destructive DDL operation — PostgreSQL ALTER TABLE RENAME
keeps all data, indexes, constraints, and sequences intact.

Revision ID: 008
"""
from alembic import op


revision = "008"
down_revision = "007b"
branch_labels = None
depends_on = None

_RENAMES = [
    ("kora_memories",          "s9nmv_memories"),
    ("kora_agent_registry",    "s9nmv_agent_registry"),
    ("kora_audit_log",         "s9nmv_audit_log"),
    ("kora_permission_rules",  "s9nmv_permission_rules"),
    ("kora_consent_requests",  "s9nmv_consent_requests"),
    ("kora_waitlist",          "s9nmv_waitlist"),
    ("kora_referral_events",   "s9nmv_referral_events"),
]


def upgrade() -> None:
    for old, new in _RENAMES:
        op.rename_table(old, new)


def downgrade() -> None:
    for old, new in _RENAMES:
        op.rename_table(new, old)
