"""
kemory/service/memory_service.py
=======================================
The MemoryService is the LIBRARY-shaped entry point for memory operations.

It depends ONLY on the ``StorageBackend`` interface — never on any concrete
implementation.  The active backend is injected at construction time, making
the service fully testable and mode-agnostic. Used by:
  * ``kemory.consolidation.worker`` (background consolidation)
  * embedded callers (cognition-os internals, future agents that use
    kemory as a library rather than via HTTP)

It is intentionally distinct from ``backend/services/memory_service.py``,
which is the REST/HTTP-shaped layer (Pydantic models, Gatekeeper, audit
emission). The two services serve different consumers; both ultimately
write to the same Postgres tables (or, in local mode, the same SQLite DB).

The dedup-critical content-hash primitive lives in
``kemory/utils/text.py`` so both layers compute identical hashes
for the same content. Phase 2 of the consolidation work — having the
HTTP layer delegate its storage calls through this service's
StorageBackend interface — is tracked as P0 #1 follow-up tickets.

Story: KMV-S1.2 — Refactor Production Backends
Story: KMV-V2-E08 — Time-Aware Query Expansion (temporal detection + routing)
Story: KMV-V2-E09b — Chain-of-Note + JSON Output (structured search response)
Story: KMV-V2-E09 — Stable Context (vault_context v2)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from kemory.context.vault_context import VaultContext
from kemory.observer.extractor import observe
from kemory.reflector.agent import ReflectionResult, reflect
from kemory.search.chain_of_note import format_results
from kemory.search.temporal import extract_time_range, has_temporal_reference
from kemory.storage.base import StorageBackend

logger = logging.getLogger(__name__)


class MemoryService:
    """
    Orchestrates all memory operations for the S9N Memory Vault.

    The service is responsible for:
    - Validating inputs before delegating to the backend.
    - Applying business rules (e.g., ensuring ``valid_at`` is always set).
    - Providing a clean, stable API to callers (REST layer, agents, tests).

    Parameters
    ----------
    backend:
        A fully initialised ``StorageBackend`` instance.
    """

    def __init__(self, backend: StorageBackend) -> None:
        if not isinstance(backend, StorageBackend):
            raise TypeError(f"backend must be an instance of StorageBackend, got {type(backend).__name__}")
        self._backend = backend
        self._vault_context = VaultContext()
        logger.info(
            "MemoryService initialised with backend: %s",
            type(backend).__name__,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def remember(
        self,
        content: str,
        source_agent: str,
        session_id: str,
        org_id: str,
        valid_at: str | None = None,
        extra: dict[str, Any] | None = None,
        *,
        namespace: str = "shared",
        content_type: str = "text",
        round_id: str | None = None,
    ) -> str:
        """
        Store a new memory episode.

        Parameters
        ----------
        content:
            The text to remember.
        source_agent:
            Identifier of the agent creating this memory.
        session_id:
            Session context.
        org_id:
            Organisation scope (maps to user_id in unified model).
        valid_at:
            When this fact became true (ISO-8601 UTC). Defaults to now.
        extra:
            Optional extra metadata.
        namespace:
            Namespace for multi-namespace isolation. Default: 'shared'.
        content_type:
            Content type: text, structured, conversation, fact, preference.
        round_id:
            Round/turn identifier within a session.

        Returns
        -------
        str
            The UUID of the created episode.
        """
        if not content:
            raise ValueError("content must not be empty")

        metadata: dict[str, Any] = {
            "source_agent": source_agent,
            "session_id": session_id,
            "org_id": org_id,
            "valid_at": valid_at or datetime.now(UTC).isoformat(),
            # Unified model fields (MV2-S01.4)
            "namespace": namespace,
            "content_type": content_type,
        }
        if round_id:
            metadata["round_id"] = round_id
        if extra:
            metadata["extra"] = extra

        episode_id = await self._backend.add_episode(content, metadata)
        logger.debug("MemoryService.remember: stored episode %s (ns=%s)", episode_id, namespace)
        return episode_id

    async def recall(
        self,
        query: str,
        org_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Search for relevant memories.

        In v2.0, automatically detects temporal references in *query* (e.g.
        "last week", "in January", "2026-03-15") and filters results to the
        resolved date range.  Falls back to unfiltered search when no
        temporal reference is detected or extraction fails.

        Parameters
        ----------
        query:
            Natural language query.
        org_id:
            Organisation scope for isolation.
        limit:
            Maximum results to return.

        Returns
        -------
        list[dict[str, Any]]
            Ordered list of matching episode dictionaries.

        Story: KMV-V2-E08 — Time-Aware Query Expansion
        """
        if limit < 0:
            raise ValueError("limit must be >= 0")

        temporal_range = None
        if has_temporal_reference(query):
            tr = extract_time_range(query)
            if tr is not None:
                temporal_range = tr.to_iso()
                logger.debug(
                    "Temporal expansion: query=%r → range=%s to %s",
                    query,
                    temporal_range[0],
                    temporal_range[1],
                )

        return await self._backend.search_episodes(
            query,
            limit=limit,
            org_id=org_id,
            temporal_range=temporal_range,
        )

    async def recall_structured(
        self,
        query: str,
        org_id: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """
        Search for relevant memories and return a structured CoN response.

        This is the v2.0 replacement for ``recall()`` in agent-facing contexts.
        It returns a structured JSON-serialisable dict following the Chain-of-Note
        output schema (spec §8.10).

        - **Local Edition**: ``summary`` and ``chain_of_note`` per result are
          ``None``; relevance scores are rank-based approximations.
        - **Cloud Edition** (Groq): full CoN generation with natural language
          summaries (implemented in V2-E05).

        Parameters
        ----------
        query:
            Natural language query.
        org_id:
            Organisation scope for isolation.
        limit:
            Maximum results to return.

        Returns
        -------
        dict[str, Any]
            Structured response with ``query``, ``time_range``, ``result_count``,
            ``summary``, and ``results`` (list of enriched episode dicts).

        Story: KMV-V2-E09b — Chain-of-Note + JSON Output
        """
        if limit < 0:
            raise ValueError("limit must be >= 0")

        temporal_range = None
        if has_temporal_reference(query):
            tr = extract_time_range(query)
            if tr is not None:
                temporal_range = tr.to_iso()
                logger.debug(
                    "Temporal expansion: query=%r → range=%s to %s",
                    query,
                    temporal_range[0],
                    temporal_range[1],
                )

        results = await self._backend.search_episodes(
            query,
            limit=limit,
            org_id=org_id,
            temporal_range=temporal_range,
        )

        return format_results(
            query=query,
            results=results,
            time_range=temporal_range,
        )

    async def observe_and_remember(
        self,
        content: str,
        source_agent: str,
        session_id: str,
        org_id: str,
        valid_at: str | None = None,
        extra: dict[str, Any] | None = None,
        round_id: str | None = None,
        use_groq: bool | None = None,
        *,
        namespace: str = "shared",
    ) -> str:
        """
        Extract structured metadata from *content* via the Observer Agent,
        then persist the enriched episode.

        This is the v2.0 replacement for bare ``remember()`` in agent-facing
        contexts.  It automatically:

        1. Runs the dual-mode Observer (Local regex or Cloud Groq) to extract
           ``facts``, ``temporal_anchor``, ``memory_type``, and ``content_type``.
        2. Stores the enriched episode via ``remember()``.

        Parameters
        ----------
        content:
            Episode text.
        source_agent, session_id, org_id, valid_at, extra:
            Same as :meth:`remember`.
        round_id:
            Optional conversation turn identifier (``{session_id}_turn_{n}``).
        use_groq:
            ``None`` = auto-detect from ``GROQ_API_KEY`` env var.

        Returns
        -------
        str
            UUID of the created episode.

        Story: KMV-V2-E05 — Observer Agent (Dual-Mode)
        """
        if not content:
            raise ValueError("content must not be empty")

        result = await observe(content, use_groq=use_groq)
        enriched_extra = dict(extra or {})
        enriched_extra["memory_type"] = result.memory_type
        enriched_extra["content_type"] = result.content_type
        enriched_extra["observer_source"] = result.source

        metadata: dict[str, Any] = {
            "source_agent": source_agent,
            "session_id": session_id,
            "org_id": org_id,
            "valid_at": valid_at or datetime.now(UTC).isoformat(),
            "extra": enriched_extra,
            "facts": result.facts,
            "namespace": namespace,
            "content_type": result.content_type or "text",
        }
        if result.temporal_anchor:
            metadata["temporal_anchor"] = result.temporal_anchor
        if round_id:
            metadata["round_id"] = round_id

        episode_id = await self._backend.add_episode(content, metadata)
        logger.debug(
            "MemoryService.observe_and_remember: stored episode %s (observer=%s, facts=%d)",
            episode_id,
            result.source,
            len(result.facts),
        )
        return episode_id

    async def reflect_session(
        self,
        org_id: str,
        session_id: str | None = None,
        limit: int = 20,
        persist: bool = True,
        use_groq: bool | None = None,
    ) -> ReflectionResult:
        """
        Generate a reflection over recent memories for a session or org.

        Fetches the most recent *limit* episodic memories, runs the Reflector
        Agent, and optionally persists the reflection as a new semantic episode.

        Parameters
        ----------
        org_id:
            Organisation scope.
        session_id:
            If provided, restrict to this session.
        limit:
            Number of recent episodes to reflect on.
        persist:
            If ``True``, persist the reflection summary as a new semantic
            episode with ``memory_type="semantic"``.
        use_groq:
            ``None`` = auto-detect from ``GROQ_API_KEY`` env var.

        Returns
        -------
        ReflectionResult
            Summary, themes, and source episode IDs.

        Story: KMV-V2-E06 — Reflector Agent
        """
        episodes = await self._backend.list_episodes(
            org_id=org_id,
            session_id=session_id,
            limit=limit,
        )

        result = await reflect(episodes, use_groq=use_groq)

        if persist and result.summary:
            summary_content = f"[Reflection] {result.summary}" + (
                f" Themes: {', '.join(result.themes)}." if result.themes else ""
            )
            await self._backend.add_episode(
                summary_content,
                {
                    "source_agent": "reflector",
                    "session_id": session_id or "reflection",
                    "org_id": org_id,
                    "valid_at": datetime.now(UTC).isoformat(),
                    "extra": {
                        "memory_type": "semantic",
                        "content_type": "reflection",
                        "source_episode_ids": result.source_episode_ids,
                        "reflector_source": result.source,
                    },
                },
            )
            logger.debug(
                "MemoryService.reflect_session: persisted reflection for org=%s",
                org_id,
            )

        return result

    async def vault_context(
        self,
        org_id: str,
        session_id: str | None = None,
        token_budget: int = 2000,
        limit: int = 100,
    ) -> str:
        """
        Return a stable, token-budgeted structured context string for *org_id*.

        Fetches recent valid episodes, partitions them into Reflections /
        Observations / Procedural sections, and returns a formatted string
        ready for injection into an agent's system prompt.

        Uses hash-based caching: the string is only regenerated when the
        underlying episode set changes (by ID).

        Parameters
        ----------
        org_id:
            Organisation scope.
        session_id:
            If provided, restrict context to this session only.
        token_budget:
            Maximum tokens for the context string (default 2000).
        limit:
            Maximum episodes to fetch before partitioning (default 100).

        Returns
        -------
        str
            Structured context string with Key Knowledge, Recent Context,
            and How-To Knowledge sections.

        Story: KMV-V2-E09 — Stable Context
        """
        episodes = await self._backend.list_episodes(
            org_id=org_id,
            session_id=session_id,
            limit=limit,
        )
        self._vault_context._token_budget = token_budget
        return await self._vault_context.get_context(episodes, org_id=org_id)

    async def find_conflicts(
        self,
        content: str,
        org_id: str,
        threshold: float = 0.85,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Find existing episodes that may conflict with *content*.

        Returns episodes whose similarity score meets *threshold*, ordered
        by similarity descending.

        Parameters
        ----------
        content:
            The new content to check against stored episodes.
        org_id:
            Organisation scope for isolation.
        threshold:
            Minimum similarity score (0–1) to include in results.
        limit:
            Maximum results.

        Returns
        -------
        list[dict[str, Any]]
            Similar episodes (each has a ``similarity_score`` field).

        Story: KMV-V2-E03 — Memory Deduplication + Conflict Detection
        """
        candidates = await self._backend.find_similar(content, org_id=org_id, limit=limit)
        return [ep for ep in candidates if ep.get("similarity_score", 0) >= threshold]

    async def resolve_conflict(
        self,
        source_id: str,
        target_id: str,
        resolution: str = "supersedes",
    ) -> bool:
        """
        Resolve a conflict: soft-delete *source_id* and link it to *target_id*.

        Parameters
        ----------
        source_id:
            The episode being superseded or resolved.
        target_id:
            The authoritative / newer episode.
        resolution:
            Edge relation type (default: ``"supersedes"``).

        Returns
        -------
        bool
            ``True`` if source was found and invalidated.

        Story: KMV-V2-E03 — Memory Deduplication + Conflict Detection
        """
        if not source_id or not source_id.strip():
            raise ValueError("source_id must not be empty")
        if not target_id or not target_id.strip():
            raise ValueError("target_id must not be empty")
        return await self._backend.resolve_conflict(source_id, target_id, resolution)

    async def prune_decayed(
        self,
        org_id: str | None = None,
        floor: float = 0.35,
    ) -> int:
        """
        Compute decay scores and soft-delete episodes that have fallen
        below *floor*.

        Uses a 30-day half-life exponential decay model.  Episodes below
        *floor* are soft-deleted (``invalid_at`` set to now).

        Parameters
        ----------
        org_id:
            Restrict to this organisation.  ``None`` processes all orgs.
        floor:
            Score floor.  Must be in (0, 1).

        Returns
        -------
        int
            Number of episodes invalidated.

        Story: KMV-V2-E04 — Principled Forgetting
        """
        if not (0 < floor < 1):
            raise ValueError("floor must be in (0, 1)")
        return await self._backend.forget_decayed(org_id=org_id, floor=floor)

    async def link(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 1.0,
    ) -> None:
        """
        Create a directed semantic edge between two episodes.

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
            Edge strength in [0.0, 1.0].

        Story: KMV-V2-E02 — Lightweight Graph Layer
        """
        await self._backend.add_edge(source_id, target_id, relation_type, weight)

    async def memory_related(
        self,
        episode_id: str,
        relation_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Return episodes that are semantically linked to *episode_id*.

        Traverses the graph edges table; returns only valid (non-invalidated)
        episodes, ordered by edge weight descending.

        Parameters
        ----------
        episode_id:
            UUID of the episode whose neighbours to retrieve.
        relation_type:
            If provided, restrict to this edge type only.
        limit:
            Maximum results.

        Returns
        -------
        list[dict[str, Any]]
            Related episode dicts.

        Story: KMV-V2-E02 — Lightweight Graph Layer
        """
        if not episode_id or not episode_id.strip():
            raise ValueError("episode_id must not be empty")
        return await self._backend.get_related(episode_id, relation_type=relation_type, limit=limit)

    async def get(self, episode_id: str) -> dict[str, Any] | None:
        """
        Retrieve a specific episode by ID.

        Returns ``None`` if not found.
        """
        if not episode_id or not episode_id.strip():
            raise ValueError("episode_id must not be empty")
        return await self._backend.get_episode_by_id(episode_id)

    async def forget(self, episode_id: str, invalid_at: str | None = None) -> bool:
        """
        Invalidate (soft-delete) an episode.

        Parameters
        ----------
        episode_id:
            UUID of the episode to invalidate.
        invalid_at:
            When the episode became invalid. Defaults to now.

        Returns
        -------
        bool
            ``True`` if found and invalidated, ``False`` if not found.
        """
        if not episode_id or not episode_id.strip():
            raise ValueError("episode_id must not be empty")
        ts = invalid_at or datetime.now(UTC).isoformat()
        return await self._backend.invalidate_episode(episode_id, ts)

    async def list_memories(
        self,
        org_id: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_invalid: bool = False,
    ) -> list[dict[str, Any]]:
        """
        List episodes with optional filtering.

        Parameters
        ----------
        org_id:
            Filter by organisation.
        session_id:
            Filter by session.
        limit:
            Maximum results.
        offset:
            Pagination offset.
        include_invalid:
            Include invalidated episodes.

        Returns
        -------
        list[dict[str, Any]]
        """
        if limit < 0:
            raise ValueError("limit must be >= 0")
        if offset < 0:
            raise ValueError("offset must be >= 0")
        return await self._backend.list_episodes(
            org_id=org_id,
            session_id=session_id,
            limit=limit,
            offset=offset,
            include_invalid=include_invalid,
        )

    async def health(self) -> dict[str, Any]:
        """Return health status from the active backend."""
        return await self._backend.health_check()
