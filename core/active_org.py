"""
Kemory — Active-org resolution seam (ADR-012 Phase 2).

This module is the single place kemory decides *which org a request is
authorized against*. Every tenant-scoped read and write funnels through
``require_auth`` (see backend/core/auth.py), which calls
``resolve_active_org`` exactly once per request and overwrites
``AuthContext.org_id`` / ``.org_role`` / ``.org_type`` with the result.
Downstream — the SQLAlchemy tenant filter, ``get_tenant_scope``, and the
write path that stamps ``org_id=auth.org_id`` — all inherit that value with
no further plumbing.

Today the body is the identity function: it returns whatever org the auth
path already put on the token (the single ``org_id`` claim, ADR-004 mirror).
This is a pure refactor — no behavior change for single-org users.

The mechanism the Phase 0 spike picks (ADR-012 Part 2) replaces only the
return value here:

  * M2 (mint-time callback) — the verified token already carries the active
    ``org_id`` + ``org_role`` + ``org_type`` (``token_org_ver=2``); read them
    from the claims.
  * M3 (resolve-at-resource) — read the *validated* ``X-Organization-ID``
    request input (never trusted; an input, not a trust boundary), resolve
    ``(sub, active_org) -> role`` against core_backend membership behind a
    short-TTL cache, and fail **closed** (deny ⇒ empty org_id ⇒ downstream
    401) when core_backend is unreachable.

``request`` and ``db`` are in the signature now because M2/M3 need them
(the active-org header, the membership lookup). The signature is the
forward-compatible part; the body is not gated by any flag.

Notes for the M2/M3 follow-ups (S3):
  * "No active org → 401" is THIS seam's decision. Legacy/M2 keep the
    missing-org enforce check where it is today (claim time, in
    ``_try_keycloak``). M3 must move it to post-resolution, because an M3
    token is thin (no ``org_id`` claim) by design.
  * ``require_auth`` runs per request, so the M3 body MUST cache — otherwise
    every request triggers a core_backend membership call.
  * Resolution keys off ``auth.user_id``. Today acting-as (X-Acting-User-Id)
    only records ``acting_user_id`` and does not swap ``user_id``, so this is
    correct. When full delegation lands, resolve AFTER the user_id swap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.services.auth_service import AuthContext


@dataclass(frozen=True)
class ResolvedActiveOrg:
    """The org a request is authorized against, plus the caller's role in it.

    ``org_role`` is ``None`` until a resolution mechanism (M2/M3) populates
    it; a ``None`` role means "no role information" and write gates treat it
    permissively, preserving today's behavior.
    """

    org_id: str
    org_role: str | None = None  # owner | admin | member | None
    org_type: str | None = None  # personal | organisation | family | None


async def resolve_active_org(
    auth: AuthContext,
    request: Request,
    db: AsyncSession,
) -> ResolvedActiveOrg:
    """Resolve the active org + role for this request.

    Today: identity — the org the auth path already put on the token. The
    M2 (claims) / M3 (cached membership resolve) bodies replace this return
    when the Phase 0 spike decides; that is the only line that changes.
    """
    return ResolvedActiveOrg(org_id=auth.org_id or "")
