"""Focused contracts for source chronology (migration 019)."""

from datetime import UTC, datetime
from importlib import import_module
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, text

from backend.api.routes.artifacts import _parse_occurred_at
from backend.models.ai_chat import AIChatArtifact, AIChatTurn
from backend.models.memory import Memory
from backend.services.ai_chat_service import (
    ArtifactUpsert,
    TurnUpsert,
    _artifact_to_response,
    _canonical_turn_dict,
)
from backend.services.memory_service import MemoryCreate
from kemory.search.hybrid import _row_to_dict

SOURCE_TIME = datetime(2025, 2, 3, 4, 5, tzinfo=UTC)


def test_memory_create_validates_occurred_at() -> None:
    request = MemoryCreate(
        namespace="project",
        content="Source-dated memory",
        occurred_at="2025-02-03T04:05:00Z",
    )
    assert request.occurred_at == "2025-02-03T04:05:00Z"

    with pytest.raises(ValidationError, match="valid ISO-8601"):
        MemoryCreate(namespace="project", content="Bad date", occurred_at="last Tuesday-ish")


def test_models_expose_nullable_source_date_columns() -> None:
    assert Memory.__table__.c.occurred_at.nullable
    assert AIChatTurn.__table__.c.occurred_at.nullable
    assert AIChatArtifact.__table__.c.occurred_at.nullable


def test_turn_timestamp_changes_hash_projection_only_when_supplied() -> None:
    base = TurnUpsert(role="user", content="hello", sequence=0)
    dated = TurnUpsert(role="user", content="hello", sequence=0, timestamp=SOURCE_TIME)

    assert "timestamp" not in _canonical_turn_dict(base)
    assert _canonical_turn_dict(dated)["timestamp"] == SOURCE_TIME.isoformat()


def test_hybrid_row_surfaces_occurred_at() -> None:
    row = SimpleNamespace(
        memory_id=uuid4(),
        namespace="project",
        content="hello",
        content_type="text",
        meta={},
        source_agent_id=None,
        source_type="agent",
        quality_score=None,
        enrichment_status="pending",
        version=1,
        ttl_seconds=None,
        expires_at=None,
        session_id=None,
        round_id=None,
        valid_at=None,
        occurred_at=SOURCE_TIME,
        invalid_at=None,
        decay_score=1.0,
        temporal_anchor=None,
        access_count=0,
        created_at=SOURCE_TIME,
        updated_at=SOURCE_TIME,
    )
    assert _row_to_dict(row)["occurred_at"] == SOURCE_TIME.isoformat()


def test_artifact_response_surfaces_occurred_at() -> None:
    row = AIChatArtifact(
        artifact_id=uuid4(),
        turn_id=None,
        chat_id=None,
        user_id=uuid4(),
        org_id="local",
        namespace="project",
        artifact_type="file",
        content_sha256="0" * 64,
        artifact_metadata=None,
        occurred_at=SOURCE_TIME,
        created_at=SOURCE_TIME,
    )
    assert _artifact_to_response(row).occurred_at == SOURCE_TIME.isoformat()


def test_artifact_form_date_parser_rejects_malformed_values() -> None:
    assert _parse_occurred_at("2025-02-03T04:05:00Z") == SOURCE_TIME
    with pytest.raises(HTTPException) as exc_info:
        _parse_occurred_at("not-a-date")
    assert exc_info.value.status_code == 422


def test_artifact_date_is_hash_excluded_for_noop_backfill() -> None:
    plain = ArtifactUpsert(artifact_type="file", content="same")
    dated = ArtifactUpsert(artifact_type="file", content="same", occurred_at=SOURCE_TIME)
    plain_turn = TurnUpsert(role="user", content="hello", sequence=0, artifacts=[plain])
    dated_turn = TurnUpsert(role="user", content="hello", sequence=0, artifacts=[dated])
    assert _canonical_turn_dict(plain_turn) == _canonical_turn_dict(dated_turn)


def test_migration_backfills_null_dates_from_source_chat() -> None:
    migration = import_module("backend.migrations.versions.019_content_dates")
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE kemory_ai_chats "
                "(chat_id TEXT PRIMARY KEY, captured_at TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE kemory_memories "
                "(memory_id TEXT PRIMARY KEY, source_chat_id TEXT, occurred_at TIMESTAMP)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE kemory_ai_chat_artifacts "
                "(artifact_id TEXT PRIMARY KEY, chat_id TEXT, occurred_at TIMESTAMP)"
            )
        )
        conn.execute(
            text("INSERT INTO kemory_ai_chats VALUES ('chat-1', :captured_at)"),
            {"captured_at": SOURCE_TIME},
        )
        conn.execute(text("INSERT INTO kemory_memories VALUES ('memory-1', 'chat-1', NULL)"))
        conn.execute(
            text("INSERT INTO kemory_ai_chat_artifacts VALUES ('artifact-1', 'chat-1', NULL)")
        )

        migration._backfill_from_source_chat(conn)

        memory_date = conn.execute(
            text("SELECT occurred_at FROM kemory_memories WHERE memory_id='memory-1'")
        ).scalar_one()
        artifact_date = conn.execute(
            text("SELECT occurred_at FROM kemory_ai_chat_artifacts WHERE artifact_id='artifact-1'")
        ).scalar_one()
        assert memory_date.startswith("2025-02-03 04:05:00")
        assert artifact_date.startswith("2025-02-03 04:05:00")
