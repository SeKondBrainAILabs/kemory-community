"""
S9N Memory Vault — Authentication Dependencies

FastAPI dependencies for extracting and validating authentication from requests.
Triple-path auth:
  1. Bearer token → try Keycloak RS256 → try internal HS256
  2. X-API-Key → authenticate_api_key()
  3. No credentials → 401

Usage in routes:
    @router.get("/protected")
    async def protected_endpoint(auth: AuthContext = Depends(require_auth)):
        ...
"""

import uuid

import structlog
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.identity_provider import get_identity_provider
from backend.config.settings import settings
from backend.core.active_org import resolve_active_org
from backend.core.database import get_db
from backend.services.auth_service import AuthContext

logger = structlog.get_logger(__name__)

# Bearer token scheme (optional — allows both auth methods)
bearer_scheme = HTTPBearer(auto_error=False)


async def _try_keycloak(token: str) -> AuthContext | None:
    """Community edition does not verify hosted bearer tokens."""
    return None


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    x_acting_user_id: str | None = Header(None, alias="X-Acting-User-Id"),
    db: AsyncSession = Depends(get_db),
) -> AuthContext | None:
    """
    Extract authentication context from the request.

    Checks in order:
    1. Bearer token → Keycloak RS256 → internal HS256
    2. X-API-Key header

    WS-6: X-Acting-User-Id is honoured only on the API-key path (shared MCP
    bridge serving multiple users). It is informational in this foundation
    branch — the field is recorded on AuthContext.acting_user_id so audit
    can log both identities, but it does NOT change the effective user_id.
    Full delegation (switching user_id and team_ids to the target) lands in
    a follow-up once the user-lookup contract for cross-org validation is
    settled. Header on the Keycloak / HS256 paths is silently ignored.
    """
    auth: AuthContext | None = None
    identity_provider = get_identity_provider()
    if credentials and credentials.credentials:
        token = credentials.credentials
        auth = await identity_provider.verify_bearer(token)

    # Try API key
    if auth is None and x_api_key:
        auth = await identity_provider.verify_api_key(x_api_key, db)

    if auth is None:
        return None

    # WS-6: capture acting-as on api_key path only, and only when the
    # target user is in the same org as the key. We confirm same-org by
    # looking up an AgentRegistry row for that target user_id within
    # auth.org_id — if none exists OR none in the same org, reject.
    # This is conservative: a user without any agent rows can't be
    # acted-as. That is acceptable for v1 because the only legitimate
    # use case is shared MCP bridges talking to kemory, which inherently
    # requires the target user to have at least one registered agent.
    if x_acting_user_id and auth.auth_method == "api_key":
        try:
            target_uuid = uuid.UUID(x_acting_user_id)
        except ValueError:
            logger.warning(
                "auth.invalid_acting_user_id",
                value=x_acting_user_id,
                key_user_id=str(auth.user_id),
            )
            return auth

        if not auth.org_id:
            logger.warning("auth.acting_as_rejected.no_caller_org", key_user_id=str(auth.user_id))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="acting-as requires the caller key to have an org",
            )

        # Cross-org acting-as is the attack we are defending against.
        from sqlalchemy import select as _select  # local — cycle avoid

        from backend.models.agent import AgentRegistry as _AgentRegistry

        result = await db.execute(
            _select(_AgentRegistry.user_id)
            .where(_AgentRegistry.user_id == target_uuid)
            .where(_AgentRegistry.org_id == auth.org_id)
            .limit(1)
        )
        if result.scalar_one_or_none() is None:
            logger.warning(
                "auth.acting_as_rejected.cross_org",
                caller=str(auth.user_id),
                target=x_acting_user_id,
                org=auth.org_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="acting-as: target user is not in the caller's org",
            )

        auth = auth.model_copy(update={"acting_user_id": target_uuid})

    return auth


