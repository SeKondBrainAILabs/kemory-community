"""MinIO-backed artifact blob store."""

from __future__ import annotations

import hashlib
import io
import mimetypes
import os
import threading
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, cast
from uuid import UUID

import structlog

from backend.adapters.blob_store.base import BlobMetadata, BlobReadResult, BlobStore

logger = structlog.get_logger(__name__)


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


class MinioBlobStore(BlobStore):
    def __init__(
        self,
        *,
        bucket: str | None = None,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool | None = None,
    ) -> None:
        self.bucket = bucket or _env("KEMORY_ARTIFACT_BUCKET", "kemory-chat-artifacts")
        self.endpoint = endpoint or _env("KEMORY_ARTIFACT_S3_ENDPOINT", "minio:9000")
        self.access_key = access_key or _env("KEMORY_ARTIFACT_S3_ACCESS_KEY", "minioadmin")
        self.secret_key = secret_key or _env("KEMORY_ARTIFACT_S3_SECRET_KEY", "sharedinfra_minio_2026")
        self.secure = (
            secure
            if secure is not None
            else _env("KEMORY_ARTIFACT_S3_SECURE", "false").lower() in {"true", "1", "yes"}
        )
        self._client = None
        self._lock = threading.Lock()

    def _get_client(self):
        if self._client is not None:
            return self._client
        with self._lock:
            if self._client is not None:
                return self._client
            from minio import Minio

            client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
            try:
                if not client.bucket_exists(self.bucket):
                    client.make_bucket(self.bucket)
                    logger.info("blob_store.minio.bucket_created", bucket=self.bucket)
            except Exception as exc:
                logger.warning("blob_store.minio.bucket_check_failed", bucket=self.bucket, error=str(exc))
            self._client = client
            return self._client

    async def put(
        self,
        *,
        key: str,
        body: bytes | AsyncIterator[bytes],
        content_type: str,
        user_id: UUID,
        org_id: UUID,
    ) -> BlobMetadata:
        data = await _coerce_bytes(body)
        return self.put_bytes(key=key, data=data, content_type=content_type)

    def put_bytes(self, *, key: str, data: bytes, content_type: str | None) -> BlobMetadata:
        effective_content_type = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
        self._get_client().put_object(
            bucket_name=self.bucket,
            object_name=key,
            data=io.BytesIO(data),
            length=len(data),
            content_type=effective_content_type,
        )
        return BlobMetadata(
            bucket=self.bucket,
            key=key,
            size_bytes=len(data),
            content_type=effective_content_type,
            sha256=hashlib.sha256(data).hexdigest(),
        )

    async def get(
        self,
        *,
        key: str,
        user_id: UUID,
        org_id: UUID,
    ) -> AsyncIterator[bytes]:
        result = self.get_stream(key=key, bucket=None)
        stream = cast(Any, result.stream)
        try:
            for chunk in stream.stream(amt=64 * 1024):
                yield chunk
        finally:
            release_conn = getattr(stream, "release_conn", None)
            if release_conn is not None:
                try:
                    release_conn()
                except Exception:
                    pass
            result.stream.close()

    def get_stream(self, *, key: str, bucket: str | None) -> BlobReadResult:
        effective_bucket = bucket or self.bucket
        response = self._get_client().get_object(effective_bucket, key)
        size = None
        if response.headers and response.headers.get("Content-Length"):
            try:
                size = int(response.headers["Content-Length"])
            except (TypeError, ValueError):
                size = None
        content_type = response.headers.get("Content-Type") if response.headers else None
        return BlobReadResult(
            bucket=effective_bucket,
            key=key,
            size_bytes=size,
            content_type=content_type,
            stream=response,
        )

    async def delete(
        self,
        *,
        key: str,
        user_id: UUID,
        org_id: UUID,
    ) -> None:
        self.delete_key(key=key, bucket=None)

    def delete_key(self, *, key: str, bucket: str | None) -> None:
        effective_bucket = bucket or self.bucket
        self._get_client().remove_object(effective_bucket, key)

    def signed_url(
        self,
        *,
        key: str,
        ttl_seconds: int,
        user_id: UUID,
        org_id: UUID,
    ) -> str:
        return self._get_client().presigned_get_object(self.bucket, key, expires=timedelta(seconds=ttl_seconds))


async def _coerce_bytes(body: bytes | AsyncIterator[bytes]) -> bytes:
    if isinstance(body, bytes):
        return body
    chunks: list[bytes] = []
    async for chunk in body:
        chunks.append(chunk)
    return b"".join(chunks)
