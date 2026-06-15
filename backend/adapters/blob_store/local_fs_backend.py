"""Local filesystem blob store for community deployments."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from uuid import UUID

from backend.adapters.blob_store.base import BlobMetadata, BlobReadResult, BlobStore


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value if value else default


class LocalFSBlobStore(BlobStore):
    bucket = "local_fs"

    def __init__(
        self,
        *,
        root: Path | str | None = None,
        signing_key: str | None = None,
        public_base_url: str | None = None,
        max_file_mb: int | None = None,
        max_total_gb: int | None = None,
    ) -> None:
        self.root = Path(root or _env("KMV_BLOB_LOCAL_ROOT", "~/.kemory-community/artifacts")).expanduser()
        self.signing_key = signing_key or os.environ.get("KEMORY_LOCAL_BLOB_SIGNING_KEY", "").strip()
        self.public_base_url = (public_base_url or _env("API_PUBLIC_URL", "http://localhost:8100")).rstrip(
            "/"
        )
        self.max_file_bytes = (max_file_mb or int(_env("KMV_BLOB_MAX_FILE_MB", "100"))) * 1024 * 1024
        self.max_total_bytes = (max_total_gb or int(_env("KMV_BLOB_MAX_TOTAL_GB", "5"))) * 1024 * 1024 * 1024
        self.root.mkdir(parents=True, exist_ok=True)
        if not self.signing_key:
            raise RuntimeError("KEMORY_LOCAL_BLOB_SIGNING_KEY is required for KMV_BLOB_BACKEND=local_fs.")

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
        return self.put_bytes(key=key, data=data, content_type=content_type, user_id=user_id, org_id=org_id)

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str | None,
        user_id: UUID,
        org_id: UUID,
    ) -> BlobMetadata:
        if len(data) > self.max_file_bytes:
            raise ValueError(f"Blob exceeds local_fs file limit of {self.max_file_bytes} bytes.")
        current_total = self._total_size_bytes()
        existing_size = self._existing_size_for_key(key)
        if current_total - existing_size + len(data) > self.max_total_bytes:
            raise ValueError(f"Blob store exceeds local_fs total limit of {self.max_total_bytes} bytes.")

        path = self._path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

        body_sha = hashlib.sha256(data).hexdigest()
        effective_content_type = content_type or "application/octet-stream"
        meta = {
            "key": key,
            "user_id": str(user_id),
            "org_id": str(org_id),
            "content_type": effective_content_type,
            "size_bytes": len(data),
            "sha256": body_sha,
        }
        self._meta_path_for_key(key).write_text(json.dumps(meta, sort_keys=True), encoding="utf-8")
        return BlobMetadata(
            bucket=self.bucket,
            key=key,
            size_bytes=len(data),
            content_type=effective_content_type,
            sha256=body_sha,
        )

    async def get(
        self,
        *,
        key: str,
        user_id: UUID,
        org_id: UUID,
    ) -> AsyncIterator[bytes]:
        result = self.get_stream(key=key, user_id=user_id, org_id=org_id)
        try:
            while chunk := result.stream.read(64 * 1024):
                yield chunk
        finally:
            result.stream.close()

    def get_stream(self, *, key: str, user_id: UUID, org_id: UUID) -> BlobReadResult:
        meta = self._read_meta(key)
        self._assert_owner(meta, user_id=user_id, org_id=org_id)
        path = self._path_for_key(key)
        if not path.exists():
            raise FileNotFoundError(key)
        return BlobReadResult(
            bucket=self.bucket,
            key=key,
            size_bytes=_int_or_none(meta.get("size_bytes")),
            content_type=str(meta.get("content_type") or "application/octet-stream"),
            stream=path.open("rb"),
        )

    async def delete(
        self,
        *,
        key: str,
        user_id: UUID,
        org_id: UUID,
    ) -> None:
        self.delete_key(key=key, user_id=user_id, org_id=org_id)

    def delete_key(self, *, key: str, user_id: UUID, org_id: UUID) -> None:
        meta = self._read_meta(key)
        self._assert_owner(meta, user_id=user_id, org_id=org_id)
        for path in (self._path_for_key(key), self._meta_path_for_key(key)):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def signed_url(
        self,
        *,
        key: str,
        ttl_seconds: int,
        user_id: UUID,
        org_id: UUID,
    ) -> str:
        expiry = int(time.time()) + ttl_seconds
        token = self._encode_token(key=key, user_id=user_id, org_id=org_id, expiry=expiry)
        return f"{self.public_base_url}/artifacts/{token}"

    def stream_from_token(self, token: str) -> BlobReadResult:
        payload = self.verify_token(token)
        if payload is None:
            raise PermissionError("invalid_or_expired_signature")
        return self.get_stream(
            key=str(payload["key"]),
            user_id=UUID(str(payload["user_id"])),
            org_id=UUID(str(payload["org_id"])),
        )

    def verify_token(self, token: str) -> dict[str, Any] | None:
        try:
            raw = json.loads(_b64decode(token))
        except (ValueError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        required = {"key", "user_id", "org_id", "exp", "sig"}
        if not required.issubset(raw):
            return None
        try:
            expiry = int(raw["exp"])
        except (TypeError, ValueError):
            return None
        if expiry < int(time.time()):
            return None
        expected = self._signature(
            key=str(raw["key"]),
            user_id=str(raw["user_id"]),
            org_id=str(raw["org_id"]),
            expiry=expiry,
        )
        if not hmac.compare_digest(expected, str(raw["sig"])):
            return None
        return raw

    def _encode_token(self, *, key: str, user_id: UUID, org_id: UUID, expiry: int) -> str:
        payload: dict[str, str | int] = {
            "key": key,
            "user_id": str(user_id),
            "org_id": str(org_id),
            "exp": expiry,
        }
        payload["sig"] = self._signature(
            key=key,
            user_id=str(user_id),
            org_id=str(org_id),
            expiry=expiry,
        )
        return _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))

    def _signature(self, *, key: str, user_id: str, org_id: str, expiry: int) -> str:
        payload = f"{key}|{user_id}|{org_id}|{expiry}".encode()
        return hmac.new(self.signing_key.encode(), payload, hashlib.sha256).hexdigest()

    def _path_for_key(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / digest[:2] / digest

    def _meta_path_for_key(self, key: str) -> Path:
        return self._path_for_key(key).with_suffix(".json")

    def _read_meta(self, key: str) -> dict[str, Any]:
        path = self._meta_path_for_key(key)
        if not path.exists():
            raise FileNotFoundError(key)
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid blob metadata for {key}.")
        return raw

    def _assert_owner(self, meta: dict[str, Any], *, user_id: UUID, org_id: UUID) -> None:
        if str(meta.get("user_id")) != str(user_id) or str(meta.get("org_id")) != str(org_id):
            raise PermissionError("Blob owner mismatch.")

    def _existing_size_for_key(self, key: str) -> int:
        try:
            meta = self._read_meta(key)
        except FileNotFoundError:
            return 0
        return _int_or_none(meta.get("size_bytes")) or 0

    def _total_size_bytes(self) -> int:
        total = 0
        for path in self.root.glob("*/*"):
            if path.suffix == ".json":
                continue
            if path.is_file():
                total += path.stat().st_size
        return total


async def _coerce_bytes(body: bytes | AsyncIterator[bytes]) -> bytes:
    if isinstance(body, bytes):
        return body
    buffer = io.BytesIO()
    async for chunk in body:
        buffer.write(chunk)
    return buffer.getvalue()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii")).decode("utf-8")


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
