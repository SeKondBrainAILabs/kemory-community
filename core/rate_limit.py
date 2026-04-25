"""
S9N Memory Vault — Simple Redis Rate Limiter

Sliding-window rate limiter using Redis INCR + EXPIRE.
Use as a FastAPI dependency on endpoints that need protection.
"""
import time
from fastapi import HTTPException, Request, status
import structlog

from backend.core.redis import redis_client

logger = structlog.get_logger(__name__)


def rate_limit(max_requests: int = 10, window_seconds: int = 60):
    """
    FastAPI dependency factory for rate limiting.

    Usage:
        @router.post("/join", dependencies=[Depends(rate_limit(5, 60))])
    """

    async def _check(request: Request) -> None:
        if redis_client is None:
            return  # skip rate limiting if Redis is unavailable

        # Key by IP + path for unauthenticated; auth middleware adds user_id later
        client_ip = request.client.host if request.client else "unknown"
        key = f"rl:{client_ip}:{request.url.path}"

        try:
            count = await redis_client.incr(key)
            if count == 1:
                await redis_client.expire(key, window_seconds)

            if count > max_requests:
                ttl = await redis_client.ttl(key)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Try again in {ttl}s.",
                    headers={"Retry-After": str(ttl)},
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("rate_limit.redis_error", error=str(exc))

    return _check
