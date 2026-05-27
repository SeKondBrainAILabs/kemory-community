"""
Kemory — chat artifact storage (chats-v1 file/audio/video, v3.33.0+).

Two responsibilities:

  1. Put / get / delete binary artifact bodies in S3-compatible object
     storage.  Two backends are supported:

     * ``minio`` (default) — Kemory writes directly to its own minio
       bucket (``kemory-chat-artifacts``) using the minio SDK.

     * ``core_backend`` — Kemory delegates all storage operations to
       Core_Backend's tenant storage API (``/storage/*``).  Auth is
       via a long-lived application API key (``X-API-Key: sk-…``)
       minted against the kemory Application in Core_Backend.

       Core_Backend stores each file in a per-org minio bucket named
       ``{STORAGE_BUCKET_PREFIX}-{org_id}`` (default prefix ``tenant``).
       Bucket creation is idempotent — Core_Backend auto-creates it on
       first upload.

       Key encoding in AIChatArtifact.artifact_metadata['storage_key']:
         minio mode  →  plain path  e.g. ``org/user/chat/artifact.mp3``
         core_backend mode  →  ``cb:{core_backend_file_uuid}``

       This lets get_artifact / delete_artifact dispatch correctly for
       both new uploads and legacy minio-stored artifacts without any
       DB migration.

  2. Mint HMAC-signed short-lived URLs that the browser can use directly
     in ``<audio src=…>`` / ``<video src=…>`` / ``<img src=…>`` tags.
     Bearer-token auth doesn't work for these because the browser
     doesn't attach headers to media element fetches. The signed URL
     embeds the signature in the query string; the blob endpoint
     verifies it on read. TTL 1 hour by default.

Config (env):

    KEMORY_ARTIFACT_BACKEND          default 'minio'  ('minio' | 'core_backend')

    For minio backend:
    KEMORY_ARTIFACT_BUCKET           default 'kemory-chat-artifacts'
    KEMORY_ARTIFACT_S3_ENDPOINT      default 'minio:9000'
    KEMORY_ARTIFACT_S3_ACCESS_KEY    default 'minioadmin'
    KEMORY_ARTIFACT_S3_SECRET_KEY    default '' (env required in prod)
    KEMORY_ARTIFACT_S3_SECURE        default 'false' (http inside docker)
    KEMORY_ARTIFACT_SIGNED_URL_TTL   default '3600' (seconds)

    For core_backend backend:
    KEMORY_CORE_BACKEND_URL          default 'http://core_backend:8001'
    KEMORY_CORE_BACKEND_API_KEY      required — sk-… key minted via
                                     POST /api-keys in Core_Backend admin
"""

from __future__ import annotations

import hashlib
import hmac
import io as _io
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

# ── minio backend ──────────────────────────────────────────────────
DEFAULT_BUCKET = _env("KEMORY_ARTIFACT_BUCKET", "kemory-chat-artifacts")
S3_ENDPOINT = _env("KEMORY_ARTIFACT_S3_ENDPOINT", "minio:9000")
S3_ACCESS_KEY = _env("KEMORY_ARTIFACT_S3_ACCESS_KEY", "minioadmin")
# Defaults to the shared-infra dev secret. Override in prod via env.
S3_SECRET_KEY = _env("KEMORY_ARTIFACT_S3_SECRET_KEY", "sharedinfra_minio_2026")
S3_SECURE = _env("KEMORY_ARTIFACT_S3_SECURE", "false").lower() in {"true", "1", "yes"}
SIGNED_URL_TTL_SECONDS = int(_env("KEMORY_ARTIFACT_SIGNED_URL_TTL", "3600"))

# ── core_backend backend ───────────────────────────────────────────
CORE_BACKEND_URL = _env("KEMORY_CORE_BACKEND_URL", "http://core_backend:8001")
# API key for the kemory Application in Core_Backend (sk-… format).
# Must be minted once via POST /api-keys in Core_Backend admin.
CORE_BACKEND_API_KEY = os.environ.get("KEMORY_CORE_BACKEND_API_KEY", "").strip()

