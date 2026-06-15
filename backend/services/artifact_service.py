"""
Kemory — unified Artifact service (project files — v3.35.0).

Handles the full lifecycle for namespace-level and memory-level artifacts:
upload, list, get, delete, and signed-blob-URL generation.

Chat-turn artifacts created via ``POST /api/v1/chats/{id}/artifacts/upload``
are NOT managed here; they remain in ``ai_chats.py`` for back-compat.  This
service covers:

  * ``POST /api/v1/artifacts/upload``
  * ``GET  /api/v1/namespaces/{namespace}/artifacts``
  * ``GET  /api/v1/memories/{memory_id}/artifacts``
  * ``POST /api/v1/memories/{memory_id}/artifacts/upload``
  * ``GET  /api/v1/artifacts/{artifact_id}``
  * ``GET  /api/v1/artifacts/{artifact_id}/blob``
  * ``DELETE /api/v1/artifacts/{artifact_id}``

Storage is delegated to :mod:`backend.services.artifact_storage` (minio or
core_backend depending on ``KEMORY_ARTIFACT_BACKEND`` env var).
"""

from __future__ import annotations

import mimetypes
import uuid
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.ai_chat import AIChatArtifact
from backend.services.ai_chat_service import ArtifactResponse, _artifact_to_response
from backend.services.artifact_storage import (
    delete_artifact,
    put_artifact,
)
from backend.services.namespace_resolver import resolve_artifact_namespace

logger = structlog.get_logger(__name__)

# ─── Content-type → artifact_type mapping ───────────────────────────

_VALID_ARTIFACT_TYPES = frozenset({"code", "image", "file", "react", "html", "svg", "audio", "video"})


def _infer_artifact_type(mimetype: str | None, filename: str | None) -> str:
    """Derive artifact_type from MIME type, falling back to 'file'."""
    if not mimetype:
        if filename:
            guessed, _ = mimetypes.guess_type(filename)
            mimetype = guessed or ""
        else:
            return "file"

    m = mimetype.lower()
    if m.startswith("image/svg"):
        return "svg"
    if m.startswith("image/"):
        return "image"
    if m.startswith("audio/"):
        return "audio"
    if m.startswith("video/"):
        return "video"
    if m in {"text/html", "application/xhtml+xml"}:
        return "html"
    if m.startswith("text/") or m in {"application/json", "application/xml"}:
        return "code"
    return "file"


# ─── Upload ─────────────────────────────────────────────────────────


