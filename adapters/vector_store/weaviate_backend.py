"""Weaviate-backed VectorStore implementation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

from backend.adapters.vector_store.base import SearchHit, VectorStore

logger = logging.getLogger(__name__)

WEAVIATE_COLLECTION = "S9nmvEpisode"


class WeaviateBackend(VectorStore):
    """Hosted vector backend. Behaviour mirrors the former platform storage code."""

    def __init__(self, *, weaviate_url: str = "http://localhost:8080", client: Any | None = None) -> None:
        self._weaviate_url = weaviate_url
        self._client = client

    @property
    def client(self) -> Any | None:
        return self._client

    def _require_client(self) -> Any:
        if self._client is None:
            raise RuntimeError("Weaviate client is not initialised")
        return self._client

    async def initialise(self) -> None:
        if self._client is None:
            try:
                import weaviate as _weaviate
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "weaviate-client package is not installed. Install it with: pip install weaviate-client"
                ) from exc

            def _connect_weaviate() -> Any:
                parsed = urlparse(self._weaviate_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 8080
                secure = parsed.scheme == "https"
                return _weaviate.connect_to_custom(
                    http_host=host,
                    http_port=port,
                    http_secure=secure,
                    grpc_host=host,
                    grpc_port=50051,
                    grpc_secure=secure,
                    skip_init_checks=True,
                )

            self._client = await asyncio.to_thread(_connect_weaviate)

        await asyncio.to_thread(self.ensure_collection)

    def ensure_collection(self) -> None:
        try:
            from weaviate.classes.config import Configure, DataType, Property

            client = self._require_client()
            existing = list(client.collections.list_all().keys())
            if WEAVIATE_COLLECTION not in existing:
                client.collections.create(
                    name=WEAVIATE_COLLECTION,
                    vectorizer_config=Configure.Vectorizer.none(),
                    properties=[
                        Property(name="episode_id", data_type=DataType.TEXT),
                        Property(name="memory_id", data_type=DataType.TEXT),
                        Property(name="namespace", data_type=DataType.TEXT),
                        Property(name="user_id", data_type=DataType.TEXT),
                        Property(name="org_id", data_type=DataType.TEXT),
                        Property(name="content", data_type=DataType.TEXT),
                    ],
                )
                logger.info("Weaviate collection %s created.", WEAVIATE_COLLECTION)
        except Exception as exc:
            logger.warning("Could not ensure Weaviate collection: %s", exc)

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
        if self._client is None:
            return
        client = self._require_client()

        def _insert() -> None:
            col = client.collections.get(WEAVIATE_COLLECTION)
            col.data.insert(
                properties={
                    "episode_id": str(memory_id),
                    "memory_id": str(memory_id),
                    "namespace": namespace,
                    "user_id": str(user_id),
                    "org_id": str(org_id),
                    "content": str(metadata.get("content", "")),
                },
                vector=embedding,
                uuid=str(memory_id),
            )

        await asyncio.to_thread(_insert)

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
        if self._client is None:
            return []
        client = self._require_client()

        try:
            from weaviate.classes.query import Filter as WvFilter
            from weaviate.classes.query import MetadataQuery

            # Hosted compatibility: the existing collection only stored org_id.
            # Keep that as the default filter so old vectors remain searchable.
            wv_filter = WvFilter.by_property("org_id").equal(str(org_id)) if org_id else None
            if filters and filters.get("strict_scope"):
                scope_filter = WvFilter.by_property("namespace").equal(namespace) & WvFilter.by_property(
                    "user_id"
                ).equal(str(user_id))
                wv_filter = scope_filter if wv_filter is None else wv_filter & scope_filter
            meta_query = MetadataQuery(distance=True)

            def _search() -> list[Any]:
                col = client.collections.get(WEAVIATE_COLLECTION)
                result = col.query.near_vector(
                    near_vector=query_embedding,
                    limit=limit,
                    return_metadata=meta_query,
                    filters=wv_filter,
                )
                return result.objects

            objects = await asyncio.to_thread(_search)
        except Exception as exc:
            logger.warning("Weaviate search failed: %s", exc)
            return []

        hits: list[SearchHit] = []
        for obj in objects:
            props = dict(obj.properties or {})
            raw_id = props.get("memory_id") or props.get("episode_id") or str(obj.uuid)
            try:
                memory_id = UUID(str(raw_id))
            except (TypeError, ValueError):
                memory_id = uuid5(NAMESPACE_URL, str(raw_id))
            distance = getattr(obj.metadata, "distance", None)
            score = 1.0 - float(distance or 0.0)
            hits.append(SearchHit(memory_id=memory_id, score=score, metadata=props))
        return hits

    async def delete(
        self,
        *,
        memory_id: UUID,
        user_id: UUID,
        org_id: UUID | str,
    ) -> None:
        if self._client is None:
            return
        client = self._require_client()

        def _delete() -> None:
            col = client.collections.get(WEAVIATE_COLLECTION)
            col.data.delete_by_id(str(memory_id))

        await asyncio.to_thread(_delete)

    async def healthcheck(self) -> bool:
        if self._client is None:
            return False
        client = self._require_client()
        try:
            return bool(await asyncio.to_thread(client.is_ready))
        except Exception:
            return False

    async def close(self) -> None:
        if self._client is not None:
            client = self._require_client()
            await asyncio.to_thread(client.close)
