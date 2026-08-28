"""Unified namespace timeline service contracts."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import JSON, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession

os.environ.setdefault("TENANT_ENFORCEMENT", "off")

import backend.models  # noqa: E402, F401
from backend.core.database import Base  # noqa: E402
from backend.core.tenancy import (  # noqa: E402
    _current_org_id,
    _current_team_ids,
    _current_user_id,
    register_tenant_filter,
)
from backend.models.agent import AgentRegistry  # noqa: E402
from backend.models.ai_chat import AIChat, AIChatArtifact, AIChatTurn  # noqa: E402
from backend.models.memory import Memory  # noqa: E402
from backend.services.namespace_timeline_service import (  # noqa: E402
    _decode_cursor,
    get_namespace_timeline,
)

USER = uuid.uuid4()
OTHER_USER = uuid.uuid4()
ORG = "local"
NAMESPACE = "project:timeline"
AGENT_ID = uuid.uuid4()
T0 = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)

C1 = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
C2 = uuid.UUID("00000000-0000-0000-0000-0000000000c2")
C_OTHER = uuid.UUID("00000000-0000-0000-0000-0000000000cf")
M1 = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
M2 = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
M3 = uuid.UUID("00000000-0000-0000-0000-0000000000a3")


@pytest_asyncio.fixture
async def db() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    register_tenant_filter(SyncSession)
    org_token = _current_org_id.set(ORG)
    user_token = _current_user_id.set(str(USER))
    team_token = _current_team_ids.set(())
    embedding_column = Memory.__table__.columns["embedding"]
    original_type = embedding_column.type
    embedding_column.type = JSON()
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            await _seed(session)
            yield session
    finally:
        _current_team_ids.reset(team_token)
        _current_user_id.reset(user_token)
        _current_org_id.reset(org_token)
        embedding_column.type = original_type
        await engine.dispose()


def _chat(chat_id: uuid.UUID, *, captured_at: datetime | None, updated_at: datetime, user=USER):
    return AIChat(
        chat_id=chat_id,
        user_id=user,
        org_id=ORG,
        platform="chatgpt",
        platform_conversation_id=f"conv-{chat_id}",
        namespace=NAMESPACE,
        title=f"chat {chat_id}",
        content_hash=f"hash-{chat_id}",
        source_type="extension",
        captured_at=captured_at,
        created_at=updated_at,
        updated_at=updated_at,
    )


def _memory(
    memory_id: uuid.UUID,
    *,
    created_at: datetime,
    content: str,
    occurred_at: datetime | None = None,
    source_chat_id: uuid.UUID | None = None,
    source_agent_id: uuid.UUID | None = None,
):
    return Memory(
        memory_id=memory_id,
        user_id=USER,
        org_id=ORG,
        namespace=NAMESPACE,
        content=content,
        content_type="text",
        content_hash=f"hash-{memory_id}",
        source_chat_id=source_chat_id,
        source_agent_id=source_agent_id,
        occurred_at=occurred_at,
        created_at=created_at,
        updated_at=created_at,
    )


async def _seed(db: AsyncSession) -> None:
    db.add(
        AgentRegistry(
            agent_id=AGENT_ID,
            user_id=USER,
            org_id=ORG,
            agent_name="claude-code",
            agent_description="timeline test",
            api_key_hash="test",
        )
    )
    db.add(_chat(C1, captured_at=None, updated_at=T0 + timedelta(hours=2)))
    db.add(_chat(C2, captured_at=T0 + timedelta(hours=4), updated_at=T0 + timedelta(hours=1)))
    db.add(_chat(C_OTHER, captured_at=T0 + timedelta(hours=20), updated_at=T0, user=OTHER_USER))
    db.add(
        _memory(
            M1,
            created_at=T0 + timedelta(hours=9),
            content="bridged memory",
            source_chat_id=C1,
        )
    )
    db.add(
        _memory(
            M2,
            created_at=T0 + timedelta(hours=5),
            content="direct memory " * 40,
            source_agent_id=AGENT_ID,
        )
    )
    db.add(
        _memory(
            M3,
            created_at=T0 + timedelta(hours=10),
            occurred_at=T0 + timedelta(hours=6),
            content="explicit source date",
            source_chat_id=C1,
        )
    )
    await db.flush()
    turn = AIChatTurn(
        chat_id=C2,
        user_id=USER,
        org_id=ORG,
        source_turn_id="turn-1",
        role="user",
        content="hello",
        sequence=0,
    )
    db.add(turn)
    await db.flush()
    db.add(
        AIChatArtifact(
            turn_id=turn.turn_id,
            chat_id=C2,
            user_id=USER,
            org_id=ORG,
            namespace=NAMESPACE,
            artifact_type="file",
            content_sha256="0" * 64,
        )
    )
    await db.commit()


async def _all_pages(db: AsyncSession, *, limit: int = 2, types: str | None = None):
    items = []
    cursor = None
    for _ in range(10):
        response = await get_namespace_timeline(
            USER,
            NAMESPACE,
            db,
            limit=limit,
            cursor=cursor,
            types=types,
        )
        items.extend(response.items)
        if not response.has_more:
            return items, response
        cursor = response.next_cursor
    raise AssertionError("timeline pagination did not terminate")


@pytest.mark.asyncio
async def test_interleaves_source_dates_and_provenance(db: AsyncSession) -> None:
    items, response = await _all_pages(db)
    assert [(item.kind, item.id) for item in items] == [
        ("memory", str(M3)),
        ("memory", str(M2)),
        ("chat", str(C2)),
        ("chat", str(C1)),
        ("memory", str(M1)),
    ]
    assert response.next_cursor is None

    by_id = {item.id: item for item in items}
    source_chat_time = (T0 + timedelta(hours=2)).isoformat()[:19]
    assert by_id[str(M1)].occurred_at.startswith(source_chat_time)
    assert by_id[str(M3)].occurred_at.startswith((T0 + timedelta(hours=6)).isoformat()[:19])
    assert by_id[str(M1)].source_chat_id == str(C1)
    assert by_id[str(C1)].memory_count == 2
    assert by_id[str(C2)].turn_count == 1
    assert by_id[str(C2)].artifact_count == 1
    assert by_id[str(M1)].platform == "chatgpt"
    assert by_id[str(M2)].platform == "claude"
    assert by_id[str(M2)].preview.endswith("...")
    assert str(C_OTHER) not in by_id


@pytest.mark.asyncio
async def test_timeline_does_not_move_when_chat_is_updated(db: AsyncSession) -> None:
    chat = (await db.execute(select(AIChat).where(AIChat.chat_id == C1))).scalar_one()
    chat.updated_at = T0 + timedelta(days=30)
    await db.flush()

    items, _ = await _all_pages(db)
    c1 = next(item for item in items if item.id == str(C1))
    m1 = next(item for item in items if item.id == str(M1))

    assert c1.occurred_at.startswith((T0 + timedelta(hours=2)).isoformat()[:19])
    assert m1.occurred_at.startswith((T0 + timedelta(hours=2)).isoformat()[:19])


@pytest.mark.asyncio
async def test_type_filters_and_invalid_type(db: AsyncSession) -> None:
    memories, _ = await _all_pages(db, types="memory")
    assert all(item.kind == "memory" for item in memories)
    assert len(memories) == 3

    chats, _ = await _all_pages(db, types="chat")
    assert [item.id for item in chats] == [str(C2), str(C1)]

    empty = await get_namespace_timeline(USER, NAMESPACE, db, types="artifact")
    assert empty.items == []


def test_cursor_decoder_rejects_malformed_values() -> None:
    assert _decode_cursor("not-base64") is None
