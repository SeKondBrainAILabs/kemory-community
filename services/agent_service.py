"""
S9N Memory Vault — Agent Registration Service

Handles agent CRUD operations: registration, approval, suspension, revocation.
Implements F01-US-001 (JWT auth), F01-US-002 (API key management),
F01-US-003 (audit logging), F02-US-001 (scope declaration).

Business rules:
- Agent names must be unique per user
- New agents start in 'pending_approval' status
- API key is generated at registration and shown ONCE
- Callback URLs must not point to internal/private IPs
"""
import uuid
import ipaddress
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent import AgentRegistry
from backend.services.auth_service import generate_api_key, create_access_token


# ─── Request/Response Schemas ─────────────────────────────────────

class ScopeDeclaration(BaseModel):
    """A single scope declaration from an agent."""
    scope: str = Field(..., min_length=1, max_length=100, description="Scope string e.g. 'memory:read'")
    reason: str = Field(..., min_length=1, max_length=500, description="Why the agent needs this scope")


class AgentRegistrationRequest(BaseModel):
    """Request body for registering a new agent."""
    agent_name: str = Field(..., min_length=1, max_length=100, description="Human-readable agent name")
    agent_description: str = Field(..., min_length=1, max_length=500, description="What the agent does")
    declared_scopes: list[ScopeDeclaration] = Field(..., min_length=1, description="Scopes the agent requires")
    callback_url: Optional[str] = Field(None, max_length=2048, description="Agent callback URL")

    @field_validator("callback_url")
    @classmethod
    def validate_callback_url(cls, v):
        """Reject callback URLs pointing to internal/private IPs."""
        if v is None:
            return v
        parsed = urlparse(v)
        hostname = parsed.hostname
        if hostname:
            try:
                ip = ipaddress.ip_address(hostname)
                if ip.is_private or ip.is_loopback or ip.is_reserved:
                    raise ValueError("Callback URL must not point to private/internal IPs")
            except ValueError as e:
                if "private" in str(e) or "internal" in str(e):
                    raise
                # hostname is a domain name, not an IP — that's fine
                pass
        if parsed.scheme not in ("https", "http"):
            raise ValueError("Callback URL must use https:// or http://")
        return v


class AgentRegistrationResponse(BaseModel):
    """Response body after successful agent registration."""
    agent_id: str
    agent_name: str
    status: str
    api_key: str  # Shown ONCE at registration
    declared_scopes: list[dict]
    message: str


class AgentResponse(BaseModel):
    """Public agent info (no API key)."""
    agent_id: str
    agent_name: str
    agent_description: str
    status: str
    declared_scopes: list[dict]
    registered_at: str
    last_active_at: Optional[str]
    total_reads: int
    total_writes: int
    denied_requests: int


# ─── Service Functions ────────────────────────────────────────────

