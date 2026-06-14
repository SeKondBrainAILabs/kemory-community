"""Abstract vector-store contract for semantic memory lookup."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from uuid import UUID


@dataclass(frozen=True)
class SearchHit:
    memory_id: UUID
    score: float
    metadata: dict[str, Any]


class VectorStore(ABC):
    @abstractmethod
    async def upsert(
        self,
        *,
        memory_id: UUID,
        namespace: str,
        user_id: UUID,
        org_id: UUID | str,
        embedding: list[float],
        metadata: dict[str, Any],
    ) -> None: ...

    @abstractmethod
    async def search(
        self,
        *,
        namespace: str,
        user_id: UUID,
        org_id: UUID | str,
        query_embedding: list[float],
        limit: int,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchHit]: ...

    @abstractmethod
    async def delete(
        self,
        *,
        memory_id: UUID,
        user_id: UUID,
        org_id: UUID | str,
    ) -> None: ...

    @abstractmethod
    async def healthcheck(self) -> bool: ...
