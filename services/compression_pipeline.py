"""
backend/services/compression_pipeline.py
==========================================
F12 — Write-time async compression pipeline.

When a memory is created (L1 raw), this pipeline fires asynchronously
in the background to:

  1. Encode the memory into L2 AAAK and write `_compression_tier="L2"`
     back to the memory's metadata field.

  2. If the namespace now has enough semantically similar memories
     (>= L3_SYNTHESIS_THRESHOLD), run L3.1 concept synthesis and
     create a new *concept memory* in the same namespace with:
       - content_type = "concept"
       - metadata._compression_tier = "L3.1"
       - metadata._source_memory_ids = [list of source memory IDs]
       - metadata._synthesis_source = "core_ai_backend" | "raw_fallback"

This makes `compression_tier` a **stored, queryable field** on every
memory record rather than a read-time derivation.  The dashboard reads
it directly — no on-the-fly computation needed.

Architecture notes:
  - All work is fire-and-forget via asyncio.create_task().
  - Failures are logged and swallowed — the write path is never blocked.
  - L3.1 synthesis is debounced per namespace: we only re-synthesize when
    the namespace has grown by at least L3_SYNTHESIS_MIN_NEW_MEMORIES
    since the last synthesis run (tracked in a simple in-process dict).
  - The pipeline is intentionally stateless across restarts; on restart
    the debounce counter resets and the next write triggers a fresh check.

Story: F12-US-001 / F12-US-002
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import _get_session_factory
from backend.models.memory import Memory

logger = structlog.get_logger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────

# Minimum number of active memories in a namespace before L3.1 synthesis runs
L3_SYNTHESIS_THRESHOLD: int = 3

# Minimum number of *new* memories added since last synthesis before we re-run
L3_SYNTHESIS_MIN_NEW_MEMORIES: int = 2

# Maximum source memories fed into a single L3.1 synthesis call
L3_SYNTHESIS_MAX_SOURCES: int = 50

# ── In-process debounce state ──────────────────────────────────────────────
# Maps (user_id_str, namespace) → count of memories at last synthesis run
_last_synthesis_count: dict[tuple[str, str], int] = {}


# ── Public entry point ─────────────────────────────────────────────────────


def schedule_compression(
    user_id: uuid.UUID,
    memory_id: uuid.UUID,
    namespace: str,
) -> None:
    """Fire-and-forget: schedule async compression for a newly created memory.

    Called from create_memory() immediately after the new record is committed.
    Does not block the write path.
    """
    asyncio.create_task(
        _run_compression(str(user_id), str(memory_id), namespace),
        name=f"compress:{memory_id}",
    )


# ── Pipeline implementation ────────────────────────────────────────────────


async def _run_compression(
    user_id: str,
    memory_id: str,
    namespace: str,
) -> None:
    """Full compression pipeline for one newly written memory."""
    try:
        async with _get_session_factory()() as db:
            await _promote_to_l2(db, memory_id)
            await db.commit()

        async with _get_session_factory()() as db:
            await _maybe_synthesize_l3(db, user_id, namespace)
            await db.commit()

    except Exception as exc:
        logger.warning(
            "compression_pipeline.failed",
            memory_id=memory_id,
            namespace=namespace,
            error=str(exc),
        )


async def _promote_to_l2(db: AsyncSession, memory_id: str) -> None:
    """Encode the memory to AAAK (L2) and stamp its metadata."""
    result = await db.execute(select(Memory).where(Memory.memory_id == uuid.UUID(memory_id)))
    memory = result.scalar_one_or_none()
    if memory is None:
        return

    # Already at L2 or above — skip
    existing_tier = (memory.meta or {}).get("_compression_tier", "L1")
    if existing_tier != "L1":
        return

    try:
        from memory_vault.compression.aaak import compression_ratio, encode_aaak
    except ImportError:
        logger.debug("compression_pipeline.aaak_unavailable")
        return

    mem_dict = _memory_to_dict(memory)
    encoded = encode_aaak([mem_dict])
    ratio = compression_ratio([mem_dict], encoded)

    # Merge into existing metadata (preserve all existing keys)
    meta = dict(memory.meta or {})
    meta["_compression_tier"] = "L2"
    meta["_aaak_ratio"] = ratio
    meta["_compressed_at"] = datetime.now(UTC).isoformat()

    await db.execute(update(Memory).where(Memory.memory_id == uuid.UUID(memory_id)).values(meta=meta))
    logger.debug(
        "compression_pipeline.l2_promoted",
        memory_id=memory_id,
        ratio=ratio,
    )


async def _maybe_synthesize_l3(
    db: AsyncSession,
    user_id: str,
    namespace: str,
) -> None:
    """Run L3.1 concept synthesis if the namespace is ready for it."""
    # Count active non-concept memories in the namespace
    result = await db.execute(
        select(Memory).where(
            Memory.user_id == uuid.UUID(user_id),
            Memory.namespace == namespace,
            Memory.invalid_at == None,  # noqa: E711
            Memory.content_type != "concept",  # don't re-synthesize concepts
        )
    )
    source_memories = result.scalars().all()
    count = len(source_memories)

    if count < L3_SYNTHESIS_THRESHOLD:
        return

    # Debounce: only re-run if enough new memories have been added
    key = (user_id, namespace)
    last_count = _last_synthesis_count.get(key, 0)
    if count - last_count < L3_SYNTHESIS_MIN_NEW_MEMORIES and last_count > 0:
        return

    # Cap sources
    sources = source_memories[:L3_SYNTHESIS_MAX_SOURCES]
    source_dicts = [_memory_to_dict(m) for m in sources]
    source_ids = [str(m.memory_id) for m in sources]

    # Run L3.1 synthesis
    try:
        concept = await _synthesize_concept(source_dicts, user_id, namespace)
    except Exception as exc:
        logger.warning(
            "compression_pipeline.l3_synthesis_failed",
            namespace=namespace,
            error=str(exc),
        )
        return

    # Soft-invalidate any existing concept memory for this namespace
    await db.execute(
        update(Memory)
        .where(
            Memory.user_id == uuid.UUID(user_id),
            Memory.namespace == namespace,
            Memory.content_type == "concept",
            Memory.invalid_at == None,  # noqa: E711
        )
        .values(invalid_at=datetime.now(UTC))
    )

    # Create the new concept memory
    concept_meta = {
        "_compression_tier": "L3.1",
        "_source_memory_ids": source_ids,
        "_synthesis_source": concept.get("source", "unknown"),
        "_synthesized_at": datetime.now(UTC).isoformat(),
        "_source_count": len(sources),
        "_directional": concept.get("directional", False),
        "_positions_merged": concept.get("positions_merged", len(sources)),
    }
    concept_memory = Memory(
        user_id=uuid.UUID(user_id),
        namespace=namespace,
        content=concept.get("synthesis", ""),
        content_type="concept",
        content_hash=_content_hash(concept.get("synthesis", "")),
        meta=concept_meta,
        source_agent_id=None,
        source_type="compression_pipeline",
        quality_score=None,
        enrichment_status="pending",
        version=1,
        ttl_seconds=None,
        expires_at=None,
        invalid_at=None,
        decay_score=1.0,
        visibility="user-private",
        team_id=None,
    )
    db.add(concept_memory)

    # Update debounce counter
    _last_synthesis_count[key] = count

    logger.info(
        "compression_pipeline.l3_synthesized",
        namespace=namespace,
        source_count=len(sources),
        concept_name=concept.get("name", ""),
        synthesis_source=concept.get("source", "unknown"),
    )


async def _synthesize_concept(
    memory_dicts: list[dict],
    user_id: str,
    namespace: str,
) -> dict:
    """Run L3.1 concept synthesis via the existing compression module."""
    from memory_vault.compression.concept import synthesize_namespace_local
    from memory_vault.compression.llm_client import CoreAIBackendClient

    class _StaticAdapter:
        """Minimal StorageBackend adapter for the compression module."""

        def __init__(self, mems: list[dict]) -> None:
            self._mems = mems

        async def list_episodes(self, *, org_id, limit=200, offset=0, include_invalid=False):
            return self._mems[offset : offset + limit]

        async def find_similar(self, *, content, org_id, limit=20):
            return []  # Fallback: each memory is its own group

        async def get_related(self, *, episode_id, relation_type, limit=10):
            return []

    adapter = _StaticAdapter(memory_dicts)
    client = CoreAIBackendClient()
    result = await synthesize_namespace_local(
        adapter,
        llm_client=client,
        org_id=user_id,
        namespace=namespace,
        merge_mode="current",
    )

    concepts = result.get("concepts", [])
    if not concepts:
        return {
            "name": "empty",
            "synthesis": "",
            "source": "raw_fallback",
            "directional": False,
            "positions_merged": 0,
        }

    # If multiple concept groups, pick the largest (most source memories)
    best = max(concepts, key=lambda c: len(c.get("source_memory_ids", [])))
    return best


# ── Helpers ────────────────────────────────────────────────────────────────


def _memory_to_dict(memory: Memory) -> dict:
    """Convert a Memory ORM object to the plain-dict shape used by compression."""
    return {
        "id": str(memory.memory_id),
        "namespace": memory.namespace,
        "content": memory.content,
        "content_type": memory.content_type,
        "created_at": memory.created_at.isoformat() if memory.created_at else "",
        "valid_at": memory.valid_at.isoformat() if memory.valid_at else None,
        "invalid_at": memory.invalid_at.isoformat() if memory.invalid_at else None,
        "metadata": memory.meta,
        "source_agent": str(memory.source_agent_id) if memory.source_agent_id else "",
        "session_id": memory.session_id,
        "round_id": memory.round_id,
        "tier": memory.tier,
        "visibility": memory.visibility,
        "org_id": str(memory.user_id),
    }


def _content_hash(content: str) -> str:
    """SHA-256 hex digest of normalised content."""
    import hashlib
    import unicodedata

    normalised = unicodedata.normalize("NFC", content).strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()
