"""
Alembic environment configuration for async SQLAlchemy.
"""
import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import all models so Alembic can detect them
from backend.core.database import Base
from backend.models import *  # noqa: F401, F403

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Allow the DB URL to come from the runtime environment. The alembic.ini file
# ships with a sync psycopg2 URL for offline use, but the async engine path
# requires an asyncpg URL. Prefer DATABASE_URL (set by docker-compose), fall
# back to translating the sync URL to asyncpg form. S9N-3073 relies on
# init_db() calling `alembic upgrade head` on container startup — it cannot
# succeed unless this path resolves to an async driver.
_env_url = os.environ.get("DATABASE_URL", "")
if _env_url:
    config.set_main_option("sqlalchemy.url", _env_url)
else:
    _cfg_url = config.get_main_option("sqlalchemy.url") or ""
    if _cfg_url.startswith("postgresql://"):
        config.set_main_option(
            "sqlalchemy.url",
            _cfg_url.replace("postgresql://", "postgresql+asyncpg://", 1),
        )

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