# Prefix used in AIChatArtifact.storage_key to identify core_backend-stored
# artifacts.  Value: "cb:{core_backend_file_uuid}".
_CB_KEY_PREFIX = "cb:"


def _core_backend_headers() -> dict[str, str]:
    """Build auth headers for Core_Backend storage API calls."""
    if not CORE_BACKEND_API_KEY:
        raise RuntimeError(
            "KEMORY_CORE_BACKEND_API_KEY is not set. "
            "Create an API key in Core_Backend (POST /api-keys) and set this env var."
        )
    return {"X-API-Key": CORE_BACKEND_API_KEY}


# ─── Signing helpers (HMAC-SHA256 over canonical token) ─────────────


def _signing_key() -> bytes:
    """Reuse JWT_SECRET_KEY so we don't introduce a second long-lived secret."""
    from backend.config.settings import settings

    return (
        settings.jwt_secret_key.encode("utf-8")
        if isinstance(settings.jwt_secret_key, str)
        else bytes(settings.jwt_secret_key)
    )


def make_signed_token(chat_id: str, artifact_id: str, expires_at: int) -> str:
    """HMAC-SHA256 over ``chat_id|artifact_id|exp``. Stable, URL-safe."""
    payload = f"{chat_id}|{artifact_id}|{expires_at}".encode()
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

    For namespace-level / memory-level artifacts (no chat_id) use
    :func:`build_artifact_blob_url` instead.
    """
    chat_id = str(chat_id)
    artifact_id = str(artifact_id)
    ttl = ttl_seconds if ttl_seconds is not None else SIGNED_URL_TTL_SECONDS
    exp = int(time.time()) + ttl
    sig = make_signed_token(chat_id, artifact_id, exp)
    return f"/api/v1/chats/{chat_id}/artifacts/{artifact_id}/blob?exp={exp}&sig={sig}"


# ─── v3.35.0: generic artifact signed URLs (no chat_id required) ────


def _make_artifact_sig(artifact_id: str, expires_at: int) -> str:
    """HMAC-SHA256 over ``artifact_id|exp``."""
    payload = f"{artifact_id}|{expires_at}".encode()
    return hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()


def verify_artifact_sig(artifact_id: str, expires_at: int, sig: str) -> bool:
    """Verify a token minted by :func:`build_artifact_blob_url`."""
    if expires_at < int(time.time()):
        return False
    expected = _make_artifact_sig(artifact_id, expires_at)
    return hmac.compare_digest(expected, sig)


def build_artifact_blob_url(
    artifact_id: str | uuid.UUID,
    ttl_seconds: int | None = None,
) -> str:
    """Return a signed relative URL for ``GET /api/v1/artifacts/{id}/blob``.

    Used for namespace-level and memory-level artifacts that have no
    parent chat.  HMAC payload is ``artifact_id|exp`` (omits chat_id).
    The TTL defaults to the same ``KEMORY_ARTIFACT_SIGNED_URL_TTL`` env
    variable as the chat-artifact path.
    """
    artifact_id = str(artifact_id)
    ttl = ttl_seconds if ttl_seconds is not None else SIGNED_URL_TTL_SECONDS
    exp = int(time.time()) + ttl
    sig = _make_artifact_sig(artifact_id, exp)
    return f"/api/v1/artifacts/{artifact_id}/blob?exp={exp}&sig={sig}"


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
    """Result of a get_object / download call.

    ``stream`` must be closed by the caller.  For minio results also call
    ``stream.release_conn()`` in the finally block.  For core_backend
    results ``stream`` is a ``BytesIO`` — ``close()`` is sufficient.
    """

    bucket: str
    key: str
    size_bytes: int | None
    mimetype: str | None
    stream: IO[bytes]


# ─── Minio client (minio backend) ───────────────────────────────────


_minio_client = None
_minio_lock = threading.Lock()


def _get_minio_client():
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
        # Idempotent bucket bootstrap for the direct minio path.
        try:
            if not client.bucket_exists(DEFAULT_BUCKET):
                client.make_bucket(DEFAULT_BUCKET)
                logger.info("artifact_storage.bucket_created", bucket=DEFAULT_BUCKET)
        except Exception as exc:
            logger.warning("artifact_storage.bucket_check_failed", bucket=DEFAULT_BUCKET, error=str(exc))
        _minio_client = client
        return _minio_client


# ─── Storage-key helpers ────────────────────────────────────────────


def storage_key_for(
    org_id: str,
    user_id: str | uuid.UUID,
    chat_id: str | uuid.UUID,
    artifact_id: str | uuid.UUID,
    filename: str | None = None,
) -> str:
    """Build the canonical minio object key (``minio`` backend only).

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


