"""Multi-tenant foundation: add org_id to tenant-scoped tables.

Renumbered from the original 009 to 013 during merge with main — main's
009/010 dropped waitlist + renamed `s9nmv_*` tables to `kemory_*`. This
migration runs against the post-rename `kemory_*` tables.

What this migration does:
  - Adds a nullable `org_id VARCHAR(64)` column to:
      * kemory_memories
      * kemory_agent_registry
      * kemory_audit_log         (also adds team_id for WS-8)
      * kemory_permission_rules
  - Backfills every existing row with org_id='legacy' so the NOT NULL
    enforcement in revision 014 can run without scanning for orphans.
  - Adds composite indexes (org_id, user_id) on the hot read paths so the
    tenant filter introduced in WS-3 keeps p95 read latency within budget.

What this migration does NOT do:
  - It does NOT mark org_id NOT NULL — that's revision 014.
  - It does NOT enforce any tenant filtering — controlled at runtime by
    settings.tenant_enforcement.
  - It does NOT touch teams / team_members tables (those already have
    org_id via 004_mv3_visibility_teams).

Safe to deploy alongside the current binary: the new column is invisible
to SQLAlchemy 2.x model code that hasn't been updated yet, and the
backfill runs as a single bounded UPDATE per table (low row count today).

Revision ID: 013
"""

import sqlalchemy as sa
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


# (table_name, add_team_id) — team_id is only added to audit_log; memories
# already has it from 004_mv3_visibility_teams; agent_registry/permission_rules
# don't need it.
_TABLES_WITH_ORG_ID = [
    ("kemory_memories", False),
    ("kemory_agent_registry", False),
    ("kemory_audit_log", True),
    ("kemory_permission_rules", False),
]

# Sentinel value for existing rows. Ops reassigns to real org_ids in P4
# rollout phase. SLO: legacy row count → 0 within 30 days of cutover.
_LEGACY_SENTINEL = "legacy"


def upgrade() -> None:
    bind = op.get_bind()

    # ── Add org_id (and team_id where applicable) ───────────────────
    for table, add_team_id in _TABLES_WITH_ORG_ID:
        op.add_column(
            table,
            sa.Column(
                "org_id",
                sa.String(length=64),
                nullable=True,
                comment="Tenant identifier. Multi-tenant foundation (WS-1).",
            ),
        )
        if add_team_id:
            op.add_column(
                table,
                sa.Column(
                    "team_id",
                    sa.String(length=64),
                    nullable=True,
                    comment="Team identifier when the action was team-scoped (WS-8).",
                ),
            )

    # ── Backfill ────────────────────────────────────────────────────
    for table, _ in _TABLES_WITH_ORG_ID:
        bind.execute(
            sa.text(f"UPDATE {table} SET org_id = :sentinel WHERE org_id IS NULL"),
            {"sentinel": _LEGACY_SENTINEL},
        )

    # ── Indexes ─────────────────────────────────────────────────────
    # Order matters: org_id first because every tenant-scoped query starts
    # with WHERE org_id = :caller_org_id. user_id second because that's the
    # next-most-selective predicate on memories/agents.
    op.create_index(
        "idx_memories_org_user",
        "kemory_memories",
        ["org_id", "user_id"],
    )
    op.create_index(
        "idx_agent_registry_org_user",
        "kemory_agent_registry",
        ["org_id", "user_id"],
    )
    op.create_index(
        "idx_audit_log_org_time",
        "kemory_audit_log",
        ["org_id", "created_at"],
    )
    op.create_index(
        "idx_permission_rules_org_user",
        "kemory_permission_rules",
        ["org_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_permission_rules_org_user", table_name="kemory_permission_rules")
    op.drop_index("idx_audit_log_org_time", table_name="kemory_audit_log")
    op.drop_index("idx_agent_registry_org_user", table_name="kemory_agent_registry")
    op.drop_index("idx_memories_org_user", table_name="kemory_memories")

    for table, add_team_id in reversed(_TABLES_WITH_ORG_ID):
        if add_team_id:
            op.drop_column(table, "team_id")
        op.drop_column(table, "org_id")
