"""
S9N Memory Vault — Keycloak JWT Validator

Validates RS256 JWT tokens issued by Keycloak using JWKS public keys.
Ported from Core_Ai_Backend/src/auth/keycloak_validator.py.

Features:
- JWKS fetching with in-memory cache
- RSA-256 signature verification
- Issuer + audience/azp validation
- Automatic key rotation retry
"""
import httpx
import structlog
from jose import jwt, JWTError

from backend.config.settings import settings

logger = structlog.get_logger(__name__)


class KeycloakValidator:
    """Validates Keycloak-issued RS256 JWT tokens via JWKS."""

    def __init__(self):
        self.public_keys_cache: dict | None = None

    async def get_public_keys(self, force_refresh: bool = False) -> dict:
        """Fetch and cache Keycloak's JWKS for RSA signature verification."""
        if self.public_keys_cache and not force_refresh:
            return self.public_keys_cache

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(settings.keycloak_jwks_url)
                resp.raise_for_status()
                jwks = resp.json()

            self.public_keys_cache = jwks
            logger.info(
                "keycloak.jwks_fetched",
                realm=settings.keycloak_realm,
                key_count=len(jwks.get("keys", [])),
            )
            return dict(jwks)

        except httpx.HTTPError as e:
            logger.error(
                "keycloak.jwks_fetch_failed",
                url=settings.keycloak_jwks_url,
                error=str(e),
            )
            raise

    async def validate_token(self, token: str) -> dict | None:
        """
        Validate a Keycloak RS256 JWT token.

        Returns the decoded payload on success, None if Keycloak is
        unreachable (so the caller can fall through to HS256).
        Raises JWTError for invalid/expired tokens.
        """
        try:
            jwks = await self.get_public_keys()
        except httpx.HTTPError:
            return None

        # Extract kid from token header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        if not kid:
            raise JWTError("Missing key ID (kid) in token header")

        # Find matching public key
        public_key = self._find_key(jwks, kid)
        if not public_key:
            # Key may have rotated — refresh JWKS once
            logger.warning("keycloak.key_not_found_refreshing", kid=kid)
            try:
                jwks = await self.get_public_keys(force_refresh=True)
            except httpx.HTTPError:
                return None
            public_key = self._find_key(jwks, kid)
            if not public_key:
                raise JWTError(f"Public key not found for kid={kid}")

        # Verify signature and claims
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            options={
                "verify_signature": True,
                "verify_aud": False,
                "verify_exp": True,
                "verify_iss": True,
            },
            issuer=settings.keycloak_issuer_url,
        )

        # Validate client (azp or aud must match allowed clients)
        allowed = set(settings.keycloak_client_ids_list)
        azp = payload.get("azp")
        aud = payload.get("aud")

        azp_ok = azp and azp in allowed
        aud_ok = False
        if aud:
            audiences = [aud] if isinstance(aud, str) else aud
            aud_ok = any(a in allowed for a in audiences)

        if not azp_ok and not aud_ok:
            raise JWTError(
                f"Invalid client. azp='{azp}', aud={aud}, expected one of {allowed}"
            )

        logger.info(
            "keycloak.token_validated",
            user_id=payload.get("sub"),
            client=azp,
        )
        return dict(payload)

    @staticmethod
    def _find_key(jwks: dict, kid: str) -> dict | None:
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None


# Global singleton
keycloak_validator = KeycloakValidator()
