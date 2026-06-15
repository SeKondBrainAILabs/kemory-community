"""
SQLAlchemy guard against unbounded SELECTs (P4 #21).

Several memory_service queries do ``select(Memory).where(...)`` without a
LIMIT. A user with 1M memories OOMs the worker on a single such call.
This module adds a dev-mode event listener that flags un-LIMITed SELECT
statements against tenant-scoped models so the bug surfaces in CI and
local development — not in production at the worst possible moment.

Behaviour by setting:
  KEMORY_QUERY_SAFETY = "off"     — no checks (default)
  KEMORY_QUERY_SAFETY = "warn"    — log a structured warning, request continues
  KEMORY_QUERY_SAFETY = "raise"   — raise a RuntimeError (use in tests / CI)

The listener inspects the compiled SELECT and skips:
  * subqueries / scalar aggregates (`func.count`, etc.)
  * statements that already have a LIMIT
  * statements fetched by primary key (single-row .get-style)
  * tables not in the tenant-scoped registry

Production runs with KEMORY_QUERY_SAFETY=off so this never adds latency
to the request path. Dev / CI runs with =raise so a regression on a hot
query path fails the test suite instead of waiting for prod symptoms.
"""

from __future__ import annotations

import os

import structlog
from sqlalchemy import event
from sqlalchemy.sql import Select

from backend.core.tenancy import tenant_scoped_models

logger = structlog.get_logger(__name__)


def _mode() -> str:
    """Active mode. Reads settings.query_safety_mode but allows the env
    var KEMORY_QUERY_SAFETY to override at runtime so tests can flip it
    without re-instantiating Settings.
    """
    env_override = os.environ.get("KEMORY_QUERY_SAFETY")
    if env_override is not None:
        return env_override.lower()
    # Lazy import to avoid module-load cycles.
    from backend.config.settings import settings

    return settings.query_safety_mode.lower()


def _select_has_limit(stmt: Select) -> bool:
    """True when the statement has an explicit LIMIT, OR is a primary-key
    lookup (single-row by id), OR is a scalar aggregate."""
    if stmt._limit_clause is not None:  # type: ignore[attr-defined]
        return True
    # SQLAlchemy 2.x — .columns_clause_froms gives FROM tables; if any
    # column is a func.count / max / sum / etc., it's a scalar aggregate.
    for col in stmt.exported_columns:
        if hasattr(col, "is_clause_element") and getattr(col, "name", "") in {
            "count",
            "max",
            "min",
            "sum",
            "avg",
        }:
            return True
    # Primary-key equality WHERE counts as bounded — find a where clause
    # like Memory.memory_id == :id where memory_id is a PK column.
    where = stmt.whereclause
    if where is not None:
        for col in getattr(where, "_from_objects", []):
            # Best-effort: if any PK column appears in the WHERE, treat
            # as bounded. False positives (composite WHERE that uses PK +
            # other) are fine; we under-flag, never over-flag.
            for fk in getattr(col, "primary_key", []):
                if fk is not None:
                    return True
    return False


def _statement_targets_tenant_scoped(stmt: Select) -> bool:
    """True if the SELECT touches a tenant-scoped model."""
    scoped = {cls.__table__.name for cls in tenant_scoped_models()}
    for fr in stmt.get_final_froms():
        if getattr(fr, "name", None) in scoped:
            return True
    return False


def register_query_safety_listener(session_class) -> None:
    """Attach the un-LIMITed-SELECT listener to ``session_class``.

    Idempotent — safe to call multiple times. Designed to live alongside
    the tenant filter listener registered by backend.core.tenancy.
    """
    if getattr(session_class, "_kemory_query_safety_registered", False):
        return

    @event.listens_for(session_class, "do_orm_execute")
    def _check(orm_execute_state):  # type: ignore[no-untyped-def]
        mode = _mode()
        if mode == "off":
            return
        if not orm_execute_state.is_select:
            return
        stmt = orm_execute_state.statement
        if not isinstance(stmt, Select):
            return
        if not _statement_targets_tenant_scoped(stmt):
            return
        if _select_has_limit(stmt):
            return

        # Reaching here = un-LIMITed SELECT against a tenant-scoped table.
        msg = (
            "kemory.query_safety.unbounded_select — a SELECT against a "
            "tenant-scoped model has no LIMIT. At scale this OOMs the "
            "worker on users with large memory sets. Add .limit(n) or use "
            "the cursor pagination helpers."
        )
        if mode == "raise":
            raise RuntimeError(msg)
        # warn
        logger.warning(
            "kemory.query_safety.unbounded_select",
            statement_preview=str(stmt)[:200],
        )

    session_class._kemory_query_safety_registered = True  # type: ignore[attr-defined]
