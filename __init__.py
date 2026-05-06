"""
kemory
============
S9N Memory Vault — dual-mode (local/platform) persistent memory layer for AI agents.

This package provides a clean, mode-agnostic API for storing and retrieving
episodic memories. It is designed to be used as a git submodule within the
SeKondBrain / Kora platform, or as a standalone library.

Quick start (local mode, zero infrastructure)
---------------------------------------------
>>> from kemory import MemoryService, create_backend
>>> backend = create_backend()          # auto-detects MEMORY_VAULT_MODE
>>> await backend.initialise()
>>> svc = MemoryService(backend)
>>> ep_id = await svc.remember("The sky is blue", source_agent="my-agent",
...                             session_id="sess-1", org_id="org-1")
>>> results = await svc.recall("sky", org_id="org-1")

Public API
----------
- ``StorageBackend``  — abstract interface for all backends
- ``MemoryService``   — high-level service facade
- ``EpisodeCreate``   — input model for creating episodes
- ``EpisodeRecord``   — full episode record model
- ``create_backend``  — factory function (reads MEMORY_VAULT_MODE env var)

Story: KMV-S2.1 — Move Code to New Repository
"""

from kemory.models.episode import EpisodeCreate, EpisodeRecord
from kemory.service.memory_service import MemoryService
from kemory.storage.base import StorageBackend

__version__ = "0.1.0"
__author__ = "SeKondBrain Engineering"

__all__ = [
    "StorageBackend",
    "MemoryService",
    "EpisodeCreate",
    "EpisodeRecord",
    "create_backend",
    "__version__",
]


def create_backend(mode: str | None = None) -> "StorageBackend":
    """
    Factory function that creates the appropriate storage backend.

    Reads ``MEMORY_VAULT_MODE`` from the environment if ``mode`` is not
    provided.  Defaults to ``"platform"`` with a warning if unset.

    Parameters
    ----------
    mode:
        ``"local"`` or ``"platform"``.  Overrides the environment variable.

    Returns
    -------
    StorageBackend
        An uninitialised backend instance.  Call ``await backend.initialise()``
        before use.

    Raises
    ------
    ValueError
        If the mode is not ``"local"`` or ``"platform"``.

    Notes
    -----
    This function is a convenience wrapper.  For production use, prefer
    constructing backends explicitly via ``BackendFactory`` from
    ``kemory.config.factory``.
    """
    # Defer import to avoid circular imports and keep startup fast
    from kemory.config.factory import BackendFactory

    return BackendFactory.create(mode=mode)
