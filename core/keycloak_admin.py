"""
S9N Memory Vault — Keycloak Admin API Client

Manages realm roles for users via Keycloak's Admin REST API.
Used to assign/remove `beta_approved` role on waitlist approval/rejection.

Requires a service account client (kemory-api) with realm-management roles.
"""
import uuid

import httpx
import structlog

from backend.config.settings import settings

logger = structlog.get_logger(__name__)


class KeycloakAdminClient:
    """Thin wrapper over Keycloak Admin REST API for role management."""

    def __init__(self):
        self._token: str | None = None

    async def _get_admin_token(self) -> str:
        """Get service account token via client_credentials grant."""
        url = (
            f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
            f"/protocol/openid-connect/token"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.keycloak_client_id,
                    "client_secret": settings.keycloak_admin_client_secret,
                },
            )
            resp.raise_for_status()
            self._token = resp.json()["access_token"]
            return self._token

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    @property
    def _admin_base(self) -> str:
        return f"{settings.keycloak_url}/admin/realms/{settings.keycloak_realm}"

    async def _get_role(self, role_name: str) -> dict | None:
        """Fetch a realm role by name."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self._admin_base}/roles/{role_name}",
                headers=self._headers(),
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def assign_role(self, user_id: uuid.UUID, role_name: str) -> bool:
        """Assign a realm role to a user."""
        await self._get_admin_token()

        role = await self._get_role(role_name)
        if not role:
            logger.error("keycloak_admin.role_not_found", role=role_name)
            return False

        url = f"{self._admin_base}/users/{user_id}/role-mappings/realm"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers=self._headers(),
                json=[{"id": role["id"], "name": role["name"]}],
            )

        if resp.status_code in (200, 204):
            logger.info(
                "keycloak_admin.role_assigned",
                user_id=str(user_id),
                role=role_name,
            )
            return True

        logger.error(
            "keycloak_admin.role_assign_failed",
            user_id=str(user_id),
            role=role_name,
            status=resp.status_code,
            body=resp.text,
        )
        return False

    async def remove_role(self, user_id: uuid.UUID, role_name: str) -> bool:
        """Remove a realm role from a user."""
        await self._get_admin_token()

        role = await self._get_role(role_name)
        if not role:
            return False

        url = f"{self._admin_base}/users/{user_id}/role-mappings/realm"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(
                "DELETE",
                url,
                headers=self._headers(),
                json=[{"id": role["id"], "name": role["name"]}],
            )

        if resp.status_code in (200, 204):
            logger.info(
                "keycloak_admin.role_removed",
                user_id=str(user_id),
                role=role_name,
            )
            return True

        return False


keycloak_admin = KeycloakAdminClient()
