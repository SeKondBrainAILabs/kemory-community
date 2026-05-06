"""
kemory/contrib/core_ai_backend/adapter.py
================================================
Adapter that bridges Core_Ai_Backend to the kemory package.

This module is part of the kemory package and is designed to be
imported by Core_Ai_Backend after adding agent_memory_vault as a git
submodule at ``lib/kemory``.

Usage in Core_Ai_Backend
------------------------
In ``src/services/memory/memory_vault_adapter.py`` (thin shim):

.. code-block:: python

    from kemory.contrib.core_ai_backend.adapter import (
        get_memory_vault_mode,
        is_local_mode,
        create_local_memory_service,
        health_check_submodule,
    )

The mode is controlled by the ``MEMORY_VAULT_MODE`` environment variable:

- ``MEMORY_VAULT_MODE=platform`` (default) — uses Neo4j/Graphiti/Postgres
- ``MEMORY_VAULT_MODE=local``    — uses Kuzu + SQLite (zero infrastructure)

Story: KMV-S2.2 — Integrate Submodule into Core_Ai_Backend
"""

from __future__ import annotations

import logging
import os
from typing import Any

from kemory.config.factory import BackendFactory
from kemory.service.memory_service import MemoryService
from kemory.storage.base import StorageBackend

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mode helpers
# ---------------------------------------------------------------------------


def get_memory_vault_mode() -> str:
    """
    Return the current memory vault mode.

    Returns
    -------
    str
        ``"local"`` or ``"platform"``.  Defaults to ``"platform"`` if the
        environment variable is not set.
    """
    return os.environ.get("MEMORY_VAULT_MODE", "platform").lower().strip()


def is_local_mode() -> bool:
    """Return ``True`` if running in local (zero-infra) mode."""
    return get_memory_vault_mode() == "local"


# ---------------------------------------------------------------------------
# Service factory
# ---------------------------------------------------------------------------


async def create_local_memory_service() -> MemoryService:
    """
    Create and initialise a MemoryService backed by the local (Kuzu + SQLite)
    storage backend.

    Returns
    -------
    MemoryService
        A fully initialised MemoryService instance.

    Raises
    ------
    RuntimeError
        If initialisation fails (e.g., missing ``aiosqlite`` or ``kuzu``
        packages).
    """
    backend: StorageBackend = BackendFactory.create()
    await backend.initialise()
    service = MemoryService(backend)
    logger.info(
        "kemory adapter: local MemoryService initialised (db_path=%s)",
        os.environ.get("MEMORY_VAULT_LOCAL_DB_PATH", "./.vault_data"),
    )
    return service


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


async def health_check_submodule() -> dict[str, Any]:
    """
    Run a health check on the kemory backend.

    In platform mode, returns a static ``ok`` response — the real health
    check is delegated to Core_Ai_Backend's GraphitiService.

    In local mode, creates a temporary backend instance, runs its
    ``health_check()`` method, then closes it.

    Returns
    -------
    dict[str, Any]
        Health status dict.  Always includes ``mode`` and ``status`` keys.
    """
    if not is_local_mode():
        return {
            "mode": "platform",
            "status": "ok",
            "note": "Platform mode — health check delegated to GraphitiService.",
        }

    try:
        backend: StorageBackend = BackendFactory.create()
        await backend.initialise()
        result = await backend.health_check()
        await backend.close()
        return result
    except Exception as exc:
        logger.error("kemory adapter: health check failed: %s", exc)
        return {
            "mode": "local",
            "status": "error",
            "error": str(exc),
        }
