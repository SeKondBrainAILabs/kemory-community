"""
Kemory — Identity endpoint (WS-11 backend).

``GET /api/v1/me`` returns everything the dashboard / CLI needs to render
identity context in one call: user, org, teams (with role + can_write),
and roles. Dashboard uses it to populate the scope picker; the ``kemory``
CLI uses it for ``kemory whoami``.

Designed to be called once per page load. ETag support lets clients
revalidate cheaply on focus refresh.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.core.tenancy import (
    TenantScope,
    TenantScopeDep,
    bypass_tenant_filter,
)
from backend.models.team import Team, TeamMember

router = APIRouter(prefix="/api/v1", tags=["Identity"])


class MeTeam(BaseModel):
    id: str
    name: str
    role: str
    can_write: bool


class MeResponse(BaseModel):
    user_id: str
    email: str
    org_id: str
    org_name: str
    teams: list[MeTeam]
    roles: list[str]


@router.get(
    "/me",
    response_model=MeResponse,
    summary="Identity, organisation, and team membership for the caller",
)
async def get_me(
    response: Response,
    auth: AuthContext = Depends(require_auth),
    scope: TenantScope = TenantScopeDep,
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
):
    """Return the caller's identity, org, teams, and roles."""
    # Look up team rows so we can include role + can_write in the response.
    # Bypass the tenant filter — we explicitly scope by user_id and org_id
    # in the query, and we want to include team membership even before the
    # filter has finished resolving.
    with bypass_tenant_filter():
        stmt = (
            select(TeamMember, Team)
            .join(Team, Team.team_id == TeamMember.team_id)
            .where(
                TeamMember.user_id == auth.user_id,
                Team.org_id == scope.org_id,
                Team.is_deleted == False,  # noqa: E712
            )
            .order_by(Team.name)
        )
        result = await db.execute(stmt)
        rows = result.all()

    teams = [
        MeTeam(
            id=str(team.team_id),
            name=team.name,
            role=member.role,
            can_write=member.can_write,
        )
        for (member, team) in rows
    ]

    # Only Keycloak tokens carry an email. API-key / internal-JWT auth
    # populates AuthContext.agent_name with the agent name, not an email
    # — surfacing that as `email` would make the dashboard render
    # gibberish for service-account callers. Leave empty and let the
    # client decide whether to render or hide.
    email = auth.agent_name if auth.auth_method == "keycloak" else ""

    payload = MeResponse(
        user_id=str(auth.user_id),
        email=email,
        org_id=scope.org_id,
        # Org name is not stored anywhere yet — best-effort: use org_id.
        # When an Org table lands (post-MVP), populate properly.
        org_name=scope.org_id,
        teams=teams,
        roles=list(scope.roles),
    )

    # ETag for cheap revalidation on focus refresh.
    body = payload.model_dump_json()
    etag = '"' + hashlib.sha256(body.encode("utf-8")).hexdigest()[:16] + '"'
    if if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=60"
    return payload