def _is_core_backend_key(key: str) -> bool:
    """True when ``key`` encodes a Core_Backend file UUID (``cb:{uuid}``)."""
    return key.startswith(_CB_KEY_PREFIX)


def _extract_cb_file_id(key: str) -> str:
    """Strip the ``cb:`` prefix and return the bare Core_Backend file UUID."""
    return key[len(_CB_KEY_PREFIX) :]


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

    Routes to Core_Backend's ``/storage/upload`` endpoint when
    ``KEMORY_ARTIFACT_BACKEND=core_backend``; otherwise writes directly
    to minio.
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
    """Direct minio upload (``minio`` backend)."""
    bucket = bucket or DEFAULT_BUCKET
    key = storage_key_for(org_id, user_id, chat_id, artifact_id, filename)

    if not mimetype:
        guess, _ = mimetypes.guess_type(filename or "")
        mimetype = guess or "application/octet-stream"

    client = _get_minio_client()
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
    """Upload via Core_Backend's tenant storage API (``core_backend`` backend).

    Calls ``POST /storage/upload`` with ``X-API-Key`` auth.  Core_Backend
    stores the file in the per-org minio bucket ``tenant-{org_id}`` (or
    whichever prefix is configured via ``STORAGE_BUCKET_PREFIX``) and
    returns a DB metadata record including a stable file ``id``.

    The returned ``PutResult.key`` is encoded as ``cb:{file_uuid}`` so
    that ``get_artifact`` and ``delete_artifact`` can transparently route
    subsequent reads / deletes through Core_Backend's HTTP API rather
    than hitting minio directly.

    Response shape (Core_Backend Development branch):
        {
          "id": "uuid",
          "storage_key": "uploads/{hex}-{filename}",
          "storage_bucket": "tenant-{org_id}",
          "checksum": "<sha256>",
          "mime_type": "...",
          "size_bytes": 12345,
          ...
        }
    """
    import httpx

    if not mimetype:
        guess, _ = mimetypes.guess_type(filename or "")
        mimetype = guess or "application/octet-stream"

    safe_name = filename or "artifact"
    upload_url = f"{CORE_BACKEND_URL.rstrip('/')}/storage/upload"

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                upload_url,
                files={"file": (safe_name, _io.BytesIO(data), mimetype)},
                headers=_core_backend_headers(),
            )
        resp.raise_for_status()
        result = resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "artifact_storage.core_backend_upload_failed",
            status=exc.response.status_code,
            body=exc.response.text[:200],
        )
        raise RuntimeError(
            f"Core_Backend upload failed: HTTP {exc.response.status_code} — {exc.response.text[:120]}"
        ) from exc
    except Exception as exc:
        logger.error("artifact_storage.core_backend_upload_error", error=str(exc))
        raise RuntimeError(f"Core_Backend upload error: {exc}") from exc

    file_id = result.get("id")
    if not file_id:
        raise RuntimeError(f"Core_Backend /storage/upload returned no id: {result}")

    # Prefer the checksum Core_Backend computed; fall back to local.
    sha = result.get("checksum") or hashlib.sha256(data).hexdigest()

    logger.info(
        "artifact_storage.core_backend_upload_ok",
        file_id=file_id,
        storage_key=result.get("storage_key"),
        storage_bucket=result.get("storage_bucket"),
        size=result.get("size_bytes", len(data)),
    )

    return PutResult(
        # Bucket from core_backend response (e.g. "tenant-{org_id}")
        bucket=result.get("storage_bucket", "core_backend_tenant"),
        # Encode the Core_Backend file UUID so we can route reads/deletes
        # through the HTTP API without touching minio directly.
        key=f"{_CB_KEY_PREFIX}{file_id}",
        size_bytes=result.get("size_bytes", len(data)),
        mimetype=result.get("mime_type", mimetype),
        sha256=sha,
    )


