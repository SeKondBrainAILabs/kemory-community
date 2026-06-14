"""Blob storage adapter contract for artifact bodies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import IO
from uuid import UUID


@dataclass(frozen=True)
class BlobMetadata:
    bucket: str
    key: str
    size_bytes: int
    content_type: str
    sha256: str


@dataclass(frozen=True)
class BlobReadResult:
    bucket: str
    key: str
    size_bytes: int | None
    content_type: str | None
    stream: IO[bytes]


class BlobStore(ABC):
    @abstractmethod
    async def put(
        self,
        *,
        key: str,
        body: bytes | AsyncIterator[bytes],
        content_type: str,
        user_id: UUID,
        org_id: UUID,
    ) -> BlobMetadata: ...

    @abstractmethod
    async def get(
        self,
        *,
        key: str,
        user_id: UUID,
        org_id: UUID,
    ) -> AsyncIterator[bytes]:
        if False:
            yield b""

    @abstractmethod
    async def delete(
        self,
        *,
        key: str,
        user_id: UUID,
        org_id: UUID,
    ) -> None: ...

    @abstractmethod
    def signed_url(
        self,
        *,
        key: str,
        ttl_seconds: int,
        user_id: UUID,
        org_id: UUID,
    ) -> str: ...
