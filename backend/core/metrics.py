"""
Prometheus metrics for kemory — per-org HTTP observability (WS-8).

Why prometheus_client and not OTEL
-----------------------------------
The deployment sets ``OTEL_*`` env vars, but no OTEL SDK instrumentation is
initialised in the app, so nothing actually reaches the collector (verified
2026-05-26: kemory is absent from Tempo span-metrics and exports no
``http_server_*`` series to Prometheus). Rather than stand up the full OTEL
metrics pipeline, we expose a ``/metrics`` endpoint scraped by Prometheus
directly — matching how core-backend / pulse-bff already expose
``http_requests_total``.

The ``org_id`` label is what makes WS-8's per-org dashboard possible.
Cardinality is safe:
- ``org_id``  — tens of orgs (low). Safe as a label, per ADR-004 / WS-8 note.
- ``route``   — the TEMPLATED path (``/api/v1/memories/{memory_id}``), not the
  raw URL, so UUIDs don't explode the series count. Unmatched paths (404s,
  scanners) collapse to a single ``"unmatched"`` series.
- ``status`` / ``method`` — bounded.

org_id propagation
------------------
``get_tenant_scope`` stashes the resolved org on ``request.state.org_id``.
We read it from ``request.state`` (shared across the BaseHTTPMiddleware
boundary via the ASGI scope) rather than the ``current_org_id()`` ContextVar,
because ContextVars set inside the endpoint are not reliably visible in a
BaseHTTPMiddleware after ``call_next`` (it runs the downstream app in a
separate anyio task). Routes without tenant scope (health, unauthenticated,
pre-auth rejections like 429/413) record ``org_id="none"`` — correct, those
aren't tenant-attributable.
"""

from __future__ import annotations

import time

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.requests import Request
from starlette.responses import Response

REQUESTS = Counter(
    "kemory_http_requests_total",
    "Total kemory HTTP requests, labelled by org.",
    ["method", "route", "status", "org_id"],
)

DURATION = Histogram(
    "kemory_http_request_duration_seconds",
    "kemory HTTP request duration in seconds, labelled by org.",
    ["method", "route", "org_id"],
    # API-shaped buckets: sub-10ms to 10s.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# Never count these — avoids scrape feedback loops and health-probe noise.
_SKIP_PATHS = frozenset({"/metrics", "/health", "/health/live", "/health/ready", "/health/deep"})


def _route_template(request: Request) -> str:
    """Return the matched route's templated path, or 'unmatched'.

    Using the template (``/api/v1/memories/{memory_id}``) instead of the raw
    path keeps cardinality bounded — without this, every UUID in a URL would
    mint a new time series.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if path else "unmatched"


async def metrics_middleware(request: Request, call_next):
    """Record per-request count + duration, labelled by org.

    Wraps the whole stack so it also counts pre-auth rejections (429/413).
    Records in a ``finally`` so unhandled exceptions still increment as 500 —
    important for the error-rate panel.
    """
    if request.url.path in _SKIP_PATHS:
        return await call_next(request)

    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        elapsed = time.perf_counter() - start
        org_id = getattr(request.state, "org_id", "none") or "none"
        route = _route_template(request)
        REQUESTS.labels(request.method, route, str(status_code), org_id).inc()
        DURATION.labels(request.method, route, org_id).observe(elapsed)


async def metrics_endpoint(request: Request) -> Response:
    """Prometheus scrape endpoint. No auth (oauth2-proxy skip-auth ^/metrics)."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
