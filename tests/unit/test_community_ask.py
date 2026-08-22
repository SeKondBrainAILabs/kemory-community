from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from backend.services.ask_service import AskRequest, NotSynthesized, ask


def _item(kind: str = "memory", score: float = 0.8) -> dict:
    return {
        "type": kind,
        "id": f"{kind}-1",
        "title": f"{kind} title",
        "snippet": f"evidence from {kind}",
        "score": score,
        "namespace": "project",
        "captured_at": "2026-08-20T10:00:00+00:00",
        "source": "local",
    }


@pytest.mark.asyncio
async def test_ask_synthesizes_questions_and_keeps_evidence(monkeypatch):
    monkeypatch.setattr(
        "backend.services.ask_service._search_memory_items", AsyncMock(return_value=[_item()])
    )
    monkeypatch.setattr(
        "backend.services.ask_service._search_chat_items", AsyncMock(return_value=[_item("chat", 0.9)])
    )
    monkeypatch.setattr("backend.services.ask_service._search_file_items", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        "backend.services.ask_service._synthesize", AsyncMock(return_value="We chose pgvector [1].")
    )

    result = await ask(
        AsyncMock(),
        user_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        request=AskRequest(query="What did we choose?", token_budget=500),
    )

    assert result.synthesized is True
    assert result.answer == "We chose pgvector [1]."
    assert result.items[0]["type"] == "chat"
    assert result.counts == {"chat": 1, "memory": 1}
    assert result.evidence
    assert result.approx_tokens and result.approx_tokens > 0


@pytest.mark.asyncio
async def test_ask_returns_items_when_synthesis_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        "backend.services.ask_service._search_memory_items", AsyncMock(return_value=[_item()])
    )
    monkeypatch.setattr("backend.services.ask_service._search_chat_items", AsyncMock(return_value=[]))
    monkeypatch.setattr("backend.services.ask_service._search_file_items", AsyncMock(return_value=[]))
    monkeypatch.setattr("backend.services.ask_service._synthesize", AsyncMock(return_value=None))

    result = await ask(
        AsyncMock(),
        user_id=uuid.uuid4(),
        agent_id=None,
        request=AskRequest(query="Why did we choose pgvector?"),
    )

    assert result.synthesized is False
    assert result.not_synthesized_reason is NotSynthesized.DIGEST_UNAVAILABLE
    assert len(result.items) == 1


@pytest.mark.asyncio
async def test_lookup_and_no_synth_never_call_model(monkeypatch):
    monkeypatch.setattr(
        "backend.services.ask_service._search_memory_items", AsyncMock(return_value=[_item()])
    )
    monkeypatch.setattr("backend.services.ask_service._search_chat_items", AsyncMock(return_value=[]))
    monkeypatch.setattr("backend.services.ask_service._search_file_items", AsyncMock(return_value=[]))
    synth = AsyncMock()
    monkeypatch.setattr("backend.services.ask_service._synthesize", synth)

    lookup = await ask(
        AsyncMock(),
        user_id=uuid.uuid4(),
        agent_id=None,
        request=AskRequest(query="S9N-7376"),
    )
    retrieval_only = await ask(
        AsyncMock(),
        user_id=uuid.uuid4(),
        agent_id=None,
        request=AskRequest(query="What changed?", synthesize=False),
    )

    assert lookup.not_synthesized_reason is NotSynthesized.LOOKUP
    assert retrieval_only.not_synthesized_reason is NotSynthesized.NOT_REQUESTED
    synth.assert_not_awaited()


def test_ask_request_rejects_unknown_surface():
    with pytest.raises(ValidationError):
        AskRequest(query="What changed?", types=["email"])


@pytest.mark.asyncio
async def test_ask_route_uses_local_auth_context(monkeypatch):
    from backend.api.routes.ask import ask_endpoint

    expected = SimpleNamespace(query="q")
    service = AsyncMock(return_value=expected)
    monkeypatch.setattr("backend.api.routes.ask.ask", service)
    auth = SimpleNamespace(user_id=uuid.uuid4(), agent_id=uuid.uuid4())
    db = AsyncMock()

    assert await ask_endpoint(AskRequest(query="q?"), auth, db) is expected
    service.assert_awaited_once_with(
        db, user_id=auth.user_id, agent_id=auth.agent_id, request=AskRequest(query="q?")
    )
