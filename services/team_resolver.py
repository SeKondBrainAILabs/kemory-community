"""
Kemory — Team membership resolver (WS-4).

Resolves a (user_id, org_id) → list of team_ids by querying the
``team_members`` table, with a 60-second in-process LRU cache so chatty
MCP traffic doesn't hammer Postgres.

Cache invalidation
------------------
Calls to ``invalidate(user_id)`` clear the cache for that user. The admin
endpoints that mutate TeamMember rows (WS-9) call this; future improvements
might wire SQLAlchemy after_insert / after_delete events to make it fully
automatic.

The 60-second TTL is deliberate: short enough that team add/remove feels
live within a minute; long enough to absorb 100 MCP tool calls inside a
single conversation without a DB round-trip per call.
"""
from __future__ import annotations

import time
import uuid
from typing import Optional

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.tenancy import bypass_tenant_filter
from backend.models.team import Team, TeamMember

logger = structlog.get_logger(__name__)

_CACHE_TTL_SECONDS = 60
_cache: dict[tuple[str, str], tuple[tuple[str, ...], float]] = {}


def invalidate(user_id: str) -> None:
    """Drop every cache entry for ``user_id`` across all orgs."""
    keys = [k for k in _cache if k[0] == user_id]
    for k in keys:
        _cache.pop(k, None)
    if keys:
        logger.info("team_resolver.invalidate", user_id=user_id, count=len(keys))


async def get_team_ids(
    user_id: uuid.UUID | str,
    org_id: str,
    db: AsyncSession,
) -> list[str]:
    """Return team_ids the user belongs to within the given org."""
    user_id_str = str(user_id)
    now = time.monotonic()
    key = (user_id_str, org_id)

    cached = _cache.get(key)
    if cached and cached[1] > now:
        return list(cached[0])

    # Bypass the tenant filter for this lookup — the resolver runs at
    # request-bind time before TenantScope is fully populated, and we
    # explicitly scope by (user_id, org_id) in the query itself.
    with bypass_tenant_filter():
        stmt = (
            select(TeamMember.team_id)
            .join(Team, Team.team_id == TeamMember.team_id)
            .where(
                TeamMember.user_id == user_id,
                Team.org_id == org_id,
                Team.is_deleted == False,  # noqa: E712 — SQL needs ==
            )
        )
        result = await db.execute(stmt)
        team_ids = tuple(str(t) for (t,) in result.all())

    _cache[key] = (team_ids, now + _CACHE_TTL_SECONDS)
    return list(team_ids)
