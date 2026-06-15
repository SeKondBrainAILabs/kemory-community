"""Identity-provider adapter interface for Kemory auth."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.auth_service import AuthContext


class IdentityProvider(ABC):
    """Pluggable auth backend for hosted and community identity modes."""

    @abstractmethod
    async def verify_bearer(self, token: str) -> AuthContext | None:
        """Validate a Bearer token and return an auth context when accepted."""

    @abstractmethod
    async def verify_api_key(self, api_key: str, db: AsyncSession | None = None) -> AuthContext | None:
        """Validate an API key and return an auth context when accepted."""

    @abstractmethod
    async def resolve_org(self, user_id: UUID) -> UUID | str:
        """Resolve the org bound to a user for this provider."""
