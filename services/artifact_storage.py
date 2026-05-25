"""
Kemory — chat artifact storage (chats-v1 file/audio/video, v3.33.0).

Two responsibilities:

  1. Put / get / delete binary artifact bodies in S3-compatible object
     storage.  Two backends are supported:

     * ``minio`` (default) — Kemory writes directly to its own minio
       bucket (``kemory-chat-artifacts``) using the minio SDK.

     * ``core_backend`` — Kemory delegates uploads to Core_Backend's
       ``POST /upload`` public endpoint (no auth required; same minio
       instance, ``core-backend`` bucket).  Reads and deletes still go
       via minio SDK using shared credentials because Core_Backend has
       no download or delete HTTP endpoints.

  2. Mint HMAC-signed short-lived URLs that the browser can use directly
     in ``<audio src=…>`` / ``<video src=…>`` / ``<img src=…>`` tags.
     Bearer-token auth doesn't work for these because the browser
     doesn't attach headers to media element fetches. The signed URL
     embeds the signature in the query string; the blob endpoint
     verifies it on read. TTL 1 hour by default.

Storage layout:

  minio mode:
    kemory-chat-artifacts / {org_id}/{user_id}/{chat_id}/{artifact_id}{ext}

  core_backend mode:
    core-backend / uploads/{uuid}-{filename}  (key returned by Core_Backend)

Config (env):

    KEMORY_ARTIFACT_BACKEND          default 'minio'  ('minio' | 'core_backend')
    KEMORY_CORE_BACKEND_URL          default 'http://core-backend:8001'

    For minio backend:
    KEMORY_ARTIFACT_BUCKET           default 'kemory-chat-artifacts'
    KEMORY_ARTIFACT_S3_ENDPOINT      default 'minio:9000'
    KEMORY_ARTIFACT_S3_ACCESS_KEY    default 'minioadmin'
    KEMORY_ARTIFACT_S3_SECRET_KEY    default '' (env required in prod)
    KEMORY_ARTIFACT_S3_SECURE        default 'false' (http inside docker)
    KEMORY_ARTIFACT_SIGNED_URL_TTL   default '3600' (seconds)

    For core_backend backend the same minio env vars are used for the
    read/delete path (same shared-infra minio, different bucket).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import mimetypes
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import IO

import structlog

logger = structlog.get_logger(__name__)


# ─── Config ─────────────────────────────────────────────────────────


def _env(name: str, default: str) -> str:
    v = os.environ.get(name, "").strip()
    return v if v else default


ARTIFACT_BACKEND = _env("KEMORY_ARTIFACT_BACKEND", "minio")
CORE_BACKEND_URL = _env("KEMORY_CORE_BACKEND_URL", "http://core_backend:8001")

DEFAULT_BUCKET = _env("KEMORY_ARTIFACT_BUCKET", "kemory-chat-artifacts")
# The core-backend bucket name — must match MINIO_BUCKET in Core_Backend's env.
CORE_BACKEND_BUCKET = _env("KEMORY_CORE_BACKEND_BUCKET", "core-backend")

S3_ENDPOINT = _env("KEMORY_ARTIFACT_S3_ENDPOINT", "minio:9000")
S3_ACCESS_KEY = _env("KEMORY_ARTIFACT_S3_ACCESS_KEY", "minioadmin")
# Defaults to the shared-infra dev secret. Override in prod via env.
S3_SECRET_KEY = _env("KEMORY_ARTIFACT_S3_SECRET_KEY", "sharedinfra_minio_2026")
S3_SECURE = _env("KEMORY_ARTIFACT_S3_SECURE", "false").lower() in {"true", "1", "yes"}
SIGNED_URL_TTL_SECONDS = int(_env("KEMORY_ARTIFACT_SIGNED_URL_TTL", "3600"))


# ─── Signing helpers (HMAC-SHA256 over canonical token) ─────────────


def _signing_key() -> bytes:
    """Reuse JWT_SECRET_KEY so we don't introduce a second long-lived secret."""
    from backend.config.settings import settings

    return settings.jwt_secret_key.encode("utf-8") if isinstance(
        settings.jwt_secret_key, str
    ) else bytes(settings.jwt_secret_key)


def make_signed_token(chat_id: str, artifact_id: str, expires_at: int) -> str:
    """HMAC-SHA256 over ``chat_id|artifact_id|exp``. Stable, URL-safe."""
    payload = f"{chat_id}|{artifact_id}|{expires_at}".encode("utf-8")
    sig = hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()
    return sig


def verify_signed_token(chat_id: str, artifact_id: str, expires_at: int, sig: str) -> bool:
    if expires_at < int(time.time()):
        return False
    expected = make_signed_token(chat_id, artifact_id, expires_at)
    # Constant-time compare to avoid timing leaks.
    return hmac.compare_digest(expected, sig)


