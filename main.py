"""
S9N Memory Vault — Main Application Entry Point

FastAPI application with lifecycle management for all service connections.
Follows the spec architecture: S9N Memory Vault API Gateway is the single entry point.
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes.agents import router as agents_router
from backend.api.routes.ai_chats import router as ai_chats_router  # chats-v1
from backend.api.routes.audit import router as audit_router
from backend.api.routes.chat_mappings import router as chat_mappings_router  # chats-v1
from backend.api.routes.consolidation import router as consolidation_router  # KMV-E14
from backend.api.routes.enrichment import router as enrichment_router
from backend.api.routes.extension_keys import router as extension_keys_router  # chats-v1
from backend.api.routes.graph import router as graph_router  # F12: Access Graph
from backend.api.routes.health import router as health_router
from backend.api.routes.me import router as me_router  # WS-11: identity
from backend.api.routes.memories import router as memories_router
from backend.api.routes.pair import router as pair_router  # quick‑connect pairing
from backend.api.routes.permissions import gatekeeper_router, permissions_router
from backend.api.routes.security import router as security_router
from backend.api.routes.teams import router as teams_router  # WS-9: team admin
from backend.api.routes.user import router as user_router  # KMV-CTX-01: user context
from backend.config.settings import settings
from backend.core.body_size_limit import body_size_limit_middleware
from backend.core.database import close_db, init_db
from backend.core.redis import close_redis, init_redis
from backend.core.tenant_rate_limit import tenant_rate_limit_middleware
from backend.mcp.server import router as mcp_router

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
# CORS — wildcard allow_origins with allow_credentials=False is the
# correct shape for kemory because every authenticated client speaks
# header-based auth (X-API-Key or Authorization: Bearer ...), NEVER
# cookies. Concretely:
#
#   * Dashboard (app.memory.dxb-gw.basanti.ai)  → Bearer token via ky
#   * MCP agents                                → X-API-Key
#   * Kanvas Chrome Extension                   → X-API-Key
#
# None of these set `credentials: 'include'` on fetch, so flipping
# allow_credentials=False does NOT regress them. It DOES let
# chrome-extension://* origins through the preflight, which the prior
# allow-list-based config blocked (extension-id origins can't be
# enumerated up front, and Chrome rejects Allow-Origin:* when paired
# with Allow-Credentials:true).
#
# If a future client ever needs cookie-credentialed cross-origin
# requests, switch back to a specific allow-list and set
# allow_credentials=True — those two MUST move together.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Per-tenant rate limiting (WS-3 hardening). Mounted last in the user code
# so it runs first on the inbound path — we want to reject 429s before
# expensive auth/db work. The middleware reads the ContextVars set by
# get_tenant_scope; unauthenticated routes pass through unchanged.
app.middleware("http")(tenant_rate_limit_middleware)

# Body size limit (P4 #22). Mounted AFTER the rate-limit middleware so it
# registers as the OUTERMOST layer and runs first on the inbound path —
# rejecting oversized payloads before the rate-limiter does any Redis work
# or auth runs any bcrypt verification. ASGI middleware ordering: the last
# .middleware() registered is the first to run.
app.middleware("http")(body_size_limit_middleware)

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
app.include_router(graph_router)  # F12: Access Graph
app.include_router(me_router)  # WS-11: GET /api/v1/me
app.include_router(teams_router)  # WS-9: org/team admin
app.include_router(consolidation_router)  # KMV-E14: namespace policies + consolidation stats
app.include_router(user_router)  # KMV-CTX-01: cross-namespace user context
app.include_router(pair_router)  # quick‑connect pair flow
# ── chats-v1: AI Chats module ─────────────────────────────────────
# Routers registered after pair so the existing pair-flow paths keep
# their order; the chats routes live under /api/v1/chats,
# /api/v1/chat-mappings, and /api/v1/extension/keys.
app.include_router(ai_chats_router)
app.include_router(chat_mappings_router)
app.include_router(extension_keys_router)
