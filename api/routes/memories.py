"""
S9N Memory Vault — Memory API Routes

Endpoints for memory CRUD operations:
- POST   /api/v1/memories                                    — Create a memory
- GET    /api/v1/memories/{memory_id}                        — Get a memory
- PUT    /api/v1/memories/{memory_id}                        — Update a memory
- DELETE /api/v1/memories/{memory_id}                        — Delete a memory (soft)
- POST   /api/v1/memories/search                             — Search memories
- GET    /api/v1/namespaces                                  — List namespaces
- GET    /api/v1/namespaces/{namespace}/compressed           — Multi-level memory read (L1-L4)

Spec reference: Section 10 (API Contracts), Section 7.4 (Memory Operations)
Story: KMV-S11.2
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, is_admin, require_auth
from backend.core.database import get_db
from backend.services.memory_service import (
    MemoryCreate,
    MemoryListResponse,
    MemoryResponse,
    MemorySearchRequest,
    MemoryUpdate,
    create_memory,
    delete_memory,
    get_memory,
    get_namespace_compressed,
    get_namespace_summary,
    list_namespaces,
    search_memories,
    update_memory,
)
from backend.services.namespace_matcher import RelatedNamespaceConflict

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
        memory = await create_memory(
            auth.user_id, auth.agent_id, request, db, org_id=auth.org_id,
        )
        # Always 201 — dedup info is in the response body (memory.dedup field)
        # so clients don't need to branch on status code.
        return JSONResponse(
            content=memory.model_dump(mode="json"),
            status_code=201,
        )
    except RelatedNamespaceConflict as e:
        # 409 — the agent tried to create a namespace that's 60..90% similar
        # to an existing one. Surface the suggestions so the agent can pick
        # an existing namespace or re-submit with allow_duplicate=true.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=e.to_dict())
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

    Non-admin callers are filtered by the Gatekeeper on memory:read so agents
    cannot enumerate namespaces they have no access to.
    """
    # Consolidation + policy endpoints have moved to backend/api/routes/consolidation.py
    # (KMV-E14). list_namespaces is now agent-scoped for non-admin callers.
    admin = is_admin(auth)
    return await list_namespaces(
        auth.user_id,
        db,
        admin_view=admin,
        agent_id=None if admin else auth.agent_id,
    )


@router.get(
    "/namespaces/{namespace}/summary",
    summary="Get consolidated cross-session summary for a namespace",
)
async def get_namespace_summary_endpoint(
    namespace: str,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Return the rolling L3.1 consolidated summary for a namespace.

    Falls back to the latest L3.0 concept memory when L3.1 hasn't been
    synthesized yet. Gatekeeper-gated on memory:read.
    """
    admin = is_admin(auth)
    try:
        return await get_namespace_summary(
            auth.user_id,
            auth.agent_id,
            namespace,
            db,
            skip_gatekeeper=admin,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get(
    "/namespaces/{namespace}/sessions/{session_id}/summary",
    summary="Get per-session L3 rollup (session + cumulative-to-this-point)",
)
async def get_session_summary_endpoint(
    namespace: str,
    session_id: str,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Return the session's L3 rollup for this namespace.

    Response shape:
      {
        namespace, session_id,
        session_summary, session_summary_tier, session_memory_count,
        cumulative_summary, cumulative_summary_tier, cumulative_memory_count,
        up_to_ts, updated_at
      }

    `session_summary` covers only memories with session_id=<session_id>.
    `cumulative_summary` covers all active namespace memories with
    created_at ≤ up_to_ts — a point-in-time snapshot of the namespace as
    of this session's boundary. Returns 404 if no summary has been
    generated yet (e.g. the session has <2 memories).
    """
    from sqlalchemy import select as _select

    from backend.models.session_summary import SessionSummary

    # Gatekeeper: agents need memory:read on the namespace. Admins bypass.
    admin = is_admin(auth)
    if not admin:
        from backend.services.gatekeeper_service import (
            EvaluationRequest,
            evaluate,
        )

        decision = await evaluate(
            auth.user_id,
            EvaluationRequest(
                agent_id=str(auth.agent_id),
                scope="memory:read",
                namespace=namespace,
            ),
            db,
        )
        if decision.decision != "allow":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"memory:read on '{namespace}' denied by gatekeeper",
            )

    row = (
        await db.execute(
            _select(SessionSummary).where(
                SessionSummary.user_id == auth.user_id,
                SessionSummary.namespace == namespace,
                SessionSummary.session_id == session_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No session summary for namespace='{namespace}' "
                f"session_id='{session_id}'. Needs ≥1 memory in the session "
                f"(and ≥2 in the namespace for the cumulative summary)."
            ),
        )

    return {
        "namespace": row.namespace,
        "session_id": row.session_id,
        "session_summary": row.session_summary,
        "session_summary_tier": row.session_summary_tier,
        "session_memory_count": row.session_memory_count,
        "cumulative_summary": row.cumulative_summary,
        "cumulative_summary_tier": row.cumulative_summary_tier,
        "cumulative_memory_count": row.cumulative_memory_count,
        "up_to_ts": row.up_to_ts.isoformat() if row.up_to_ts else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


_VALID_MEMORY_MODES = {"raw", "aaak", "concept", "cognition"}


@router.get(
    "/namespaces/{namespace}/compressed",
    summary="Multi-level memory read (L1 raw / L2 AAAK / L3.1 concept / L4 cognition)",
)
async def get_namespace_compressed_endpoint(
    namespace: str,
    mode: str = Query(
        default="concept",
        description="Memory read level: raw (L1), aaak (L2), concept (L3.1), cognition (L4)",
    ),
    merge_mode: str = Query(
        default="current",
        description="Merge strategy: current (latest only) or aggregate (all history)",
    ),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Return namespace memories at the requested compression level.

    | Mode      | Level | Description                                      |
    |-----------|-------|--------------------------------------------------|
    | raw       | L1    | Every active memory as raw dicts                 |
    | aaak      | L2    | Lossless AAAK encoding with compression metrics  |
    | concept   | L3.1  | LLM-synthesized concepts                         |
    | cognition | L4    | Concepts + Cognition OS graph entities           |

    Story: KMV-S11.2
    """
    if mode not in _VALID_MEMORY_MODES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mode '{mode}'. Must be one of: {', '.join(sorted(_VALID_MEMORY_MODES))}",
        )
    if merge_mode not in {"current", "aggregate"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="merge_mode must be 'current' or 'aggregate'",
        )
    try:
        # Use a dummy agent_id for dashboard reads (admin context)
        import uuid as _uuid

        agent_id = auth.agent_id if hasattr(auth, "agent_id") and auth.agent_id else _uuid.UUID(int=0)
        payload = await get_namespace_compressed(
            auth.user_id,
            agent_id,
            namespace,
            db,
            mode=mode,
            merge_mode=merge_mode,
            skip_gatekeeper=is_admin(auth),
        )
        return JSONResponse(content=payload)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