async def register_agent(
    user_id: uuid.UUID,
    request: AgentRegistrationRequest,
    db: AsyncSession,
) -> AgentRegistrationResponse:
    """
    Register a new agent for a user.

    Business rules:
    1. Agent name must be unique per user
    2. At least one scope must be declared
    3. Callback URL must not point to private IPs
    4. New agents start in 'pending_approval' status
    5. API key is generated and shown ONCE

    Args:
        user_id: The owning user's UUID
        request: Registration request data
        db: Database session

    Returns:
        AgentRegistrationResponse with the one-time API key

    Raises:
        ValueError: If agent name already exists for this user
    """
    # Check for duplicate agent name
    existing = await db.execute(
        select(AgentRegistry).where(
            AgentRegistry.user_id == user_id,
            AgentRegistry.agent_name == request.agent_name,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError(f"Agent '{request.agent_name}' already exists for this user")

    # Generate API key
    plaintext_key, hashed_key, key_prefix = generate_api_key()

    # Create agent record
    agent = AgentRegistry(
        user_id=user_id,
        agent_name=request.agent_name,
        agent_description=request.agent_description,
        declared_scopes=[s.model_dump() for s in request.declared_scopes],
        api_key_hash=hashed_key,
        api_key_prefix=key_prefix,
        callback_url=request.callback_url,
        status="pending_approval",
    )
    db.add(agent)
    await db.flush()

    return AgentRegistrationResponse(
        agent_id=str(agent.agent_id),
        agent_name=agent.agent_name,
        status=agent.status,
        api_key=plaintext_key,
        declared_scopes=agent.declared_scopes,
        message="Agent registered. API key shown once — store it securely. Agent requires approval before use.",
    )


async def approve_agent(
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AgentResponse:
    """
    Approve a pending agent, transitioning it to 'active' status.

    Only the owning user can approve their agents.
    """
    agent = await _get_agent_for_user(agent_id, user_id, db)
    if agent.status != "pending_approval":
        raise ValueError(f"Agent is in '{agent.status}' status, not 'pending_approval'")

    agent.status = "active"
    await db.flush()
    return _to_response(agent)


async def suspend_agent(
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AgentResponse:
    """Suspend an active agent."""
    agent = await _get_agent_for_user(agent_id, user_id, db)
    if agent.status not in ("active", "pending_approval"):
        raise ValueError(f"Cannot suspend agent in '{agent.status}' status")

    agent.status = "suspended"
    await db.flush()
    return _to_response(agent)


async def revoke_agent(
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AgentResponse:
    """Permanently revoke an agent. This is irreversible."""
    agent = await _get_agent_for_user(agent_id, user_id, db)
    agent.status = "revoked"
    await db.flush()
    return _to_response(agent)


async def get_agent(
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
    admin_view: bool = False,
) -> AgentResponse:
    """
    Get a single agent by ID.

    Fix KMV-QA-002: When ``admin_view`` is True the user_id ownership
    check is bypassed so Memory Vault admins can inspect any agent.
    """
    if admin_view:
        result = await db.execute(
            select(AgentRegistry).where(AgentRegistry.agent_id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise ValueError("Agent not found")
    else:
        agent = await _get_agent_for_user(agent_id, user_id, db)
    return _to_response(agent)


async def list_agents(
    user_id: uuid.UUID,
    db: AsyncSession,
    status: Optional[str] = None,
    admin_view: bool = False,
) -> list[AgentResponse]:
    """
    List agents.

    When ``admin_view`` is True (Memory Vault admin role) all agents across
    every user are returned.  Regular users only see their own agents.
    """
    if admin_view:
        query = select(AgentRegistry)
    else:
        query = select(AgentRegistry).where(AgentRegistry.user_id == user_id)
    if status:
        query = query.where(AgentRegistry.status == status)
    query = query.order_by(AgentRegistry.registered_at.desc())

    result = await db.execute(query)
    agents = result.scalars().all()
    return [_to_response(a) for a in agents]


async def generate_token_for_agent(
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> dict:
    """
    Generate a JWT access token for an active agent.

    Only active agents can get tokens.
    """
    agent = await _get_agent_for_user(agent_id, user_id, db)
    if agent.status != "active":
        raise ValueError(f"Cannot generate token for agent in '{agent.status}' status")

    # Extract scope strings
    scopes = []
    if agent.declared_scopes:
        for scope_obj in agent.declared_scopes:
            if isinstance(scope_obj, dict) and "scope" in scope_obj:
                scopes.append(scope_obj["scope"])
            elif isinstance(scope_obj, str):
                scopes.append(scope_obj)

    token = create_access_token(
        agent_id=agent.agent_id,
        user_id=agent.user_id,
        agent_name=agent.agent_name,
        scopes=scopes,
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": settings.jwt_expiry_minutes * 60,
        "agent_id": str(agent.agent_id),
        "scopes": scopes,
    }


# ─── Internal Helpers ─────────────────────────────────────────────

async def _get_agent_for_user(
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> AgentRegistry:
    """Fetch an agent ensuring it belongs to the specified user."""
    result = await db.execute(
        select(AgentRegistry).where(
            AgentRegistry.agent_id == agent_id,
            AgentRegistry.user_id == user_id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise ValueError("Agent not found")
    return agent


def _to_response(agent: AgentRegistry) -> AgentResponse:
    """Convert an AgentRegistry ORM object to an AgentResponse."""
    return AgentResponse(
        agent_id=str(agent.agent_id),
        agent_name=agent.agent_name,
        agent_description=agent.agent_description,
        status=agent.status,
        declared_scopes=agent.declared_scopes or [],
        registered_at=agent.registered_at.isoformat() if agent.registered_at else "",
        last_active_at=agent.last_active_at.isoformat() if agent.last_active_at else None,
        total_reads=agent.total_reads or 0,
        total_writes=agent.total_writes or 0,
        denied_requests=agent.denied_requests or 0,
    )


# Import settings at module level (after function defs to avoid circular)
from backend.config.settings import settings
