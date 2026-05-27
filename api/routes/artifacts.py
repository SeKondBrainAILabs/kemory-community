"""
Kemory — Artifact routes (project files — v3.35.0).

Generic artifact endpoints for namespace-level and memory-level files.
Chat-turn artifacts have their own upload path at
``POST /api/v1/chats/{id}/artifacts/upload`` in ``ai_chats.py``.

Endpoints (all under ``/api/v1``):
  * POST   /artifacts/upload                  — upload to a namespace or memory
  * GET    /artifacts/{artifact_id}           — get metadata
  * GET    /artifacts/{artifact_id}/blob      — stream binary (signed-URL auth)
  * DELETE /artifacts/{artifact_id}           — delete row + blob
  * GET    /namespaces/{namespace}/artifacts  — list namespace artifacts
  * POST   /memories/{memory_id}/artifacts/upload — upload attached to memory
  * GET    /memories/{memory_id}/artifacts    — list memory artifacts

Auth: all endpoints except ``/blob`` require Bearer or X-API-Key. The blob
endpoint uses HMAC signed-URL auth (no bearer) so ``<img>``, ``<audio>``, and
``<video>`` elements can reference it directly.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.services.artifact_service import (
    delete_artifact_row,
    get_artifact_response,
    get_artifact_row,
    list_memory_artifacts,
    list_namespace_artifacts,
    upload_artifact,
)

router = APIRouter(prefix="/api/v1", tags=["artifacts"])

# ─── Upload — generic ───────────────────────────────────────────────


@router.post(
    "/artifacts/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file to a namespace or memory (project files)",
)
async def upload_artifact_endpoint(
    file: UploadFile = File(..., description="Binary payload (any type)."),
    # Namespace resolution inputs.
    namespace: str | None = Form(
        None,
        description="Explicit namespace to store the file in. "
        "If omitted, provide platform + project_id / project_name instead.",
    ),
    platform: str | None = Form(
        None,
        description="Source platform (chatgpt | claude | gemini | manus | other). "
        "Used for namespace resolution via ChatNamespaceMapping when namespace "
        "is not provided directly.",
    ),
    project_id: str | None = Form(
        None,
        description="Source project id (e.g. ChatGPT Project uuid / Claude Project id). "
        "Combined with platform for exact namespace mapping lookup.",
    ),
    project_name: str | None = Form(
        None,
        description="Human-readable project name. Used for pattern mapping fallback "
        "and to derive a slug namespace when no mapping fires.",
    ),
    # Optional parent.
    memory_id: str | None = Form(
        None,
        description="UUID of a memory row to attach this file to. "
        "When provided the artifact's namespace is resolved from the memory.",
    ),
    # Type override.
    artifact_type: str | None = Form(
        None,
        description="Artifact type override (code | image | file | react | html | svg | "
        "audio | video). Inferred from Content-Type when omitted.",
    ),
    language: str | None = Form(None, description="Language hint for code artifacts."),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Upload a binary file as a project artifact.

    The file can be attached to:

    * **A namespace** (``namespace=`` or resolved from ``platform``/``project_id``).
    * **A memory** (``memory_id=``; namespace is inherited from the memory row).

    Namespace is resolved in this order:
      1. ``namespace`` form field — used as-is.
      2. ``memory_id`` — namespace taken from the parent memory row.
      3. ``platform`` + ``project_id`` / ``project_name`` — ChatNamespaceMapping
         lookup, then slugified derivation.
      4. Fallback: ``"shared"``.

    Returns the artifact metadata including a short-lived signed ``content_url``
    that the browser can use directly in ``<img>``, ``<audio>``, ``<video>`` tags.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload body.")

    mem_uuid: uuid.UUID | None = None
    if memory_id:
        try:
            mem_uuid = uuid.UUID(memory_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="memory_id must be a valid UUID.")

    try:
        response = await upload_artifact(
            user_id=auth.user_id,
            org_id=auth.org_id or "no-org",
            data=data,
            filename=file.filename,
            content_type=file.content_type,
            namespace=namespace,
            platform=platform,
            source_project_id=project_id,
            source_project_name=project_name,
            memory_id=mem_uuid,
            artifact_type=artifact_type,
            language=language,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return response.model_dump(mode="json")


# ─── Get metadata ───────────────────────────────────────────────────


@router.get(
    "/artifacts/{artifact_id}",
    summary="Get artifact metadata",
)
async def get_artifact_endpoint(
    artifact_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Fetch the metadata for a single artifact (scoped to the caller)."""
    artifact = await get_artifact_response(auth.user_id, artifact_id, db)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found.")
    return artifact.model_dump(mode="json")


# ─── Blob streaming ─────────────────────────────────────────────────


