from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.adapters.vector_store.base import SearchHit
from backend.adapters.vector_store.pgvector_backend import PgvectorBackend
from backend.services.memory_service import (
    MemorySearchRequest,
    _find_semantic_duplicate,
    search_memories,
)
from kemory.embeddings import encoder
from kemory.search.hybrid import _dedupe_by_memory_id, _rrf_merge, _sparse_pass
from kemory.search.ranking import DEFAULT_WEIGHTS, env_weights, rank_results


class _Vector:
    def __init__(self, value: float) -> None:
        self.value = value

    def tolist(self) -> list[float]:
        return [self.value] * encoder.EMBEDDING_DIM


class _FastEmbed:
    def __init__(self, vectors: list[_Vector]) -> None:
        self.vectors = vectors
        self.calls: list[tuple[list[str], int]] = []

    def embed(self, texts: list[str], *, batch_size: int):
        self.calls.append((texts, batch_size))
        yield from self.vectors


class _ConnectionContext:
    def __init__(self, connection: SimpleNamespace) -> None:
        self.connection = connection

    async def __aenter__(self) -> SimpleNamespace:
        return self.connection

    async def __aexit__(self, *_args) -> None:
        return None


def test_encode_batch_uses_one_ordered_fastembed_call(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _FastEmbed([_Vector(1.0), _Vector(2.0)])
    monkeypatch.setattr(encoder, "_remote_enabled", lambda: False)
    monkeypatch.setattr(encoder, "_load_model", lambda: model)

    vectors = encoder.encode_batch(["first", "second"])

    assert [vector[0] for vector in vectors] == [1.0, 2.0]
    assert model.calls == [(["first", "second"], encoder._LOCAL_BATCH_SIZE)]


def test_encode_batch_rejects_missing_or_wrong_dimension_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(encoder, "_remote_enabled", lambda: False)
    monkeypatch.setattr(encoder, "_load_model", lambda: _FastEmbed([_Vector(1.0)]))
    with pytest.raises(RuntimeError, match="1 vectors for 2 texts"):
        encoder.encode_batch(["first", "second"])

    monkeypatch.setattr(encoder, "_remote_enabled", lambda: True)
    monkeypatch.setattr(encoder, "_encode_remote", lambda _text: [0.0])
    with pytest.raises(RuntimeError, match="1 dims at index 0"):
        encoder.encode_batch(["first"])


@pytest.mark.asyncio
async def test_pgvector_rejects_invalid_dimensions_before_io() -> None:
    store = PgvectorBackend(engine=object())
    with pytest.raises(ValueError, match="3 dimensions; expected 384"):
        await store.search(
            namespace="shared",
            user_id=uuid.uuid4(),
            org_id="local",
            query_embedding=[1.0, 2.0, 3.0],
            limit=5,
        )


@pytest.mark.asyncio
async def test_pgvector_upsert_reuses_caller_transaction() -> None:
    connection = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), execute=AsyncMock())
    store = PgvectorBackend(engine=object())
    memory_id = uuid.uuid4()
    user_id = uuid.uuid4()

    await store.upsert(
        memory_id=memory_id,
        namespace="shared",
        user_id=user_id,
        org_id="local",
        embedding=[0.0] * 384,
        metadata={"memory_id": str(memory_id)},
        connection=connection,
    )

    statement = str(connection.execute.await_args.args[0])
    assert "INSERT INTO kemory_memory_vectors" in statement


@pytest.mark.asyncio
async def test_pgvector_search_uses_hnsw_order_without_namespace_requirement() -> None:
    result = SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: []))
    connection = SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"),
        execute=AsyncMock(return_value=result),
    )
    engine = SimpleNamespace(connect=lambda: _ConnectionContext(connection))
    store = PgvectorBackend(engine=engine)

    assert (
        await store.search(
            namespace=None,
            user_id=uuid.uuid4(),
            org_id="local",
            query_embedding=[0.0] * 384,
            limit=5,
        )
        == []
    )

    statement = str(connection.execute.await_args.args[0])
    params = connection.execute.await_args.args[1]
    assert "FROM kemory_memory_vectors" in statement
    assert "ORDER BY embedding <=>" in statement
    assert "namespace = :namespace" not in statement
    assert "namespace" not in params


def test_rrf_and_final_dedup_are_unique_and_deterministic() -> None:
    dense = [
        {"memory_id": "b", "content": "dense-b"},
        {"memory_id": "a", "content": "dense-a"},
    ]
    sparse = [
        {"memory_id": "a", "content": "sparse-a"},
        {"memory_id": "b", "content": "sparse-b"},
        {"memory_id": "", "content": "unidentifiable"},
    ]

    merged = _rrf_merge(dense, sparse)
    assert [item["memory_id"] for item in merged] == ["a", "b"]
    assert _dedupe_by_memory_id([merged[0], merged[0], merged[1]]) == merged


