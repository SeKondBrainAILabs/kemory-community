"""
Kemory — Team admin endpoints (WS-9).

HTTP-first surface for ops + customers to manage tenant structure:
``POST /v1/orgs/{org_id}/teams`` to create a team, ``POST /v1/teams/{id}/members``
to add members. No dashboard UI in v1; ops uses curl + a runbook.

Authorization model
-------------------
* Team creation     — caller must be a member of ``org_id`` (taken from
                      AuthContext) and hold the ``org_admin`` role.
* Member management — caller must own the team (TeamMember.role='owner')
                      OR hold the ``org_admin`` role.

The path-supplied ``org_id`` is checked against ``scope.org_id`` so an
org_admin in org A can never act on org B's teams. The 404-not-403
contract from WS-3 holds: cross-org actions return 404, not 403.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.core.tenancy import (
    TenantScope,
    TenantScopeDep,
)
from backend.models.team import Team, TeamMember
from backend.services.team_resolver import (
    invalidate_for_org as invalidate_team_cache_for_org,
)

logger = structlog.get_logger(__name__)


router = APIRouter(tags=["Teams"])


# ─── Schemas ───────────────────────────────────────────────────────────────


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class TeamResponse(BaseModel):
    id: str
    name: str
    description: str | None
    org_id: str


class MemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str = Field(default="member")
    can_write: bool = False


class MemberResponse(BaseModel):
    team_id: str
    user_id: str
    role: str
    can_write: bool


# ─── Authz helpers ─────────────────────────────────────────────────────────


def _require_org_admin(scope: TenantScope) -> None:
    if not scope.has_role("org_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="org_admin role required",
        )


async def _require_team_owner_or_admin(
    team_id: uuid.UUID,
    auth: AuthContext,
    scope: TenantScope,
    db: AsyncSession,
) -> Team:
    """Return the Team if the caller can manage it, else raise 403/404."""
    # Cross-org reads return 404 via the global filter.
    result = await db.execute(
        select(Team).where(
            Team.team_id == team_id,
            Team.is_deleted == False,  # noqa: E712
        )
    )
    team = result.scalar_one_or_none()
    if team is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    if scope.has_role("org_admin"):
        return team

    # Owner check.
    member_result = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == auth.user_id,
            TeamMember.role == "owner",
        )
    )
    if member_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Team owner or org_admin role required",
        )
    return team


# ─── Routes ────────────────────────────────────────────────────────────────


@router.post(
    "/api/v1/orgs/{org_id}/teams",
    response_model=TeamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a team in an org",
)
async def create_team(
    org_id: str,
    request: TeamCreate,
    auth: AuthContext = Depends(require_auth),
    scope: TenantScope = TenantScopeDep,
    db: AsyncSession = Depends(get_db),
):
    """Create a team. Caller is added as TeamMember(role='owner', can_write=True)."""
    if org_id != scope.org_id:
        # Don't acknowledge that another org exists.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Org not found")
    _require_org_admin(scope)

    team = Team(
        org_id=org_id,
        name=request.name,
        description=request.description,
        created_by=auth.user_id,
    )
    db.add(team)
    await db.flush()  # populate team_id

    db.add(
        TeamMember(
            team_id=team.team_id,
            user_id=auth.user_id,
            role="owner",
            can_write=True,
        )
    )
    await db.flush()

    await invalidate_team_cache_for_org(auth.user_id, org_id)
    logger.info("team.created", team_id=str(team.team_id), org_id=org_id, by=str(auth.user_id))
    return TeamResponse(
        id=str(team.team_id),
        name=team.name,
        description=team.description,
        org_id=str(team.org_id),
    )


@router.get(
    "/api/v1/orgs/{org_id}/teams",
    response_model=list[TeamResponse],
    summary="List teams in an org",
)
async def list_teams(
    org_id: str,
    auth: AuthContext = Depends(require_auth),
    scope: TenantScope = TenantScopeDep,
    db: AsyncSession = Depends(get_db),
):
    if org_id != scope.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Org not found")

    # Tenant filter is already on; the explicit scope predicate documents intent.
    result = await db.execute(
        select(Team)
        .where(
            Team.org_id == scope.org_id,
            Team.is_deleted == False,  # noqa: E712
        )
        .order_by(Team.name)
    )
    return [
        TeamResponse(id=str(t.team_id), name=t.name, description=t.description, org_id=str(t.org_id))
        for t in result.scalars().all()
    ]


@router.post(
    "/api/v1/teams/{team_id}/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member to a team",
)
async def add_member(
    team_id: uuid.UUID,
    request: MemberAdd,
    auth: AuthContext = Depends(require_auth),
    scope: TenantScope = TenantScopeDep,
    db: AsyncSession = Depends(get_db),
):
    """Idempotent: re-adding an existing member returns the existing row."""
    team = await _require_team_owner_or_admin(team_id, auth, scope, db)

    # Idempotency check.
    existing = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == request.user_id,
        )
    )
    member = existing.scalar_one_or_none()
    if member is None:
        member = TeamMember(
            team_id=team_id,
            user_id=request.user_id,
            role=request.role,
            can_write=request.can_write,
        )
        db.add(member)
        await db.flush()

    await invalidate_team_cache_for_org(request.user_id, scope.org_id)
    return MemberResponse(
        team_id=str(team_id),
        user_id=str(request.user_id),
        role=member.role,
        can_write=member.can_write,
    )


@router.delete(
    "/api/v1/teams/{team_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from a team",
)
async def remove_member(
    team_id: uuid.UUID,
    user_id: uuid.UUID,
    auth: AuthContext = Depends(require_auth),
    scope: TenantScope = TenantScopeDep,
    db: AsyncSession = Depends(get_db),
):
    await _require_team_owner_or_admin(team_id, auth, scope, db)

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user_id,
        )
    )
    member = result.scalar_one_or_none()
    if member is not None:
        await db.delete(member)
        await db.flush()
    await invalidate_team_cache_for_org(user_id, scope.org_id)
    return None
