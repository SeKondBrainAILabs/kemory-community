"""Hosted Keycloak-backed identity provider."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import structlog
from fastapi import HTTPException, status
from jwt.exceptions import PyJWKClientError
from s9n_auth.jwt_verify import JwtVerificationError, KeycloakVerifier
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.identity_provider.base import IdentityProvider
from backend.config.settings import settings
from backend.services.auth_service import (
    AuthContext,
    _emit_auth_event,
    authenticate_api_key,
    decode_access_token,
)

logger = structlog.get_logger(__name__)

_kc_verifier: KeycloakVerifier | None = None


def _get_kc_verifier() -> KeycloakVerifier:
    """Return the lazily-built process-wide Keycloak verifier."""
    global _kc_verifier
    if _kc_verifier is None:
        client_ids = tuple(settings.keycloak_client_ids_list)
        _kc_verifier = KeycloakVerifier(
            issuer=settings.keycloak_issuer_url,
            audience=settings.keycloak_client_ids_list,
            jwks_uri=settings.keycloak_jwks_url,
            allowed_azp=client_ids,
            org_claim=settings.tenant_org_claim,
            require_org=False,
            on_event=_emit_auth_event,
        )
    return _kc_verifier


class KeycloakIDP(IdentityProvider):
    """Hosted auth provider preserving the existing Keycloak + HS256 flow."""

    def __init__(self, verifier_factory: Callable[[], KeycloakVerifier] = _get_kc_verifier) -> None:
        self._verifier_factory = verifier_factory

    async def verify_bearer(self, token: str) -> AuthContext | None:
        auth = await self.verify_keycloak_token(token)
        if auth is not None:
            return auth
        return decode_access_token(token)

    async def verify_api_key(self, api_key: str, db: AsyncSession | None = None) -> AuthContext | None:
        if db is None:
            raise RuntimeError("KeycloakIDP.verify_api_key requires a database session")
        return await authenticate_api_key(api_key, db)

    async def resolve_org(self, user_id: uuid.UUID) -> str:
        """Hosted bearer tokens carry org claims; user-only lookup is not available here."""
        return settings.tenant_legacy_sentinel

    async def verify_keycloak_token(self, token: str) -> AuthContext | None:
        """Attempt Keycloak RS256 validation.

        WS-2: extracts the tenant claim (settings.tenant_org_claim, default
        "org_id") into AuthContext.org_id. Behaviour when the claim is missing
        is gated on settings.tenant_enforcement:
          * "off"     — accept token, set org_id = legacy sentinel
          * "shadow"  — accept token, log a violation, set org_id = sentinel
          * "enforce" — raise 401 missing_org_claim
        """
        if not settings.keycloak_enabled:
            return None

        try:
            claims = self._verifier_factory().verify_claims(token)
        except JwtVerificationError as exc:
            # Preserve hosted resilience: JWKS outages fall through to HS256;
            # other invalid Keycloak tokens just fail this provider path.
            if isinstance(exc.__cause__, PyJWKClientError):
                logger.warning("keycloak.jwks_unreachable.fallthrough", error=str(exc))
            return None

        realm_access = claims.get("realm_access", {})
        scopes = realm_access.get("roles", [])

        client_id = settings.keycloak_client_id
        resource_access = claims.get("resource_access", {})
        client_roles = resource_access.get(client_id, {}).get("roles", [])
        roles = sorted({*scopes, *client_roles})

        org_claim = claims.get(settings.tenant_org_claim)
        if not org_claim:
            mode = settings.tenant_enforcement
            if mode == "enforce":
                logger.warning(
                    "keycloak.missing_org_claim.reject",
                    sub=claims.get("sub"),
                    azp=claims.get("azp"),
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
                    sub=claims.get("sub"),
                    azp=claims.get("azp"),
                    mode=mode,
                )
            org_claim = settings.tenant_legacy_sentinel

        return AuthContext(
            user_id=uuid.UUID(claims["sub"]),
            agent_id=None,
            agent_name=claims.get("preferred_username", claims.get("email", "")),
            scopes=scopes,
            roles=roles,
            auth_method="keycloak",
            org_id=org_claim,
        )