@pytest.mark.asyncio
async def test_sparse_pass_defers_legacy_embedding_column() -> None:
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    assert await _sparse_pass(db, uuid.uuid4(), "needle", "shared", None) == []

    statement = str(db.execute.await_args.args[0])
    assert "kemory_memories.embedding," not in statement
    assert "kemory_memories.content" in statement


def test_concept_boost_and_weight_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"memory_id": "raw", "content_type": "text", "vector_sim": 0.8},
        {"memory_id": "concept", "content_type": "concept", "vector_sim": 0.8},
    ]
    assert rank_results(rows)[0]["memory_id"] == "concept"

    monkeypatch.setenv("KMV_RANK_CONCEPT_BOOST", "0")
    ranked = rank_results(rows)
    assert ranked[0]["rank_score"] == ranked[1]["rank_score"]

    monkeypatch.setenv("KMV_RANK_W_RECENCY", "0.5")
    assert env_weights()["recency"] == 0.5
    assert env_weights()["vector_sim"] == DEFAULT_WEIGHTS["vector_sim"]


@pytest.mark.asyncio
async def test_semantic_dedup_uses_precomputed_pgvector_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory_id = uuid.uuid4()
    memory = SimpleNamespace(memory_id=memory_id)
    store = SimpleNamespace(
        search=AsyncMock(return_value=[SearchHit(memory_id=memory_id, score=0.93, metadata={})])
    )
    db_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [memory]))
    db = SimpleNamespace(execute=AsyncMock(return_value=db_result))
    monkeypatch.setattr("backend.adapters.vector_store.create_vector_store", lambda **_kw: store)
    monkeypatch.setattr(
        "kemory.embeddings.encoder.encode",
        lambda _text: pytest.fail("precomputed embedding should be reused"),
    )
    query_embedding = [0.0] * 384

    match = await _find_semantic_duplicate(
        uuid.uuid4(),
        "shared",
        "same meaning",
        0.9,
        10,
        db,
        query_embedding=query_embedding,
    )

    assert match == (memory, 0.93)
    assert store.search.await_args.kwargs["query_embedding"] is query_embedding


@pytest.mark.asyncio
async def test_semantic_dedup_falls_back_to_legacy_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = SimpleNamespace(memory_id=uuid.uuid4(), embedding=[1.0, 0.0])
    store = SimpleNamespace(search=AsyncMock(return_value=[]))
    db_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [memory]))
    db = SimpleNamespace(execute=AsyncMock(return_value=db_result))
    monkeypatch.setattr("backend.adapters.vector_store.create_vector_store", lambda **_kw: store)

    match = await _find_semantic_duplicate(
        uuid.uuid4(),
        "shared",
        "same meaning",
        0.9,
        10,
        db,
        query_embedding=[1.0, 0.0],
    )

    assert match == (memory, 1.0)


@pytest.mark.asyncio
async def test_semantic_dedup_falls_back_when_vector_search_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = SimpleNamespace(memory_id=uuid.uuid4(), embedding=[1.0, 0.0])
    store = SimpleNamespace(search=AsyncMock(side_effect=RuntimeError("vector unavailable")))
    db_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [memory]))
    db = SimpleNamespace(execute=AsyncMock(return_value=db_result))
    monkeypatch.setattr("backend.adapters.vector_store.create_vector_store", lambda **_kw: store)

    match = await _find_semantic_duplicate(
        uuid.uuid4(),
        "shared",
        "same meaning",
        0.9,
        10,
        db,
        query_embedding=[1.0, 0.0],
    )

    assert match == (memory, 1.0)


@pytest.mark.asyncio
async def test_hybrid_min_score_admits_only_strong_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def row(memory_id: str, score: float) -> dict:
        return {
            "memory_id": memory_id,
            "namespace": "shared",
            "content": memory_id,
            "content_type": "text",
            "rank_score": score,
        }

    hybrid = AsyncMock(return_value=[row("strong", 0.8), row("weak", 0.4)])
    monkeypatch.setattr("kemory.search.hybrid.hybrid_search", hybrid)
    request = MemorySearchRequest(query="topic", min_score=0.6)

    result = await search_memories(
        uuid.uuid4(),
        uuid.uuid4(),
        request,
        SimpleNamespace(),
        skip_gatekeeper=True,
    )

    assert [item.memory_id for item in result.items] == ["strong"]
    assert result.total == 1


def test_min_score_schema_bounds() -> None:
    assert MemorySearchRequest(query="topic").min_score is None
    assert MemorySearchRequest(query="topic", min_score=0.5).min_score == 0.5
    with pytest.raises(ValueError):
        MemorySearchRequest(query="topic", min_score=1.01)
