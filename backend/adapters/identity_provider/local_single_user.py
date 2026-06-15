"""Community single-user identity provider."""

from __future__ import annotations

import hmac
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.identity_provider.base import IdentityProvider
from backend.services.auth_service import AuthContext

_UPGRADE_URL = "https://kemory.s9n.ai"


class JWTRequiresHostedKemory(Exception):
    """Raised when community mode receives a Bearer token."""

    status_code = 401
    body = {"error": "jwt_requires_hosted_kemory", "upgrade_url": _UPGRADE_URL}


@dataclass(frozen=True)
class LocalSingleUserConfig:
    api_key: str
    user_id: uuid.UUID
    org_id: uuid.UUID
    agent_id: uuid.UUID


class LocalSingleUserIDP(IdentityProvider):
    """Static local identity for community edition API-key auth."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        config_path: Path | None = None,
    ) -> None:
        self._explicit_api_key = api_key
        self._config_path = config_path or _default_config_path()
        self._config = self._load_or_create_config()

    @property
    def config(self) -> LocalSingleUserConfig:
        return self._config

    async def verify_bearer(self, token: str) -> AuthContext | None:
        raise JWTRequiresHostedKemory

    async def verify_api_key(self, api_key: str, db: AsyncSession | None = None) -> AuthContext | None:
        configured_key = self._config.api_key
        if not configured_key:
            return None
        if not hmac.compare_digest(api_key.encode("utf-8"), configured_key.encode("utf-8")):
            return None
        return self._build_context()

    async def resolve_org(self, user_id: uuid.UUID) -> uuid.UUID:
        return self._config.org_id

    def _build_context(self) -> AuthContext:
        return AuthContext(
            user_id=self._config.user_id,
            agent_id=self._config.agent_id,
            agent_name="local-single-user",
            scopes=[
                "memory:read",
                "memory:write",
                "memory:delete",
                "namespace:read",
                "namespace:write",
                "namespace:create",
                "graph:read",
                "graph:write",
            ],
            auth_method="api_key",
            org_id=str(self._config.org_id),
        )

    def _load_or_create_config(self) -> LocalSingleUserConfig:
        data = _read_config(self._config_path)
        changed = False

        for key in ("user_id", "org_id", "agent_id"):
            if not data.get(key):
                data[key] = str(uuid.uuid4())
                changed = True

        configured_key = self._explicit_api_key
        if configured_key is None:
            configured_key = data.get("local_api_key") or data.get("api_key") or ""

        if changed:
            _write_config(self._config_path, data)

        return LocalSingleUserConfig(
            api_key=str(configured_key),
            user_id=uuid.UUID(str(data["user_id"])),
            org_id=uuid.UUID(str(data["org_id"])),
            agent_id=uuid.UUID(str(data["agent_id"])),
        )


def _default_config_path() -> Path:
    override = os.environ.get("KEMORY_COMMUNITY_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".kemory-community" / "config.json"


def _read_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        loaded = json.load(fh)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def _write_config(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
