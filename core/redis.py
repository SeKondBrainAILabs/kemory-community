"""
S9N Memory Vault — Redis Connection Manager

Provides async Redis client for rate limiting, caching, and feature_bus transport.
All S9N Memory Vault keys use the 's9nmv:' prefix for namespace isolation.

In local mode (MEMORY_VAULT_MODE=local), Redis is optional — init_redis()
logs a warning and leaves redis_client as None. The rate limiter and other
consumers gracefully skip when redis_client is None.

Story: MV2-S06.3 — Make Redis Optional
"""
import asyncio
import os

import structlog
import redis.asyncio as aioredis
from backend.config.settings import settings

logger = structlog.get_logger(__name__)

# Global Redis client — initialized on app startup (None = disabled)
redis_client: aioredis.Redis | None = None
_redis_lock = asyncio.Lock()


async def init_redis() -> aioredis.Redis | None:
    """Initialize the async Redis connection pool.

    In local mode, gracefully returns None if Redis is unreachable.
    """
    global redis_client
    try:
        redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
            socket_connect_timeout=3,
        )
        await redis_client.ping()
        return redis_client
    except Exception as exc:
        is_local = os.environ.get("MEMORY_VAULT_MODE", "").lower() == "local"
        if is_local:
            logger.warning(
                "redis.optional_skip",
                reason=str(exc),
                hint="Redis unavailable in local mode — rate limiting disabled",
            )
            redis_client = None
            return None
        else:
            raise  # In platform mode, Redis is required


async def get_redis() -> aioredis.Redis | None:
    """FastAPI dependency that returns the Redis client (or None in local mode)."""
    global redis_client
    if redis_client is not None:
        return redis_client
    async with _redis_lock:
        if redis_client is None:
            await init_redis()
    return redis_client


async def close_redis():
    """Close the Redis connection pool."""
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None
