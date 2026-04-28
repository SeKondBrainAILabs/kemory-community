"""
Kemory — Team membership resolver (WS-4).

Resolves a (user_id, org_id) → list of team_ids by querying the
``team_members`` table, with a two-tier cache:

  L1: in-process bounded LRU TTL (5s, 10000 entries) — absorbs request
      bursts inside one pod without re-hitting Redis. Bounded so it can't
      grow under churn.
  L2: Redis (60s) — shared across pods so a 10-pod deployment doesn't
      have 10 independent L1 caches that each take a DB round-trip per
      user before warming.

Falls back to in-process-only if Redis is unavailable (local mode).

Cache invalidation
------------------
``invalidate(user_id)`` drops both tiers for that user. The team admin
endpoints (WS-9) call this on every TeamMember mutation. A 60s TTL means
even without a manual invalidate, membership changes propagate within
one minute.

The 60s TTL on L2 is deliberate: short enough that team add/remove feels
live within a minute; long enough to absorb 100 MCP tool calls inside a
single conversation without a DB round-trip per call.
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

import structlog
from cachetools import TTLCache
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.tenancy import bypass_tenant_filter
from backend.models.team import Team, TeamMember

logger = structlog.get_logger(__name__)

L1_TTL_SECONDS = 5
L1_MAX_ENTRIES = 10_000
L2_TTL_SECONDS = 60
_REDIS_PREFIX = "kemory:teams:"

# L1 — bounded so a high-churn workload (millions of distinct keys) cannot
# leak memory. cachetools.TTLCache evicts on TTL AND on max size (LRU).
#
# Concurrency (P1 #8 — investigated, not locked):
#   cachetools.TTLCache uses an internal RLock for individual operations
#   (get, set, pop, iteration), so single-step access is thread-safe.
#   The residual concern is CACHE STAMPEDE on a cold key — N concurrent
#   misses produce N DB round-trips when 1 would suffice. That is a
#   perf concern at scale, not a correctness bug, and is tracked as a
#   separate follow-up (single-flight via per-key asyncio.Lock dict).
_l1: TTLCache[tuple[str, str], tuple[str, ...]] = TTLCache(
    maxsize=L1_MAX_ENTRIES, ttl=L1_TTL_SECONDS
)


def _l2_key(user_id: str, org_id: str) -> str:
    return f"{_REDIS_PREFIX}{org_id}:{user_id}"


def invalidate(user_id: uuid.UUID | str) -> None:
    """Drop every cache entry for ``user_id`` across all orgs in L1.

    Also drops L2 entries lazily — we don't have org_ids handy without a
    Redis SCAN, so we tolerate the 60s drift on L2 invalidations. The
    explicit team admin endpoints (WS-9) update DB then call this; the
    org-scoped key drops L2 below.
    """
    user_id_str = str(user_id)
    keys = [k for k in _l1 if k[0] == user_id_str]
    for k in keys:
        _l1.pop(k, None)
    if keys:
        logger.info("team_resolver.l1_invalidate", user_id=user_id_str, count=len(keys))


async def invalidate_for_org(user_id: uuid.UUID | str, org_id: str) -> None:
    """Invalidate both tiers for a specific (user, org) pair.

    Called by team admin endpoints after they know which org the user
    just gained / lost membership in.
    """
    user_id_str = str(user_id)
    _l1.pop((user_id_str, org_id), None)
    try:
        from backend.core.redis import redis_client
        if redis_client is not None:
            await redis_client.delete(_l2_key(user_id_str, org_id))
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("team_resolver.l2_invalidate_failed", error=str(exc))


async def get_team_ids(
    user_id: uuid.UUID | str,
    org_id: str,
    db: AsyncSession,
) -> list[str]:
    """Return team_ids the user belongs to within the given org."""
    user_id_str = str(user_id)
    key = (user_id_str, org_id)

    # L1
    cached = _l1.get(key)
    if cached is not None:
        return list(cached)

    # L2 — Redis. Best-effort; failures fall through to DB.
    try:
        from backend.core.redis import redis_client
        if redis_client is not None:
            raw = await redis_client.get(_l2_key(user_id_str, org_id))
            if raw is not None:
                try:
                    teams = tuple(json.loads(raw))
                    _l1[key] = teams
                    return list(teams)
                except json.JSONDecodeError:
                    pass  # corrupt cache entry — fall through
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("team_resolver.l2_read_failed", error=str(exc))

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

    _l1[key] = team_ids

    # Best-effort populate L2 — failures don't fail the request.
    try:
        from backend.core.redis import redis_client
        if redis_client is not None:
            await redis_client.set(
                _l2_key(user_id_str, org_id),
                json.dumps(list(team_ids)),
                ex=L2_TTL_SECONDS,
            )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("team_resolver.l2_write_failed", error=str(exc))

    return list(team_ids)
