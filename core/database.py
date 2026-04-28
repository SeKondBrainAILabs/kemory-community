"""
S9N Memory Vault — Database Engine & Session Factory

Supports dual-mode:
- platform (default): PostgreSQL via asyncpg with connection pooling
- local: SQLite via aiosqlite with file-based storage

Story: MV2-S06.1 — SQLite Engine Swap
"""

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from backend.config.settings import settings

_engine = None
_async_session_factory = None


def _is_local_mode() -> bool:
    """Check if we're in local/SQLite mode."""
    return os.environ.get("MEMORY_VAULT_MODE", "").lower() == "local"


def _get_engine():
    """Lazily create the async engine on first access."""
    global _engine
    if _engine is None:
        if _is_local_mode():
            # SQLite via aiosqlite — no connection pooling
            db_path = os.environ.get("MEMORY_VAULT_LOCAL_DB_PATH", "./.vault_data")
            os.makedirs(db_path, exist_ok=True)
            # Prefer new name; fall back to legacy name if it already exists
            new_db = os.path.join(db_path, "s9nmv_vault.db")
            old_db = os.path.join(db_path, "kora_vault.db")
            db_file = old_db if (not os.path.exists(new_db) and os.path.exists(old_db)) else new_db
            sqlite_url = f"sqlite+aiosqlite:///{db_file}"
            _engine = create_async_engine(
                sqlite_url,
                echo=settings.debug,
                # SQLite doesn't support pool_size/max_overflow
            )
        else:
            # PostgreSQL via asyncpg — full connection pooling
            _engine = create_async_engine(
                settings.database_url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout,
                pool_pre_ping=True,
                echo=settings.debug,
            )
    return _engine


def _get_session_factory():
    """Lazily create the session factory on first access.

    On first creation, registers the multi-tenant SQLAlchemy global query
    filter (WS-3). The listener is attached to the AsyncSession's underlying
    sync_session_class so SELECTs against tenant-scoped models are
    automatically filtered by the active TenantScope. See
    ``backend.core.tenancy`` for how the filter resolves the active org_id.
    """
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
        # Lazy import to avoid the import cycle:
        #   tenancy → auth_service → settings (fine)
        #   database → tenancy → auth_service → ... (fine, but only safe
        # AFTER the session factory is in place).
        from sqlalchemy.orm import Session as _SyncSession

        from backend.core.tenancy import register_tenant_filter

        # AsyncSession proxies do_orm_execute through to the underlying
        # sync Session, so registering against Session catches both async
        # and any sync use of get_db (e.g. seed scripts).
        register_tenant_filter(_SyncSession)
    return _async_session_factory


# Module-level aliases for backwards compatibility
class _LazyEngine:
    def __getattr__(self, name):
        return getattr(_get_engine(), name)

    def __repr__(self):
        return repr(_get_engine())


engine = _LazyEngine()


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""

    pass


async def get_db() -> AsyncSession:
    """
    FastAPI dependency that yields an async database session.
    Automatically commits on success, rolls back on exception.
    """
    async with _get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """
    Initialise the database schema.

    - Local/SQLite mode: uses SQLAlchemy ``create_all`` (Alembic not supported
      on SQLite in this project).
    - Platform/PostgreSQL mode: runs ``alembic upgrade head`` so that all
      pending migrations — including 005_s9n3073_hybrid_vector_search — are
      applied automatically on every container start.  Alembic is idempotent;
      re-running against an already-migrated database is safe.

    S9N-3073: migration execution wired here so SDDMini-KH/v3.1.0 tag
    triggers the embedding column + GIN index creation automatically.
    """
    if _is_local_mode():
        # SQLite path — Alembic is not used in local mode
        async with _get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        # Codebase review P1 #4 — running `alembic upgrade head` on every
        # container start blocks the readiness probe under a slow ALTER.
        # Production deployments should run a kemory-migrate Job instead
        # (Core_Infrastructure/k8s/.../kemory-migrate-job.yaml) and set
        # KEMORY_RUN_MIGRATIONS=false on the app Deployment.
        # Local docker-compose still defaults to true so contributors don't
        # have to run a separate command.
        if os.environ.get("KEMORY_RUN_MIGRATIONS", "true").lower() not in {"true", "1", "yes"}:
            return
        # PostgreSQL path — run Alembic migrations (S9N-3073)
        import subprocess
        import sys

        alembic_ini = os.path.join(
            os.path.dirname(  # backend/
                os.path.dirname(  # backend/core/
                    os.path.abspath(__file__)
                )
            ),
            "..",
            "alembic.ini",
        )
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", os.path.normpath(alembic_ini), "upgrade", "head"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"alembic upgrade head failed (S9N-3073):\n{result.stdout}\n{result.stderr}")


async def close_db():
    """Dispose of the engine connection pool."""
    await _get_engine().dispose()
