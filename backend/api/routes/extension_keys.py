"""
Kemory — Chrome Extension API key endpoints (chats-v1).

Mint / list / revoke per-install API keys for the Kanvas Chrome Extension.

Endpoints (all under ``/api/v1``):
  * POST   /extension/keys             — mint (or rotate) a key
  * GET    /extension/keys             — list own keys (never plaintext)
  * DELETE /extension/keys/{key_id}    — revoke

Under the hood: extension installs are stored as ``kemory_agent_registry``
rows with ``agent_kind='extension'``. Mint/list/revoke use these endpoints
instead of the regular ``/api/v1/agents`` so the dashboard can render a
clean "Devices" tab without intermixing them with MCP agent registrations.
See ``backend/services/extension_key_service.py`` for the rationale.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.services.auth_service import clear_auth_cache_for_agent
from backend.services.extension_key_service import (
    ExtensionKeyInfo,
    ExtensionKeyMintRequest,
    ExtensionKeyMintResponse,
    list_extension_keys,
    mint_extension_key,
    revoke_extension_key,
)

router = APIRouter(prefix="/api/v1/extension", tags=["Extension Keys"])


@router.post(
    "/keys",
    response_model=ExtensionKeyMintResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mint (or rotate) a Chrome Extension API key",
)
async def mint_key_endpoint(
    request: ExtensionKeyMintRequest,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Mint a new key, or rotate the existing key when ``installation_id``
    matches a previous mint for this user. The plaintext key is returned
    ONCE — the extension must store it in chrome.storage immediately."""
    try:
        return await mint_extension_key(auth.user_id, auth.org_id, request, db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/keys",
    response_model=list[ExtensionKeyInfo],
    summary="List own extension keys",
)
async def list_keys_endpoint(
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """List the calling user's extension installs. Plaintext keys are
    never returned — the user re-mints if a device loses its key."""
    return await list_extension_keys(auth.user_id, db)


@router.delete(
    "/keys/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an extension key",
)
async def revoke_key_endpoint(
    key_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Soft-revoke: flips ``status='revoked'`` and wipes the auth cache
    so the old key stops working immediately on the next request."""
    try:
        agent_id = await revoke_extension_key(key_id, auth.user_id, db)
        # Commit revocation before clearing the in-process auth cache. If a
        # follow-up request repopulates the cache, it must see the revoked row.
        await db.commit()
        await clear_auth_cache_for_agent(agent_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
