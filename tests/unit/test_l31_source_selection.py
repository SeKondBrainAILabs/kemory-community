"""L3.1 source-selection contracts."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services import compression_pipeline


class _CountResult:
    def scalar_one(self):
        return 4


class _SourceResult:
    def __init__(self, sources):
        self._sources = sources

    def scalars(self):
        return self

    def all(self):
        return self._sources


@pytest.mark.asyncio
async def test_l31_sources_are_newest_first_and_capped(monkeypatch) -> None:
    sources = [SimpleNamespace(memory_id=uuid.uuid4()) for _ in range(2)]
    db = SimpleNamespace(execute=AsyncMock(side_effect=[_CountResult(), _SourceResult(sources)]))
    synthesize = AsyncMock(return_value={"synthesis": ""})
    monkeypatch.setattr(compression_pipeline, "_synthesize_concept", synthesize)
    monkeypatch.setattr(compression_pipeline, "_memory_to_dict", lambda item: {"id": str(item.memory_id)})
    monkeypatch.setattr(compression_pipeline, "L3_SYNTHESIS_THRESHOLD", 1)
    monkeypatch.setattr(compression_pipeline, "L3_SYNTHESIS_MAX_SOURCES", 2)
    compression_pipeline._last_synthesis_count.clear()

    await compression_pipeline._maybe_synthesize_l3_1(db, str(uuid.uuid4()), "project:kemory")

    source_query = db.execute.await_args_list[1].args[0]
    rendered = str(source_query)
    assert "ORDER BY kemory_memories.created_at DESC, kemory_memories.memory_id DESC" in rendered
    assert "LIMIT" in rendered
    assert synthesize.await_args.args[0] == [{"id": str(item.memory_id)} for item in sources]
