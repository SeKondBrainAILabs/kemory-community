"""
Kemory — per-tenant rate limiting middleware.

Wraps backend/core/rate_limit.py with a tenant-aware key. Lets us cap a
noisy org without affecting the rest of the platform — a hard requirement
for "popular worldwide" because one customer's misconfigured agent at
1000 RPS will otherwise DoS everyone else.

Tiering
-------
The middleware checks two limits in series:

  1. Per-org   — caps the whole tenant. Generous default, override via
                 settings.tenant_rps_per_org.
  2. Per-user  — caps an individual user inside an org so one
                 user can't burn the whole org's budget.

Unauthenticated requests (no TenantScope) fall back to the existing
IP-based limiter in core/rate_limit.py.

Failure mode
------------
Redis-down → fail open (don't block traffic). The existing rate_limit.py
already does this; we keep the same behaviour.
"""

from __future__ import annotations

import structlog
from fastapi import HTTPException, Request, status

from backend.config.settings import settings
from backend.core.redis import redis_client

logger = structlog.get_logger(__name__)


async def _bump_and_check(key: str, max_requests: int, window: int) -> None:
    """Increment the counter for ``key``, raise 429 if it exceeds ``max_requests``.

    Soft-fails to allow on Redis errors so an outage doesn't take the
    platform down with it.
    """
    if redis_client is None:
        return
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, window)
        if count > max_requests:
            ttl = await redis_client.ttl(key)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "scope": key.split(":")[1] if ":" in key else "unknown",
                    "retry_after_seconds": ttl if ttl > 0 else window,
                },
                headers={"Retry-After": str(max(ttl, 1))},
            )
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        logger.warning("tenant_rate_limit.redis_failed", error=str(exc), fail_open=True)


async def tenant_rate_limit_middleware(request: Request, call_next):
    """ASGI-style middleware. Reads the TenantScope contextvars set by
    backend.core.tenancy and applies per-org + per-user counters.

    Mounted near the top of the middleware stack (after auth resolves
    the request, before route handlers run).
    """
    # Lazy import to avoid the module-load cycle:
    # tenancy → auth_service → settings → ... → tenant_rate_limit
    from backend.core.tenancy import current_org_id, current_user_id

    org = current_org_id()
    user = current_user_id()
    window = settings.tenant_rate_limit_window_seconds

    if org and org != settings.tenant_legacy_sentinel:
        await _bump_and_check(
            f"rl:org:{org}",
            settings.tenant_rps_per_org * window,
            window,
        )
        if user:
            await _bump_and_check(
                f"rl:user:{org}:{user}",
                settings.tenant_rps_per_user * window,
                window,
            )

    return await call_next(request)
