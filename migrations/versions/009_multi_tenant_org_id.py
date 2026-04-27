"""Multi-tenant foundation: add org_id to tenant-scoped tables.

This is step 1 of the 3-step nullable→backfill→NOT NULL chain described in
docs/architecture/KEMORY_MULTI_TENANT_AUTH_PLAN.md (WS-1).

What this migration does:
  - Adds a nullable `org_id VARCHAR(64)` column to:
      * s9nmv_memories
      * s9nmv_agent_registry
      * s9nmv_audit_log         (also adds team_id for WS-8)
      * s9nmv_permission_rules
  - Backfills every existing row with org_id='legacy' so future NOT NULL
    enforcement (revision 011) can run without scanning for orphans.
  - Adds composite indexes (org_id, user_id) on the hot read paths so the
    tenant filter introduced in WS-3 keeps p95 read latency within budget.

What this migration does NOT do:
  - It does NOT mark org_id NOT NULL — that's revision 011, gated on WS-2
    being live in shadow mode for ≥72h so producers populate the column.
  - It does NOT enforce any tenant filtering — TENANT_ENFORCEMENT defaults
    to "off" until WS-3 lands.
  - It does NOT touch teams / team_members tables (those already have org_id
    via 004_mv3_visibility_teams).

Safe to deploy alongside the current binary: the new column is invisible to
SQLAlchemy 2.x model code that hasn't been updated yet, and the backfill
runs as a single bounded UPDATE per table (low row count today).

Revision ID: 009
"""
from alembic import op
import sqlalchemy as sa


revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


# (table_name, add_team_id) — team_id is only added to audit_log; memories
# already has it from 004_mv3_visibility_teams; agent_registry/permission_rules
# don't need it.
_TABLES_WITH_ORG_ID = [
    ("s9nmv_memories", False),
    ("s9nmv_agent_registry", False),
    ("s9nmv_audit_log", True),
    ("s9nmv_permission_rules", False),
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
    # Single statement per table — row counts in staging are low today.
    # If this needs to scale, switch to batched UPDATE LIMIT N.
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
        "s9nmv_memories",
        ["org_id", "user_id"],
    )
    op.create_index(
        "idx_agent_registry_org_user",
        "s9nmv_agent_registry",
        ["org_id", "user_id"],
    )
    op.create_index(
        "idx_audit_log_org_time",
        "s9nmv_audit_log",
        ["org_id", "created_at"],
    )
    op.create_index(
        "idx_permission_rules_org_user",
        "s9nmv_permission_rules",
        ["org_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_permission_rules_org_user", table_name="s9nmv_permission_rules")
    op.drop_index("idx_audit_log_org_time", table_name="s9nmv_audit_log")
    op.drop_index("idx_agent_registry_org_user", table_name="s9nmv_agent_registry")
    op.drop_index("idx_memories_org_user", table_name="s9nmv_memories")

    for table, add_team_id in reversed(_TABLES_WITH_ORG_ID):
        if add_team_id:
            op.drop_column(table, "team_id")
        op.drop_column(table, "org_id")