# ─── Read path ──────────────────────────────────────────────────────


def get_artifact(bucket: str | None, key: str) -> GetResult:
    """Open a streaming read against the stored object.

    Dispatches to Core_Backend's ``GET /storage/files/{id}/download``
    when ``key`` starts with ``cb:`` (i.e. was uploaded via the
    core_backend backend).  Falls back to minio SDK for plain keys
    (minio backend, or legacy artifacts uploaded before the switch).
    """
    if _is_core_backend_key(key):
        return _get_via_core_backend(key, bucket)
    return _get_via_minio(bucket, key)


def _get_via_minio(bucket: str | None, key: str) -> GetResult:
    effective_bucket = bucket or DEFAULT_BUCKET
    client = _get_minio_client()
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


def _get_via_core_backend(key: str, bucket: str | None) -> GetResult:
    """Stream artifact bytes from Core_Backend's download endpoint.

    Reads the full body into a BytesIO buffer so the caller gets a
    uniform stream interface.  For artifact sizes in the chat use-case
    (typically <10 MB) this is acceptable; a chunked streaming path
    can be added later if needed.
    """
    import httpx

    file_id = _extract_cb_file_id(key)
    download_url = f"{CORE_BACKEND_URL.rstrip('/')}/storage/files/{file_id}/download"

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.get(download_url, headers=_core_backend_headers())
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "artifact_storage.core_backend_download_failed",
            file_id=file_id,
            status=exc.response.status_code,
        )
        raise RuntimeError(
            f"Core_Backend download failed for file {file_id}: HTTP {exc.response.status_code}"
        ) from exc
    except Exception as exc:
        logger.error("artifact_storage.core_backend_download_error", file_id=file_id, error=str(exc))
        raise RuntimeError(f"Core_Backend download error: {exc}") from exc

    # Content-Disposition carries the original filename but we don't need it here.
    mimetype = resp.headers.get("Content-Type", "application/octet-stream")
    body = resp.content
    size = len(body)

    logger.debug("artifact_storage.core_backend_download_ok", file_id=file_id, size=size)

    return GetResult(
        bucket=bucket or "core_backend_tenant",
        key=key,
        size_bytes=size,
        mimetype=mimetype,
        stream=_io.BytesIO(body),
    )


# ─── Delete path ────────────────────────────────────────────────────


def delete_artifact(bucket: str | None, key: str) -> None:
    """Delete or soft-delete a stored artifact.

    * For ``cb:``-prefixed keys: calls ``DELETE /storage/files/{id}``
      on Core_Backend (soft-delete — DB record marked deleted; lifecycle
      policies on the bucket handle physical cleanup).

    * For plain keys: removes the object directly from minio.

    Both paths are best-effort — errors are logged but not re-raised so
    a failed delete never breaks chat soft-delete on the DB side.
    """
    if _is_core_backend_key(key):
        _delete_via_core_backend(key)
    else:
        _delete_via_minio(bucket, key)


def _delete_via_minio(bucket: str | None, key: str) -> None:
    effective_bucket = bucket or DEFAULT_BUCKET
    try:
        _get_minio_client().remove_object(effective_bucket, key)
    except Exception as exc:
        logger.warning(
            "artifact_storage.minio_delete_failed",
            bucket=effective_bucket,
            key=key,
            error=str(exc),
        )


def _delete_via_core_backend(key: str) -> None:
    import httpx

    file_id = _extract_cb_file_id(key)
    delete_url = f"{CORE_BACKEND_URL.rstrip('/')}/storage/files/{file_id}"

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.delete(delete_url, headers=_core_backend_headers())
        if resp.status_code not in (204, 404):
            logger.warning(
                "artifact_storage.core_backend_delete_unexpected",
                file_id=file_id,
                status=resp.status_code,
            )
        else:
            logger.debug("artifact_storage.core_backend_delete_ok", file_id=file_id)
    except Exception as exc:
        logger.warning(
            "artifact_storage.core_backend_delete_failed",
            file_id=file_id,
            error=str(exc),
        )
