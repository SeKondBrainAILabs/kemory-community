"""
S9N Memory Vault — Health Check Endpoints

Three-tier health check system:
- /health/live  — Liveness probe (is the process running?)
- /health/ready — Readiness probe (can the service accept traffic?)
- /health/deep  — Deep health check (are all dependencies healthy?)

Spec reference: Section 10, Appendix B.1
"""
from fastapi import APIRouter, Depends
from datetime import datetime, timezone
import structlog

from backend.config.settings import settings

logger = structlog.get_logger(__name__)

# Module-level FalkorDB (Redis) client — reused across health check requests
_falkordb_client = None


def _get_falkordb_url() -> str:
    """Return the FalkorDB Redis URL from env or settings."""
    import os
    return os.environ.get("FALKORDB_URL", "") or getattr(settings, "neo4j_uri", "redis://localhost:6379")


router = APIRouter(tags=["Health"])


@router.get("/health/live")
async def liveness():
    """
    Liveness probe — confirms the process is running.
    Used by container orchestrators to detect crashed processes.
    Always returns 200 if the server is up.
    """
    return {
        "status": "alive",
        "service": settings.app_name,
        "version": settings.app_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/ready")
async def readiness():
    """
    Readiness probe — confirms the service can accept traffic.
    Checks that critical dependencies (Postgres, Redis) are reachable.
    Returns 200 if ready, 503 if not.
    """
    checks = {}
    all_healthy = True

    # Check PostgreSQL
    try:
        from backend.core.database import engine
        async with engine.connect() as conn:
            await conn.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        checks["postgres"] = {"status": "healthy", "latency_ms": 0}
    except Exception as e:
        checks["postgres"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    # Check Redis
    try:
        from backend.core.redis import redis_client
        if redis_client:
            await redis_client.ping()
            checks["redis"] = {"status": "healthy", "latency_ms": 0}
        else:
            checks["redis"] = {"status": "not_initialized"}
            all_healthy = False
    except Exception as e:
        checks["redis"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    status_code = 200 if all_healthy else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_healthy else "not_ready",
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


@router.get("/health/deep")
async def deep_health():
    """
    Deep health check — verifies ALL dependencies including Neo4j and Weaviate.
    More expensive than readiness; used for monitoring dashboards, not orchestrator probes.
    """
    checks = {}
    all_healthy = True

    # Check PostgreSQL
    try:
        from backend.core.database import engine
        import time
        start = time.monotonic()
        async with engine.connect() as conn:
            await conn.execute(
                __import__("sqlalchemy").text("SELECT 1")
            )
        latency = round((time.monotonic() - start) * 1000, 2)
        checks["postgres"] = {"status": "healthy", "latency_ms": latency}
    except Exception as e:
        checks["postgres"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    # Check Redis
    try:
        from backend.core.redis import redis_client
        import time
        start = time.monotonic()
        if redis_client:
            await redis_client.ping()
            latency = round((time.monotonic() - start) * 1000, 2)
            checks["redis"] = {"status": "healthy", "latency_ms": latency}
        else:
            checks["redis"] = {"status": "not_initialized"}
            all_healthy = False
    except Exception as e:
        checks["redis"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    # Check FalkorDB (Redis-based graph DB)
    try:
        import time
        import redis.asyncio as aioredis
        start = time.monotonic()
        falkordb_url = _get_falkordb_url()
        r = aioredis.from_url(falkordb_url, socket_connect_timeout=5)
        await r.ping()
        await r.aclose()
        latency = round((time.monotonic() - start) * 1000, 2)
        checks["falkordb"] = {"status": "healthy", "latency_ms": latency}
    except Exception as e:
        checks["falkordb"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    # Check Weaviate
    try:
        import time
        import httpx
        start = time.monotonic()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{settings.weaviate_url}/v1/.well-known/ready",
                timeout=5.0,
            )
            resp.raise_for_status()
        latency = round((time.monotonic() - start) * 1000, 2)
        checks["weaviate"] = {"status": "healthy", "latency_ms": latency}
    except Exception as e:
        checks["weaviate"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    # Check Keycloak (only when enabled)
    if settings.keycloak_enabled:
        try:
            import time
            import httpx
            start = time.monotonic()
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/.well-known/openid-configuration",
                    timeout=5.0,
                )
                resp.raise_for_status()
            latency = round((time.monotonic() - start) * 1000, 2)
            checks["keycloak"] = {"status": "healthy", "latency_ms": latency}
        except Exception as e:
            checks["keycloak"] = {"status": "unhealthy", "error": str(e)}
            all_healthy = False

    status_code = 200 if all_healthy else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "healthy" if all_healthy else "degraded",
            "service": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
            "checks": checks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
