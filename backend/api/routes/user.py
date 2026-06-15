"""
backend/api/routes/user.py
============================
User-level context API.

GET /api/v1/user/context — aggregated cross-namespace summary for the
    authenticated user. Provides a single injectable context block for
    agent session start, closing the session-prewarm gap vs Honcho-style
    user models.

Story: KMV-CTX-01
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.services.user_context_service import get_user_context

router = APIRouter(prefix="/api/v1/user", tags=["User Context"])


class NamespaceSummaryItem(BaseModel):
    namespace: str
    summary: str | None = None
    tier: str | None = None
    memory_count: int
    updated_at: str | None = None


class UserContextResponse(BaseModel):
    user_id: str
    depth: str
    namespaces: list[NamespaceSummaryItem]
    synthesis: str | None = None
    generated_at: str


@router.get(
    "/context",
    response_model=UserContextResponse,
    summary="Cross-namespace context summary for the authenticated user",
    description=(
        "Aggregate namespace summaries for the authenticated user into a single "
        "injectable context block.\n\n"
        "**depth=l3** (default): reads `NamespacePolicy.consolidated_summary` for "
        "all user namespaces — no LLM call, sub-100ms.\n\n"
        "**depth=l4**: l3 + one LLM synthesis pass across all non-null summaries "
        "via core-ai-backend. `synthesis` is null if the backend is unavailable.\n\n"
        "The `user_id` is always taken from the JWT — an agent calling on behalf "
        "of a user sees that user's namespaces (not the agent's own). Gatekeeper "
        "is not applied — the user is accessing their own data."
    ),
)
async def get_user_context_endpoint(
    depth: str = Query(
        default="l3",
        description="'l3' = stored summaries (fast, no LLM). 'l4' = LLM synthesis across all summaries.",
    ),
    namespaces: str | None = Query(
        default=None,
        description="Comma-separated namespace names to include. Default: all.",
    ),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    if depth not in ("l3", "l4"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"depth must be 'l3' or 'l4', got '{depth}'",
        )

    ns_filter: list[str] | None = None
    if namespaces:
        ns_filter = [n.strip() for n in namespaces.split(",") if n.strip()]

    result = await get_user_context(
        auth.user_id,
        db,
        depth=depth,
        namespaces_filter=ns_filter,
    )
    return result
