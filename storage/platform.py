"""
kemory/storage/platform.py
==================================
Platform-mode storage backend for the S9N Memory Vault.

Uses FalkorDB (graph layer), Weaviate (vector similarity search), and
PostgreSQL (episode metadata).  All three services are expected to be
running as part of the shared SeKondBrain stack.

Story: KMV-S1.2  — Refactor Production Backends
Story: KMV-V2-E02 — Lightweight Graph Layer (FalkorDB)
Story: KMV-V2-E03 — Memory Deduplication + Conflict Detection
Story: KMV-V2-E04 — Principled Forgetting (TTL decay + prune)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from kemory.models.episode import EpisodeCreate, EpisodeRecord
from kemory.storage.base import StorageBackend, escape_like

logger = logging.getLogger(__name__)

_WEAVIATE_COLLECTION = "S9nmvEpisode"


class PlatformStorageBackend(StorageBackend):
    """
    Production storage backend using FalkorDB, Weaviate, and PostgreSQL.

    Parameters
    ----------
    postgres_uri:
        PostgreSQL async DSN, e.g.
        ``postgresql+asyncpg://user:pass@localhost/memvault``.
    falkordb_url:
        FalkorDB Redis URL, e.g. ``redis://localhost:6379``.
    falkordb_graph:
        FalkorDB graph name.  Defaults to ``"s9nmv_memory"``.
    weaviate_url:
        Weaviate HTTP URL, e.g. ``http://localhost:8080``.
    encoder_fn:
        Optional ``(text: str) -> list[float]`` callable for producing
        384-dim embeddings.  When *None* the default
        ``kemory.embeddings.encoder.encode`` function is used if
        available; otherwise vector operations degrade to text search.
    """

    MODE = "platform"

    def __init__(
        self,
        postgres_uri: str,
        falkordb_url: str = "redis://localhost:6379",
        falkordb_graph: str = "s9nmv_memory",
        weaviate_url: str = "http://localhost:8080",
        encoder_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        self._postgres_uri = postgres_uri
        self._falkordb_url = falkordb_url
        self._falkordb_graph = falkordb_graph
        self._weaviate_url = weaviate_url
        self._encoder_fn = encoder_fn

        # Set during initialise()
        self._pg_engine: Any = None
        self._falkordb_conn: Any = None  # falkordb.Graph instance
        self._weaviate_client: Any = None
        self._initialised = False
        self._closed = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialise(self) -> None:
        """Connect to PostgreSQL, FalkorDB, and Weaviate; create schemas."""
        if self._initialised:
            return

        # ── PostgreSQL ────────────────────────────────────────────────
        try:
            from sqlalchemy.ext.asyncio import create_async_engine

            self._pg_engine = create_async_engine(self._postgres_uri, echo=False)
            await self._ensure_schema()
            logger.info("PlatformStorageBackend: PostgreSQL engine initialised.")
        except ImportError:  # pragma: no cover
            raise RuntimeError(
                "sqlalchemy and asyncpg are not installed. Install them with: pip install sqlalchemy asyncpg"
            )  # pragma: no cover

        # ── FalkorDB ──────────────────────────────────────────────────
        try:
            import falkordb as _falkordb

            def _connect_falkordb() -> Any:
                # falkordb client ignores the `url` kwarg for host/port resolution;
                # parse the URL manually and pass host/port explicitly.
                parsed = urlparse(self._falkordb_url)
                host = parsed.hostname or "localhost"
                port = parsed.port or 6379
                password = parsed.password or None
                db = _falkordb.FalkorDB(host=host, port=port, password=password)
                return db.select_graph(self._falkordb_graph)

            self._falkordb_conn = await asyncio.to_thread(_connect_falkordb)
            logger.info("PlatformStorageBackend: FalkorDB graph connected.")
        except ImportError:  # pragma: no cover
            raise RuntimeError(
                "falkordb package is not installed. Install it with: pip install falkordb"
            )  # pragma: no cover

        # ── Weaviate ──────────────────────────────────────────────────
        try:
            import weaviate as _weaviate

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

            self._weaviate_client = await asyncio.to_thread(_connect_weaviate)
            await asyncio.to_thread(self._ensure_weaviate_collection)
            logger.info("PlatformStorageBackend: Weaviate client connected.")
        except ImportError:  # pragma: no cover
            raise RuntimeError(
                "weaviate-client package is not installed. Install it with: pip install weaviate-client"
            )  # pragma: no cover

        self._initialised = True

    async def _ensure_schema(self) -> None:
        """Create the episodes table (with v2 columns) if it does not exist."""
        from sqlalchemy import text

        async with self._pg_engine.begin() as conn:
            await conn.execute(
                text("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id              TEXT PRIMARY KEY,
                    content         TEXT NOT NULL,
                    source_agent    TEXT,
                    session_id      TEXT,
                    org_id          TEXT,
                    created_at      TEXT NOT NULL,
                    valid_at        TEXT NOT NULL,
                    invalid_at      TEXT,
                    extra_json      TEXT,
                    decay_score     REAL DEFAULT 1.0,
                    last_accessed_at TEXT,
                    round_id        TEXT,
                    temporal_anchor TEXT
                )
            """)
            )
            # Idempotent ALTER for pre-existing tables (PostgreSQL 9.6+)
            for col, defn in [
                ("decay_score", "REAL DEFAULT 1.0"),
                ("last_accessed_at", "TEXT"),
                ("round_id", "TEXT"),
                ("temporal_anchor", "TEXT"),
            ]:
                try:
                    await conn.execute(text(f"ALTER TABLE episodes ADD COLUMN IF NOT EXISTS {col} {defn}"))
                except Exception:
                    pass  # column already exists in some PostgreSQL versions

    def _ensure_weaviate_collection(self) -> None:
        """Create the S9nmvEpisode Weaviate collection if it does not exist."""
        try:
            from weaviate.classes.config import Configure, DataType, Property

            existing = list(self._weaviate_client.collections.list_all().keys())
            if _WEAVIATE_COLLECTION not in existing:
                self._weaviate_client.collections.create(
                    name=_WEAVIATE_COLLECTION,
                    vectorizer_config=Configure.Vectorizer.none(),
                    properties=[
                        Property(name="episode_id", data_type=DataType.TEXT),
                        Property(name="org_id", data_type=DataType.TEXT),
                        Property(name="content", data_type=DataType.TEXT),
                    ],
                )
                logger.info("Weaviate collection %s created.", _WEAVIATE_COLLECTION)
        except Exception as exc:
            logger.warning("Could not ensure Weaviate collection: %s", exc)

    async def close(self) -> None:
        """Release PostgreSQL engine and Weaviate client."""
        if self._closed:
            return
        if self._pg_engine is not None:
            await self._pg_engine.dispose()
        if self._weaviate_client is not None:
            try:
                await asyncio.to_thread(self._weaviate_client.close)
            except Exception:
                pass
        self._closed = True
        logger.info("PlatformStorageBackend: closed.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assert_initialised(self) -> None:
        if not self._initialised:
            raise RuntimeError(
                "PlatformStorageBackend has not been initialised. Call await backend.initialise() before use."
            )

    def _get_encoder(self) -> Callable[[str], list[float]] | None:
        if self._encoder_fn is not None:
            return self._encoder_fn
        try:
            from kemory.embeddings.encoder import encode

            return encode
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Episode CRUD (PostgreSQL)
    # ------------------------------------------------------------------

    async def add_episode(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> str:
        """Write to PostgreSQL (source of truth) then Weaviate (best-effort)."""
        self._assert_initialised()

        create = EpisodeCreate(content=content, **metadata)
        record = EpisodeRecord.from_create(create)

        from sqlalchemy import text

        async with self._pg_engine.begin() as conn:
            await conn.execute(
                text("""
                    INSERT INTO episodes
                        (id, content, source_agent, session_id, org_id,
                         created_at, valid_at, invalid_at, extra_json,
                         decay_score, last_accessed_at, round_id, temporal_anchor)
                    VALUES
                        (:id, :content, :source_agent, :session_id, :org_id,
                         :created_at, :valid_at, :invalid_at, :extra_json,
                         1.0, :created_at, :round_id, :temporal_anchor)
                """),
                {
                    "id": record.id,
                    "content": record.content,
                    "source_agent": record.source_agent,
                    "session_id": record.session_id,
                    "org_id": record.org_id,
                    "created_at": record.created_at,
                    "valid_at": record.valid_at,
                    "invalid_at": record.invalid_at,
                    "extra_json": json.dumps(record.extra),
                    "round_id": metadata.get("round_id"),
                    "temporal_anchor": metadata.get("temporal_anchor"),
                },
            )

        # Weaviate write — best-effort; failure does NOT roll back PostgreSQL
        encoder = self._get_encoder()
        if encoder is not None and self._weaviate_client is not None:
            try:
                vector = encoder(content)
                episode_id = record.id
                org_id = record.org_id or ""

                def _insert() -> None:
                    col = self._weaviate_client.collections.get(_WEAVIATE_COLLECTION)
                    col.data.insert(
                        properties={
                            "episode_id": episode_id,
                            "org_id": org_id,
                            "content": content,
                        },
                        vector=vector,
                        uuid=episode_id,
                    )

                await asyncio.to_thread(_insert)
            except Exception as exc:
                logger.warning("Weaviate insert failed for episode %s: %s", record.id, exc)

        logger.debug("PlatformStorageBackend: added episode %s", record.id)
        return record.id

    async def get_episode_by_id(self, episode_id: str) -> dict[str, Any] | None:
        self._assert_initialised()
        from sqlalchemy import text

        async with self._pg_engine.connect() as conn:
            result = await conn.execute(
                text("SELECT * FROM episodes WHERE id = :id"),
                {"id": episode_id},
            )
            row = result.mappings().first()
        if row is None:
            return None
        return dict(row)

    async def invalidate_episode(self, episode_id: str, invalid_at: str) -> bool:
        self._assert_initialised()
        from sqlalchemy import text

        async with self._pg_engine.begin() as conn:
            result = await conn.execute(
                text("UPDATE episodes SET invalid_at = :invalid_at WHERE id = :id AND invalid_at IS NULL"),
                {"id": episode_id, "invalid_at": invalid_at},
            )
        return result.rowcount > 0

    async def search_episodes(
        self,
        query: str,
        limit: int = 10,
        org_id: str | None = None,
        temporal_range: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """ILIKE full-text search with optional org and temporal filters."""
        self._assert_initialised()
        from sqlalchemy import text

        escaped = escape_like(query)
        params: dict[str, Any] = {"query": f"%{escaped}%", "limit": limit}
        filters = ["content ILIKE :query ESCAPE '\\'", "invalid_at IS NULL"]

        if org_id:
            filters.append("org_id = :org_id")
            params["org_id"] = org_id
        if temporal_range:
            start, end = temporal_range
            filters.append("valid_at >= :tr_start AND valid_at <= :tr_end")
            params["tr_start"] = start
            params["tr_end"] = end

        where = "WHERE " + " AND ".join(filters)
        async with self._pg_engine.connect() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT * FROM episodes
                    {where}
                    ORDER BY created_at DESC
                    LIMIT :limit
                """),
                params,
            )
            rows = result.mappings().all()
        return [dict(r) for r in rows]

    async def list_episodes(
        self,
        org_id: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_invalid: bool = False,
    ) -> list[dict[str, Any]]:
        self._assert_initialised()
        from sqlalchemy import text

        filters = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if not include_invalid:
            filters.append("invalid_at IS NULL")
        if org_id:
            filters.append("org_id = :org_id")
            params["org_id"] = org_id
        if session_id:
            filters.append("session_id = :session_id")
            params["session_id"] = session_id

        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        async with self._pg_engine.connect() as conn:
            result = await conn.execute(
                text(f"""
                    SELECT * FROM episodes
                    {where}
                    ORDER BY created_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                params,
            )
            rows = result.mappings().all()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Vector Similarity Search (Weaviate)
    # ------------------------------------------------------------------

    async def find_similar(
        self,
        content: str,
        org_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Semantic similarity search via Weaviate near-vector query.

        Degrades to ILIKE text search if the encoder or Weaviate client is
        unavailable, or if the Weaviate query fails.
        """
        self._assert_initialised()
        encoder = self._get_encoder()

        if encoder is None or self._weaviate_client is None:
            return await self.search_episodes(content, limit=limit, org_id=org_id)

        try:
            from weaviate.classes.query import Filter as WvFilter
            from weaviate.classes.query import MetadataQuery

            vector = encoder(content)
            wv_filter = WvFilter.by_property("org_id").equal(org_id) if org_id else None
            meta_query = MetadataQuery(distance=True)

            def _search() -> list[Any]:
                col = self._weaviate_client.collections.get(_WEAVIATE_COLLECTION)
                result = col.query.near_vector(
                    near_vector=vector,
                    limit=limit,
                    return_metadata=meta_query,
                    filters=wv_filter,
                )
                return result.objects

            objects = await asyncio.to_thread(_search)
        except Exception as exc:
            logger.warning("Weaviate search failed: %s — falling back to text search", exc)
            return await self.search_episodes(content, limit=limit, org_id=org_id)

        if not objects:
            return []

        ids = [obj.properties.get("episode_id", str(obj.uuid)) for obj in objects]
        distances = {
            obj.properties.get("episode_id", str(obj.uuid)): obj.metadata.distance for obj in objects
        }

        # Fetch full metadata from PostgreSQL
        from sqlalchemy import text

        placeholders = ", ".join(f":id_{i}" for i in range(len(ids)))
        pg_params: dict[str, Any] = {f"id_{i}": eid for i, eid in enumerate(ids)}
        async with self._pg_engine.connect() as conn:
            pg_result = await conn.execute(
                text(f"SELECT * FROM episodes WHERE id IN ({placeholders})"),
                pg_params,
            )
            rows = pg_result.mappings().all()

        rows_by_id = {r["id"]: dict(r) for r in rows}
        out = []
        for eid in ids:
            row = rows_by_id.get(eid)
            if row:
                row["similarity_score"] = 1.0 - (distances.get(eid) or 0.0)
                out.append(row)
        return out

    # ------------------------------------------------------------------
    # Conflict Resolution (PostgreSQL + FalkorDB edge)
    # ------------------------------------------------------------------

    async def resolve_conflict(
        self,
        source_id: str,
        target_id: str,
        resolution: str = "supersedes",
    ) -> bool:
        """
        Soft-delete *source_id* and record a ``supersedes`` edge to *target_id*.

        Returns ``True`` if the source episode was found and invalidated.
        """
        self._assert_initialised()
        now = datetime.now(UTC).isoformat()
        invalidated = await self.invalidate_episode(source_id, now)
        if invalidated:
            await self.add_edge(source_id, target_id, "supersedes", weight=1.0)
        return invalidated

    # ------------------------------------------------------------------
    # Principled Forgetting (PostgreSQL)
    # ------------------------------------------------------------------

    async def forget_decayed(
        self,
        org_id: str | None = None,
        floor: float = 0.35,
    ) -> int:
        """
        Recompute decay scores then soft-delete episodes that fall at or
        below *floor*.

        Decay formula: ``max(floor, exp(-0.1 * days_since_last_access))``.
        """
        self._assert_initialised()
        from sqlalchemy import text

        params: dict[str, Any] = {"floor": floor}
        org_filter = ""
        if org_id:
            org_filter = "AND org_id = :org_id"
            params["org_id"] = org_id

        async with self._pg_engine.begin() as conn:
            # Recompute decay_score in-place
            await conn.execute(
                text(f"""
                UPDATE episodes
                SET decay_score = GREATEST(
                    :floor,
                    EXP(-0.1 * EXTRACT(EPOCH FROM (
                        NOW() - COALESCE(
                            last_accessed_at::TIMESTAMPTZ,
                            created_at::TIMESTAMPTZ
                        )
                    )) / 86400.0)
                )
                WHERE invalid_at IS NULL
                {org_filter}
            """),
                params,
            )

            # Soft-delete episodes at or below the floor
            result = await conn.execute(
                text(f"""
                UPDATE episodes
                SET invalid_at = NOW()::TEXT
                WHERE invalid_at IS NULL
                AND decay_score <= :floor
                {org_filter}
            """),
                params,
            )

        return result.rowcount

    # ------------------------------------------------------------------
    # Graph Layer (FalkorDB via Cypher)
    # ------------------------------------------------------------------

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 1.0,
    ) -> None:
        """Create or update a directed relationship edge in FalkorDB."""
        self._assert_initialised()
        if self._falkordb_conn is None:
            return  # pragma: no cover

        cypher = """
            MERGE (a:Episode {id: $src})
            MERGE (b:Episode {id: $tgt})
            MERGE (a)-[r:REL {type: $rel_type}]->(b)
            SET r.weight = $weight
        """
        params = {
            "src": source_id,
            "tgt": target_id,
            "rel_type": relation_type,
            "weight": weight,
        }
        await asyncio.to_thread(self._falkordb_conn.query, cypher, params)

    async def get_related(
        self,
        episode_id: str,
        relation_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Retrieve episodes connected to *episode_id* via FalkorDB edges.

        Returns episode dicts (from PostgreSQL) enriched with
        ``relation_type`` and ``weight`` fields.
        """
        self._assert_initialised()
        if self._falkordb_conn is None:
            return []  # pragma: no cover

        if relation_type:
            cypher = """
                MATCH (a:Episode {id: $eid})-[r:REL {type: $rel_type}]->(b:Episode)
                RETURN b.id AS target_id, r.type AS relation_type, r.weight AS weight
                ORDER BY r.weight DESC
                LIMIT $limit
            """
            params: dict[str, Any] = {
                "eid": episode_id,
                "rel_type": relation_type,
                "limit": limit,
            }
        else:
            cypher = """
                MATCH (a:Episode {id: $eid})-[r:REL]->(b:Episode)
                RETURN b.id AS target_id, r.type AS relation_type, r.weight AS weight
                ORDER BY r.weight DESC
                LIMIT $limit
            """
            params = {"eid": episode_id, "limit": limit}

        graph_result = await asyncio.to_thread(self._falkordb_conn.query, cypher, params)
        rows = graph_result.result_set if graph_result else []
        target_ids = [row[0] for row in rows if row[0]]

        if not target_ids:
            return []

        # Hydrate from PostgreSQL
        from sqlalchemy import text

        placeholders = ", ".join(f":id_{i}" for i in range(len(target_ids)))
        pg_params: dict[str, Any] = {f"id_{i}": eid for i, eid in enumerate(target_ids)}
        async with self._pg_engine.connect() as conn:
            pg_result = await conn.execute(
                text(f"SELECT * FROM episodes WHERE id IN ({placeholders})"),
                pg_params,
            )
            ep_rows = pg_result.mappings().all()

        ep_by_id = {r["id"]: dict(r) for r in ep_rows}
        out = []
        for row, target_id_val in zip(rows, target_ids, strict=False):
            ep = ep_by_id.get(target_id_val, {})
            ep["relation_type"] = row[1]
            ep["weight"] = row[2]
            out.append(ep)
        return out

    # ------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------

    async def health_check(self) -> dict[str, Any]:
        """Return health status for PostgreSQL, FalkorDB, and Weaviate."""
        pg_ok = False
        falkordb_ok = False
        weaviate_ok = False

        if self._pg_engine is not None:
            try:
                from sqlalchemy import text

                async with self._pg_engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
                pg_ok = True
            except Exception:
                pass

        if self._falkordb_conn is not None:
            try:
                await asyncio.to_thread(self._falkordb_conn.query, "RETURN 1")
                falkordb_ok = True
            except Exception:
                pass

        if self._weaviate_client is not None:
            try:
                ok = await asyncio.to_thread(self._weaviate_client.is_ready)
                weaviate_ok = bool(ok)
            except Exception:
                pass

        all_ok = pg_ok and falkordb_ok and weaviate_ok
        return {
            "status": "ok" if all_ok else "degraded",
            "backend": "PlatformStorageBackend",
            "mode": self.MODE,
            "postgres": "ok" if pg_ok else "error",
            "falkordb": "ok" if falkordb_ok else "error",
            "weaviate": "ok" if weaviate_ok else "error",
        }
