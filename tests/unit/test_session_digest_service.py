"""S9N-6291 rolling session digest tests."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import JSON, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session as SyncSession

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("TENANT_ENFORCEMENT", "off")

import backend.models  # noqa: F401, E402
from backend.core import tenancy  # noqa: E402
from backend.core.database import Base  # noqa: E402
from backend.core.tenancy import bypass_tenant_filter, register_tenant_filter  # noqa: E402
from backend.models.memory import Memory  # noqa: E402
from backend.models.namespace_policy import NamespacePolicy  # noqa: E402
from backend.models.session_digest import SessionDigest  # noqa: E402
from backend.models.session_summary import SessionSummary  # noqa: E402
from backend.services.session_digest_service import (  # noqa: E402
    count_tokens,
    detect_rehydration_trigger,
    get_session_context,
    load_session_exchanges,
    rehydrate_session_sources,
)


@contextmanager
def scoped_tenant(org_id: str, user_id: uuid.UUID):
    org_token = tenancy._current_org_id.set(org_id)
    user_token = tenancy._current_user_id.set(str(user_id))
    try:
        yield
    finally:
        tenancy._current_user_id.reset(user_token)
        tenancy._current_org_id.reset(org_token)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    register_tenant_filter(SyncSession)

    memory_table = Memory.__table__
    embedding_col = memory_table.columns.get("embedding")
    original_type = embedding_col.type if embedding_col is not None else None
    if embedding_col is not None:
        embedding_col.type = JSON()

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session
            await session.rollback()
        await engine.dispose()
    finally:
        if embedding_col is not None and original_type is not None:
            embedding_col.type = original_type


@pytest.mark.asyncio
async def test_session_context_compacts_older_exchanges_and_keeps_latest_three_raw(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("CORE_AI_BACKEND_URL", raising=False)
    monkeypatch.delenv("AI_BACKEND_URL", raising=False)

    user_id = uuid.uuid4()
    org_id = "org-test"
    namespace = "project-kemory"
    session_id = "sess-ctx"
    base_ts = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)

    with bypass_tenant_filter():
        db_session.add(
            NamespacePolicy(
                namespace=namespace,
                created_by=user_id,
                consolidated_summary="Kemory is tightening prompt context around readable summaries.",
                consolidated_summary_tier="L3.1",
            )
        )
        db_session.add(
            SessionSummary(
                user_id=user_id,
                namespace=namespace,
                session_id=session_id,
                session_summary="The current session is about S9N-6291 rolling context.",
                session_summary_tier="L3",
                session_memory_count=5,
                cumulative_summary="Earlier namespace work established AAAK as byte compression only.",
                cumulative_summary_tier="L3",
                cumulative_memory_count=9,
                up_to_ts=base_ts,
            )
        )
        for idx in range(5):
            db_session.add(
                Memory(
                    user_id=user_id,
                    org_id=org_id,
                    namespace=namespace,
                    content=f"User: question {idx + 1}\nAssistant: answer {idx + 1}",
                    content_type="text",
                    content_hash=f"hash-{idx}",
                    source_type="api",
                    session_id=session_id,
                    created_at=base_ts + timedelta(minutes=idx),
                    updated_at=base_ts + timedelta(minutes=idx),
                )
            )
        await db_session.flush()

    with scoped_tenant(org_id, user_id):
        result = await get_session_context(
            user_id,
            uuid.uuid4(),
            namespace,
            session_id,
            db_session,
            token_budget=600,
            max_relevant_memories=0,
            include_expansion_hooks=True,
        )

        row = (
            await db_session.execute(
                select(SessionDigest).where(
                    SessionDigest.user_id == user_id,
                    SessionDigest.namespace == namespace,
                    SessionDigest.session_id == session_id,
                )
            )
        ).scalar_one()

    assert result["source_exchange_count"] == 5
    assert result["digest"]["tier"] == "L2.1-extractive"
    assert result["digest"]["compacted_exchange_count"] == 2
    assert result["digest"]["pending_source_count"] == 2
    assert len(result["raw_tail"]) == 3
    assert "question 1" in result["digest"]["text"]
    assert "question 5" in result["raw_tail"][-1]["content"]
    assert "Namespace/session summary" in result["context"]["text"]
    assert "Latest 3 raw exchange(s)" in result["context"]["text"]
    assert "AAAK encoding" not in result["context"]["text"]
    assert result["expansion_hooks"]["tool"] == "kemory_rehydrate_session_sources"
    assert len(result["expansion_hooks"]["digest"]["source_memory_ids"]) == 2
    assert row.compacted_exchange_count == 2
    assert len(row.source_memory_ids) == 2

    with scoped_tenant(org_id, user_id):
        second = await get_session_context(
            user_id,
            uuid.uuid4(),
            namespace,
            session_id,
            db_session,
            token_budget=600,
            max_relevant_memories=0,
        )

    assert second["digest"]["pending_source_count"] == 0
    assert second["digest"]["source_exchange_ids"] == result["digest"]["source_exchange_ids"]


def test_token_counter_documents_fallback_when_model_has_no_tiktoken_mapping():
    counted = count_tokens("abcdef", "llama-3.3-70b-versatile")
    assert counted.count == 2
    assert counted.model == "llama-3.3-70b-versatile"
    assert counted.tokenizer_name is None
    assert counted.method == "fallback_chars_per_token_3"


@pytest.mark.asyncio
async def test_load_session_exchanges_can_fall_back_to_chat_turns(
    db_session: AsyncSession,
):
    from backend.models.ai_chat import AIChat, AIChatTurn

    user_id = uuid.uuid4()
    org_id = "org-test"
    namespace = "project-kemory"
    chat_id = uuid.uuid4()
    base_ts = datetime(2026, 7, 21, 11, 0, tzinfo=UTC)

    with bypass_tenant_filter():
        db_session.add(
            AIChat(
                chat_id=chat_id,
                user_id=user_id,
                org_id=org_id,
                platform="chatgpt",
                platform_conversation_id="conv-1",
                namespace=namespace,
                title="Rolling context",
                content_hash="chat-hash",
            )
        )
        db_session.add_all(
            [
                AIChatTurn(
                    turn_id=uuid.uuid4(),
                    chat_id=chat_id,
                    user_id=user_id,
                    org_id=org_id,
                    source_turn_id="t1",
                    role="user",
                    content="How should the rolling digest work?",
                    sequence=1,
                    created_at=base_ts,
                ),
                AIChatTurn(
                    turn_id=uuid.uuid4(),
                    chat_id=chat_id,
                    user_id=user_id,
                    org_id=org_id,
                    source_turn_id="t2",
                    role="assistant",
                    content="Keep the latest exchange raw and compact older exchanges.",
                    sequence=2,
                    created_at=base_ts + timedelta(minutes=1),
                ),
            ]
        )
        await db_session.flush()

    with scoped_tenant(org_id, user_id):
        exchanges = await load_session_exchanges(user_id, namespace, str(chat_id), db_session)

    assert len(exchanges) == 1
    assert exchanges[0].source == "chat_turn"
    assert "Rolling context" in exchanges[0].content
    assert "Keep the latest exchange raw" in exchanges[0].content


@pytest.mark.asyncio
async def test_rehydrate_session_sources_expands_exact_raw_memory_without_mutation(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("CORE_AI_BACKEND_URL", raising=False)
    monkeypatch.delenv("AI_BACKEND_URL", raising=False)

    user_id = uuid.uuid4()
    org_id = "org-test"
    namespace = "project-kemory"
    session_id = "sess-rehydrate"
    base_ts = datetime(2026, 7, 21, 12, 0, tzinfo=UTC)
    raw_contents = [
        "User: decide the drill-to-raw path\nAssistant: use source IDs and keep raw read-only.",
        "User: add a second point\nAssistant: budget raw expansions by whole item.",
        "User: latest one\nAssistant: keep it raw.",
        "User: latest two\nAssistant: keep it raw.",
    ]

    with bypass_tenant_filter():
        memory_ids: list[str] = []
        for idx, content in enumerate(raw_contents):
            memory = Memory(
                user_id=user_id,
                org_id=org_id,
                namespace=namespace,
                content=content,
                content_type="conversation",
                content_hash=f"rehydrate-hash-{idx}",
                source_type="api",
                session_id=session_id,
                created_at=base_ts + timedelta(minutes=idx),
                updated_at=base_ts + timedelta(minutes=idx),
            )
            db_session.add(memory)
            await db_session.flush()
            memory_ids.append(str(memory.memory_id))

    with scoped_tenant(org_id, user_id):
        await get_session_context(
            user_id,
            uuid.uuid4(),
            namespace,
            session_id,
            db_session,
            token_budget=600,
            max_relevant_memories=0,
        )
        result = await rehydrate_session_sources(
            user_id,
            namespace,
            session_id,
            db_session,
            source_memory_ids=[memory_ids[0]],
            token_budget=300,
            trigger="explicit",
        )
        stored = (
            await db_session.execute(select(Memory).where(Memory.memory_id == uuid.UUID(memory_ids[0])))
        ).scalar_one()

    assert result["expanded_count"] == 1
    assert result["items"][0]["content"] == raw_contents[0]
    assert result["items"][0]["memory_id"] == memory_ids[0]
    assert result["omitted_items"] == []
    assert stored.content == raw_contents[0]
    assert stored.version == 1
    assert "AAAK" not in result["text"]


@pytest.mark.asyncio
async def test_rehydrate_session_sources_omits_whole_items_over_token_budget(
    db_session: AsyncSession,
):
    user_id = uuid.uuid4()
    org_id = "org-test"
    namespace = "project-kemory"
    session_id = "sess-budget"
    base_ts = datetime(2026, 7, 21, 13, 0, tzinfo=UTC)

    with bypass_tenant_filter():
        large = Memory(
            user_id=user_id,
            org_id=org_id,
            namespace=namespace,
            content="User: " + ("alpha beta gamma delta " * 80),
            content_type="conversation",
            content_hash="large-budget",
            source_type="api",
            session_id=session_id,
            created_at=base_ts,
            updated_at=base_ts,
        )
        small = Memory(
            user_id=user_id,
            org_id=org_id,
            namespace=namespace,
            content="User: ship selective rehydration.\nAssistant: include this exact short item.",
            content_type="conversation",
            content_hash="small-budget",
            source_type="api",
            session_id=session_id,
            created_at=base_ts + timedelta(minutes=1),
            updated_at=base_ts + timedelta(minutes=1),
        )
        db_session.add_all([large, small])
        await db_session.flush()
        db_session.add(
            SessionDigest(
                org_id=org_id,
                user_id=user_id,
                namespace=namespace,
                session_id=session_id,
                digest="Open loops\n- ship selective rehydration",
                digest_tier="L2.1-extractive",
                source_exchange_ids=[f"memory:{large.memory_id}", f"memory:{small.memory_id}"],
                source_memory_ids=[str(large.memory_id), str(small.memory_id)],
                source_turn_ids=[],
                compacted_exchange_count=2,
            )
        )
        await db_session.flush()

    with scoped_tenant(org_id, user_id):
        result = await rehydrate_session_sources(
            user_id,
            namespace,
            session_id,
            db_session,
            source_memory_ids=[str(large.memory_id), str(small.memory_id)],
            token_budget=120,
            model="llama-3.3-70b-versatile",
            max_items=1,
            trigger="explicit",
        )

    assert result["expanded_count"] == 1
    assert result["items"][0]["memory_id"] == str(small.memory_id)
    assert result["omitted_items"][0]["memory_id"] == str(large.memory_id)
    assert result["omitted_items"][0]["reason"] == "over_token_budget_whole_item_not_sliced"
    assert "alpha beta gamma delta" not in result["text"]
    assert "include this exact short item" in result["text"]


@pytest.mark.asyncio
async def test_heuristic_rehydration_ranks_digest_sources_by_query(
    db_session: AsyncSession,
):
    user_id = uuid.uuid4()
    org_id = "org-test"
    namespace = "project-kemory"
    session_id = "sess-heuristic"
    base_ts = datetime(2026, 7, 21, 14, 0, tzinfo=UTC)

    with bypass_tenant_filter():
        unrelated = Memory(
            user_id=user_id,
            org_id=org_id,
            namespace=namespace,
            content="User: discuss the dashboard colors.\nAssistant: keep the palette restrained.",
            content_type="conversation",
            content_hash="heuristic-unrelated",
            source_type="api",
            session_id=session_id,
            created_at=base_ts,
            updated_at=base_ts,
        )
        relevant = Memory(
            user_id=user_id,
            org_id=org_id,
            namespace=namespace,
            content="User: what should Postgres store?\nAssistant: Postgres stores source IDs for raw fallback.",
            content_type="conversation",
            content_hash="heuristic-relevant",
            source_type="api",
            session_id=session_id,
            created_at=base_ts + timedelta(minutes=1),
            updated_at=base_ts + timedelta(minutes=1),
        )
        db_session.add_all([unrelated, relevant])
        await db_session.flush()
        db_session.add(
            SessionDigest(
                org_id=org_id,
                user_id=user_id,
                namespace=namespace,
                session_id=session_id,
                digest=f"Retrieval hooks\n- Postgres storage decision [memory:{relevant.memory_id}]",
                digest_tier="L2.1",
                source_exchange_ids=[f"memory:{unrelated.memory_id}", f"memory:{relevant.memory_id}"],
                source_memory_ids=[str(unrelated.memory_id), str(relevant.memory_id)],
                source_turn_ids=[],
                compacted_exchange_count=2,
            )
        )
        await db_session.flush()

    with scoped_tenant(org_id, user_id):
        result = await rehydrate_session_sources(
            user_id,
            namespace,
            session_id,
            db_session,
            query="exact raw source for postgres fallback",
            trigger="heuristic",
            token_budget=300,
        )

    assert result["trigger"]["mode"] == "heuristic"
    assert result["items"][0]["memory_id"] == str(relevant.memory_id)
    assert "Postgres stores source IDs" in result["text"]


def test_detect_rehydration_trigger_suggests_heuristic_for_detail_query():
    trigger = detect_rehydration_trigger(
        topic="show the exact raw source for that decision",
        digest_state={
            "text": "Open loops\n- decide fallback",
            "source_exchange_ids": [f"memory:{uuid.uuid4()}"],
            "source_memory_ids": [],
            "source_turn_ids": [],
        },
        explicit=False,
    )

    assert trigger["suggested"] is True
    assert trigger["trigger"] == "heuristic"
    assert trigger["tool"] == "kemory_rehydrate_session_sources"


def test_fit_text_to_budget_omits_lines_without_syntactic_fragment_markers():
    from backend.services.session_digest_service import fit_text_to_budget

    text = "\n".join(
        [
            "Open loops",
            "- preserve raw source IDs",
            "- " + ("full semantic line " * 80),
        ]
    )
    fitted, token_meta = fit_text_to_budget(text, 32, "llama-3.3-70b-versatile")

    assert token_meta.count <= 32
    assert "..." not in fitted
    assert "[trimmed" not in fitted
    assert "additional semantic digest lines omitted" in fitted
