from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from backend.mcp.tools import TOOL_DEFINITIONS
from backend.mcp.tools.ask import _handle_ask
from backend.services.ask_service import AskResponse, NotSynthesized


def test_ask_is_canonical_and_declares_structured_output():
    definition = next(tool for tool in TOOL_DEFINITIONS if tool.name == "kemory_ask")
    assert definition.outputSchema
    assert definition.inputSchema["required"] == ["query"]


@pytest.mark.asyncio
async def test_ask_handler_returns_text_and_structured_content(monkeypatch):
    service = AsyncMock(
        return_value=AskResponse(
            query="What changed?",
            answer="Ask was added [1].",
            synthesized=True,
            evidence=[{"type": "memory", "id": "m1"}],
            items=[{"type": "memory", "id": "m1"}],
            counts={"memory": 1},
        )
    )
    monkeypatch.setattr("backend.services.ask_service.ask", service)

    result = await _handle_ask(
        {"query": "What changed?"},
        uuid.uuid4(),
        uuid.uuid4(),
        AsyncMock(),
    )

    assert result.content[0]["text"] == "Ask was added [1]."
    assert result.structuredContent["synthesized"] is True


@pytest.mark.asyncio
async def test_ask_handler_has_actionable_validation_and_fallback(monkeypatch):
    missing = await _handle_ask({}, uuid.uuid4(), None, AsyncMock())
    assert missing.isError is True
    assert "query is required" in missing.content[0]["text"]

    monkeypatch.setattr(
        "backend.services.ask_service.ask",
        AsyncMock(
            return_value=AskResponse(
                query="q",
                not_synthesized_reason=NotSynthesized.DIGEST_UNAVAILABLE,
                items=[{"type": "chat", "id": "c1"}],
                counts={"chat": 1},
            )
        ),
    )
    fallback = await _handle_ask({"query": "q"}, uuid.uuid4(), None, AsyncMock())
    assert "Retrieved 1 evidence item" in fallback.content[0]["text"]
    assert fallback.structuredContent["items"]
