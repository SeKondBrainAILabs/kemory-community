"""Add api_key_prefix column for fast API key lookup.

Bcrypt verification is ~170ms per call. With N agents, authentication
takes O(N * 170ms). Adding a SHA-256 prefix column enables O(1) lookup
via indexed query, reducing auth from ~500ms to ~5ms.

Existing agents will have NULL prefix and will be backfilled on first
successful auth (the fallback path handles this automatically).

Revision ID: 006
"""
from alembic import op
import sqlalchemy as sa


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "kora_agent_registry",
        sa.Column("api_key_prefix", sa.String(16), nullable=True),
    )
    op.create_index(
        "idx_agent_registry_key_prefix",
        "kora_agent_registry",
        ["api_key_prefix"],
    )


def downgrade() -> None:
    op.drop_index("idx_agent_registry_key_prefix", table_name="kora_agent_registry")
    op.drop_column("kora_agent_registry", "api_key_prefix")
