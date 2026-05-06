"""
kemory/storage/local.py
================================
LocalStorageBackend — zero-infrastructure local mode backend.

This backend uses:
- SQLite for relational episode metadata and graph edges
- SQLite FTS5 for BM25 keyword search (v2.0)
- sqlite-vec for cosine-similarity vector search (v2.0)
- bge-small-en-v1.5 via sentence-transformers for embeddings (v2.0)

Story: KMV-S3.1 — Implement SQLite Metadata Backend
Story: KMV-V2-S01.1 — Install sqlite-vec, create vec_episodes virtual table
Story: KMV-V2-S01.2 — Integrate bge-small-en-v1.5 ONNX embedding service
Story: KMV-V2-S01.3 — Generate embedding on every add_episode call
Story: KMV-V2-S01.4 — Implement cosine similarity search via vec_episodes
Story: KMV-V2-S01.5 — Implement RRF merge of FTS5 + vector results
Story: KMV-V2-S01.6 — FTS5 virtual table for BM25 keyword search
Story: KMV-V2-S01.7 — Graceful degradation when sqlite-vec not installed
Story: KMV-V2-E07 — Round-Level Granularity + Key Expansion
Story: KMV-V2-E02 — Lightweight Graph Layer (SQLite edges table)
Story: KMV-V2-E04 — Principled Forgetting (TTL decay + prune)
Story: KMV-V2-E03 — Memory Deduplication + Conflict Detection
"""

from __future__ import annotations

import logging
import struct
from collections.abc import Callable
from datetime import UTC
from typing import Any

from kemory.storage.base import StorageBackend, escape_like

logger = logging.getLogger(__name__)

# Embedding dimension for bge-small-en-v1.5
_EMBEDDING_DIM = 384

# RRF constant — standard value from the original paper
_RRF_K = 60


_VALID_RELATION_TYPES = frozenset({"related", "contradicts", "elaborates", "supersedes"})


