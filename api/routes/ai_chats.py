"""
Kemory — AI Chats routes (chats-v1).

REST endpoints for the AI Chats module. The Kanvas Chrome Extension is
the primary consumer; it authenticates with the X-API-Key it minted via
``POST /api/v1/extension/keys`` and pushes captured conversations here.

Endpoints (all under ``/api/v1``):
  * POST   /chats                              — idempotent upsert
  * POST   /chats/{chat_id}/turns:batch        — append/upsert turns
  * GET    /chats                              — list with filters
  * GET    /chats/{chat_id}                    — get one (optional include=turns,artifacts)
  * DELETE /chats/{chat_id}                    — soft delete

The 409 contract on POST /chats mirrors POST /memories: when the
namespace matcher returns SUGGEST, the response body is
``{error, message, requested, suggested[], force_create_param}``.
The extension can retry with ``allow_duplicate=true`` or let the user
pick from the suggestions.

Spec reference: ``docs/chrome-extension-push-guide.md``.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.services.ai_chat_service import (
    ChatListResponse,
    ChatResponse,
    ChatUpsert,
    TurnUpsert,
    append_turns,
    get_chat,
    list_chats,
    move_chat,
    soft_delete_chat,
    upsert_chat,
)
from backend.services.chat_classifier import ChatClassifyResponse, classify_chat
from backend.services.namespace_matcher import RelatedNamespaceConflict


class ChatMoveRequest(BaseModel):
    """Body for ``POST /api/v1/chats/{chat_id}/move``."""

    namespace: str = Field(..., min_length=1, max_length=100)
    allow_duplicate: bool = Field(
        default=False,
        description=(
            "Skip the namespace matcher 409 path — accept the namespace "
            "as-is even when it looks similar to an existing one."
        ),
    )

router = APIRouter(prefix="/api/v1", tags=["AI Chats"])


@router.post(
    "/chats",
    response_model=ChatResponse,
    summary="Idempotent upsert of a captured chat (+ turns + artifacts)",
)
async def upsert_chat_endpoint(
    request: ChatUpsert,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Push a chat captured by the extension.

    Idempotent on ``(user_id, platform, platform_conversation_id)``:
      * 201 + ``was_created=true`` — new chat row written
      * 200 + ``was_updated=true`` — chat existed, content_hash changed,
        we updated metadata and upserted any new/changed turns
      * 200 + ``was_created=false, was_updated=false`` — payload hashed
        identically to the stored chat, no-op

    Namespace resolution: mapping table override → namespace_matcher →
    derived default (``kora:<platform>:<slug>``). See
    ``ai_chat_service._resolve_namespace`` for the precedence rules.
    """
    try:
        # installation_id is sourced from the payload — the extension knows
        # which install it is. We don't read it from headers (org_id-from-
        # row invariant applies here too: identity stays attached to the
        # AgentRegistry row, no spoofable headers in the trust path).
        response = await upsert_chat(
            auth.user_id,
            auth.org_id,
            request,
            db,
            installation_id=request.installation_id,
        )
        status_code = 201 if response.was_created else 200
        return JSONResponse(
            content=response.model_dump(mode="json"),
            status_code=status_code,
        )
    except RelatedNamespaceConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.to_dict(),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/chats/{chat_id}/turns:batch",
    summary="Append (or upsert by source_turn_id) a batch of turns",
)
async def append_turns_endpoint(
    chat_id: uuid.UUID,
    turns: list[TurnUpsert],
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Streaming write path: extension pushes the chat once, then appends
    turns as the user reads / continues the conversation. Idempotent by
    ``source_turn_id`` when supplied."""
    try:
        return await append_turns(chat_id, auth.user_id, turns, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/chats",
    response_model=ChatListResponse,
    summary="List captured chats with filters",
)
async def list_chats_endpoint(
    namespace: str | None = Query(None, max_length=100),
    platform: str | None = Query(None, max_length=32),
    since: datetime | None = Query(None, description="Only chats updated at-or-after this timestamp."),
    # Cap raised from 100 → 500 so the NamespacesPage aggregator (which
    # pulls every chat to group by namespace client-side) can fetch a
    # whole user's catalogue in one shot. Hits the matching guard in
    # ai_chat_service.list_chats which clamps to the same upper bound.
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    return await list_chats(
        auth.user_id,
        db,
        namespace=namespace,
        platform=platform,
        since=since,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/chats/{chat_id}",
    response_model=ChatResponse,
    summary="Get one chat, optionally with turns + artifacts",
)
async def get_chat_endpoint(
    chat_id: uuid.UUID,
    include: str | None = Query(
        None,
        description="Comma-separated includes: 'turns', 'artifacts'.",
    ),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    parts = {p.strip() for p in (include or "").split(",") if p.strip()}
    include_turns = "turns" in parts or "artifacts" in parts
    include_artifacts = "artifacts" in parts
    try:
        return await get_chat(
            chat_id,
            auth.user_id,
            db,
            include_turns=include_turns,
            include_artifacts=include_artifacts,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/chats/{chat_id}/classify",
    response_model=ChatClassifyResponse,
    summary="Suggest destination namespaces for a chat based on its content",
)
async def classify_chat_endpoint(
    chat_id: uuid.UUID,
    limit: int = Query(5, ge=1, le=20),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Pure read — never modifies the chat. Returns top-N existing
    namespaces by embedding-cosine of the chat content against each
    namespace's representative text (consolidated summary > description
    > name).

    The UI uses this to power the "Suggested namespaces" panel; the user
    explicitly clicks one to call ``POST /chats/{chat_id}/move``.
    Background classifiers can do the same — auto-move on similarity
    above a chosen threshold — but kemory itself does NOT auto-move.
    """
    try:
        return await classify_chat(auth.user_id, chat_id, db, limit=limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/chats/{chat_id}/move",
    response_model=ChatResponse,
    summary="Move a chat to a different namespace",
)
async def move_chat_endpoint(
    chat_id: uuid.UUID,
    request: ChatMoveRequest,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Move a chat between namespaces. Runs the namespace matcher to
    auto-redirect typos and 409 on close-but-not-matching names — the
    same contract as memory writes. After a move, subsequent extension
    upserts of this chat preserve the new destination (see the
    ``preserve_user_namespace`` rule in ``ai_chat_service.upsert_chat``)."""
    try:
        return await move_chat(
            chat_id,
            auth.user_id,
            request.namespace,
            db,
            allow_duplicate=request.allow_duplicate,
        )
    except RelatedNamespaceConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=exc.to_dict(),
        ) from exc
    except ValueError as exc:
        # ValueError from _get_chat_for_user (not found) vs an explicit
        # validation error — both surface as 400-or-404. Use 404 for the
        # not-found shape and 400 for the rest.
        msg = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND if "not found" in msg.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg) from exc


# ── chats-v1 file/audio/video (v3.33.0) ─────────────────────────────


@router.post(
    "/chats/{chat_id}/artifacts/upload",
    summary="Upload a binary artifact (file / audio / video / image) for a turn",
)
async def upload_artifact_endpoint(
    chat_id: uuid.UUID,
    file: UploadFile = File(..., description="The binary payload (any type)."),
    artifact_type: str = Form(
        ...,
        description="One of: file, audio, video, image, code, html, react, svg.",
    ),
    source_turn_id: str = Form(
        ...,
        description="The Kanvas source_turn_id (NOT the internal turn_id UUID). "
        "We resolve it to the turn row server-side.",
    ),
    language: str | None = Form(None),
    artifact_metadata: str | None = Form(
        None,
        description="Optional extra JSON metadata. Filename + mimetype + size "
        "are added automatically from the upload.",
    ),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Upload the binary body of an artifact to object storage and
    create the matching AIChatArtifact row.

    Designed for the Kanvas Chrome Extension to call when it observes
    a user attaching a file/audio/video in ChatGPT or Claude (where
    inline base64 in the JSON push is wasteful or impossible because
    of the 1 MB body cap). The extension:

      1. Pushes the chat shell via POST /api/v1/chats (text-only turns).
      2. Calls this endpoint once per attached binary, referencing the
         turn via its source_turn_id (the data-message-id the extension
         already tracks).
      3. The artifact row's content_url is generated on response build
         as a short-lived signed URL the browser can use directly in
         <audio>/<video>/<img> tags — no auth header needed.

    Storage layout in minio:
      ``kemory-chat-artifacts/{org_id}/{user_id}/{chat_id}/{artifact_id}{ext}``
    """
    from backend.models.ai_chat import AIChat, AIChatArtifact, AIChatTurn
    from backend.services.ai_chat_service import (
        VALID_ARTIFACT_TYPES,
        _artifact_to_response,
    )
    from backend.services.artifact_storage import put_artifact

    if artifact_type not in VALID_ARTIFACT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid artifact_type '{artifact_type}'. "
            f"Valid: {sorted(VALID_ARTIFACT_TYPES)}",
        )

    # Look up the chat (scoped to the auth user) and the target turn.
    chat = (
        await db.execute(
            select(AIChat).where(
                AIChat.chat_id == chat_id,
                AIChat.user_id == auth.user_id,
                AIChat.invalid_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    turn = (
        await db.execute(
            select(AIChatTurn).where(
                AIChatTurn.chat_id == chat_id,
                AIChatTurn.source_turn_id == source_turn_id,
            )
        )
    ).scalar_one_or_none()
    if turn is None:
        raise HTTPException(
            status_code=404,
            detail=f"Turn with source_turn_id={source_turn_id!r} not found on this chat. "
            "Push the chat (including this turn) first via POST /api/v1/chats.",
        )

    # Read whole body into memory. ASGI multipart in this codebase
    # already buffers to disk for large uploads, so this isn't doubling
    # peak memory beyond what FastAPI already holds.
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty upload body.")

    artifact_id = uuid.uuid4()
    try:
        put_result = put_artifact(
            org_id=auth.org_id or "no-org",
            user_id=auth.user_id,
            chat_id=chat_id,
            artifact_id=artifact_id,
            data=data,
            filename=file.filename,
            mimetype=file.content_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Object storage write failed: {exc}",
        ) from exc

    # Merge caller-supplied metadata with storage facts. Caller-supplied
    # keys win EXCEPT for the storage_* keys which we own — letting the
    # extension forge those would let it point us at someone else's
    # bucket key.
    extra_meta: dict = {}
    if artifact_metadata:
        try:
            extra_meta = json.loads(artifact_metadata)
            if not isinstance(extra_meta, dict):
                extra_meta = {}
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="artifact_metadata must be a JSON object string.",
            )
    meta = {
        **extra_meta,
        "filename": file.filename or extra_meta.get("filename"),
        "mimetype": put_result.mimetype,
        "size_bytes": put_result.size_bytes,
        "storage_bucket": put_result.bucket,
        "storage_key": put_result.key,
    }

    row = AIChatArtifact(
        artifact_id=artifact_id,
        turn_id=turn.turn_id,
        chat_id=chat_id,
        user_id=auth.user_id,
        org_id=chat.org_id,
        # namespace populated since v3.35.0 (required column after migration 016).
        namespace=chat.namespace,
        artifact_type=artifact_type,
        language=language,
        content=None,  # body lives in minio, not Postgres
        content_url=None,  # generated on read via _artifact_to_response
        content_sha256=put_result.sha256,
        artifact_metadata=meta,
    )
    db.add(row)
    await db.flush()
    return _artifact_to_response(row).model_dump(mode="json")


@router.get(
    "/chats/{chat_id}/artifacts/{artifact_id}/blob",
    summary="Stream a binary artifact body (signed-URL auth, no bearer needed)",
)
async def stream_artifact_blob_endpoint(
    chat_id: uuid.UUID,
    artifact_id: uuid.UUID,
    exp: int = Query(..., description="Unix timestamp after which the URL is invalid."),
    sig: str = Query(..., description="HMAC-SHA256 signature minted by the API."),
    db: AsyncSession = Depends(get_db),
):
    """Stream the artifact body to the browser. Authentication is the
    HMAC signature in the query string (NOT Bearer / X-API-Key) so
    ``<audio src=…>`` / ``<video src=…>`` / ``<img src=…>`` work
    directly — those elements don't attach auth headers.

    The signature was minted by ``build_signed_blob_url`` when the
    ChatResponse was assembled. The dashboard receives the signed URL
    inside ArtifactResponse.content_url and uses it as-is.

    Security model:
      * Signature is HMAC-SHA256 over ``chat_id|artifact_id|exp`` using
        the same secret JWT_SECRET_KEY uses, so a leaked signed URL
        cannot escalate privileges (it grants exactly the data inside
        one artifact row).
      * Default TTL is 1 hour — copying a URL to another browser works
        until expiry; after that, the dashboard has to refresh and get
        a new signed URL via GET /chats/{id}?include=artifacts.
    """
    from backend.core.tenancy import bypass_tenant_filter
    from backend.models.ai_chat import AIChatArtifact
    from backend.services.artifact_storage import get_artifact, verify_signed_token

    if not verify_signed_token(str(chat_id), str(artifact_id), exp, sig):
        # Combined "expired or bad sig" — don't tell the caller which
        # so signature-grinding attacks can't distinguish.
        raise HTTPException(status_code=403, detail="invalid_or_expired_signature")

    # The signature already authorises this read — no user-scoped DB
    # filter needed (and we don't have an AuthContext anyway). Bypass
    # the tenancy filter so the SELECT actually returns the row.
    with bypass_tenant_filter():
        row = (
            await db.execute(
                select(AIChatArtifact).where(
                    AIChatArtifact.artifact_id == artifact_id,
                    AIChatArtifact.chat_id == chat_id,
                )
            )
        ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    meta = row.artifact_metadata or {}
    if not isinstance(meta, dict) or not meta.get("storage_key"):
        # Legacy / inline / external-URL artifact — there's nothing to
        # stream from minio. The dashboard shouldn't be hitting this
        # endpoint for those rows (the response builder only signs URLs
        # when storage_key is present), but be explicit.
        raise HTTPException(
            status_code=404,
            detail="No object-storage body for this artifact",
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
        # inline so audio/video/image render in-page; the file dialog
        # only opens if the browser decides it can't render the type.
        response_headers["Content-Disposition"] = f'inline; filename="{filename}"'

    def _iter():
        try:
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


@router.delete(
    "/chats/{chat_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a chat",
)
async def delete_chat_endpoint(
    chat_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        await soft_delete_chat(chat_id, auth.user_id, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
