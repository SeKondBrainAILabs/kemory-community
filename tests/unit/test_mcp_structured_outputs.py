"""Community MCP output-schema and upstream-adapter contracts."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.mcp.tools import TOOL_DEFINITIONS
from backend.mcp.tools import memory as memory_tools


def test_every_advertised_tool_declares_an_output_schema() -> None:
    assert TOOL_DEFINITIONS
    assert all(tool.outputSchema for tool in TOOL_DEFINITIONS)


@pytest.mark.asyncio
async def test_store_memory_forwards_namespace_tag_and_returns_structure(monkeypatch) -> None:
    stored = SimpleNamespace(
        memory_id="00000000-0000-0000-0000-000000000001",
        namespace="project:kemory",
        namespace_tag="release",
        version=1,
        content_type="fact",
        dedup=None,
        model_dump=lambda **_: {
            "memory_id": "00000000-0000-0000-0000-000000000001",
            "namespace": "project:kemory",
            "namespace_tag": "release",
            "content": "Ship the release",
            "content_type": "fact",
        },
    )
    create = AsyncMock(return_value=stored)
    monkeypatch.setattr(memory_tools, "create_memory", create)

    result = await memory_tools._handle_store_memory(
        {
            "namespace": "project:kemory",
            "namespace_tag": "release",
            "content": "Ship the release",
            "content_type": "fact",
        },
        uuid.uuid4(),
        uuid.uuid4(),
        object(),
    )

    request = create.await_args.args[2]
    assert request.namespace_tag == "release"
    assert result.structuredContent["memory"]["namespace_tag"] == "release"
    assert result.structuredContent["deduplicated"] is False
    assert result.content[0]["text"].startswith("Memory stored successfully.")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("handler", "arguments"),
    [
        (memory_tools._handle_recall_memory, {"query": "release", "min_relevance": 0.42}),
        (memory_tools._handle_find_similar, {"content": "release", "min_relevance": 0.42}),
    ],
)
async def test_memory_reads_forward_relevance_floor_and_return_empty_structure(
    monkeypatch,
    handler,
    arguments,
) -> None:
    search = AsyncMock(return_value=SimpleNamespace(total=0, items=[]))
    monkeypatch.setattr(memory_tools, "search_memories", search)
    monkeypatch.setattr(memory_tools, "_skip_gatekeeper", lambda: True)

    result = await handler(arguments, uuid.uuid4(), uuid.uuid4(), object())

    request = search.await_args.args[2]
    assert request.min_score == 0.42
    assert result.structuredContent == {"total": 0, "showing": 0, "memories": []}

