"""
Kemory — Tenant scope (WS-3 foundation).

This module is the single entry point for tenant context inside route
handlers and services. It exposes:

    * TenantScope             — request-scoped (org_id, team_ids, roles)
    * TenantScopeDep          — FastAPI Depends(...) shorthand
    * tenant_scoped_models()  — registry of models the global filter applies to
    * apply_tenant_filter()   — helper that injects WHERE org_id = :caller_org

The actual SQLAlchemy global query filter is wired into get_db() in a
follow-up commit (under WS-3) so this scaffold can land independently
behind TENANT_ENFORCEMENT='off'. Until the filter is wired and the flag
is flipped to 'shadow' or 'enforce', this module is read-only context.

Design choices (recorded so they survive the next reviewer):

  * `org_id` is a string, not a UUID. This matches the Cognition OS graph
    model (cognition_os/src/models/graph_models.py:30) and the CCB Kafka
    envelope. We do not invent a kemory-specific UUID.

  * 404, never 403, on cross-org. Industry standard for tenant isolation
    — 403 leaks the fact that a resource exists in another tenant.

  * Defense in depth. Every tenant-scoped query goes through THREE layers:
      1. Request-scope filter (this dep) — typed, explicit
      2. SQLAlchemy with_loader_criteria — catches forgotten manual filters
      3. require_user / Gatekeeper — catches owner-vs-tenant mismatches
    Any single layer being bypassed (refactor, raw SQL, new endpoint)
    is caught by the others.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable, Type

import structlog
from fastapi import Depends, HTTPException, status

from backend.config.settings import settings
from backend.core.auth import require_auth
from backend.core.database import Base
from backend.services.auth_service import AuthContext

logger = structlog.get_logger(__name__)


# ─── Public types ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TenantScope:
    """Resolved per-request tenant context.

    Frozen so handlers can't accidentally mutate it mid-request. If you
    need to fork the scope (e.g. an admin elevating to a different org for
    a single read), use `dataclasses.replace`.
    """

    org_id: str
    team_ids: tuple[str, ...]
    roles: tuple[str, ...]
    user_id: str  # str form for use in raw SQL bind params

    @property
    def is_legacy(self) -> bool:
        """True when the caller is on the migration sentinel (pre-WS-2)."""
        return self.org_id == settings.tenant_legacy_sentinel


# ─── Request dependency ────────────────────────────────────────────────────


async def get_tenant_scope(
    auth: AuthContext = Depends(require_auth),
) -> TenantScope:
    """FastAPI dependency that resolves AuthContext → TenantScope.

    Behaviour by settings.tenant_enforcement:

      "off"     → always returns the scope (org_id may be the sentinel)
      "shadow"  → returns the scope, logs a violation if org_id is sentinel
      "enforce" → raises 401 if org_id is sentinel (no legacy callers allowed)

    team_ids is empty in this foundation branch. WS-4 wires the
    team_resolver in here so team-tier visibility can be enforced.
    """
    mode = settings.tenant_enforcement
    org_id = auth.org_id or settings.tenant_legacy_sentinel

    if org_id == settings.tenant_legacy_sentinel:
        if mode == "enforce":
            logger.warning(
                "kemory.tenancy.legacy_blocked",
                user_id=str(auth.user_id),
                auth_method=auth.auth_method,
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing_org_claim",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if mode == "shadow":
            logger.warning(
                "kemory.tenancy.violation",
                kind="legacy_org",
                user_id=str(auth.user_id),
                auth_method=auth.auth_method,
                mode=mode,
            )

    return TenantScope(
        org_id=org_id,
        team_ids=tuple(auth.team_ids),
        roles=tuple(auth.roles),
        user_id=str(auth.user_id),
    )


# Convenience alias so handlers can `Depends(TenantScopeDep)` without an
# import of `Depends` and the function — keeps route signatures clean.
TenantScopeDep = Depends(get_tenant_scope)


# ─── Model registry ────────────────────────────────────────────────────────


# Models that carry an org_id column and should be touched by the global
# filter. Listed by string name to avoid a circular import at module load —
# the filter wiring imports them lazily.
TENANT_SCOPED_MODEL_NAMES: tuple[str, ...] = (
    "Memory",
    "AgentRegistry",
    "AuditLog",
    "PermissionRule",
)


def tenant_scoped_models() -> Iterable[Type[Base]]:
    """Yield the model classes that have an org_id column.

    Resolved by class name from SQLAlchemy's registry so this module can
    be imported before models — and because importing each model directly
    risks pulling in the API layer (see CLAUDE.md note about
    src.api.__init__ side-effects).
    """
    for mapper in Base.registry.mappers:  # type: ignore[attr-defined]
        cls = mapper.class_
        if cls.__name__ in TENANT_SCOPED_MODEL_NAMES:
            yield cls


# ─── Helper for explicit query scoping ────────────────────────────────────


def apply_tenant_filter(stmt, model: Type[Base], scope: TenantScope):
    """Apply WHERE org_id = :caller_org_id to a Select statement.

    Use this when you already have a `select(Model)` and want explicit
    org filtering before the global SQLAlchemy filter (WS-3 follow-up)
    is in place. After the global filter ships this becomes a no-op
    safety net — calling it twice is harmless because the predicate is
    idempotent.

    Example:
        stmt = select(Memory).where(Memory.user_id == auth.user_id)
        stmt = apply_tenant_filter(stmt, Memory, scope)
    """
    return stmt.where(model.org_id == scope.org_id)
