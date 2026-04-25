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
from typing import Optional

import structlog
from fastapi import Depends, HTTPException, Header, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.core.database import get_db
from backend.services.auth_service import (
    AuthContext,
    decode_access_token,
    authenticate_api_key,
)

logger = structlog.get_logger(__name__)

# Bearer token scheme (optional — allows both auth methods)
bearer_scheme = HTTPBearer(auto_error=False)


async def _try_keycloak(token: str) -> Optional[AuthContext]:
    """Attempt Keycloak RS256 validation. Returns None if Keycloak is disabled or unreachable."""
    if not settings.keycloak_enabled:
        return None

    from backend.core.keycloak_validator import keycloak_validator

    try:
        payload = await keycloak_validator.validate_token(token)
        if payload is None:
            # Keycloak unreachable — fall through to HS256
            return None

        # Extract realm roles for scopes
        realm_access = payload.get("realm_access", {})
        roles = realm_access.get("roles", [])

        return AuthContext(
            user_id=uuid.UUID(payload["sub"]),
            agent_id=None,
            agent_name=payload.get("preferred_username", payload.get("email", "")),
            scopes=roles,
            auth_method="keycloak",
        )
    except JWTError:
        # Token looked like a Keycloak token (RS256) but was invalid
        return None


async def get_auth_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Optional[AuthContext]:
    """
    Extract authentication context from the request.

    Checks in order:
    1. Bearer token → Keycloak RS256 → internal HS256
    2. X-API-Key header
    """
    if credentials and credentials.credentials:
        token = credentials.credentials

        # Try Keycloak RS256 first (if enabled)
        auth = await _try_keycloak(token)
        if auth:
            return auth

        # Fall back to internal HS256 JWT
        auth = decode_access_token(token)
        if auth:
            return auth

    # Try API key
    if x_api_key:
        auth = await authenticate_api_key(x_api_key, db)
        if auth:
            return auth

    return None


async def require_auth(
    auth: Optional[AuthContext] = Depends(get_auth_context),
) -> AuthContext:
    """Require authentication — raises 401 if no valid auth is provided."""
    if auth is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token or X-API-Key header.",
            headers={"WWW-Authenticate": "Bearer"},
        )
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
    """Require that the authenticated identity matches the specified user."""
    if auth.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied. Agent does not belong to this user.",
        )
    return auth
