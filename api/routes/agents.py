"""
S9N Memory Vault — Agent Registration & Management API

Endpoints for agent lifecycle management:
- POST   /api/v1/agents              — Register a new agent
- GET    /api/v1/agents              — List user's agents
- GET    /api/v1/agents/{agent_id}   — Get agent details
- POST   /api/v1/agents/{agent_id}/approve   — Approve a pending agent
- POST   /api/v1/agents/{agent_id}/suspend   — Suspend an agent
- POST   /api/v1/agents/{agent_id}/revoke    — Revoke an agent
- POST   /api/v1/agents/{agent_id}/token     — Generate JWT for agent

Spec reference: Section 10 (API Contracts), F01-US-001 through F01-US-003
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.auth import require_auth, AuthContext, is_admin
from backend.core.tenancy import TenantScope, TenantScopeDep
from backend.services.agent_service import (
    AgentRegistrationRequest,
    AgentRegistrationResponse,
    AgentResponse,
    register_agent,
    approve_agent,
    suspend_agent,
    revoke_agent,
    get_agent,
    list_agents,
    generate_token_for_agent,
)

router = APIRouter(prefix="/api/v1/agents", tags=["Agents"])


@router.post(
    "",
    response_model=AgentRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new agent",
)
async def register_agent_endpoint(
    request: AgentRegistrationRequest,
    auth: AuthContext = Depends(require_auth),
    scope: TenantScope = TenantScopeDep,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new AI agent for the authenticated user.

    The agent starts in 'pending_approval' status and must be approved
    before it can access the memory vault. The API key is returned ONCE
    in the response — store it securely.

    WS-5: the resulting key is bound to the caller's org. A leaked key
    cannot read another org's data because authenticate_api_key() reads
    org_id from this row, never from request headers.
    """
    try:
        return await register_agent(auth.user_id, request, db, org_id=scope.org_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get(
    "",
    response_model=list[AgentResponse],
    summary="List user's agents",
)
async def list_agents_endpoint(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    List agents.

    Admin users receive a cross-user list of all registered agents.
    Regular users only see their own agents.
    """
    return await list_agents(auth.user_id, db, status=status_filter, admin_view=is_admin(auth))


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Get agent details",
)
async def get_agent_endpoint(
    agent_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Get details for a specific agent.

    Fix KMV-QA-002: Admin users can retrieve any agent regardless of owner.
    Regular users can only retrieve agents they registered.
    """
    try:
        return await get_agent(agent_id, auth.user_id, db, admin_view=is_admin(auth))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post(
    "/{agent_id}/approve",
    response_model=AgentResponse,
    summary="Approve a pending agent",
)
async def approve_agent_endpoint(
    agent_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending agent, transitioning it to 'active' status."""
    try:
        return await approve_agent(agent_id, auth.user_id, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{agent_id}/suspend",
    response_model=AgentResponse,
    summary="Suspend an agent",
)
async def suspend_agent_endpoint(
    agent_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Suspend an active agent."""
    try:
        return await suspend_agent(agent_id, auth.user_id, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{agent_id}/revoke",
    response_model=AgentResponse,
    summary="Permanently revoke an agent",
)
async def revoke_agent_endpoint(
    agent_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Permanently revoke an agent. This action is irreversible."""
    try:
        return await revoke_agent(agent_id, auth.user_id, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/{agent_id}/token",
    summary="Generate JWT access token for an agent",
)
async def generate_token_endpoint(
    agent_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a short-lived JWT access token for an active agent.

    The token expires after the configured JWT_EXPIRY_MINUTES (default: 15).
    Only active agents can receive tokens.
    """
    try:
        return await generate_token_for_agent(agent_id, auth.user_id, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─── WS-5: key rotation ────────────────────────────────────────────────


@router.post(
    "/{agent_id}/rotate-key",
    summary="Rotate the API key for an agent",
    description=(
        "Generates a fresh API key for an existing agent. The new key is "
        "returned ONCE; the old key is invalidated immediately. Use this "
        "when a key is suspected of being leaked or as part of routine "
        "rotation. Requires the caller to own the agent."
    ),
)
async def rotate_key_endpoint(
    agent_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    scope: TenantScope = TenantScopeDep,
    db: AsyncSession = Depends(get_db),
):
    from backend.services.agent_service import rotate_agent_key
    try:
        return await rotate_agent_key(agent_id, auth.user_id, scope.org_id, db)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
