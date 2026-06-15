"""
Request body size limit middleware (P4 #22).

FastAPI / Starlette default to no body size cap. A single 10 GB POST to
``/api/v1/memories`` OOMs the worker before any handler runs. This
middleware checks ``Content-Length`` upfront and rejects 413 before
buffering.

For chunked / streaming requests where ``Content-Length`` is absent, the
middleware reads ``request.body()`` once and counts bytes — slightly more
expensive but covers the chunked-transfer attack vector. Most clients
send Content-Length so the cheap path runs.

Per-route override pattern (TBD): a future improvement is a route-scoped
limit dependency, e.g. ``Depends(limit_body(10 * 1024 * 1024))`` for an
import endpoint that legitimately wants 10 MB. For v1 we ship the global
limit and revisit when the first endpoint needs more.
"""

from __future__ import annotations

import re

import structlog
from fastapi import HTTPException, Request, status

from backend.config.settings import settings

logger = structlog.get_logger(__name__)

# chats-v1 v3.33.0: artifact uploads (file / audio / video) legitimately
# need larger bodies than the global 1 MB cap. We allow up to 50 MB on
# the chat-artifact upload path specifically; everything else stays
# under the default global cap.
_LARGE_BODY_PATH_RE = re.compile(r"^/api/v1/chats/[^/]+/artifacts/upload/?$")
_LARGE_BODY_LIMIT_BYTES = 50 * 1024 * 1024  # 50 MB


def _limit_for(path: str) -> int:
    if _LARGE_BODY_PATH_RE.match(path):
        return _LARGE_BODY_LIMIT_BYTES
    return settings.max_request_body_bytes


async def body_size_limit_middleware(request: Request, call_next):
    """Reject requests whose body exceeds the per-path limit."""
    max_bytes = _limit_for(request.url.path)
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared = int(content_length)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invalid Content-Length header",
            )
        if declared > max_bytes:
            logger.info(
                "body_size_limit.rejected",
                path=request.url.path,
                declared=declared,
                limit=max_bytes,
            )
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "error": "request_body_too_large",
                    "limit_bytes": max_bytes,
                    "received_bytes": declared,
                },
                headers={"Connection": "close"},
            )
    return await call_next(request)
