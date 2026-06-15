"""
S9N Memory Vault — Health Check Endpoints

Three-tier health check system:
- /health/live  — Liveness probe (is the process running?)
- /health/ready — Readiness probe (can the service accept traffic?)
- /health/deep  — Deep health check (are all dependencies healthy?)

Spec reference: Section 10, Appendix B.1
"""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter

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
        "timestamp": datetime.now(UTC).isoformat(),
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

    # Check PostgreSQL — connectivity AND that the schema is initialized.
    # A reachable-but-empty DB (e.g. failed bootstrap) must read as not-ready,
    # otherwise the API advertises readiness while every query 500s.
    try:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy import text as sa_text

        from backend.core.database import engine

        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
            has_core = await conn.run_sync(lambda c: sa_inspect(c).has_table("kemory_memories"))
        if has_core:
            checks["postgres"] = {"status": "healthy", "latency_ms": 0}
        else:
            checks["postgres"] = {"status": "unhealthy", "error": "schema not initialized"}
            all_healthy = False
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
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )


@router.get("/health/deep")
async def deep_health():
    """
    Deep health check — verifies community dependencies.
    More expensive than readiness; used for monitoring dashboards, not orchestrator probes.
    """
    checks = {}
    all_healthy = True

    # Check PostgreSQL
    try:
        import time

        from backend.core.database import engine

        start = time.monotonic()
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        latency = round((time.monotonic() - start) * 1000, 2)
        checks["postgres"] = {"status": "healthy", "latency_ms": latency}
    except Exception as e:
        checks["postgres"] = {"status": "unhealthy", "error": str(e)}
        all_healthy = False

    # Check Redis
    try:
        import time

        from backend.core.redis import redis_client

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
            "timestamp": datetime.now(UTC).isoformat(),
        },
    )
