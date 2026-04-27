"""
S9N Memory Vault — Main Application Entry Point

FastAPI application with lifecycle management for all service connections.
Follows the spec architecture: S9N Memory Vault API Gateway is the single entry point.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

from backend.config.settings import settings
from backend.core.database import init_db, close_db
from backend.core.redis import init_redis, close_redis
from backend.api.routes.health import router as health_router
from backend.api.routes.agents import router as agents_router
from backend.api.routes.permissions import permissions_router, gatekeeper_router
from backend.api.routes.memories import router as memories_router
from backend.mcp.server import router as mcp_router
from backend.api.routes.enrichment import router as enrichment_router
from backend.api.routes.audit import router as audit_router
from backend.api.routes.security import router as security_router
from backend.api.routes.waitlist import public_router as waitlist_router, admin_router as waitlist_admin_router
from backend.api.routes.graph import router as graph_router  # F12: Access Graph
from backend.api.routes.me import router as me_router  # WS-11: identity
from backend.api.routes.teams import router as teams_router  # WS-9: team admin
from backend.core.tenant_rate_limit import tenant_rate_limit_middleware

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle manager.
    Initializes all service connections on startup and cleans up on shutdown.
    """
    logger.info(
        "kora.startup",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
    )

    # ─── Startup ──────────────────────────────────────────────────
    try:
        # Initialize database (create tables in dev mode)
        await init_db()
        logger.info("kora.db.connected", url=settings.database_url[:30] + "...")
    except Exception as e:
        logger.error("kora.db.connection_failed", error=str(e))

    try:
        # Initialize Redis
        await init_redis()
        logger.info("kora.redis.connected", url=settings.redis_url)
    except Exception as e:
        logger.error("kora.redis.connection_failed", error=str(e))

    yield

    # ─── Shutdown ─────────────────────────────────────────────────
    logger.info("kora.shutdown")
    await close_db()
    await close_redis()


# ─── Application Factory ─────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="User-owned, encrypted personal memory layer for AI agents",
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url="/redoc" if settings.environment == "development" else None,
    lifespan=lifespan,
)

# ─── Middleware ───────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "development" else settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Per-tenant rate limiting (WS-3 hardening). Mounted last in the user code
# so it runs first on the inbound path — we want to reject 429s before
# expensive auth/db work. The middleware reads the ContextVars set by
# get_tenant_scope; unauthenticated routes pass through unchanged.
app.middleware("http")(tenant_rate_limit_middleware)

# ─── Routes ──────────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(agents_router)
app.include_router(permissions_router)
app.include_router(gatekeeper_router)
app.include_router(memories_router)
app.include_router(mcp_router)
app.include_router(enrichment_router)
app.include_router(audit_router)
app.include_router(security_router)
app.include_router(waitlist_router)
app.include_router(waitlist_admin_router)
app.include_router(graph_router)  # F12: Access Graph
app.include_router(me_router)  # WS-11: GET /api/v1/me
app.include_router(teams_router)  # WS-9: org/team admin
