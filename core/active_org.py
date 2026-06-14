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

import structlog

from backend.config.settings import settings

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.services.auth_service import AuthContext

logger = structlog.get_logger(__name__)

# Header carrying the caller-requested active org (M3). It is an *input*, never
# trusted — every request validates it against membership — so an unsigned
# header is acceptable here (token-contract §4a).
_ACTIVE_ORG_HEADER = "X-Organization-ID"


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

    ``active_org_mode`` (settings) selects the mechanism:

    * ``legacy`` (default) — identity: the org the auth path already put on the
      token (ADR-004 mirror claim). No behavior change.
    * ``m3`` — resolve-at-resource (spike-ratified for the internal plane).
      For human (keycloak) callers, the active org is the validated
      ``X-Organization-ID`` header (else the token org), and the role is
      resolved against core_backend membership via a cached client. Fails
      CLOSED (empty org → downstream 401) on a non-member or a resolution
      failure. Agents (api_key/jwt) always keep their token-bound org — they
      aren't org-switchable members.
    """
    if settings.active_org_mode != "m3":
        return ResolvedActiveOrg(org_id=auth.org_id or "")

    # M3 applies only to human callers. Agents authenticate with a key/HS256
    # token whose org is bound at issue (AgentRegistry / token claim) and have
    # no Keycloak membership to resolve.
    if auth.auth_method != "keycloak":
        return ResolvedActiveOrg(org_id=auth.org_id or "")

    # Active org = requested header (validated below), else the token's org
    # (the caller's primary / last-active). Empty → nothing to resolve → 401.
    requested = request.headers.get(_ACTIVE_ORG_HEADER) or (auth.org_id or "")
    if not requested or requested == settings.tenant_legacy_sentinel:
        return ResolvedActiveOrg(org_id="")

    sub = str(auth.user_id)
    from backend.services.org_role_resolver import OrgResolveError, resolve_org_role

    try:
        membership = await resolve_org_role(sub, requested)
    except OrgResolveError as exc:
        # Fail closed — never grant a stale/blank scope when the resolver is
        # down (token-contract §7).
        logger.warning("active_org.resolve_failed_fail_closed", sub=sub, org_id=requested, error=str(exc))
        return ResolvedActiveOrg(org_id="")

    if membership.org_role is None:
        # Not a member of the requested org → deny (no leakage).
        logger.info("active_org.non_member_denied", sub=sub, org_id=requested)
        return ResolvedActiveOrg(org_id="")

    return ResolvedActiveOrg(
        org_id=requested,
        org_role=membership.org_role,
        org_type=membership.org_type,
    )
