"""
S9N Memory Vault — Memory API Routes

Endpoints for memory CRUD operations:
- POST   /api/v1/memories              — Create a memory
- GET    /api/v1/memories/{memory_id}  — Get a memory
- PUT    /api/v1/memories/{memory_id}  — Update a memory
- DELETE /api/v1/memories/{memory_id}  — Delete a memory (soft)
- POST   /api/v1/memories/search       — Search memories
- GET    /api/v1/namespaces            — List namespaces

Spec reference: Section 10 (API Contracts), Section 7.4 (Memory Operations)
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.auth import require_auth, AuthContext, is_admin
from backend.services.memory_service import (
    MemoryCreate,
    MemoryUpdate,
    MemoryResponse,
    MemorySearchRequest,
    MemoryListResponse,
    create_memory,
    get_memory,
    update_memory,
    delete_memory,
    search_memories,
    list_namespaces,
)

router = APIRouter(prefix="/api/v1", tags=["Memories"])


@router.post(
    "/memories",
    response_model=MemoryResponse,
    summary="Create a memory",
)
async def create_memory_endpoint(
    request: MemoryCreate,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new memory entry in the vault.

    The Gatekeeper checks that the agent has memory:write permission
    for the target namespace. Returns 201 for new memories, 200 when
    deduplication matched an existing memory (S9N-DEDUP).
    """
    try:
        memory = await create_memory(auth.user_id, auth.agent_id, request, db)
        # Always 201 — dedup info is in the response body (memory.dedup field)
        # so clients don't need to branch on status code.
        return JSONResponse(
            content=memory.model_dump(mode="json"),
            status_code=201,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/memories/{memory_id}",
    response_model=MemoryResponse,
    summary="Get a memory",
)
async def get_memory_endpoint(
    memory_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get a single memory by ID. Gatekeeper checks memory:read permission."""
    try:
        return await get_memory(memory_id, auth.user_id, auth.agent_id, db)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.put(
    "/memories/{memory_id}",
    response_model=MemoryResponse,
    summary="Update a memory",
)
async def update_memory_endpoint(
    memory_id: uuid.UUID,
    request: MemoryUpdate,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update a memory. Increments version. Gatekeeper checks memory:write permission.
    Admin users bypass the user_id ownership check and the gatekeeper."""
    admin = is_admin(auth)
    # Admin uses a sentinel UUID so _get_active_memory skips user_id filter
    effective_user_id = auth.user_id
    try:
        return await update_memory(
            memory_id,
            effective_user_id,
            auth.agent_id,
            request,
            db,
            skip_gatekeeper=admin,
            admin_view=admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete(
    "/memories/{memory_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a memory",
)
async def delete_memory_endpoint(
    memory_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a memory. Gatekeeper checks memory:delete permission.
    Admin users bypass the user_id ownership check and the gatekeeper."""
    admin = is_admin(auth)
    try:
        await delete_memory(
            memory_id,
            auth.user_id,
            auth.agent_id,
            db,
            skip_gatekeeper=admin,
            admin_view=admin,
        )
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/memories/search",
    response_model=MemoryListResponse,
    summary="Search memories",
)
async def search_memories_endpoint(
    request: MemorySearchRequest,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Search memories with filtering and pagination.

    Supports text search (LIKE), namespace filter, content type filter,
    and tag-based filtering. Results are paginated.

    Fix KMV-QA-004: Admin users can search across all users' memories.
    """
    try:
        return await search_memories(auth.user_id, auth.agent_id, request, db, admin_view=is_admin(auth))
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get(
    "/memories/{memory_id}/history",
    summary="Get memory provenance history",
)
async def get_memory_history_endpoint(
    memory_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the full provenance trail for a memory (MV2-S02.4).
    Returns events newest-first: type, actor, reason, state diffs, timestamps.
    """
    from backend.services.provenance_service import get_memory_history
    return await get_memory_history(db, memory_id, limit=limit, offset=offset)


@router.get(
    "/namespaces",
    summary="List namespaces",
)
async def list_namespaces_endpoint(
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    List all namespaces with memory counts.

    Fix KMV-QA-007: Admin users receive an aggregated view across all
    users so the Analytics page shows real data instead of "No namespace data".
    """
    return await list_namespaces(auth.user_id, db, admin_view=is_admin(auth))
