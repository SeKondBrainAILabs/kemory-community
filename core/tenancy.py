"""
Kemory — Tenant scope and SQLAlchemy global query filter.

This module is the single source of truth for tenant context inside route
handlers, services, and the ORM. It exposes:

  * TenantScope                     — frozen per-request (org_id, team_ids, roles)
  * get_tenant_scope                — FastAPI dependency
  * TenantScopeDep                  — Depends(...) shorthand
  * tenant_scoped_models()          — registry of models the global filter applies to
  * register_tenant_filter()        — wires the SQLAlchemy do_orm_execute listener
  * apply_tenant_filter()           — explicit Select-helper (defense in depth)

How it works
------------
1. On every authenticated request, ``get_tenant_scope`` reads
   ``AuthContext.org_id`` and stashes it into context-local variables.
2. A SQLAlchemy ``do_orm_execute`` event listener, registered against the
   AsyncSession factory at import time, intercepts every SELECT against a
   tenant-scoped model and injects ``WHERE org_id = :current_org_id`` via
   ``with_loader_criteria``.
3. For ``Memory`` specifically, the listener also injects the visibility-
   tier predicate (private | team | org) so a memory tagged ``team`` is
   only visible to TeamMembers of that team.

The listener applies to SELECT only. INSERT / UPDATE / DELETE go through
unaffected — handlers must still use ``apply_tenant_filter`` or set
``org_id`` explicitly when writing. This split is intentional:
  - Reads need a safety net (forgotten WHERE clauses leak data).
  - Writes need explicit intent (the caller must pick which tenant a row
    belongs to). Letting the listener auto-tag writes would silently move
    cross-org data on a sloppy refactor.

Bypassing the filter
--------------------
For admin / migration / health-check code paths that genuinely need cross-
tenant access, use ``with bypass_tenant_filter():`` — a context manager
that flips a contextvar the listener checks before injecting. Logged.

Design choices
--------------
* ``org_id`` is a string (matches Cognition OS / CCB envelope).
* Default mode is ``enforce``: a request without an org_id is rejected 401.
* No legacy sentinel for new writes — kemory is greenfield, every request
  must carry an org_id. The migration sentinel ``legacy`` is only used for
  any rows accidentally produced before WS-2 is plumbed end-to-end and is
  treated as a bug, not a fallback.
"""
from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable, Iterator, Type

import structlog
from fastapi import Depends, HTTPException, status
from sqlalchemy import event, or_
from sqlalchemy.orm import Session, with_loader_criteria

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config.settings import settings
from backend.core.auth import require_auth
from backend.core.database import Base, get_db
from backend.services.auth_service import AuthContext

logger = structlog.get_logger(__name__)


# ─── Public types ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TenantScope:
    """Resolved per-request tenant context.

    Frozen so handlers can't accidentally mutate it mid-request. If you
    need to fork the scope (e.g. an admin elevating to a different org for
    a single read), use ``dataclasses.replace`` and ``set_current_scope``.
    """

    org_id: str
    team_ids: tuple[str, ...]
    roles: tuple[str, ...]
    user_id: str  # str form for use in raw SQL bind params

    @property
    def is_legacy(self) -> bool:
        """True when the caller is on the migration sentinel — a bug."""
        return self.org_id == settings.tenant_legacy_sentinel

    def has_role(self, role: str) -> bool:
        return role in self.roles


# ─── Context variables ─────────────────────────────────────────────────────
# These thread the active tenant context through async call stacks without
# requiring every function signature to take a TenantScope. The ORM event
# listener reads them; handlers should use the FastAPI dependency above.

_current_org_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "kemory_current_org_id", default=""
)
_current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "kemory_current_user_id", default=""
)
_current_team_ids: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar(
    "kemory_current_team_ids", default=()
)
_bypass_filter: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "kemory_bypass_tenant_filter", default=False
)


def current_org_id() -> str:
    """Return the request-bound org_id or '' when no scope is active."""
    return _current_org_id.get()


def current_user_id() -> str:
    return _current_user_id.get()


def current_team_ids() -> tuple[str, ...]:
    return _current_team_ids.get()


@contextmanager
def bypass_tenant_filter() -> Iterator[None]:
    """Context manager that disables the global filter for the duration.

    Use only for admin / migration / health-check paths that genuinely
    need cross-tenant reads. Every entry is logged for audit.
    """
    token = _bypass_filter.set(True)
    logger.warning("kemory.tenancy.bypass.enter")
    try:
        yield
    finally:
        _bypass_filter.reset(token)
        logger.warning("kemory.tenancy.bypass.exit")


# ─── Request dependency ────────────────────────────────────────────────────


