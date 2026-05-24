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

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
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
    limit: int = Query(20, ge=1, le=100),
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
