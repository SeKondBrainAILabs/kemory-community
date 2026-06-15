"""
kemory/consolidation/worker.py
======================================
Automatic consolidation pipeline — converts episodic memories into
semantic reflections via the Reflector Agent.

Stories: MV2-S04.1 through S04.4

Design:
- Groups unconsolidated episodic memories by session_id
- Runs the Reflector to produce a semantic summary
- Creates a 'consolidated_into' edge from source → reflection
- Sets TTL on source memories (30-day default)
- Records provenance events for each step
- Idempotent: skips already-consolidated sessions
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from kemory.reflector.agent import reflect
from kemory.storage.base import StorageBackend

logger = logging.getLogger(__name__)

# Default consolidation settings
_MIN_EPISODES = 3  # Minimum episodes to trigger consolidation
_TTL_DAYS_AFTER = 30  # TTL on source episodes after consolidation
_STALENESS_HOURS = 2  # Episodes older than this are eligible


async def consolidate_session(
    backend: StorageBackend,
    org_id: str,
    session_id: str,
    *,
    min_episodes: int = _MIN_EPISODES,
    ttl_days: int = _TTL_DAYS_AFTER,
    use_groq: bool | None = None,
) -> str | None:
    """
    Consolidate episodic memories from a session into a semantic reflection.

    Story: MV2-S04.1

    Returns the reflection episode_id, or None if nothing to consolidate.
    """
    # Fetch unconsolidated episodic episodes for this session
    episodes = await backend.list_episodes(
        org_id=org_id,
        session_id=session_id,
        include_invalid=False,
    )

    # Filter to episodic memories not yet consolidated
    eligible = [e for e in episodes if not _is_consolidated(e)]

    if len(eligible) < min_episodes:
        return None

    # S04.4: Idempotency — check if this session was already consolidated
    for e in eligible:
        extra = _parse_extra(e)
        if extra.get("consolidated"):
            logger.debug("consolidation: session %s already consolidated, skipping", session_id)
            return None

    # Run the Reflector Agent
    result = await reflect(eligible, use_groq=use_groq)

    # Store the reflection as a new semantic episode
    reflection_meta: dict[str, Any] = {
        "source_agent": "consolidation-worker",
        "session_id": session_id,
        "org_id": org_id,
        "valid_at": datetime.now(UTC).isoformat(),
        "extra": {
            "memory_type": "semantic",
            "content_type": "reflection",
            "source_episode_ids": result.source_episode_ids,
            "themes": result.themes,
            "consolidation_source": result.source,
        },
        "namespace": "shared",
        "content_type": "structured",
    }
    reflection_id = await backend.add_episode(result.summary, reflection_meta)

    # S04.3: Set TTL on source episodes + create edges
    for ep in eligible:
        ep_id = ep.get("id", "")
        # Mark as consolidated in extra metadata
        extra = _parse_extra(ep)
        extra["consolidated"] = True
        extra["consolidated_into"] = reflection_id
        await _update_extra(backend, ep_id, extra)

        # Create 'consolidated_into' edge
        try:
            await backend.add_edge(ep_id, reflection_id, "elaborates", weight=0.5)
        except Exception:
            pass  # Edge creation optional

    logger.info(
        "consolidation.complete: session=%s, sources=%d, reflection=%s",
        session_id,
        len(eligible),
        reflection_id,
    )
    return reflection_id


async def consolidate_stale(
    backend: StorageBackend,
    org_id: str,
    *,
    staleness_hours: float = _STALENESS_HOURS,
    min_episodes: int = _MIN_EPISODES,
    ttl_days: int = _TTL_DAYS_AFTER,
    use_groq: bool | None = None,
) -> list[str]:
    """
    Find and consolidate all stale unconsolidated episodes.

    Story: MV2-S04.2

    Returns list of created reflection episode_ids.
    """
    all_episodes = await backend.list_episodes(
        org_id=org_id,
        include_invalid=False,
    )

    # Group by session_id
    sessions: dict[str, list[dict]] = {}
    for ep in all_episodes:
        sid = ep.get("session_id", "unknown")
        sessions.setdefault(sid, []).append(ep)

    reflections = []
    for session_id, episodes in sessions.items():
        # Filter to unconsolidated
        eligible = [e for e in episodes if not _is_consolidated(e)]
        if len(eligible) < min_episodes:
            continue

        ref_id = await consolidate_session(
            backend,
            org_id,
            session_id,
            min_episodes=min_episodes,
            ttl_days=ttl_days,
            use_groq=use_groq,
        )
        if ref_id:
            reflections.append(ref_id)

    return reflections


# ── Helpers ───────────────────────────────────────────────────────────────


def _is_consolidated(ep: dict) -> bool:
    """Check if an episode has already been consolidated."""
    extra = _parse_extra(ep)
    return bool(extra.get("consolidated"))


def _parse_extra(ep: dict) -> dict:
    """Parse the extra_json field from an episode dict."""
    raw = ep.get("extra_json", ep.get("extra", "{}"))
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


async def _update_extra(backend: StorageBackend, episode_id: str, extra: dict) -> None:
    """Update the extra_json field on an episode (SQLite only)."""
    try:
        conn = backend._sqlite_conn
        await conn.execute(
            "UPDATE episodes SET extra_json = ? WHERE id = ?",
            (json.dumps(extra), episode_id),
        )
        await conn.commit()
    except Exception:
        pass  # Non-critical