class LocalStorageBackend(StorageBackend):
    """
    Zero-infrastructure local storage backend.

    Uses SQLite for episode metadata and graph edges, FTS5 for BM25 keyword
    search, and sqlite-vec for cosine-similarity vector search.
    Requires no external services.

    Parameters
    ----------
    db_path:
        Directory where SQLite database files will be created.
        Defaults to ``./.vault_data``.
    encoder_fn:
        Optional callable ``(text: str) -> list[float]`` used to generate
        384-dim embeddings.  When *None* the default ``kemory.embeddings.encoder.encode``
        function is used.  Inject a mock in tests to avoid loading the model.
    """

    def __init__(
        self,
        db_path: str = "./.vault_data",
        encoder_fn: Callable[[str], list[float]] | None = None,
    ) -> None:
        self._db_path = db_path
        self._encoder_fn = encoder_fn
        self._initialised = False
        self._closed = False
        # Set during initialise()
        self._sqlite_conn: Any = None
        # v2.0 feature flags — enabled when the respective extension/table is available
        self._fts_enabled: bool = False
        self._vec_enabled: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialise(self) -> None:
        """
        Initialise the local backend.

        Creates the database directory, initialises the SQLite database,
        and (v2.0) enables FTS5 and sqlite-vec if available.
        Idempotent — safe to call multiple times.

        Raises
        ------
        RuntimeError
            If ``aiosqlite`` is not installed.
        """
        if self._initialised:
            logger.debug("LocalStorageBackend: already initialised, skipping.")
            return

        import os

        os.makedirs(self._db_path, exist_ok=True)

        await self._init_sqlite()
        await self._init_edges()
        await self._init_fts()
        await self._init_vec()
        await self._backfill_embeddings()

        self._initialised = True
        logger.info(
            "LocalStorageBackend: initialised at '%s' (fts=%s, vec=%s)",
            self._db_path,
            self._fts_enabled,
            self._vec_enabled,
        )

    async def _init_sqlite(self) -> None:
        """Initialise the SQLite database and create the episodes table."""
        try:
            import aiosqlite  # type: ignore[import]
        except ImportError:  # pragma: no cover
            raise RuntimeError(
                "aiosqlite is not installed. Install it with: pip install aiosqlite"
            )  # pragma: no cover

        import os

        db_file = os.path.join(self._db_path, "episodes.db")
        self._sqlite_conn = await aiosqlite.connect(db_file)
        self._sqlite_conn.row_factory = aiosqlite.Row

        await self._sqlite_conn.execute("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                source_agent TEXT NOT NULL,
                session_id TEXT NOT NULL,
                org_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                valid_at TEXT NOT NULL,
                invalid_at TEXT,
                extra_json TEXT DEFAULT '{}'
            )
        """)
        await self._sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_org_id ON episodes (org_id)")
        await self._sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_session_id ON episodes (session_id)")
        # v2.0 E07: round_id + facts columns (idempotent ALTER for existing DBs)
        await self._add_column_if_missing("episodes", "round_id", "TEXT")
        await self._add_column_if_missing("episodes", "facts", "TEXT DEFAULT '[]'")
        await self._sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_round_id ON episodes (round_id)")
        # v2.0 E08: temporal_anchor — ISO date extracted from content for time-aware search
        await self._add_column_if_missing("episodes", "temporal_anchor", "TEXT")
        await self._sqlite_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_temporal_anchor ON episodes (temporal_anchor)"
        )
        # v2.0 E04: decay_score and last_accessed_at for Principled Forgetting
        await self._add_column_if_missing("episodes", "decay_score", "REAL DEFAULT 1.0")
        await self._add_column_if_missing("episodes", "last_accessed_at", "TEXT")
        # MV2-E07: access_count for utility salience
        await self._add_column_if_missing("episodes", "access_count", "INTEGER DEFAULT 0")
        # MV2-E03: tier column for 3-tier lifecycle (active → demoted → deleted)
        await self._add_column_if_missing("episodes", "tier", "TEXT DEFAULT 'active'")
        # MV3-E01: visibility column for 4-tier visibility model
        await self._add_column_if_missing("episodes", "visibility", "TEXT DEFAULT 'user-private'")
        await self._add_column_if_missing("episodes", "team_id", "TEXT")
        # MV2-E02: memory_events provenance table
        await self._sqlite_conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_events (
                event_id TEXT PRIMARY KEY,
                memory_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor_type TEXT NOT NULL DEFAULT 'system',
                actor_id TEXT,
                reason TEXT,
                before_state TEXT DEFAULT '{}',
                after_state TEXT DEFAULT '{}',
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            )
        """)
        await self._sqlite_conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_memory ON memory_events (memory_id)"
        )
        await self._sqlite_conn.commit()
        logger.debug("LocalStorageBackend: SQLite initialised at '%s'", db_file)

    async def _add_column_if_missing(self, table: str, column: str, col_def: str) -> None:
        """Add *column* to *table* if it does not already exist (idempotent)."""
        async with self._sqlite_conn.execute(f"PRAGMA table_info({table})") as cursor:
            existing = {row[1] for row in await cursor.fetchall()}
        if column not in existing:
            await self._sqlite_conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
            logger.debug("Added column '%s' to '%s'", column, table)

    async def _init_fts(self) -> None:
        """
        Create the FTS5 virtual table for BM25 keyword search.

        Uses Porter stemmer tokeniser for recall-friendly matching.
        Falls back gracefully if FTS5 is not compiled into SQLite.

        Story: KMV-V2-S01.6
        """
        try:
            await self._sqlite_conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts
                USING fts5(
                    episode_id UNINDEXED,
                    content,
                    tokenize='porter unicode61'
                )
            """)
            await self._sqlite_conn.commit()
            self._fts_enabled = True
            logger.debug("LocalStorageBackend: FTS5 enabled")
        except Exception as exc:
            logger.warning("FTS5 not available — falling back to LIKE search: %s", exc)

    async def _init_vec(self) -> None:
        """
        Load the sqlite-vec extension and create the vec_episodes virtual table.

        Silently disabled when sqlite-vec is not installed or SQLite was
        compiled without extension-loading support.

        Story: KMV-V2-S01.1, KMV-V2-S01.7
        """
        try:
            import sqlite_vec  # type: ignore[import]

            # sqlite-vec must be loaded on the underlying sync connection
            raw_conn = self._sqlite_conn._conn  # aiosqlite internals
            raw_conn.enable_load_extension(True)
            sqlite_vec.load(raw_conn)
            raw_conn.enable_load_extension(False)

            await self._sqlite_conn.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_episodes
                USING vec0(
                    episode_id TEXT PRIMARY KEY,
                    embedding float[{_EMBEDDING_DIM}]
                )
            """)
            await self._sqlite_conn.commit()
            self._vec_enabled = True
            logger.info(
                "LocalStorageBackend: sqlite-vec enabled (%d-dim embeddings)",
                _EMBEDDING_DIM,
            )
        except ImportError:
            logger.warning(
                "sqlite-vec not installed — vector search disabled. Install with: pip install sqlite-vec"
            )
        except Exception as exc:
            logger.warning("sqlite-vec could not be initialised — vector search disabled: %s", exc)

    async def _backfill_embeddings(self) -> None:
        """
        Backfill embeddings for episodes that exist in the DB but not in vec_episodes.

        Called during initialise() to handle the upgrade path from pre-v2.0 databases.

        Story: KMV-V2-S01.6
        """
        if not self._vec_enabled:
            return

        try:
            # Find episodes without embeddings
            async with self._sqlite_conn.execute(
                """
                SELECT e.id, e.content
                FROM episodes e
                LEFT JOIN vec_episodes v ON e.id = v.episode_id
                WHERE v.episode_id IS NULL AND e.invalid_at IS NULL
                """
            ) as cursor:
                missing = await cursor.fetchall()

            if not missing:
                return

            backfilled = 0
            for row in missing:
                try:
                    embedding = self._get_embedding(row[1])  # row["content"]
                    vec_bytes = struct.pack(f"{_EMBEDDING_DIM}f", *embedding)
                    await self._sqlite_conn.execute(
                        "INSERT INTO vec_episodes(episode_id, embedding) VALUES (?, ?)",
                        (row[0], vec_bytes),  # row["id"]
                    )
                    backfilled += 1
                except Exception as exc:
                    logger.debug("backfill: skip episode %s: %s", row[0], exc)

            if backfilled:
                await self._sqlite_conn.commit()
                logger.info(
                    "LocalStorageBackend: backfilled %d/%d embeddings",
                    backfilled,
                    len(missing),
                )
        except Exception as exc:
            logger.debug("backfill_embeddings: skipped (%s)", exc)

    async def _init_edges(self) -> None:
        """
        Create the SQLite edges table for lightweight graph storage.

        Story: KMV-V2-E02 — Lightweight Graph Layer
        """
        await self._sqlite_conn.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                weight REAL NOT NULL DEFAULT 1.0,
                created_at TEXT NOT NULL,
                PRIMARY KEY (source_id, target_id, relation_type)
            )
        """)
        await self._sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges (source_id)")
        await self._sqlite_conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges (target_id)")
        await self._sqlite_conn.commit()
        logger.debug("LocalStorageBackend: edges table initialised")

    async def close(self) -> None:
        """Close all database connections."""
        if self._closed:
            return
        if self._sqlite_conn is not None:
            await self._sqlite_conn.close()
            self._sqlite_conn = None
        self._closed = True
        logger.info("LocalStorageBackend: closed.")

    # ------------------------------------------------------------------
    # Embedding helpers
    # ------------------------------------------------------------------

    def _get_embedding(self, text: str) -> list[float]:
        """
        Generate a 384-dim embedding for *text*.

        Uses the injected ``encoder_fn`` if provided, otherwise falls back to
        the default ``kemory.embeddings.encoder.encode``.

        Story: KMV-V2-S01.3
        """
        if self._encoder_fn is not None:
            return self._encoder_fn(text)
        from kemory.embeddings.encoder import encode

        return encode(text)

    @staticmethod
    def _compute_index_key(content: str, facts: list[str]) -> str:
        """
        Compute the FTS5 index key: ``content + " " + facts_joined``.

        Key expansion (K = V + fact) increases FTS5 retrieval recall by
        +9.4% on LongMemEval by expanding the searchable surface with
        structured facts extracted from the content.

        Story: KMV-V2-E07
        """
        if facts:
            return content + " " + " ".join(facts)
        return content

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    async def add_episode(self, content: str, metadata: dict[str, Any]) -> str:
        """
        Persist a new episode to SQLite and register it in the Kuzu graph.

        In v2.0, also inserts into the FTS5 index and the vec_episodes
        vector table if those features are enabled.

        Parameters
        ----------
        content:
            The textual content of the episode.
        metadata:
            Must contain: ``source_agent``, ``session_id``, ``org_id``,
            ``valid_at``.

            Optional v2.0 fields:

            - ``extra`` (dict): arbitrary extra data stored as JSON.
            - ``round_id`` (str): conversation turn identifier in the format
              ``{session_id}_turn_{n}``.  Null when not an Observer memory.
            - ``facts`` (list[str]): standalone extracted facts used for key
              expansion in the FTS5 index (K = V + fact, +9.4% recall).
            - ``temporal_anchor`` (str | None): ISO 8601 date (YYYY-MM-DD)
              extracted from content, used for time-aware search filtering.

        Returns
        -------
        str
            UUID of the created episode.

        Story: KMV-V2-E07 — Round-Level Granularity + Key Expansion
        """
        import json
        import uuid
        from datetime import datetime

        required = {"source_agent", "session_id", "org_id", "valid_at"}
        missing = required - metadata.keys()
        if missing:
            raise ValueError(f"Missing required metadata keys: {missing}")

        ep_id = str(uuid.uuid4())
        created_at = datetime.now(UTC).isoformat()
        extra_json = json.dumps(metadata.get("extra", {}))

        # v2.0 E07: round_id and facts for key expansion
        round_id: str | None = metadata.get("round_id")
        facts: list[str] = metadata.get("facts", [])
        if not isinstance(facts, list):
            facts = []
        facts_json = json.dumps(facts)

        # v2.0 E08: temporal_anchor for time-aware search
        temporal_anchor: str | None = metadata.get("temporal_anchor")

        await self._sqlite_conn.execute(
            """
            INSERT INTO episodes
                (id, content, source_agent, session_id, org_id,
                 created_at, valid_at, invalid_at, extra_json,
                 round_id, facts, temporal_anchor)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (
                ep_id,
                content,
                metadata["source_agent"],
                metadata["session_id"],
                metadata["org_id"],
                created_at,
                metadata["valid_at"],
                extra_json,
                round_id,
                facts_json,
                temporal_anchor,
            ),
        )
        await self._sqlite_conn.commit()

        # v2.0 E07: FTS5 index — store index_key (content + facts) for key expansion
        if self._fts_enabled:
            try:
                index_key = self._compute_index_key(content, facts)
                await self._sqlite_conn.execute(
                    "INSERT INTO episodes_fts(episode_id, content) VALUES (?, ?)",
                    (ep_id, index_key),
                )
                await self._sqlite_conn.commit()
            except Exception as exc:
                logger.warning("FTS5 insert failed for episode %s: %s", ep_id, exc)

        # v2.0: Vector index — generate embedding and insert into vec_episodes
        if self._vec_enabled:
            try:
                embedding = self._get_embedding(content)
                vec_bytes = struct.pack(f"{_EMBEDDING_DIM}f", *embedding)
                await self._sqlite_conn.execute(
                    "INSERT INTO vec_episodes(episode_id, embedding) VALUES (?, ?)",
                    (ep_id, vec_bytes),
                )
                await self._sqlite_conn.commit()
            except Exception as exc:
                logger.warning("vec_episodes insert failed for episode %s: %s", ep_id, exc)

        logger.debug("LocalStorageBackend: added episode %s", ep_id)
        return ep_id

    async def get_episode_by_id(
        self,
        episode_id: str,
        *,
        track_access: bool = False,
    ) -> dict[str, Any] | None:
        """Retrieve a single episode by its ID.

        Parameters
        ----------
        track_access:
            If True, increments access_count and may promote demoted episodes.
            Default False for internal/test calls.
        """
        async with self._sqlite_conn.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None

            episode = dict(row)

            if track_access:
                # MV2-S07.1: Increment access_count on every read
                from datetime import datetime

                now_iso = datetime.now(UTC).isoformat()
                await self._sqlite_conn.execute(
                    "UPDATE episodes SET access_count = COALESCE(access_count, 0) + 1, "
                    "last_accessed_at = ? WHERE id = ?",
                    (now_iso, episode_id),
                )

                # MV2-S03.3: Promote demoted episodes on explicit access
                if episode.get("tier") == "demoted":
                    await self._sqlite_conn.execute(
                        "UPDATE episodes SET tier = 'active', invalid_at = NULL, "
                        "decay_score = 1.0 WHERE id = ?",
                        (episode_id,),
                    )
                    await self._sqlite_conn.execute(
                        "UPDATE edges SET weight = 1.0 "
                        "WHERE (source_id = ? OR target_id = ?) AND weight < 1.0",
                        (episode_id, episode_id),
                    )
                    episode["tier"] = "active"
                    episode["invalid_at"] = None
                    episode["decay_score"] = 1.0
                    logger.info("LocalStorageBackend: promoted episode %s demoted → active", episode_id)

                await self._sqlite_conn.commit()

            return episode

    async def invalidate_episode(self, episode_id: str, invalid_at: str) -> bool:
        """
        Mark an episode as invalid (soft delete).

        Returns ``True`` if the episode was found and updated, ``False``
        if the episode does not exist.
        """
        cursor = await self._sqlite_conn.execute(
            "UPDATE episodes SET invalid_at = ? WHERE id = ? AND invalid_at IS NULL",
            (invalid_at, episode_id),
        )
        await self._sqlite_conn.commit()
        return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Graph Layer — EPIC-V2-E02
    # ------------------------------------------------------------------

    async def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 1.0,
    ) -> None:
        """
        Create or replace a directed edge between two episodes.

        Parameters
        ----------
        source_id:
            UUID of the source episode.
        target_id:
            UUID of the target episode.
        relation_type:
            One of ``"related"``, ``"contradicts"``, ``"elaborates"``,
            ``"supersedes"``.
        weight:
            Edge weight in [0.0, 1.0].  Higher = stronger relationship.
            Defaults to 1.0.

        Raises
        ------
        ValueError
            If ``relation_type`` is not one of the four valid values.

        Story: KMV-V2-E02
        """
        if relation_type not in _VALID_RELATION_TYPES:
            raise ValueError(
                f"Invalid relation_type '{relation_type}'. Must be one of: {sorted(_VALID_RELATION_TYPES)}"
            )
        from datetime import datetime

        created_at = datetime.now(UTC).isoformat()
        await self._sqlite_conn.execute(
            """
            INSERT INTO edges (source_id, target_id, relation_type, weight, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(source_id, target_id, relation_type) DO UPDATE SET
                weight = excluded.weight,
                created_at = excluded.created_at
            """,
            (source_id, target_id, relation_type, weight, created_at),
        )
        await self._sqlite_conn.commit()
        logger.debug(
            "LocalStorageBackend: edge %s -[%s]-> %s (w=%.2f)",
            source_id,
            relation_type,
            target_id,
            weight,
        )

    async def get_related(
        self,
        episode_id: str,
        relation_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Retrieve episodes connected to *episode_id* via graph edges.

        Only returns valid (non-invalidated) episodes.

        Parameters
        ----------
        episode_id:
            The UUID of the source episode.
        relation_type:
            If provided, filter to edges of this type only.
        limit:
            Maximum number of results.

        Returns
        -------
        list[dict[str, Any]]
            Episode dicts ordered by edge weight descending.

        Story: KMV-V2-E02
        """
        params: list[Any] = [episode_id]
        type_clause = ""
        if relation_type is not None:
            if relation_type not in _VALID_RELATION_TYPES:
                raise ValueError(
                    f"Invalid relation_type '{relation_type}'. "
                    f"Must be one of: {sorted(_VALID_RELATION_TYPES)}"
                )
            type_clause = " AND ed.relation_type = ?"
            params.append(relation_type)
        params.append(limit)

        sql = f"""
            SELECT e.*, ed.relation_type AS edge_relation_type,
                   ed.weight AS edge_weight
            FROM episodes e
            JOIN edges ed ON ed.target_id = e.id
            WHERE ed.source_id = ?
              AND e.invalid_at IS NULL
              {type_clause}
            ORDER BY ed.weight DESC
            LIMIT ?
        """
        async with self._sqlite_conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Deduplication + Conflict Detection — EPIC-V2-E03
    # ------------------------------------------------------------------

    async def find_similar(
        self,
        content: str,
        org_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Find episodes that are semantically similar to *content*.

        Uses vector similarity when available, falls back to FTS5/LIKE.
        Returns a list of episode dicts enriched with a ``similarity_score``
        float in [0, 1] (higher = more similar).

        Parameters
        ----------
        content:
            The text to compare against stored episodes.
        org_id:
            If provided, restrict search to this organisation.
        limit:
            Maximum number of results.

        Returns
        -------
        list[dict[str, Any]]
            Similar episodes, ordered by similarity descending.

        Story: KMV-V2-E03
        """
        candidate_limit = limit * 3

        if self._vec_enabled:
            vec_rows = await self._vec_search(content, candidate_limit)
            if vec_rows:
                ids = [r[0] for r in vec_rows]
                dist_map = {r[0]: r[1] for r in vec_rows}
                placeholders = ",".join("?" * len(ids))
                params: list[Any] = list(ids)
                sql = f"SELECT * FROM episodes WHERE id IN ({placeholders}) AND invalid_at IS NULL"
                if org_id is not None:
                    sql += " AND org_id = ?"
                    params.append(org_id)
                async with self._sqlite_conn.execute(sql, params) as cursor:
                    rows = await cursor.fetchall()
                eps = {row["id"]: dict(row) for row in rows}
                result = []
                for ep_id, dist in sorted(vec_rows, key=lambda x: x[1]):
                    if ep_id in eps:
                        ep = eps[ep_id]
                        ep["similarity_score"] = round(1.0 / (1.0 + dist), 4)
                        result.append(ep)
                return result[:limit]

        if self._fts_enabled:
            fts_rows = await self._fts_search(content, candidate_limit)
            if fts_rows:
                ids = [r[0] for r in fts_rows]
                rank_map = {r[0]: i + 1 for i, r in enumerate(fts_rows)}
                placeholders = ",".join("?" * len(ids))
                params2: list[Any] = list(ids)
                sql2 = f"SELECT * FROM episodes WHERE id IN ({placeholders}) AND invalid_at IS NULL"
                if org_id is not None:
                    sql2 += " AND org_id = ?"
                    params2.append(org_id)
                async with self._sqlite_conn.execute(sql2, params2) as cursor:
                    rows2 = await cursor.fetchall()
                eps2 = {row["id"]: dict(row) for row in rows2}
                result2 = []
                for ep_id, _ in fts_rows:
                    if ep_id in eps2:
                        ep = eps2[ep_id]
                        # Approximate similarity from rank (rank-1 = best)
                        ep["similarity_score"] = round(1.0 / (1.0 + rank_map[ep_id]), 4)
                        result2.append(ep)
                return result2[:limit]

        # LIKE fallback
        like_results = await self._like_search(content, limit, org_id)
        for i, ep in enumerate(like_results):
            ep["similarity_score"] = round(1.0 / (1.0 + i), 4)
        return like_results

    async def resolve_conflict(
        self,
        source_id: str,
        target_id: str,
        resolution: str = "supersedes",
    ) -> bool:
        """
        Resolve a conflict between two episodes.

        Creates a directed edge from *source_id* to *target_id* with the
        given *resolution* relation type, then soft-deletes *source_id*
        (the episode being superseded or resolved).

        Parameters
        ----------
        source_id:
            The episode being marked as resolved/superseded.
        target_id:
            The newer or authoritative episode.
        resolution:
            Relation type for the edge.  One of the valid relation types
            (default: ``"supersedes"``).

        Returns
        -------
        bool
            ``True`` if the source episode was found and invalidated.

        Story: KMV-V2-E03
        """
        if resolution not in _VALID_RELATION_TYPES:
            raise ValueError(
                f"Invalid resolution '{resolution}'. Must be one of: {sorted(_VALID_RELATION_TYPES)}"
            )
        await self.add_edge(target_id, source_id, resolution)
        from datetime import datetime

        ts = datetime.now(UTC).isoformat()
        return await self.invalidate_episode(source_id, ts)

    # ------------------------------------------------------------------
    # Principled Forgetting — EPIC-V2-E04
    # ------------------------------------------------------------------

    async def forget_decayed(
        self,
        org_id: str | None = None,
        floor: float = 0.35,
        ttl_days: int | None = None,
    ) -> int:
        """
        Compute current decay scores and soft-delete episodes that have fallen
        below *floor* or exceeded *ttl_days*.

        Uses a 30-day half-life exponential decay model:
        ``score = max(floor, 0.5 ^ (days_idle / 30))``

        where *days_idle* is measured from ``last_accessed_at`` (if set) or
        ``created_at``.

        Parameters
        ----------
        org_id:
            If provided, only prune episodes belonging to this organisation.
        floor:
            Minimum score to retain.  Episodes below this threshold are
            soft-deleted.  Defaults to 0.35.
        ttl_days:
            If provided, soft-delete episodes older than this many days
            regardless of their decay score.

        Returns
        -------
        int
            Number of episodes invalidated.

        Story: KMV-V2-E04 — Principled Forgetting
        """
        from datetime import datetime

        now = datetime.now(UTC)

        # Fetch all valid episodes with their timestamps
        cond = "WHERE invalid_at IS NULL"
        params: list[Any] = []
        if org_id is not None:
            cond += " AND org_id = ?"
            params.append(org_id)

        async with self._sqlite_conn.execute(
            f"SELECT id, created_at, last_accessed_at, access_count FROM episodes {cond}",
            params,
        ) as cursor:
            rows = await cursor.fetchall()

        invalidated = 0
        invalid_at = now.isoformat()

        for row in rows:
            ep_id, created_at_str, last_accessed_str = row[0], row[1], row[2]
            access_count = row[3] if len(row) > 3 else 0
            ref_str = last_accessed_str or created_at_str
            try:
                ref_dt = datetime.fromisoformat(ref_str.replace("Z", "+00:00"))
                days_idle = (now - ref_dt).total_seconds() / 86400.0
            except Exception:
                days_idle = 0.0

            # MV2-S07.3: Blended decay with utility salience
            days_since_access = None
            if last_accessed_str:
                try:
                    la_dt = datetime.fromisoformat(last_accessed_str.replace("Z", "+00:00"))
                    days_since_access = (now - la_dt).total_seconds() / 86400.0
                except Exception:
                    pass

            score = _decay_score(
                days_idle,
                floor=floor,
                access_count=access_count or 0,
                days_since_last_access=days_since_access,
            )

            # Update decay_score in DB regardless
            await self._sqlite_conn.execute(
                "UPDATE episodes SET decay_score = ? WHERE id = ?",
                (score, ep_id),
            )

            # TTL check: invalidate if older than ttl_days
            expired_by_ttl = ttl_days is not None and days_idle > ttl_days

            if score <= floor or expired_by_ttl:
                # MV2-S03.2: Demote instead of hard-invalidate
                await self._sqlite_conn.execute(
                    "UPDATE episodes SET invalid_at = ?, tier = 'demoted' "
                    "WHERE id = ? AND invalid_at IS NULL",
                    (invalid_at, ep_id),
                )
                # Reduce graph edge weights for demoted memories
                await self._sqlite_conn.execute(
                    "UPDATE edges SET weight = 0.1 WHERE (source_id = ? OR target_id = ?) AND weight > 0.1",
                    (ep_id, ep_id),
                )
                invalidated += 1

        await self._sqlite_conn.commit()
        logger.info(
            "LocalStorageBackend.forget_decayed: invalidated %d episodes (org=%s, floor=%.2f)",
            invalidated,
            org_id,
            floor,
        )
        return invalidated

    # ------------------------------------------------------------------
    # Search — v2.0 Hybrid FTS5 + Vector with RRF
    # ------------------------------------------------------------------

    async def search_episodes(
        self,
        query: str,
        limit: int = 10,
        org_id: str | None = None,
        temporal_range: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Hybrid search over episode content.

        When v2.0 features are enabled, merges BM25 (FTS5) and cosine
        similarity (sqlite-vec) results via Reciprocal Rank Fusion (RRF).
        Falls back to SQLite LIKE when neither is available.

        Parameters
        ----------
        query:
            Search string.
        limit:
            Maximum number of results to return.
        org_id:
            If provided, restricts results to the given organisation.
        temporal_range:
            Optional ``(start_iso, end_iso)`` tuple of ISO 8601 date strings.
            When set, only episodes whose ``temporal_anchor`` or ``created_at``
            (date portion) falls within the range are returned.
            Used by time-aware query expansion (V2-F09 / KMV-V2-E08).

        Returns
        -------
        list[dict[str, Any]]
            Matching episodes, excluding invalidated ones, ranked by
            relevance.

        Story: KMV-V2-S01.4, KMV-V2-S01.5, KMV-V2-E08
        """
        candidate_limit = limit * 3  # over-fetch to allow post-filter

        if not self._fts_enabled and not self._vec_enabled:
            # Legacy LIKE fallback
            return await self._like_search(query, limit, org_id, temporal_range)

        fts_rows = await self._fts_search(query, candidate_limit)
        vec_rows = await self._vec_search(query, candidate_limit)

        # FTS5 may fail or return nothing on special characters (%, _, etc.).
        # Fall back to LIKE search to maintain backward-compatible behaviour.
        if not fts_rows and not vec_rows:
            return await self._like_search(query, limit, org_id, temporal_range)

        rrf_scores = _rrf(fts_rows, vec_rows)

        if not rrf_scores:
            return []

        # Fetch full episode records for all candidates, applying filters
        candidate_ids = list(rrf_scores.keys())
        placeholders = ",".join("?" * len(candidate_ids))
        params: list[Any] = list(candidate_ids)
        sql = f"SELECT * FROM episodes WHERE id IN ({placeholders}) AND invalid_at IS NULL"
        if org_id is not None:
            sql += " AND org_id = ?"
            params.append(org_id)
        if temporal_range is not None:
            sql += _temporal_sql_clause()
            params.extend([temporal_range[0], temporal_range[1], temporal_range[0], temporal_range[1]])

        async with self._sqlite_conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        rows_by_id = {row["id"]: dict(row) for row in rows}

        # Re-sort by RRF score descending
        sorted_ids = sorted(rrf_scores, key=lambda x: rrf_scores[x], reverse=True)
        result = [rows_by_id[eid] for eid in sorted_ids if eid in rows_by_id]
        return result[:limit]

    async def _like_search(
        self,
        query: str,
        limit: int,
        org_id: str | None,
        temporal_range: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Legacy LIKE-based search — used when FTS5 and vec are unavailable."""
        escaped = escape_like(query)
        conditions = ["content LIKE ? ESCAPE '\\'", "invalid_at IS NULL"]
        params: list[Any] = [f"%{escaped}%"]

        if org_id is not None:
            conditions.append("org_id = ?")
            params.append(org_id)
        if temporal_range is not None:
            conditions.append(_temporal_sql_clause().lstrip(" AND"))
            params.extend([temporal_range[0], temporal_range[1], temporal_range[0], temporal_range[1]])

        where = " AND ".join(conditions)
        sql = f"SELECT * FROM episodes WHERE {where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        async with self._sqlite_conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def _fts_search(
        self,
        query: str,
        limit: int,
    ) -> list[tuple[str, float]]:
        """
        BM25 keyword search via FTS5.

        Returns a list of ``(episode_id, rank)`` tuples where *rank* is the
        raw FTS5 rank (negative; lower = better).

        Story: KMV-V2-S01.6
        """
        if not self._fts_enabled:
            return []
        try:
            # Build a safe FTS5 expression. Each term is double-quoted to neutralise
            # FTS5 operators and reserved chars (-, +, *, NOT, AND, OR, ?, :).
            # Multi-word queries are joined with OR so natural-language questions
            # match on any salient term — a phrase search would have ~zero recall.
            terms = [
                t.strip(".,!?;:'\"()[]{}<>") for t in query.split() if len(t.strip(".,!?;:'\"()[]{}<>")) >= 2
            ]
            if not terms:
                return []
            quoted = [f'"{t}"' for t in terms if all(c not in t for c in '"')]
            if not quoted:
                return []
            fts_query = " OR ".join(quoted)
            async with self._sqlite_conn.execute(
                "SELECT episode_id, rank FROM episodes_fts WHERE content MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, limit),
            ) as cursor:
                rows = await cursor.fetchall()
                return [(row[0], float(row[1])) for row in rows]
        except Exception as exc:
            logger.warning("FTS5 search failed: %s", exc)
            return []

    async def _vec_search(
        self,
        query: str,
        limit: int,
    ) -> list[tuple[str, float]]:
        """
        Cosine similarity search via sqlite-vec.

        Returns a list of ``(episode_id, distance)`` tuples where *distance*
        is the L2 distance (lower = more similar for normalised vectors).

        Story: KMV-V2-S01.4
        """
        if not self._vec_enabled:
            return []
        try:
            embedding = self._get_embedding(query)
            vec_bytes = struct.pack(f"{_EMBEDDING_DIM}f", *embedding)
            async with self._sqlite_conn.execute(
                "SELECT episode_id, distance FROM vec_episodes"
                " WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
                [vec_bytes, limit],
            ) as cursor:
                rows = await cursor.fetchall()
                return [(row[0], float(row[1])) for row in rows]
        except Exception as exc:
            logger.warning("Vec search failed: %s", exc)
            return []

    async def list_episodes(
        self,
        org_id: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_invalid: bool = False,
    ) -> list[dict[str, Any]]:
        """
        List episodes with optional filtering and pagination.

        Parameters
        ----------
        org_id:
            Filter by organisation ID.
        session_id:
            Filter by session ID.
        limit:
            Maximum number of results.
        offset:
            Number of results to skip (for pagination).
        include_invalid:
            If ``True``, includes invalidated episodes.

        Returns
        -------
        list[dict[str, Any]]
        """
        conditions = []
        params: list[Any] = []

        if not include_invalid:
            conditions.append("invalid_at IS NULL")

        if org_id is not None:
            conditions.append("org_id = ?")
            params.append(org_id)

        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)

        where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([limit, offset])

        sql = f"""
            SELECT * FROM episodes
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """

        async with self._sqlite_conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def health_check(self) -> dict[str, Any]:
        """
        Return the health status of the local backend.

        Returns
        -------
        dict[str, Any]
            Contains ``status``, ``mode``, ``backend``, ``sqlite``,
            ``fts``, ``vec``, and ``kuzu`` keys.
        """
        result: dict[str, Any] = {
            "mode": "local",
            "backend": "LocalStorageBackend",
            "db_path": self._db_path,
        }

        # SQLite
        try:
            async with self._sqlite_conn.execute("SELECT 1") as cursor:
                await cursor.fetchone()
            result["sqlite"] = "ok"
        except Exception as e:
            result["sqlite"] = "error"
            logger.error("LocalStorageBackend: SQLite health check failed: %s", e)

        # FTS5
        result["fts"] = "ok" if self._fts_enabled else "disabled"

        # sqlite-vec
        result["vec"] = "ok" if self._vec_enabled else "disabled"

        # Graph edges table
        try:
            async with self._sqlite_conn.execute("SELECT COUNT(*) FROM edges") as cursor:
                row = await cursor.fetchone()
                result["graph"] = f"ok ({row[0]} edges)"
        except Exception:
            result["graph"] = "error"

        result["status"] = "ok" if result.get("sqlite") == "ok" else "degraded"
        return result


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _utility_salience(access_count: int, days_since_last_access: float) -> float:
    """
    Compute utility salience score from access frequency and recency.

    Formula: min(1.0, log2(access_count + 1) * recency_factor)
    where recency_factor = exp(-0.05 * days_since_last_access)

    Story: MV2-S07.2
    """
    import math

    if access_count <= 0:
        return 0.0
    recency_factor = math.exp(-0.05 * max(0.0, days_since_last_access))
    return min(1.0, math.log2(access_count + 1) * recency_factor)


