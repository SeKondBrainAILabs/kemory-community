"""Identity-provider adapter factory."""

from __future__ import annotations

from pathlib import Path

from backend.adapters.identity_provider.base import IdentityProvider
from backend.adapters.identity_provider.local_single_user import LocalSingleUserIDP
from backend.config.settings import settings

_provider: IdentityProvider | None = None
_provider_identity: str | None = None


def normalize_identity(identity: str | None) -> str:
    return (identity or "local_single_user").strip().lower()


def create_identity_provider(identity: str | None = None) -> IdentityProvider:
    selected = normalize_identity(identity or settings.kmv_identity)
    if selected == "keycloak":
        raise ValueError("Keycloak identity is available only in hosted Kemory.")
    if selected == "local_single_user":
        config_path = Path(settings.kemory_community_config) if settings.kemory_community_config else None
        return LocalSingleUserIDP(
            api_key=settings.kemory_local_api_key or None,
            config_path=config_path,
        )
    raise ValueError("KMV_IDENTITY must be local_single_user in Kemory Community.")


def configure_identity_provider(identity: str | None = None) -> IdentityProvider:
    global _provider, _provider_identity
    selected = normalize_identity(identity or settings.kmv_identity)
    _provider = create_identity_provider(selected)
    _provider_identity = selected
    return _provider


def reset_identity_provider() -> None:
    global _provider, _provider_identity
    _provider = None
    _provider_identity = None


def get_identity_provider() -> IdentityProvider:
    selected = normalize_identity(settings.kmv_identity)
    if _provider is None or _provider_identity != selected:
        return configure_identity_provider(selected)
    return _provider


__all__ = [
    "IdentityProvider",
    "LocalSingleUserIDP",
    "configure_identity_provider",
    "create_identity_provider",
    "get_identity_provider",
    "reset_identity_provider",
]
