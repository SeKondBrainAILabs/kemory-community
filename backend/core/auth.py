"""Community X-API-Key authentication dependencies.

Usage in routes:
    @router.get("/protected")
    async def protected_endpoint(auth: AuthContext = Depends(require_auth)):
        ...
"""

import uuid

from fastapi import Depends, Header, HTTPException, status

from backend.adapters.identity_provider import get_identity_provider
from backend.core.auth_context import AuthContext


async def get_auth_context(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
) -> AuthContext | None:
    """Resolve the local single-user context from ``X-API-Key`` only."""
    if not x_api_key:
        return None
    return await get_identity_provider().verify_api_key(x_api_key)


async def require_auth(
    auth: AuthContext | None = Depends(get_auth_context),
) -> AuthContext:
    """Require the local API key and seed portable schema context."""
    if auth is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide the X-API-Key header.",
        )

    # Portable hosted/community tables retain org columns. Seed their existing
    # SQLAlchemy context with the one immutable local identity; no org/team
    # resolution or delegation is performed in community mode.
    try:
        from backend.core.tenancy import (
            _current_org_id,
            _current_org_role,
            _current_team_ids,
            _current_user_id,
        )

        _current_org_id.set(auth.org_id or "local")
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