def _decay_score(
    days_idle: float,
    floor: float = 0.35,
    access_count: int = 0,
    days_since_last_access: float | None = None,
) -> float:
    """
    Compute the blended decay score for an episode.

    Blends time-based decay with utility salience:
    ``decay_score = max(floor, 0.6 * time_decay + 0.4 * utility_salience)``

    When access_count is 0 (no reads), falls back to pure time decay.

    Parameters
    ----------
    days_idle:
        Days since created (or last accessed for time decay).
    floor:
        Minimum score floor.  Defaults to 0.35.
    access_count:
        Number of times this memory was accessed. Default: 0.
    days_since_last_access:
        Days since last access. If None, uses days_idle.

    Returns
    -------
    float
        Decay score in [floor, 1.0].

    Story: KMV-V2-E04, MV2-S07.3
    """
    import math

    _HALF_LIFE = 30.0
    time_decay = math.pow(0.5, days_idle / _HALF_LIFE)

    if access_count > 0:
        dsa = days_since_last_access if days_since_last_access is not None else days_idle
        salience = _utility_salience(access_count, dsa)
        blended = 0.6 * time_decay + 0.4 * salience
    else:
        blended = time_decay

    return max(floor, blended)


def _temporal_sql_clause() -> str:
    """
    Return the SQL AND-clause for temporal range filtering.

    Matches episodes where either the explicit ``temporal_anchor`` date OR
    the ``created_at`` timestamp falls within the given [start, end] range.
    Uses ISO 8601 string comparison which is safe for SQLite date strings.

    Expects 4 bind parameters: (start, end, start, end).

    Story: KMV-V2-E08
    """
    return (
        " AND ("
        "  (temporal_anchor IS NOT NULL AND temporal_anchor BETWEEN ? AND ?)"
        "  OR (temporal_anchor IS NULL AND substr(created_at, 1, 10) BETWEEN ? AND ?)"
        ")"
    )


