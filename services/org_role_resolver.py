"""
Kemory — Active-org role resolver (ADR-012 Phase 2, M3).

Resolves a ``(keycloak_sub, org_id) → (org_role, org_type)`` against
core_backend's membership table, behind a two-tier cache. This is the M3
("resolve-at-resource") mechanism the Phase 0 spike ratified for the internal
plane: the active org is never trusted from the token alone — it is validated
against live membership on every request (cached), giving near-immediate
revocation that a token-TTL window can't.

Source of truth
---------------
``GET {core_backend_internal_url}/auth/internal/user-org-role?keycloak_id&org_id``
— a no-auth, IP-restricted internal endpoint that returns
``{org_role, db_user_id, organization}`` for an active membership, or
``{org_role: null, ...}`` for a non-member. (Spike §8.)

> Known core_backend caveat (filed): that endpoint does not yet filter
> ``OrganizationMembership.is_active``, so a *soft-deactivated* member still
> resolves until the one-line fix lands. Hard-removed members resolve to a
> deny immediately. Our cache TTL bounds any additional staleness.

Two-tier cache (mirrors team_resolver)
--------------------------------------
  L1: in-process bounded TTLCache (5s) — absorbs request bursts in one pod.
  L2: Redis (60s) — shared across pods so an N-pod deployment doesn't do N
      cold lookups per (sub, org). Best-effort; falls back to L1+HTTP.

A confirmed non-member (deny) is cached like any result. A *transport
failure* (core_backend unreachable / timeout) is NOT cached and raises
``OrgResolveError`` so the caller can fail closed and retry next request.

Cache invalidation
------------------
``invalidate(sub)`` / ``invalidate_for_org(sub, org_id)`` drop entries so a
membership change propagates ahead of the TTL. Wire these to the
``org.membership.changed`` CCB event for near-immediate revocation (follow-up);
until then the 60s L2 TTL bounds the window.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
import structlog
from cachetools import TTLCache

from backend.config.settings import settings

logger = structlog.get_logger(__name__)

L1_TTL_SECONDS = 5
L1_MAX_ENTRIES = 10_000
L2_TTL_SECONDS = 60
_REDIS_PREFIX = "kemory:orgrole:"

# L1 — bounded TTL/LRU. cachetools.TTLCache is internally locked per-op, so
# single-step access is thread-safe; cold-key stampede is a perf concern only
# (same trade-off as team_resolver).
_l1: TTLCache[tuple[str, str], OrgMembership] = TTLCache(maxsize=L1_MAX_ENTRIES, ttl=L1_TTL_SECONDS)

# Shared async HTTP client, created lazily on first use and reused (connection
# pooling). Never closed for the process lifetime — same lifecycle as the
# Keycloak verifier / redis client.
_client: httpx.AsyncClient | None = None


@dataclass(frozen=True)
class OrgMembership:
    """Resolved membership for a (sub, org). ``org_role is None`` means a
    *confirmed non-member* (deny) — distinct from a resolution failure, which
    raises ``OrgResolveError`` instead of returning this."""

    org_role: str | None  # owner | admin | member | None(=non-member)
    org_type: str | None  # personal | organisation | family | None


class OrgResolveError(RuntimeError):
    """Raised when core_backend can't be reached / returns an unusable response.

    The caller must fail CLOSED (no org → 401), never grant a stale scope.
    """


def _l2_key(sub: str, org_id: str) -> str:
    return f"{_REDIS_PREFIX}{org_id}:{sub}"


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.core_backend_internal_url.rstrip("/"),
            timeout=settings.active_org_resolve_timeout_s,
        )
    return _client


def invalidate(sub: str) -> None:
    """Drop every L1 entry for ``sub`` across all orgs.

    L2 is left to its TTL (no SCAN) — use ``invalidate_for_org`` when the org
    is known (e.g. from an ``org.membership.changed`` event).
    """
    keys = [k for k in _l1 if k[0] == sub]
    for k in keys:
        _l1.pop(k, None)
    if keys:
        logger.info("org_role_resolver.l1_invalidate", sub=sub, count=len(keys))


async def invalidate_for_org(sub: str, org_id: str) -> None:
    """Invalidate both tiers for one (sub, org) — the membership-change path."""
    _l1.pop((sub, org_id), None)
    try:
        from backend.core.redis import redis_client

        if redis_client is not None:
            await redis_client.delete(_l2_key(sub, org_id))
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("org_role_resolver.l2_invalidate_failed", error=str(exc))


async def resolve_org_role(sub: str, org_id: str) -> OrgMembership:
    """Resolve the caller's role + org type for ``(sub, org_id)``.

    Returns ``OrgMembership`` (``org_role=None`` ⇒ confirmed non-member).
    Raises ``OrgResolveError`` if core_backend is unreachable / unusable.
    """
    key = (sub, org_id)

    cached = _l1.get(key)
    if cached is not None:
        return cached

    # L2 — Redis. Best-effort; failures fall through to HTTP.
    try:
        from backend.core.redis import redis_client

        if redis_client is not None:
            raw = await redis_client.get(_l2_key(sub, org_id))
            if raw is not None:
                try:
                    data = json.loads(raw)
                    m = OrgMembership(org_role=data.get("org_role"), org_type=data.get("org_type"))
                    _l1[key] = m
                    return m
                except json.JSONDecodeError:
                    pass  # corrupt entry — fall through
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("org_role_resolver.l2_read_failed", error=str(exc))

    # Source: core_backend internal endpoint.
    try:
        resp = await _get_client().get(
            "/auth/internal/user-org-role",
            params={"keycloak_id": sub, "org_id": org_id},
        )
    except httpx.HTTPError as exc:
        logger.warning("org_role_resolver.core_backend_unreachable", error=str(exc), org_id=org_id)
        raise OrgResolveError(str(exc)) from exc

    if resp.status_code >= 500:
        logger.warning("org_role_resolver.core_backend_5xx", status=resp.status_code, org_id=org_id)
        raise OrgResolveError(f"core_backend {resp.status_code}")
    if resp.status_code != 200:
        # 4xx (e.g. 422 bad params) — treat as a deny, but don't cache an
        # error shape; safest is to deny this request without poisoning cache.
        logger.warning("org_role_resolver.unexpected_status", status=resp.status_code, org_id=org_id)
        return OrgMembership(org_role=None, org_type=None)

    try:
        body = resp.json()
    except ValueError as exc:
        raise OrgResolveError("core_backend non-json response") from exc

    org = body.get("organization") or {}
    m = OrgMembership(
        org_role=body.get("org_role"),
        # Endpoint doesn't return space_type today; tolerate either key.
        org_type=org.get("space_type") or body.get("org_type"),
    )

    _l1[key] = m
    # Best-effort populate L2 — failures don't fail the request.
    try:
        from backend.core.redis import redis_client

        if redis_client is not None:
            await redis_client.set(
                _l2_key(sub, org_id),
                json.dumps({"org_role": m.org_role, "org_type": m.org_type}),
                ex=L2_TTL_SECONDS,
            )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("org_role_resolver.l2_write_failed", error=str(exc))

    return m
