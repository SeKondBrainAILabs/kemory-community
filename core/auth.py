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
    """Attempt Keycloak RS256 validation. Returns None if Keycloak is disabled or unreachable.

    WS-2: extracts the tenant claim (settings.tenant_org_claim, default
    "org_id") into AuthContext.org_id. Behaviour when the claim is missing
    is gated on settings.tenant_enforcement:
      * "off"     — accept token, set org_id = legacy sentinel (current default)
      * "shadow"  — accept token, log a violation, set org_id = sentinel
      * "enforce" — raise 401 missing_org_claim (caller must catch HTTPException)
    """
    if not settings.keycloak_enabled:
        return None

    from backend.core.keycloak_validator import keycloak_validator

    try:
        payload = await keycloak_validator.validate_token(token)
        if payload is None:
            # Keycloak unreachable — fall through to HS256
            return None

        # Extract realm roles for scopes (legacy field, kept for compat with
        # is_admin / require_admin etc.) plus client-specific roles for the
        # WS-2 roles list (org_admin, team_owner, ...).
        realm_access = payload.get("realm_access", {})
        scopes = realm_access.get("roles", [])

        client_id = settings.keycloak_client_id
        resource_access = payload.get("resource_access", {})
        client_roles = resource_access.get(client_id, {}).get("roles", [])
        # Merge: any role from realm_access OR resource_access.kemory-api
        # is fair game for role-checks. Keep both lists addressable.
        roles = sorted({*scopes, *client_roles})

        # WS-2: tenant claim extraction.
        org_claim = payload.get(settings.tenant_org_claim)
        if not org_claim:
            mode = settings.tenant_enforcement
            if mode == "enforce":
                logger.warning(
                    "keycloak.missing_org_claim.reject",
                    sub=payload.get("sub"),
                    azp=payload.get("azp"),
                )
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="missing_org_claim",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if mode == "shadow":
                logger.warning(
                    "kemory.tenancy.violation",
                    kind="missing_org_claim",
                    sub=payload.get("sub"),
                    azp=payload.get("azp"),
                    mode=mode,
                )
            org_claim = settings.tenant_legacy_sentinel

        return AuthContext(
            user_id=uuid.UUID(payload["sub"]),
            agent_id=None,
            agent_name=payload.get("preferred_username", payload.get("email", "")),
            scopes=scopes,
            roles=roles,
            auth_method="keycloak",
            org_id=org_claim,
        )
    except JWTError:
        # Token looked like a Keycloak token (RS256) but was invalid
        return None


async def get_auth_context(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_acting_user_id: Optional[str] = Header(None, alias="X-Acting-User-Id"),
    db: AsyncSession = Depends(get_db),
) -> Optional[AuthContext]:
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
    auth: Optional[AuthContext] = None
    if credentials and credentials.credentials:
        token = credentials.credentials

        # Try Keycloak RS256 first (if enabled)
        auth = await _try_keycloak(token)
        if auth is None:
            # Fall back to internal HS256 JWT
            auth = decode_access_token(token)

    # Try API key
    if auth is None and x_api_key:
        auth = await authenticate_api_key(x_api_key, db)

    if auth is None:
        return None

    # WS-6: capture acting-as on api_key path only.
    if x_acting_user_id and auth.auth_method == "api_key":
        try:
            auth = auth.model_copy(update={"acting_user_id": uuid.UUID(x_acting_user_id)})
        except ValueError:
            logger.warning(
                "auth.invalid_acting_user_id",
                value=x_acting_user_id,
                key_user_id=str(auth.user_id),
            )

    return auth


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
            detail="Your account is on the waitlist. You'll be notified when approved.",
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