async def require_auth(
    request: Request,
    auth: AuthContext | None = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    """Require authentication — raises 401 if no valid auth is provided.

    PR #17 added a SQLAlchemy listener that auto-injects
    ``WHERE org_id = current_org_id`` on every tenant-scoped SELECT. The
    ContextVar is set by ``get_tenant_scope`` — but many routes only depend
    on ``require_auth``, not the heavier tenant-scope dependency. Without
    a set ContextVar the listener emits an always-false predicate
    (``org_id = '__no_active_scope__'``), silently zeroing out every
    SELECT and breaking memory writes / search / permission-rule reads.

    To make ``require_auth`` self-sufficient — and so the upstream
    multi-tenant work doesn't regress every existing route handler —
    we seed the ContextVars from the auth context here. ``get_tenant_scope``
    overlays a richer view (server-resolved team_ids) on top.
    """
    if auth is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token or X-API-Key header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # ADR-012 Phase 2 — active-org resolution seam. This is the single point
    # where kemory decides which org the request is authorized against. Today
    # it is identity (returns the org already on the token); the M2/M3 body
    # (post-spike) is the only thing that changes. Overwriting auth here means
    # every downstream consumer — the write path (org_id=auth.org_id), the
    # ContextVar seeding below, and get_tenant_scope (which depends on this
    # function) — inherits the resolved org with no further plumbing.
    resolved = await resolve_active_org(auth, request, db)
    auth = auth.model_copy(
        update={
            "org_id": resolved.org_id,
            "org_role": resolved.org_role,
            "org_type": resolved.org_type,
        }
    )

    # ADR-012 Phase 2 — fail-closed for M3 denies. When the resolver denies a
    # human caller (non-member of the requested org, or core_backend
    # unreachable) it returns an empty org. Reject here so the denial covers
    # EVERY route, including the many that depend only on require_auth and never
    # reach get_tenant_scope's enforce check (e.g. the write path that stamps
    # org_id=auth.org_id). Scoped to m3 + keycloak so legacy mode and agents
    # are byte-for-byte unchanged.
    if settings.active_org_mode == "m3" and auth.auth_method == "keycloak" and not auth.org_id:
        logger.warning("auth.m3_no_active_org.reject", user_id=str(auth.user_id))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="no_active_org",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Seed the tenant ContextVars from the resolved auth so the per-session
    # SQL filter has something non-empty to match against. Falls back to
    # the legacy sentinel for tokens minted before the multi-tenant
    # rollout. Lazy-import to avoid an auth → tenancy → settings cycle.
    try:
        from backend.config.settings import settings as _settings
        from backend.core.tenancy import (
            _current_org_id,
            _current_org_role,
            _current_team_ids,
            _current_user_id,
        )

        org_id = auth.org_id or _settings.tenant_legacy_sentinel
        _current_org_id.set(org_id)
        _current_user_id.set(str(auth.user_id))
        _current_team_ids.set(())
        _current_org_role.set(auth.org_role)
    except Exception:
        # Tenancy module unavailable — proceed without the ContextVar.
        pass
    return auth


async def require_beta_access(
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """
    Require beta_approved role for Keycloak users.
    API key and internal JWT users pass through (they are agents, not gated).
    """
    if auth.auth_method == "keycloak" and "beta_approved" not in auth.scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is pending beta approval. You'll be notified when approved.",
        )
    return auth


ADMIN_ROLES = {"admin", "super_admin", "platform_admin"}
SUPER_ADMIN_ROLES = {"super_admin", "platform_admin"}


def is_admin(auth: "AuthContext") -> bool:
    """
    Return True if the authenticated identity holds an admin role.

    Memory Vault admin users authenticated via Keycloak carry one of the
    ADMIN_ROLES in their realm_access.roles claim.  API-key / internal-JWT
    identities are agent-level and are never treated as admins.
    """
    if auth.auth_method != "keycloak":
        return False
    return bool(ADMIN_ROLES.intersection(auth.scopes))


async def require_admin(
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """Require admin, super_admin, or platform_admin role."""
    if auth.auth_method == "keycloak" and not ADMIN_ROLES.intersection(auth.scopes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return auth


async def require_super_admin(
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """Require super_admin or platform_admin role."""
    if auth.auth_method == "keycloak" and not SUPER_ADMIN_ROLES.intersection(auth.scopes):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )
    return auth


async def require_user(
    user_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
) -> AuthContext:
    """Require that the authenticated identity matches the specified user.

    WS-3: when TENANT_ENFORCEMENT='enforce' the cross-org check is layered
    on top by the global SQLAlchemy filter (queries filter by org_id and
    naturally return 404). At the request level this function still does
    the user-equality check so the legacy 403 stays consistent.
    """
    if auth.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Agent does not belong to this user.",
        )
    return auth
