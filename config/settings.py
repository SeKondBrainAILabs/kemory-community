"""
kemory/config/settings.py
=================================
Pydantic-Settings configuration classes for the S9N Memory Vault.

All configuration is read from environment variables with the prefix
``MEMORY_VAULT_``.  This ensures clean separation between local and
platform settings.

Story: KMV-S2.1 — Move Code to New Repository
Story: KMV-S4.1 — Implement Mode Configuration
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class LocalSettings(BaseSettings):
    """
    Configuration for local mode (SQLite + sqlite-vec).

    Environment variables
    ---------------------
    ``MEMORY_VAULT_LOCAL_DB_PATH``
        Directory where SQLite database files will be created.
        Defaults to ``./.vault_data``.
    """

    model_config = SettingsConfigDict(
        env_prefix="MEMORY_VAULT_LOCAL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_path: str = "./.vault_data"
    """Path to the local database directory."""


class PlatformSettings(BaseSettings):
    """
    Configuration for platform mode (FalkorDB + Weaviate + PostgreSQL).

    Environment variables
    ---------------------
    ``MEMORY_VAULT_PLATFORM_POSTGRES_URI``
        PostgreSQL async DSN. Defaults to a local development URI.
    ``MEMORY_VAULT_PLATFORM_FALKORDB_URL``
        FalkorDB Redis URL. Defaults to ``redis://localhost:6379``.
    ``MEMORY_VAULT_PLATFORM_FALKORDB_GRAPH``
        FalkorDB graph name. Defaults to ``kemory_memory``. Legacy values
        ``s9nmv_memory`` and ``agent_memory_vault_graph`` are also valid;
        run ``scripts/migrations/rename_falkordb_graph.py`` to migrate
        existing data over before flipping the env var.
    ``MEMORY_VAULT_PLATFORM_WEAVIATE_URL``
        Weaviate HTTP URL. Defaults to ``http://localhost:8080``.
    """

    model_config = SettingsConfigDict(
        env_prefix="MEMORY_VAULT_PLATFORM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    postgres_uri: str = "postgresql+asyncpg://postgres:postgres@localhost/memvault"
    """PostgreSQL async DSN."""

    falkordb_url: str = "redis://localhost:6379"
    """FalkorDB Redis connection URL."""

    falkordb_graph: str = "kemory_memory"
    """FalkorDB graph name."""

    weaviate_url: str = "http://localhost:8080"
    """Weaviate HTTP endpoint."""
