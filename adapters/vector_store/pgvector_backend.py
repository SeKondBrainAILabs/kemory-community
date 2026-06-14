"""Pgvector-backed VectorStore implementation."""

from __future__ import annotations

import json
import math
from typing import Any
from uuid import UUID

from sqlalchemy import text

from backend.adapters.vector_store.base import SearchHit, VectorStore


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(float(v)) for v in values) + "]"


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


class PgvectorBackend(VectorStore):
    """VectorStore backed by pgvector, with a SQLite/PGlite-friendly fallback."""

    def __init__(self, *, engine: Any, dimension: int = 384) -> None:
        self._engine = engine
        self._dimension = dimension

    async def _dialect_name(self) -> str:
        async with self._engine.connect() as conn:
            return conn.dialect.name

    async def upsert(
        self,
        *,
        memory_id: UUID,
        namespace: str,
        user_id: UUID,
        org_id: UUID | str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> None:
        dialect = await self._dialect_name()
        if dialect == "postgresql":
            await self._upsert_postgres(
                memory_id=memory_id,
                namespace=namespace,
                user_id=user_id,
                org_id=org_id,
                embedding=embedding,
                metadata=metadata,
            )
            return
        await self._upsert_sqlite(
            memory_id=memory_id,
            namespace=namespace,
            user_id=user_id,
            org_id=org_id,
            embedding=embedding,
            metadata=metadata,
        )

    async def _upsert_postgres(
        self,
        *,
        memory_id: UUID,
        namespace: str,
        user_id: UUID,
        org_id: UUID | str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO kemory_memory_vectors
                        (memory_id, namespace, user_id, org_id, embedding, metadata, created_at, updated_at)
                    VALUES
                        (:memory_id, :namespace, :user_id, :org_id,
                         CAST(:embedding AS vector), CAST(:metadata AS jsonb), NOW(), NOW())
                    ON CONFLICT (memory_id, user_id, org_id)
                    DO UPDATE SET
                        namespace = EXCLUDED.namespace,
                        embedding = EXCLUDED.embedding,
                        metadata = EXCLUDED.metadata,
                        updated_at = NOW()
                """),
                {
                    "memory_id": str(memory_id),
                    "namespace": namespace,
                    "user_id": str(user_id),
                    "org_id": str(org_id),
                    "embedding": _vector_literal(embedding),
                    "metadata": json.dumps(metadata),
                },
            )

    async def _upsert_sqlite(
        self,
        *,
        memory_id: UUID,
        namespace: str,
        user_id: UUID,
        org_id: UUID | str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""
                    CREATE TABLE IF NOT EXISTS kemory_memory_vectors (
                        memory_id CHAR(36) NOT NULL,
                        namespace VARCHAR(100) NOT NULL,
                        user_id CHAR(36) NOT NULL,
                        org_id VARCHAR(64) NOT NULL,
                        embedding BLOB,
                        metadata TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        updated_at TEXT DEFAULT CURRENT_TIMESTAMP NOT NULL,
                        PRIMARY KEY (memory_id, user_id, org_id)
                    )
                """)
            )
            await conn.execute(
                text("""
                    INSERT INTO kemory_memory_vectors
                        (memory_id, namespace, user_id, org_id, embedding, metadata, updated_at)
                    VALUES
                        (:memory_id, :namespace, :user_id, :org_id, :embedding, :metadata, CURRENT_TIMESTAMP)
                    ON CONFLICT (memory_id, user_id, org_id)
                    DO UPDATE SET
                        namespace = excluded.namespace,
                        embedding = excluded.embedding,
                        metadata = excluded.metadata,
                        updated_at = CURRENT_TIMESTAMP
                """),
                {
                    "memory_id": str(memory_id),
                    "namespace": namespace,
                    "user_id": str(user_id),
                    "org_id": str(org_id),
                    "embedding": json.dumps(embedding),
                    "metadata": json.dumps(metadata),
                },
            )

    async def search(
        self,
        *,
        namespace: str,
        user_id: UUID,
        org_id: UUID | str,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]:
        dialect = await self._dialect_name()
        if dialect == "postgresql":
            return await self._search_postgres(
                namespace=namespace,
                user_id=user_id,
                org_id=org_id,
                query_embedding=query_embedding,
                limit=limit,
                filters=filters,
            )
        return await self._search_sqlite(
            namespace=namespace,
            user_id=user_id,
            org_id=org_id,
            query_embedding=query_embedding,
            limit=limit,
            filters=filters,
        )

    async def _search_postgres(
        self,
        *,
        namespace: str,
        user_id: UUID,
        org_id: UUID | str,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any] | None,
    ) -> list[SearchHit]:
        params: dict[str, Any] = {
            "namespace": namespace,
            "user_id": str(user_id),
            "org_id": str(org_id),
            "query_embedding": _vector_literal(query_embedding),
            "limit": limit,
        }
        metadata_filter = ""
        if filters:
            metadata_filter = "AND metadata @> CAST(:filters AS jsonb)"
            params["filters"] = json.dumps(filters)

        async with self._engine.connect() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT
                        memory_id,
                        metadata,
                        1.0 - (embedding <=> CAST(:query_embedding AS vector)) AS score
                    FROM kemory_memory_vectors
                    WHERE namespace = :namespace
                      AND user_id = CAST(:user_id AS uuid)
                      AND org_id = :org_id
                      {metadata_filter}
                    ORDER BY embedding <=> CAST(:query_embedding AS vector)
                    LIMIT :limit
                """),
                params,
            )
            rows = result.mappings().all()

        return [
            SearchHit(
                memory_id=UUID(str(row["memory_id"])),
                score=float(row["score"] or 0.0),
                metadata=dict(row["metadata"] or {}),
            )
            for row in rows
        ]

    async def _search_sqlite(
        self,
        *,
        namespace: str,
        user_id: UUID,
        org_id: UUID | str,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any] | None,
    ) -> list[SearchHit]:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                text("""
                    SELECT memory_id, embedding, metadata
                    FROM kemory_memory_vectors
                    WHERE namespace = :namespace
                      AND user_id = :user_id
                      AND org_id = :org_id
                """),
                {
                    "namespace": namespace,
                    "user_id": str(user_id),
                    "org_id": str(org_id),
                },
            )
            rows = result.mappings().all()

        hits: list[SearchHit] = []
        for row in rows:
            metadata = json.loads(row["metadata"] or "{}")
            if filters and any(metadata.get(key) != value for key, value in filters.items()):
                continue
            embedding = json.loads(row["embedding"] or "[]")
            hits.append(
                SearchHit(
                    memory_id=UUID(str(row["memory_id"])),
                    score=_cosine_similarity(query_embedding, embedding),
                    metadata=metadata,
                )
            )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:limit]

    async def delete(
        self,
        *,
        memory_id: UUID,
        user_id: UUID,
        org_id: UUID | str,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("""
                    DELETE FROM kemory_memory_vectors
                    WHERE memory_id = :memory_id
                      AND user_id = :user_id
                      AND org_id = :org_id
                """),
                {
                    "memory_id": str(memory_id),
                    "user_id": str(user_id),
                    "org_id": str(org_id),
                },
            )

    async def healthcheck(self) -> bool:
        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False
