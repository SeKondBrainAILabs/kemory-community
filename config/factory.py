"""
kemory/config/factory.py
================================
BackendFactory — creates the correct StorageBackend based on MEMORY_VAULT_MODE.

Story: KMV-S2.1 — Move Code to New Repository
Story: KMV-S4.1 — Implement Mode Configuration
"""

from __future__ import annotations

import logging
import os

from kemory.storage.base import StorageBackend

logger = logging.getLogger(__name__)

VALID_MODES = ("local", "platform")


class BackendFactory:
    """
    Creates the appropriate StorageBackend instance based on the configured mode.

    The mode is determined by the ``MEMORY_VAULT_MODE`` environment variable,
    or by the ``mode`` parameter passed directly to ``create()``.

    Mode values
    -----------
    - ``"local"``    — uses LocalStorageBackend (SQLite + sqlite-vec, zero infra)
    - ``"platform"`` — uses PlatformStorageBackend (FalkorDB + Weaviate + PostgreSQL)
    """

    @staticmethod
    def create(mode: str | None = None) -> StorageBackend:
        """
        Instantiate and return the correct backend for the given mode.

        Parameters
        ----------
        mode:
            ``"local"`` or ``"platform"``.  If ``None``, reads from the
            ``MEMORY_VAULT_MODE`` environment variable.  Defaults to
            ``"platform"`` with a warning if neither is provided.

        Returns
        -------
        StorageBackend
            An uninitialised backend.  Call ``await backend.initialise()``
            before use.

        Raises
        ------
        ValueError
            If ``mode`` is set to an unrecognised value.
        """
        resolved_mode = BackendFactory._resolve_mode(mode)

        if resolved_mode == "local":
            return BackendFactory._create_local()
        else:
            return BackendFactory._create_platform()

    @staticmethod
    def _resolve_mode(mode: str | None) -> str:
        """Resolve the effective mode string."""
        if mode is not None:
            if mode not in VALID_MODES:
                raise ValueError(f"Invalid MEMORY_VAULT_MODE: '{mode}'. Must be one of: {VALID_MODES}")
            return mode

        env_mode = os.environ.get("MEMORY_VAULT_MODE")
        if env_mode is None:
            logger.warning(
                "MEMORY_VAULT_MODE is not set. Defaulting to 'platform'. "
                "Set MEMORY_VAULT_MODE=local for zero-infrastructure local development."
            )
            return "platform"

        if env_mode not in VALID_MODES:
            raise ValueError(
                f"Invalid MEMORY_VAULT_MODE env var: '{env_mode}'. Must be one of: {VALID_MODES}"
            )
        return env_mode

    @staticmethod
    def _create_local() -> StorageBackend:
        """Create a local-mode backend (SQLite + sqlite-vec)."""
        from kemory.config.settings import LocalSettings
        from kemory.storage.local import LocalStorageBackend

        settings = LocalSettings()
        logger.info(
            "BackendFactory: creating LocalStorageBackend at '%s'",
            settings.db_path,
        )
        return LocalStorageBackend(db_path=settings.db_path)

    @staticmethod
    def _create_platform() -> StorageBackend:
        """Create a platform-mode backend (FalkorDB + Weaviate + PostgreSQL)."""
        from kemory.config.settings import PlatformSettings
        from kemory.storage.platform import PlatformStorageBackend

        settings = PlatformSettings()
        logger.info(
            "BackendFactory: creating PlatformStorageBackend (postgres=%s, falkordb=%s)",
            settings.postgres_uri,
            settings.falkordb_url,
        )
        return PlatformStorageBackend(
            postgres_uri=settings.postgres_uri,
            falkordb_url=settings.falkordb_url,
            falkordb_graph=settings.falkordb_graph,
            weaviate_url=settings.weaviate_url,
        )
