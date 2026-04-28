"""
S9N Memory Vault — Permission Rules & Gatekeeper API

Endpoints for permission management and Gatekeeper evaluation:
- POST   /api/v1/permissions              — Create a permission rule
- GET    /api/v1/permissions              — List permission rules
- GET    /api/v1/permissions/{rule_id}    — Get a permission rule
- PUT    /api/v1/permissions/{rule_id}    — Update a permission rule
- DELETE /api/v1/permissions/{rule_id}    — Delete a permission rule
- POST   /api/v1/gatekeeper/evaluate      — Evaluate a permission request
- POST   /api/v1/gatekeeper/consent/{id}/resolve — Resolve JIT consent

Spec reference: Section 10 (API Contracts), Section 7.1 (Gatekeeper)
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.auth import require_auth, AuthContext, is_admin
from backend.services.gatekeeper_service import (
    PermissionRuleCreate,
    PermissionRuleUpdate,
    PermissionRuleResponse,
    GatekeeperDecision,
    EvaluationRequest,
    ConsentRequestResponse,
    create_rule,
    update_rule,
    delete_rule,
    get_rule,
    list_rules,
    list_consent_requests,
    evaluate,
    resolve_consent,
)

# ─── Permission Rules Router ─────────────────────────────────────
permissions_router = APIRouter(prefix="/api/v1/permissions", tags=["Permissions"])


@permissions_router.post(
    "",
    response_model=PermissionRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a permission rule",
)
async def create_rule_endpoint(
    request: PermissionRuleCreate,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Create a new permission rule for the authenticated user."""
    try:
        return await create_rule(auth.user_id, request, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@permissions_router.get(
    "",
    response_model=list[PermissionRuleResponse],
    summary="List permission rules",
)
async def list_rules_endpoint(
    agent_id: str | None = Query(None, description="Filter by agent ID"),
    scope: str | None = Query(None, description="Filter by scope"),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    List permission rules.

    Fix KMV-QA-005: Admin users receive a cross-user view of all rules
    so the Permissions page shows real data instead of 0 rules.
    """
    agent_uuid = uuid.UUID(agent_id) if agent_id else None
    return await list_rules(auth.user_id, db, agent_id=agent_uuid, scope=scope, admin_view=is_admin(auth))


@permissions_router.get(
    "/{rule_id}",
    response_model=PermissionRuleResponse,
    summary="Get a permission rule",
)
async def get_rule_endpoint(
    rule_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get details of a specific permission rule."""
    try:
        return await get_rule(rule_id, auth.user_id, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@permissions_router.put(
    "/{rule_id}",
    response_model=PermissionRuleResponse,
    summary="Update a permission rule",
)
async def update_rule_endpoint(
    rule_id: uuid.UUID,
    request: PermissionRuleUpdate,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing permission rule."""
    try:
        return await update_rule(rule_id, auth.user_id, request, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@permissions_router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a permission rule",
)
async def delete_rule_endpoint(
    rule_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Delete a permission rule."""
    try:
        await delete_rule(rule_id, auth.user_id, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ─── Gatekeeper Router ───────────────────────────────────────────
gatekeeper_router = APIRouter(prefix="/api/v1/gatekeeper", tags=["Gatekeeper"])


@gatekeeper_router.post(
    "/evaluate",
    response_model=GatekeeperDecision,
    summary="Evaluate a permission request",
)
async def evaluate_endpoint(
    request: EvaluationRequest,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Evaluate a permission request through the Gatekeeper.

    The Gatekeeper evaluates rules in priority order and returns the first match.
    If no rule matches, access is DENIED (default-deny posture).
    If a rule has action='jit', a consent request is created.
    """
    return await evaluate(auth.user_id, request, db)


@gatekeeper_router.get(
    "/consent",
    response_model=list[ConsentRequestResponse],
    summary="List JIT consent requests",
)
async def list_consent_endpoint(
    status_filter: str | None = Query(None, alias="status", description="Filter by status: pending, approved, denied, timeout"),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    List JIT consent requests.

    Fix KMV-QA-006: Returns consent requests directly from the ConsentRequest
    table so the Consent Queue page shows real data.

    Admin users see all consent requests across every user's vault.
    """
    return await list_consent_requests(
        auth.user_id,
        db,
        status=status_filter,
        admin_view=is_admin(auth),
    )


@gatekeeper_router.post(
    "/consent/{consent_id}/resolve",
    response_model=GatekeeperDecision,
    summary="Resolve a JIT consent request",
)
async def resolve_consent_endpoint(
    consent_id: uuid.UUID,
    approved: bool = Query(..., description="True to approve, False to deny"),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Resolve a Just-in-Time consent request."""
    try:
        return await resolve_consent(consent_id, auth.user_id, approved, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