async def get_tenant_scope(
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> TenantScope:
    """FastAPI dependency that resolves AuthContext → TenantScope.

    Sets context variables for the lifetime of the request so the SQLAlchemy
    listener can read them without further plumbing. In ``enforce`` mode,
    requests missing an org_id are rejected 401 here so handlers never run
    against an empty tenant scope.
    """
    mode = settings.tenant_enforcement
    org_id = auth.org_id or ""

    if not org_id or org_id == settings.tenant_legacy_sentinel:
        if mode == "enforce":
            logger.warning(
                "kemory.tenancy.no_org_blocked",
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
                kind="legacy_or_missing_org",
                user_id=str(auth.user_id),
                auth_method=auth.auth_method,
                mode=mode,
            )
        # off / shadow: tolerate, but the listener will skip filtering
        # when org_id is empty so reads return nothing rather than leaking.
        org_id = org_id or settings.tenant_legacy_sentinel

    # WS-4: resolve teams server-side. The token never carries team_ids
    # because team membership is product data that changes faster than a
    # token TTL; a 60-second cache makes this cheap.
    from backend.services.team_resolver import get_team_ids
    try:
        team_ids = tuple(await get_team_ids(auth.user_id, org_id, db))
    except Exception as exc:
        # Don't let a transient DB hiccup break auth — log and proceed
        # with an empty team list (caller still sees their private memories).
        logger.warning("team_resolver.failed", error=str(exc), user_id=str(auth.user_id))
        team_ids = ()

    scope = TenantScope(
        org_id=org_id,
        team_ids=team_ids,
        roles=tuple(auth.roles),
        user_id=str(auth.user_id),
    )
    _current_org_id.set(scope.org_id)
    _current_user_id.set(scope.user_id)
    _current_team_ids.set(scope.team_ids)
    return scope


TenantScopeDep = Depends(get_tenant_scope)


# ─── Model registry ────────────────────────────────────────────────────────


# Models that carry an org_id column and should be touched by the global
# filter. Listed by string name to avoid a circular import at module load —
# the filter wiring resolves them lazily from SQLAlchemy's mapper registry.
TENANT_SCOPED_MODEL_NAMES: tuple[str, ...] = (
    "Memory",
    "AgentRegistry",
    "AuditLog",
    "PermissionRule",
    "Team",
)


def tenant_scoped_models() -> Iterable[Type[Base]]:
    """Yield the model classes that have an org_id column."""
    for mapper in Base.registry.mappers:  # type: ignore[attr-defined]
        cls = mapper.class_
        if cls.__name__ in TENANT_SCOPED_MODEL_NAMES:
            yield cls


# ─── SQLAlchemy global filter ──────────────────────────────────────────────


def _build_tenant_predicate(model_cls):
    """Build the criterion expression for ``model_cls`` using the current
    request scope from ContextVars.

    Reads the ContextVars at call time and returns a fully-bound SQL
    expression. We do NOT return a callable / lambda — SQLAlchemy's
    with_loader_criteria lambda-extraction layer rejects ContextVar
    lookups in lambda bodies (it tries to extract bound values without
    invoking the function, which fails on contextvar reads). By building
    the expression eagerly here and passing the resulting SQL element to
    with_loader_criteria, we sidestep the lambda system entirely.
    """
    name = model_cls.__name__
    org_id = _current_org_id.get()
    user_id = _current_user_id.get()
    team_ids = _current_team_ids.get()

    if not org_id:
        # No active scope — emit an always-false predicate so a forgotten
        # request context can't accidentally leak rows. Background tasks
        # / migrations that need cross-tenant access must use
        # ``with bypass_tenant_filter():``.
        return model_cls.org_id == "__no_active_scope__"

    if name == "Memory":
        visibility_clauses = [
            model_cls.user_id == user_id,
            model_cls.visibility == "org-public",
        ]
        if team_ids:
            visibility_clauses.append(
                (model_cls.visibility == "team") & model_cls.team_id.in_(team_ids)
            )
        return (model_cls.org_id == org_id) & or_(*visibility_clauses)

    # All other tenant-scoped models: simple org_id equality.
    return model_cls.org_id == org_id


def register_tenant_filter(session_class) -> None:
    """Attach a do_orm_execute listener to the given session class.

    Idempotent — safe to call multiple times. Wires every tenant-scoped
    model's predicate via ``with_loader_criteria`` so SELECTs are filtered
    at compilation time.
    """
    if getattr(session_class, "_kemory_tenant_filter_registered", False):
        return

    @event.listens_for(session_class, "do_orm_execute")
    def _do_orm_execute(orm_execute_state):  # type: ignore[no-untyped-def]
        # Skip non-SELECT statements (writes need explicit org_id).
        if not orm_execute_state.is_select:
            return
        # Allow caller-controlled bypass for admin / health paths.
        if _bypass_filter.get():
            return

        # Only attach criteria for models actually referenced by this
        # statement. Walking the full tenant_scoped_models() set on every
        # query inflates compile cost linearly with the number of
        # tenant-scoped models — and was wasteful for queries against
        # non-tenant tables (Waitlist, ConsentRequest, ReferralEvent).
        try:
            referenced = {
                desc.get("entity") or desc.get("type")
                for desc in orm_execute_state.statement.column_descriptions
                if desc.get("entity") or desc.get("type")
            }
        except (AttributeError, TypeError):
            # Statements without column_descriptions (e.g. raw text) get
            # the full apply — defensive default.
            referenced = None

        scoped = list(tenant_scoped_models())
        for cls in scoped:
            if referenced is not None and cls not in referenced:
                continue
            # Build the criterion eagerly here using the current request
            # scope. We pass the resulting SQL expression directly to
            # with_loader_criteria — no callable / lambda wrapper. This
            # sidesteps SQLAlchemy's lambda-extraction layer which would
            # reject ContextVar lookups inside a closure body.
            orm_execute_state.statement = orm_execute_state.statement.options(
                with_loader_criteria(
                    cls,
                    _build_tenant_predicate(cls),
                    include_aliases=True,
                )
            )

    session_class._kemory_tenant_filter_registered = True  # type: ignore[attr-defined]


# ─── Helper for explicit query scoping (defense in depth) ─────────────────


def apply_tenant_filter(stmt, model: Type[Base], scope: TenantScope):
    """Apply WHERE org_id = :caller_org_id to a Select statement.

    The global listener already does this for any SELECT, but calling it
    explicitly in handlers documents intent and survives a future refactor
    that disables the listener (e.g. a new test harness). Idempotent —
    calling twice produces a redundant predicate, never an error.
    """
    return stmt.where(model.org_id == scope.org_id)
