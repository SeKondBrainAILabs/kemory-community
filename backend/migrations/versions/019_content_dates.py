"""Add source content dates to memories, chat turns, and artifacts.

Revision ID: 019
Revises: 018
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def upgrade() -> None:
    columns = (
        ("kemory_memories", "occurred_at"),
        ("kemory_ai_chat_turns", "occurred_at"),
        ("kemory_ai_chat_artifacts", "occurred_at"),
    )
    for table_name, column_name in columns:
        if _has_table(table_name) and not _has_column(table_name, column_name):
            op.add_column(
                table_name,
                sa.Column(column_name, sa.DateTime(timezone=True), nullable=True),
            )

    if _has_table("kemory_memories") and not _has_index(
        "kemory_memories", "idx_memories_user_occurred"
    ):
        op.create_index(
            "idx_memories_user_occurred",
            "kemory_memories",
            ["user_id", "occurred_at"],
            unique=False,
        )

    if all(
        _has_table(table)
        for table in ("kemory_memories", "kemory_ai_chats", "kemory_ai_chat_artifacts")
    ):
        _backfill_from_source_chat(op.get_bind())


def _backfill_from_source_chat(bind) -> None:
    """Fill unknown dates from the linked chat without replacing known dates."""
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                """
                UPDATE kemory_memories m
                SET occurred_at = c.captured_at
                FROM kemory_ai_chats c
                WHERE m.source_chat_id = c.chat_id
                  AND m.occurred_at IS NULL
                  AND c.captured_at IS NOT NULL
                """
            )
        )
        bind.execute(
            sa.text(
                """
                UPDATE kemory_ai_chat_artifacts a
                SET occurred_at = c.captured_at
                FROM kemory_ai_chats c
                WHERE a.chat_id = c.chat_id
                  AND a.occurred_at IS NULL
                  AND c.captured_at IS NOT NULL
                """
            )
        )
        return

    bind.execute(
        sa.text(
            """
            UPDATE kemory_memories
            SET occurred_at = (
                SELECT c.captured_at FROM kemory_ai_chats c
                WHERE c.chat_id = kemory_memories.source_chat_id
            )
            WHERE occurred_at IS NULL
              AND source_chat_id IS NOT NULL
              AND (
                SELECT c.captured_at FROM kemory_ai_chats c
                WHERE c.chat_id = kemory_memories.source_chat_id
              ) IS NOT NULL
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE kemory_ai_chat_artifacts
            SET occurred_at = (
                SELECT c.captured_at FROM kemory_ai_chats c
                WHERE c.chat_id = kemory_ai_chat_artifacts.chat_id
            )
            WHERE occurred_at IS NULL
              AND chat_id IS NOT NULL
              AND (
                SELECT c.captured_at FROM kemory_ai_chats c
                WHERE c.chat_id = kemory_ai_chat_artifacts.chat_id
              ) IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    if _has_index("kemory_memories", "idx_memories_user_occurred"):
        op.drop_index("idx_memories_user_occurred", table_name="kemory_memories")
    for table_name, column_name in reversed(
        (
            ("kemory_memories", "occurred_at"),
            ("kemory_ai_chat_turns", "occurred_at"),
            ("kemory_ai_chat_artifacts", "occurred_at"),
        )
    ):
        if _has_column(table_name, column_name):
            op.drop_column(table_name, column_name)