def build_signed_blob_url(
    chat_id: str | uuid.UUID,
    artifact_id: str | uuid.UUID,
    ttl_seconds: int | None = None,
) -> str:
    """Return a relative API URL the dashboard / browser can use directly.

    Relative on purpose — the dashboard is served from the same host as
    the API (via Caddy `*.memory.dxb-gw.basanti.ai`), and using a
    relative URL means the browser inherits the page's origin without
    us needing to know the public hostname at server-render time.
    """
    chat_id = str(chat_id)
    artifact_id = str(artifact_id)
    ttl = ttl_seconds if ttl_seconds is not None else SIGNED_URL_TTL_SECONDS
    exp = int(time.time()) + ttl
    sig = make_signed_token(chat_id, artifact_id, exp)
    return f"/api/v1/chats/{chat_id}/artifacts/{artifact_id}/blob?exp={exp}&sig={sig}"


# ─── Data classes ────────────────────────────────────────────────────


@dataclass
class PutResult:
    bucket: str
    key: str
    size_bytes: int
    mimetype: str
    sha256: str


@dataclass
class GetResult:
    """Result of a get_object. ``stream`` is a chunked iterator that
    callers MUST close (use as a context manager or call ``release_conn``
    in the finally block — see ``stream_artifact`` in the route handler
    for the pattern)."""

    bucket: str
    key: str
    size_bytes: int | None
    mimetype: str | None
    stream: IO[bytes]


# ─── Minio client (shared for both backends on read/delete) ──────────


_minio_client = None
_minio_lock = threading.Lock()


def _get_client():
    """Lazy singleton — defer import + connection until first use so the
    rest of the app keeps booting when minio isn't reachable in dev."""
    global _minio_client
    if _minio_client is not None:
        return _minio_client
    with _minio_lock:
        if _minio_client is not None:
            return _minio_client
        from minio import Minio

        client = Minio(
            S3_ENDPOINT,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
            secure=S3_SECURE,
        )
        # Idempotent bucket bootstrap for each backend.
        for bucket in _buckets_to_ensure():
            try:
                if not client.bucket_exists(bucket):
                    client.make_bucket(bucket)
                    logger.info("artifact_storage.bucket_created", bucket=bucket)
            except Exception as exc:
                # Don't crash the process — next put_object call will
                # surface the real error.
                logger.warning("artifact_storage.bucket_check_failed", bucket=bucket, error=str(exc))
        _minio_client = client
        return _minio_client


def _buckets_to_ensure() -> list[str]:
    """Which minio buckets to auto-create on startup."""
    if ARTIFACT_BACKEND == "core_backend":
        # Kemory only reads/deletes from core-backend bucket; Core_Backend
        # creates its own bucket on first use, but it may not have run yet.
        # Ensure it exists so reads don't 404.
        return [CORE_BACKEND_BUCKET]
    return [DEFAULT_BUCKET]


# ─── Storage-key helpers ────────────────────────────────────────────


def storage_key_for(
    org_id: str,
    user_id: str | uuid.UUID,
    chat_id: str | uuid.UUID,
    artifact_id: str | uuid.UUID,
    filename: str | None = None,
) -> str:
    """Build the canonical minio object key (used by ``minio`` backend).

    Including an extension when we have one helps browsers + minio infer
    content type when serving direct URLs, even though we still set
    Content-Type explicitly.
    """
    ext = ""
    if filename:
        idx = filename.rfind(".")
        if 0 <= idx < len(filename) - 1:
            ext = filename[idx:].lower()
    safe_org = (org_id or "no-org").replace("/", "_")
    return f"{safe_org}/{user_id}/{chat_id}/{artifact_id}{ext}"


# ─── Write path ─────────────────────────────────────────────────────


def put_artifact(
    org_id: str,
    user_id: str | uuid.UUID,
    chat_id: str | uuid.UUID,
    artifact_id: str | uuid.UUID,
    *,
    data: bytes,
    filename: str | None,
    mimetype: str | None,
    bucket: str | None = None,
) -> PutResult:
    """Upload bytes to object storage.

    Delegates to Core_Backend's ``POST /upload`` when
    ``KEMORY_ARTIFACT_BACKEND=core_backend``; otherwise writes directly
    to minio.

    Returns the storage key + facts the caller persists on the
    AIChatArtifact row.
    """
    if ARTIFACT_BACKEND == "core_backend":
        return _put_via_core_backend(
            data=data,
            filename=filename,
            mimetype=mimetype,
        )
    return _put_via_minio(
        org_id=org_id,
        user_id=user_id,
        chat_id=chat_id,
        artifact_id=artifact_id,
        data=data,
        filename=filename,
        mimetype=mimetype,
        bucket=bucket,
    )


