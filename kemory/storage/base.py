"""
kemory/storage/base.py
============================
Abstract base class defining the StorageBackend interface for the S9N Memory Vault.

All concrete storage backends (local SQLite/Kuzu, platform Neo4j/Postgres) MUST
implement every method defined here.  The MemoryService depends only on this
interface — never on a concrete implementation — enabling transparent mode switching.

Story: KMV-S1.1 — Define StorageBackend Interface
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)


def escape_like(value: str) -> str:
    """Escape special SQL LIKE/ILIKE wildcard characters.

    Prevents SQL injection via ``%`` and ``_`` characters in user-supplied
    search queries.  The backslash is used as the escape character, so the
    caller must include ``ESCAPE '\\'`` in raw SQL queries or pass
    ``escape='\\\\'`` when using SQLAlchemy's ``.ilike()``/``.like()``.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class StorageBackend(ABC):
    """
    Abstract interface for all Memory Vault storage backends.

    A backend is responsible for two concerns:
    1. **Graph storage** — persisting episodes as nodes and their semantic
       relationships as edges in a graph store.
    2. **Metadata storage** — persisting structured episode metadata (timestamps,
       source agent, session context, org scope, bi-temporal validity) in a
       relational store.

    Both concerns are unified behind this single interface so that the
    ``MemoryService`` never needs to know which concrete backend is active.

    Lifecycle
    ---------
    Backends MUST be initialised via ``await backend.initialise()`` before use
    and cleaned up via ``await backend.close()`` on shutdown.  This allows
    backends to set up connection pools, create schemas, etc.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def initialise(self) -> None:
        """
        Perform any one-time setup required by the backend.

        For local backends this creates the database files and schema.
        For platform backends this validates connectivity and warms up pools.

        Raises
        ------
        RuntimeError
            If the backend cannot be initialised (e.g., missing credentials,
            unreachable server).
        """

    @abstractmethod
    async def close(self) -> None:
        """
        Release all resources held by the backend (connections, file handles).

        Safe to call multiple times; subsequent calls after the first are no-ops.
        """

    # ------------------------------------------------------------------
    # Episode CRUD
    # ------------------------------------------------------------------

    @abstractmethod
    async def add_episode(
        self,
        content: str,
        metadata: dict[str, Any],
    ) -> str:
        """
        Persist a new memory episode.

        The episode is written to both the graph store (as a node with an
        embedding) and the metadata store (as a structured row).

        Parameters
        ----------
        content:
            The raw text content of the episode.
        metadata:
            A dictionary of structured metadata.  Required keys:

            - ``source_agent`` (str): identifier of the creating agent.
            - ``session_id`` (str): session context.
            - ``org_id`` (str): organisation scope.
            - ``valid_at`` (str): ISO-8601 UTC datetime when this fact became true.

            Optional keys:

            - ``invalid_at`` (str | None): ISO-8601 UTC datetime when superseded.
            - ``extra`` (dict): arbitrary additional metadata.

        Returns
        -------
        str
            The UUID (v4) of the newly created episode.

        Raises
        ------
        ValueError
            If required metadata keys are missing.
        RuntimeError
            If the write fails in either the graph or metadata store.
        """

    @abstractmethod
    async def get_episode_by_id(self, episode_id: str) -> dict[str, Any] | None:
        """
        Retrieve a single episode by its UUID.

        Parameters
        ----------
        episode_id:
            The UUID of the episode to retrieve.

        Returns
        -------
        dict[str, Any] | None
            A dictionary containing ``id``, ``content``, and all metadata fields,
            or ``None`` if no episode with that ID exists.
        """

    @abstractmethod
    async def invalidate_episode(
        self,
        episode_id: str,
        invalid_at: str,
    ) -> bool:
        """
        Mark an episode as superseded (soft-delete via bi-temporal model).

        Sets the ``invalid_at`` timestamp on the metadata record.  The episode
        remains in the store and is queryable by its ID but will be excluded
        from ``search_episodes`` results.

        Parameters
        ----------
        episode_id:
            The UUID of the episode to invalidate.
        invalid_at:
            ISO-8601 UTC datetime string indicating when the episode became invalid.

        Returns
        -------
        bool
            ``True`` if the episode was found and updated, ``False`` if not found.
        """

    # ------------------------------------------------------------------
    # Search & Retrieval
    # ------------------------------------------------------------------

    @abstractmethod
    async def search_episodes(
        self,
        query: str,
        limit: int = 10,
        org_id: str | None = None,
        temporal_range: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Perform a semantic search over valid (non-invalidated) episodes.

        Parameters
        ----------
        query:
            Natural language search query.
        limit:
            Maximum number of results to return.  Defaults to 10.
        org_id:
            If provided, restricts results to episodes belonging to this
            organisation.  If ``None``, searches across all organisations
            (admin use only).

        Returns
        -------
        list[dict[str, Any]]
            Ordered list of episode dictionaries (most relevant first), each
            containing ``id``, ``content``, ``score``, and metadata fields.
        """

    @abstractmethod
    async def list_episodes(
        self,
        org_id: str | None = None,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_invalid: bool = False,
    ) -> list[dict[str, Any]]:
        """
        List episodes with optional filtering, ordered by ``created_at`` descending.

        Parameters
        ----------
        org_id:
            Filter by organisation scope.
        session_id:
            Filter by session context.
        limit:
            Maximum number of results.  Defaults to 50.
        offset:
            Pagination offset.  Defaults to 0.
        include_invalid:
            If ``True``, includes invalidated episodes.  Defaults to ``False``.

        Returns
        -------
        list[dict[str, Any]]
            List of episode dictionaries.
        """

    # ------------------------------------------------------------------
    # Deduplication + Conflict Detection
    # ------------------------------------------------------------------

    @abstractmethod
    async def find_similar(
        self,
        content: str,
        org_id: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Find semantically similar episodes to *content*.

        Returns episode dicts enriched with a ``similarity_score`` field.

        Story: KMV-V2-E03
        """

    @abstractmethod
    async def resolve_conflict(
        self,
        source_id: str,
        target_id: str,
        resolution: str = "supersedes",
    ) -> bool:
        """
        Mark *source_id* as resolved/superseded by *target_id*.

        Creates a directed edge and soft-deletes the source episode.

        Story: KMV-V2-E03
        """

    # ------------------------------------------------------------------
    # Principled Forgetting
    # ------------------------------------------------------------------

    @abstractmethod
    async def forget_decayed(
        self,
        org_id: str | None = None,
        floor: float = 0.35,
    ) -> int:
        """
        Compute decay scores and soft-delete episodes that have fallen
        below *floor*.

        Parameters
        ----------
        org_id:
            Restrict to this organisation.  ``None`` processes all orgs.
        floor:
            Score floor.  Episodes at or below this value are invalidated.
            Defaults to 0.35.

        Returns
        -------
        int
            Number of episodes invalidated.

        Story: KMV-V2-E04
        """

    # ------------------------------------------------------------------
    # Graph Layer
    # ------------------------------------------------------------------

    @abstractmethod
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
            Semantic relation type.  Valid values: ``"related"``,
            ``"contradicts"``, ``"elaborates"``, ``"supersedes"``.
        weight:
            Edge weight in [0.0, 1.0].  Defaults to 1.0.

        Story: KMV-V2-E02
        """

    @abstractmethod
    async def get_related(
        self,
        episode_id: str,
        relation_type: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Retrieve episodes connected to *episode_id* via graph edges.

        Parameters
        ----------
        episode_id:
            The UUID of the source episode.
        relation_type:
            If provided, filter to this edge type only.
        limit:
            Maximum number of results.

        Returns
        -------
        list[dict[str, Any]]
            Episode dicts ordered by edge weight descending.

        Story: KMV-V2-E02
        """

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """
        Return a health status dictionary for monitoring.

        Returns
        -------
        dict[str, Any]
            Must contain at minimum:

            - ``status`` (str): ``"ok"`` or ``"degraded"`` or ``"error"``.
            - ``backend`` (str): human-readable backend name.
            - ``mode`` (str): ``"local"`` or ``"platform"``.
        """