async def upload_artifact(
    *,
    user_id: uuid.UUID,
    org_id: str,
    data: bytes,
    filename: str | None,
    content_type: str | None,
    # Namespace resolution inputs — pass at least one of these groups.
    namespace: str | None = None,
    platform: str | None = None,
    source_project_id: str | None = None,
    source_project_name: str | None = None,
    # Optional parent references.
    memory_id: uuid.UUID | None = None,
    # Caller-supplied type override; inferred from MIME if not given.
    artifact_type: str | None = None,
    language: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
    db: AsyncSession,
) -> ArtifactResponse:
    """Upload a binary artifact and create the DB row.

    Namespace is resolved in this priority order:
      1. ``namespace`` explicitly provided.
      2. ``memory_id`` provided → resolve namespace from the parent memory row.
      3. ``platform`` + optional ``source_project_id`` / ``source_project_name``
         → namespace_resolver lookup / derivation.
      4. Fallback: ``"shared"``.
    """
    if not data:
        raise ValueError("Empty upload body.")

    # ── Resolve namespace ────────────────────────────────────────────
    effective_namespace: str
    if namespace:
        effective_namespace = namespace.strip()
    elif memory_id:
        # Resolve namespace from the memory row.
        from backend.models.memory import Memory

        mem = (
            await db.execute(
                select(Memory).where(
                    Memory.memory_id == memory_id,
                    Memory.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if mem is None:
            raise ValueError(f"Memory {memory_id} not found.")
        effective_namespace = mem.namespace
    else:
        effective_namespace = await resolve_artifact_namespace(
            user_id=user_id,
            namespace=None,
            platform=platform,
            source_project_id=source_project_id,
            source_project_name=source_project_name,
            db=db,
        )

    artifact_id = uuid.uuid4()
    inferred_type = artifact_type or _infer_artifact_type(content_type, filename)

    # ── Store binary body ────────────────────────────────────────────
    try:
        put_result = put_artifact(
            org_id=org_id,
            user_id=user_id,
            # chat_id is repurposed as artifact parent path in minio; use
            # the namespace slug since there is no chat.
            chat_id=effective_namespace,
            artifact_id=artifact_id,
            data=data,
            filename=filename,
            mimetype=content_type,
        )
    except Exception as exc:
        logger.error(
            "artifact_service.upload_failed",
            artifact_id=str(artifact_id),
            error=str(exc),
        )
        raise RuntimeError(f"Object storage write failed: {exc}") from exc

    # ── Build metadata ───────────────────────────────────────────────
    meta: dict[str, Any] = {
        **(extra_metadata or {}),
        "filename": filename or (extra_metadata or {}).get("filename"),
        "mimetype": put_result.mimetype,
        "size_bytes": put_result.size_bytes,
        "storage_bucket": put_result.bucket,
        "storage_key": put_result.key,
    }

    # ── Create DB row ────────────────────────────────────────────────
    row = AIChatArtifact(
        artifact_id=artifact_id,
        turn_id=None,
        chat_id=None,
        user_id=user_id,
        org_id=org_id,
        namespace=effective_namespace,
        memory_id=memory_id,
        source_project_id=source_project_id,
        source_project_name=source_project_name,
        source_platform=platform,
        artifact_type=inferred_type,
        language=language,
        content=None,
        content_url=None,
        content_sha256=put_result.sha256,
        artifact_metadata=meta,
    )
    db.add(row)
    await db.flush()

    logger.info(
        "artifact_service.uploaded",
        artifact_id=str(artifact_id),
        namespace=effective_namespace,
        size_bytes=put_result.size_bytes,
        artifact_type=inferred_type,
    )
    return _artifact_to_response(row)


# ─── List ────────────────────────────────────────────────────────────


async def list_namespace_artifacts(
    user_id: uuid.UUID,
    namespace: str,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = None,
) -> tuple[list[ArtifactResponse], int]:
    """Return artifacts belonging to ``namespace``, newest first."""
    base = (
        select(AIChatArtifact)
        .where(
            AIChatArtifact.user_id == user_id,
            AIChatArtifact.namespace == namespace,
        )
        .order_by(AIChatArtifact.created_at.desc())
    )
    total = (
        await db.execute(
            select(func.count()).select_from(
                select(AIChatArtifact)
                .where(
                    AIChatArtifact.user_id == user_id,
                    AIChatArtifact.namespace == namespace,
                )
                .subquery()
            )
        )
    ).scalar() or 0

    rows = (await db.execute(base.limit(limit).offset(offset))).scalars().all()
    return [_artifact_to_response(r) for r in rows], int(total)


async def list_memory_artifacts(
    user_id: uuid.UUID,
    memory_id: uuid.UUID,
    db: AsyncSession,
) -> list[ArtifactResponse]:
    """Return all artifacts attached to ``memory_id``."""
    rows = (
        (
            await db.execute(
                select(AIChatArtifact)
                .where(
                    AIChatArtifact.user_id == user_id,
                    AIChatArtifact.memory_id == memory_id,
                )
                .order_by(AIChatArtifact.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    return [_artifact_to_response(r) for r in rows]


# ─── Get single ─────────────────────────────────────────────────────


async def get_artifact_response(
    user_id: uuid.UUID,
    artifact_id: uuid.UUID,
    db: AsyncSession,
) -> ArtifactResponse | None:
    """Fetch a single artifact by id, scoped to the caller's user_id."""
    row = (
        await db.execute(
            select(AIChatArtifact).where(
                AIChatArtifact.artifact_id == artifact_id,
                AIChatArtifact.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return _artifact_to_response(row)


# ─── Delete ──────────────────────────────────────────────────────────


async def delete_artifact_row(
    user_id: uuid.UUID,
    artifact_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    """Delete the artifact row and its stored blob.

    Returns True if the row existed and was deleted, False if not found.
    """
    row = (
        await db.execute(
            select(AIChatArtifact).where(
                AIChatArtifact.artifact_id == artifact_id,
                AIChatArtifact.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False

    # Delete the blob from object storage (best-effort; row is deleted
    # even if storage deletion fails so the DB doesn't retain stale refs).
    meta = row.artifact_metadata or {}
    if isinstance(meta, dict):
        storage_key = meta.get("storage_key")
        storage_bucket = meta.get("storage_bucket")
    else:
        storage_key = storage_bucket = None
    if storage_key:
        try:
            delete_artifact(bucket=storage_bucket, key=storage_key, user_id=row.user_id, org_id=row.org_id)
        except Exception as exc:
            logger.warning(
                "artifact_service.storage_delete_failed",
                artifact_id=str(artifact_id),
                error=str(exc),
            )

    await db.delete(row)
    await db.flush()
    logger.info("artifact_service.deleted", artifact_id=str(artifact_id))
    return True


# ─── Blob streaming helper ───────────────────────────────────────────


async def get_artifact_row(
    user_id: uuid.UUID,
    artifact_id: uuid.UUID,
    db: AsyncSession,
) -> AIChatArtifact | None:
    """Raw row lookup — used by the blob endpoint for streaming."""
    return (
        await db.execute(
            select(AIChatArtifact).where(
                AIChatArtifact.artifact_id == artifact_id,
                AIChatArtifact.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