def _put_via_minio(
    org_id: str,
    user_id: str | uuid.UUID,
    chat_id: str | uuid.UUID,
    artifact_id: str | uuid.UUID,
    *,
    data: bytes,
    filename: str | None,
    mimetype: str | None,
    bucket: str | None,
) -> PutResult:
    """Direct minio upload (original behaviour)."""
    bucket = bucket or DEFAULT_BUCKET
    key = storage_key_for(org_id, user_id, chat_id, artifact_id, filename)

    if not mimetype:
        guess, _ = mimetypes.guess_type(filename or "")
        mimetype = guess or "application/octet-stream"

    import io as _io

    client = _get_client()
    client.put_object(
        bucket_name=bucket,
        object_name=key,
        data=_io.BytesIO(data),
        length=len(data),
        content_type=mimetype,
    )

    sha = hashlib.sha256(data).hexdigest()
    return PutResult(
        bucket=bucket,
        key=key,
        size_bytes=len(data),
        mimetype=mimetype,
        sha256=sha,
    )


def _put_via_core_backend(
    *,
    data: bytes,
    filename: str | None,
    mimetype: str | None,
) -> PutResult:
    """Upload via Core_Backend's public POST /upload endpoint.

    Core_Backend's /upload is registered as a public (IP-rate-limited)
    route — no Bearer token required.  It returns::

        {"key": "uploads/{uuid}-{filename}", "url": "http://minio:9000/..."}

    The returned URL is the internal minio address so it is NOT suitable
    for browser use; kemory generates its own signed blob URL instead and
    stores the key so it can stream the object directly from minio.
    """
    import io as _io

    import httpx

    if not mimetype:
        guess, _ = mimetypes.guess_type(filename or "")
        mimetype = guess or "application/octet-stream"

    safe_name = filename or "artifact"

    # Ensure the core-backend bucket exists before delegating. Core_Backend
    # does NOT auto-create it; if it doesn't exist the POST /upload returns
    # 500. Calling _get_client() here triggers our idempotent bucket bootstrap.
    _get_client()

    upload_url = f"{CORE_BACKEND_URL.rstrip('/')}/upload"
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                upload_url,
                files={"file": (safe_name, _io.BytesIO(data), mimetype)},
                data={"prefix": "uploads/"},
            )
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "artifact_storage.core_backend_upload_failed",
            status=exc.response.status_code,
            body=exc.response.text[:200],
        )
        raise RuntimeError(f"Core_Backend upload failed: HTTP {exc.response.status_code}") from exc
    except Exception as exc:
        logger.error("artifact_storage.core_backend_upload_error", error=str(exc))
        raise RuntimeError(f"Core_Backend upload error: {exc}") from exc

    key = result.get("key")
    if not key:
        raise RuntimeError(f"Core_Backend /upload returned no key: {result}")

    sha = hashlib.sha256(data).hexdigest()
    logger.info(
        "artifact_storage.core_backend_upload_ok",
        key=key,
        size=len(data),
    )
    return PutResult(
        bucket=CORE_BACKEND_BUCKET,
        key=key,
        size_bytes=len(data),
        mimetype=mimetype,
        sha256=sha,
    )


# ─── Read path ──────────────────────────────────────────────────────


def get_artifact(bucket: str | None, key: str) -> GetResult:
    """Open a streaming read against the stored object.

    Works for both backends — both store on the shared minio instance so
    we always read via the minio SDK using the ``bucket`` stored on the
    AIChatArtifact row.

    Caller is responsible for closing the underlying response (use
    try/finally with ``stream.close()`` + ``stream.release_conn()``).
    """
    effective_bucket = bucket or (CORE_BACKEND_BUCKET if ARTIFACT_BACKEND == "core_backend" else DEFAULT_BUCKET)
    client = _get_client()
    response = client.get_object(effective_bucket, key)
    size = None
    if response.headers and response.headers.get("Content-Length"):
        try:
            size = int(response.headers["Content-Length"])
        except (TypeError, ValueError):
            size = None
    mimetype = response.headers.get("Content-Type") if response.headers else None
    return GetResult(
        bucket=effective_bucket,
        key=key,
        size_bytes=size,
        mimetype=mimetype,
        stream=response,
    )


# ─── Delete path ────────────────────────────────────────────────────


def delete_artifact(bucket: str | None, key: str) -> None:
    """Best-effort deletion via minio SDK (Core_Backend has no delete endpoint).

    Swallows errors — orphan blobs are tolerable (not user-visible), but a
    delete that breaks chat soft-delete on the DB side would be a
    regression.
    """
    effective_bucket = bucket or (CORE_BACKEND_BUCKET if ARTIFACT_BACKEND == "core_backend" else DEFAULT_BUCKET)
    try:
        _get_client().remove_object(effective_bucket, key)
    except Exception as exc:
        logger.warning(
            "artifact_storage.delete_failed",
            bucket=effective_bucket,
            key=key,
            error=str(exc),
        )
