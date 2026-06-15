"""
backend/workers/consolidation_loop.py
======================================
Long-running worker that drives `run_daily_consolidation` on a configurable
cadence. Lives in its own container (`kemory-worker`) so the API is free
of long-running background tasks and can be restarted independently.

Runtime contract:
  - On startup: init_db() once.
  - Loop forever: sleep `KEMORY_CONSOLIDATION_INTERVAL_SEC` (default
    86400 = 24 h) then iterate every active namespace via the existing
    `list_namespaces()` admin path and call `run_daily_consolidation`
    for each.
  - Per-namespace failures are logged and swallowed so a single bad row
    doesn't stop the loop.
  - Graceful shutdown on SIGTERM / SIGINT (returns 0).

Run via:
    python -m backend.workers.consolidation_loop

Env:
    KEMORY_CONSOLIDATION_INTERVAL_SEC    seconds between runs (default 86400)
    KEMORY_CONSOLIDATION_FIRST_DELAY_SEC seconds to wait before the first run
                                         (default 60 — give API time to be
                                         ready, especially on cold start)

Story: F14-US-003
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

import structlog
from sqlalchemy import distinct, select

from backend.core.database import _get_session_factory, init_db
from backend.models.memory import Memory
from backend.services.consolidation_service import run_daily_consolidation

logger = structlog.get_logger("kemory.worker.consolidation")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))


def _interval_seconds() -> int:
    raw = os.environ.get("KEMORY_CONSOLIDATION_INTERVAL_SEC", "86400")
    try:
        return max(60, int(raw))  # never less than 1 min — protects against typos
    except ValueError:
        return 86400


def _first_delay_seconds() -> int:
    raw = os.environ.get("KEMORY_CONSOLIDATION_FIRST_DELAY_SEC", "60")
    try:
        return max(0, int(raw))
    except ValueError:
        return 60


_shutdown = asyncio.Event()


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    def _stop(*_):
        logger.info("consolidation_loop.shutdown_requested")
        _shutdown.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler on the proactor
            # event loop. We don't run there in production, but the fallback
            # via signal.signal() keeps tests portable.
            signal.signal(sig, _stop)


async def _list_active_namespaces() -> list[str]:
    """Distinct namespace strings across all active, non-concept memories."""
    async with _get_session_factory()() as db:
        rows = (
            (
                await db.execute(
                    select(distinct(Memory.namespace)).where(
                        Memory.invalid_at == None,  # noqa: E711
                        Memory.content_type != "concept",
                    )
                )
            )
            .scalars()
            .all()
        )
    return sorted([r for r in rows if r])


async def _run_one_namespace(namespace: str) -> dict | None:
    try:
        async with _get_session_factory()() as db:
            summary = await run_daily_consolidation(db, namespace=namespace)
            await db.commit()
            return summary
    except Exception as exc:
        logger.warning(
            "consolidation_loop.namespace_failed",
            namespace=namespace,
            exception_class=type(exc).__name__,
            error=str(exc),
        )
        return None


async def _run_pass() -> None:
    namespaces = await _list_active_namespaces()
    logger.info("consolidation_loop.pass_start", namespaces=len(namespaces))
    ok = failed = 0
    for ns in namespaces:
        if _shutdown.is_set():
            break
        result = await _run_one_namespace(ns)
        if result is None:
            failed += 1
        else:
            ok += 1
    logger.info(
        "consolidation_loop.pass_complete",
        namespaces_total=len(namespaces),
        succeeded=ok,
        failed=failed,
    )


async def _main() -> int:
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    await init_db()
    interval = _interval_seconds()
    first_delay = _first_delay_seconds()

    logger.info(
        "consolidation_loop.start",
        interval_sec=interval,
        first_delay_sec=first_delay,
    )

    if first_delay:
        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=first_delay)
            return 0  # shutdown during initial delay
        except TimeoutError:
            pass

    while not _shutdown.is_set():
        try:
            await _run_pass()
        except Exception as exc:
            logger.warning(
                "consolidation_loop.pass_exception",
                exception_class=type(exc).__name__,
                error=str(exc),
            )
        # Interruptible sleep so SIGTERM doesn't have to wait `interval`.
        try:
            await asyncio.wait_for(_shutdown.wait(), timeout=interval)
        except TimeoutError:
            continue

    logger.info("consolidation_loop.exit")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
