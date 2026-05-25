"""
Kemory — chat artifact storage (chats-v1 file/audio/video, v3.33.0).

Two responsibilities:

  1. Put / get / delete binary artifact bodies in S3-compatible object
     storage (default: the shared-infra ``minio`` instance, bucket
     ``kemory-chat-artifacts``). Wraps the minio SDK behind a small
     async-friendly facade so swapping to true S3 later is a config
     change, not a refactor.

  2. Mint HMAC-signed short-lived URLs that the browser can use directly
     in ``<audio src=…>`` / ``<video src=…>`` / ``<img src=…>`` tags.
     Bearer-token auth doesn't work for these because the browser
     doesn't attach headers to media element fetches. The signed URL
     embeds the signature in the query string; the blob endpoint
     verifies it on read. TTL 1 hour by default.

Storage layout in minio:

    kemory-chat-artifacts/{org_id}/{user_id}/{chat_id}/{artifact_id}{ext}

The object key is the only thing persisted on the AIChatArtifact row
(stored inside ``artifact_metadata['storage_key']``). Browser URLs are
generated on-the-fly when building the ArtifactResponse so they always
carry a fresh expiry — never persisted, never stale.

Config (env):

    KEMORY_ARTIFACT_BUCKET           default 'kemory-chat-artifacts'
    KEMORY_ARTIFACT_S3_ENDPOINT      default 'minio:9000'  (in-network)
    KEMORY_ARTIFACT_S3_ACCESS_KEY    default 'minioadmin'
    KEMORY_ARTIFACT_S3_SECRET_KEY    default '' (env required in prod)
    KEMORY_ARTIFACT_S3_SECURE        default 'false' (http inside docker)
    KEMORY_ARTIFACT_SIGNED_URL_TTL   default '3600' (seconds)
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


DEFAULT_BUCKET = _env("KEMORY_ARTIFACT_BUCKET", "kemory-chat-artifacts")
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


# ─── Object storage facade (minio SDK under the hood) ───────────────


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
        # Idempotent bucket bootstrap. Cheap once per process.
        try:
            if not client.bucket_exists(DEFAULT_BUCKET):
                client.make_bucket(DEFAULT_BUCKET)
                logger.info("artifact_storage.bucket_created", bucket=DEFAULT_BUCKET)
        except Exception as exc:
            # Don't crash the process if bucket creation fails (e.g.
            # minio temporarily unreachable on startup). The next
            # put_object call will surface the real error.
            logger.warning("artifact_storage.bucket_check_failed", error=str(exc))
        _minio_client = client
        return _minio_client


def storage_key_for(
    org_id: str,
    user_id: str | uuid.UUID,
    chat_id: str | uuid.UUID,
    artifact_id: str | uuid.UUID,
    filename: str | None = None,
) -> str:
    """Build the canonical minio object key. Including an extension when
    we have one helps browsers + minio infer content type when serving
    direct URLs, even though we still set Content-Type explicitly."""
    ext = ""
    if filename:
        # mimetypes.guess_extension is what we use elsewhere; here we
        # just lift the literal extension off the filename.
        idx = filename.rfind(".")
        if 0 <= idx < len(filename) - 1:
            ext = filename[idx:].lower()
    safe_org = (org_id or "no-org").replace("/", "_")
    return f"{safe_org}/{user_id}/{chat_id}/{artifact_id}{ext}"


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
    """Upload bytes to object storage. Returns the storage key + facts
    the caller persists on the AIChatArtifact row.

    The whole-buffer signature is fine for the chat artifact path —
    the multipart-form middleware has already read the request body
    into memory before we get here, and the upper bound is well under
    a worker process's resident set. A future streaming upload path
    would call ``put_object`` directly with a chunked iterator.
    """
    bucket = bucket or DEFAULT_BUCKET
    key = storage_key_for(org_id, user_id, chat_id, artifact_id, filename)

    # Guess MIME type from filename if not provided. Falls back to
    # application/octet-stream — browsers render that as a download link.
    if not mimetype:
        guess, _ = mimetypes.guess_type(filename or "")
        mimetype = guess or "application/octet-stream"

    # Use a BytesIO so the minio SDK can read in chunks. length= is
    # required; pre-compute it from len(data).
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


def get_artifact(bucket: str | None, key: str) -> GetResult:
    """Open a streaming read against the stored object. Caller is
    responsible for closing the underlying response (use try/finally with
    ``stream.close()`` + ``stream.release_conn()``; FastAPI's
    ``StreamingResponse(..., background=...)`` is a clean pattern)."""
    bucket = bucket or DEFAULT_BUCKET
    client = _get_client()
    response = client.get_object(bucket, key)
    # minio's urllib3 response carries headers we can read for size +
    # content-type. Both are nullable on edge cases.
    size = None
    if response.headers and response.headers.get("Content-Length"):
        try:
            size = int(response.headers["Content-Length"])
        except (TypeError, ValueError):
            size = None
    mimetype = response.headers.get("Content-Type") if response.headers else None
    return GetResult(
        bucket=bucket,
        key=key,
        size_bytes=size,
        mimetype=mimetype,
        stream=response,
    )


def delete_artifact(bucket: str | None, key: str) -> None:
    """Best-effort deletion. Swallows errors — orphan blobs are tolerable
    (they're not user-visible), but a delete that breaks chat
    soft-delete on the DB side would be a regression."""
    bucket = bucket or DEFAULT_BUCKET
    try:
        _get_client().remove_object(bucket, key)
    except Exception as exc:
        logger.warning("artifact_storage.delete_failed", bucket=bucket, key=key, error=str(exc))
