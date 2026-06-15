"""
Kemory — Chat namespace mapping CRUD (chats-v1).

Manages explicit ``(platform, project) → namespace`` overrides that the
AI Chats upsert path honours before falling through to the namespace
matcher. Many source projects can map to one namespace by inserting
multiple rows with the same ``target_namespace``.

Endpoints (all under ``/api/v1``):
  * POST   /chat-mappings              — create
  * GET    /chat-mappings              — list (own)
  * PATCH  /chat-mappings/{mapping_id} — update
  * DELETE /chat-mappings/{mapping_id} — delete
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.services.ai_chat_service import (
    ChatMappingCreate,
    ChatMappingResponse,
    ChatMappingUpdate,
    create_mapping,
    delete_mapping,
    list_mappings,
    update_mapping,
)

router = APIRouter(prefix="/api/v1", tags=["AI Chats — Mappings"])


@router.post(
    "/chat-mappings",
    response_model=ChatMappingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a chat namespace mapping override",
)
async def create_mapping_endpoint(
    request: ChatMappingCreate,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await create_mapping(auth.user_id, auth.org_id, request, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/chat-mappings",
    response_model=list[ChatMappingResponse],
    summary="List own chat namespace mappings",
)
async def list_mappings_endpoint(
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    return await list_mappings(auth.user_id, db)


@router.patch(
    "/chat-mappings/{mapping_id}",
    response_model=ChatMappingResponse,
    summary="Update a chat namespace mapping",
)
async def update_mapping_endpoint(
    mapping_id: uuid.UUID,
    request: ChatMappingUpdate,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await update_mapping(mapping_id, auth.user_id, request, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.delete(
    "/chat-mappings/{mapping_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a chat namespace mapping",
)
async def delete_mapping_endpoint(
    mapping_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    try:
        await delete_mapping(mapping_id, auth.user_id, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
