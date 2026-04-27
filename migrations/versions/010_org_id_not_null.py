"""Multi-tenant: enforce NOT NULL on org_id; align teams.org_id to String.

This is the cleanup migration for the org_id rollout. Because kemory has
no production users yet, we skip the shadow-mode bake the original plan
called for and flip enforcement on directly:

  * org_id NOT NULL on:
      s9nmv_memories
      s9nmu_agent_registry  (typo-safe alias — actual: s9nmv_agent_registry)
      s9nmv_audit_log
      s9nmv_permission_rules
  * teams.org_id changes type GUID → VARCHAR(64) so it matches the
    string-shaped tenant identifier used by Cognition OS, the CCB Kafka
    envelope, and the new columns from revision 009.

Pre-condition: every row carries a real org_id or the legacy sentinel.
Revision 009's backfill already wrote the sentinel into pre-existing
rows, so this migration sets NOT NULL safely.

Revision ID: 010
"""
from alembic import op
import sqlalchemy as sa


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


_TABLES = [
    "s9nmv_memories",
    "s9nmv_agent_registry",
    "s9nmv_audit_log",
    "s9nmv_permission_rules",
]


def upgrade() -> None:
    bind = op.get_bind()

    # Safety net — coerce any NULLs left over from local dev to the sentinel
    # before flipping NOT NULL. Cheap on small tables, idempotent.
    for table in _TABLES:
        bind.execute(
            sa.text(f"UPDATE {table} SET org_id = 'legacy' WHERE org_id IS NULL")
        )
        op.alter_column(
            table,
            "org_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )

    # Align teams.org_id to String(64). Was GUID() (UUID) from migration
    # 004; new code expects a string-shaped tenant id. The USING clause is
    # required on Postgres but unsupported on SQLite — guard by dialect.
    # SQLite stores GUID() as TEXT under the GUID TypeDecorator, so the
    # column is already string-shaped at the DB level and an ALTER would
    # be a no-op (also: SQLite local mode has no production data).
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "teams",
            "org_id",
            existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
            type_=sa.String(length=64),
            existing_nullable=False,
            postgresql_using="org_id::text",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "teams",
            "org_id",
            existing_type=sa.String(length=64),
            type_=sa.dialects.postgresql.UUID(as_uuid=True),
            existing_nullable=False,
            postgresql_using="org_id::uuid",
        )
    for table in _TABLES:
        op.alter_column(
            table,
            "org_id",
            existing_type=sa.String(length=64),
            nullable=True,
        )