@router.get(
    "/artifacts/{artifact_id}/blob",
    summary="Stream artifact binary (signed-URL auth — no bearer needed)",
)
async def stream_artifact_blob_endpoint(
    artifact_id: uuid.UUID,
    exp: int = Query(..., description="Expiry Unix timestamp."),
    sig: str = Query(..., description="HMAC-SHA256 signature from build_artifact_blob_url."),
    db: AsyncSession = Depends(get_db),
):
    """Stream the artifact body.

    Authentication is the HMAC signature in the query string — no Bearer
    / X-API-Key needed — so ``<img src=…>``, ``<audio src=…>`` and
    ``<video src=…>`` elements can reference the URL directly without
    JavaScript.

    The signed URL is provided in ``ArtifactResponse.content_url`` and
    refreshed on every metadata read.  Default TTL: 1 hour.
    """
    from backend.core.tenancy import bypass_tenant_filter
    from backend.models.ai_chat import AIChatArtifact
    from backend.services.artifact_storage import get_artifact, verify_artifact_sig

    if not verify_artifact_sig(str(artifact_id), exp, sig):
        raise HTTPException(status_code=403, detail="invalid_or_expired_signature")

    # Signature validates the artifact — bypass the tenant filter since
    # we have no AuthContext here (same pattern as the chat blob endpoint).
    with bypass_tenant_filter():
        row = (
            await db.execute(
                select(AIChatArtifact).where(
                    AIChatArtifact.artifact_id == artifact_id,
                )
            )
        ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Artifact not found.")

    meta = row.artifact_metadata or {}
    if not isinstance(meta, dict) or not meta.get("storage_key"):
        raise HTTPException(
            status_code=404,
            detail="No object-storage body for this artifact.",
        )

    try:
        result = get_artifact(meta.get("storage_bucket"), meta["storage_key"])
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Object storage read failed: {exc}",
        ) from exc

    response_headers = {
        "Cache-Control": f"private, max-age={max(0, exp - int(time.time()))}",
    }
    filename = meta.get("filename") if isinstance(meta, dict) else None
    if filename:
        response_headers["Content-Disposition"] = f'inline; filename="{filename}"'

    def _iter():
        try:
            # minio responses expose .stream(amt=); BytesIO (core_backend) uses .read(n).
            if hasattr(result.stream, "stream"):
                for chunk in result.stream.stream(amt=64 * 1024):
                    yield chunk
                try:
                    result.stream.release_conn()
                except Exception:
                    pass
            else:
                while True:
                    chunk = result.stream.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
        finally:
            result.stream.close()

    media_type = result.mimetype or meta.get("mimetype") or "application/octet-stream"
    return StreamingResponse(
        _iter(),
        media_type=media_type,
        headers=response_headers,
    )


# ─── Delete ─────────────────────────────────────────────────────────


@router.delete(
    "/artifacts/{artifact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an artifact",
)
async def delete_artifact_endpoint(
    artifact_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete an artifact row and its stored binary body."""
    deleted = await delete_artifact_row(auth.user_id, artifact_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Artifact not found.")


# ─── List by namespace ───────────────────────────────────────────────


@router.get(
    "/namespaces/{namespace}/artifacts",
    summary="List artifacts for a namespace",
)
async def list_namespace_artifacts_endpoint(
    namespace: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return artifacts belonging to ``namespace``, newest first.

    Includes all artifact types: standalone namespace files, memory-attached
    files, and chat-turn artifacts (all share the same namespace column).
    """
    items, total = await list_namespace_artifacts(
        user_id=auth.user_id,
        namespace=namespace,
        limit=limit,
        offset=offset,
        db=db,
    )
    return {
        "items": [a.model_dump(mode="json") for a in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ─── Memory artifact upload ─────────────────────────────────────────


@router.post(
    "/memories/{memory_id}/artifacts/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file attached to a memory",
)
async def upload_memory_artifact_endpoint(
    memory_id: uuid.UUID,
    file: UploadFile = File(..., description="Binary payload (any type)."),
    artifact_type: str | None = Form(None),
    language: str | None = Form(None),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file attached to a specific memory row.

    The artifact's namespace is resolved automatically from the memory.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload body.")

    try:
        response = await upload_artifact(
            user_id=auth.user_id,
            org_id=auth.org_id or "no-org",
            data=data,
            filename=file.filename,
            content_type=file.content_type,
            memory_id=memory_id,
            artifact_type=artifact_type,
            language=language,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return response.model_dump(mode="json")


# ─── List by memory ──────────────────────────────────────────────────


@router.get(
    "/memories/{memory_id}/artifacts",
    summary="List artifacts attached to a memory",
)
async def list_memory_artifacts_endpoint(
    memory_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return all artifacts attached to the given memory, oldest first."""
    items = await list_memory_artifacts(auth.user_id, memory_id, db)
    return [a.model_dump(mode="json") for a in items]