def _rrf(
    fts_results: list[tuple[str, float]],
    vec_results: list[tuple[str, float]],
    k: int = _RRF_K,
) -> dict[str, float]:
    """
    Reciprocal Rank Fusion of FTS5 and vector search results.

    Each result list contributes ``1 / (k + rank)`` to a shared score map
    keyed by episode_id.  Results are position-based (rank starts at 1) so
    the magnitude of the raw score (BM25 rank or L2 distance) is ignored —
    only ordering within each list matters.

    Parameters
    ----------
    fts_results:
        Ordered ``(episode_id, rank)`` pairs from FTS5 (lower rank = better).
    vec_results:
        Ordered ``(episode_id, distance)`` pairs from vec search (lower = better).
    k:
        RRF constant.  Typical value: 60.

    Returns
    -------
    dict[str, float]
        Mapping of episode_id → combined RRF score (higher = more relevant).

    Story: KMV-V2-S01.5
    """
    scores: dict[str, float] = {}
    for rank, (ep_id, _) in enumerate(fts_results, start=1):
        scores[ep_id] = scores.get(ep_id, 0.0) + 1.0 / (k + rank)
    for rank, (ep_id, _) in enumerate(vec_results, start=1):
        scores[ep_id] = scores.get(ep_id, 0.0) + 1.0 / (k + rank)
    return scores
