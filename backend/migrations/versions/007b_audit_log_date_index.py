"""Add created_at index on kora_audit_log for date-range filtering.

Fix KMV-QA-001 / KMV-QA-011:
  The AuditLogPage date-range filter (date_from / date_to) performs a
  WHERE created_at BETWEEN :from AND :to query.  Without an index this
  is a full-table scan which becomes slow as the audit log grows.

  This migration adds a BTREE index on (created_at) so date-range
  queries are O(log N) rather than O(N).

  Note: The table name retains the legacy kora_ prefix because renaming
  it would require a destructive data migration.  All new Memory Vault
  code refers to this table via the SQLAlchemy model (AuditLog).

Revision ID: 007b
"""
from alembic import op
import sqlalchemy as sa

revision = "007b"
down_revision = "007a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Index for date-range filtering on the audit log
    op.create_index(
        "idx_memory_vault_audit_log_created_at",
        "kora_audit_log",
        ["created_at"],
    )

    # Composite index for (user_id, created_at) — used by the admin bypass
    # path which omits the user_id filter but still orders by created_at.
    op.create_index(
        "idx_memory_vault_audit_log_user_created",
        "kora_audit_log",
        ["user_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_memory_vault_audit_log_user_created", table_name="kora_audit_log")
    op.drop_index("idx_memory_vault_audit_log_created_at", table_name="kora_audit_log")
