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

from backend.models.memory import Memory

logger = structlog.get_logger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────

# Minimum number of active memories in a namespace before L3 narrative summary runs
L3_SUMMARY_THRESHOLD: int = 2

# Minimum number of *new* memories added since last L3 summary before we re-run
# (3 = a small batch — at 3-turn granularity the summary captures essentially
# the same content; under heavy parallel ingest this naturally batches the
# Groq calls without losing freshness for human-pace usage).
L3_SUMMARY_MIN_NEW_MEMORIES: int = 3

# When the new memory's embedding is at least this similar to the *existing
# summary's* embedding, the summary already represents this content and we
# skip regen. This is the F13 cosine gate the user asked for, applied at
# memory→summary granularity (vs F13's existing memory→prior-memories gate).
# Calibrated against typical conversational-turn-vs-paragraph-summary
# similarity: aligned content lands in 0.7–0.9, unrelated content drops
# below 0.6. 0.72 catches "this turn is already in the summary" while still
# triggering regen for genuinely new topics within the namespace.
L3_SUMMARY_COVERS_THRESHOLD: float = 0.72

# Maximum source memories fed into a single L3 summary call
L3_SUMMARY_MAX_SOURCES: int = 50

# Below this count, L3 falls back to a deterministic Python-generated bullet
# list instead of calling Groq. Avoids Groq's tendency to over-elaborate on
# tiny inputs (observed in v0.13.x: user:preferences with 3 memories totalling
# 953 chars produced a 787-char "summary" — 1.21× expansion). Saves cost AND
# guarantees that L3 is always at least as compact as the source.
L3_GROQ_MIN_MEMORIES: int = 5

# Groq model used for L3 narrative summarization (cheap, fast, faithful prose)
L3_SUMMARY_GROQ_MODEL: str = "llama-3.3-70b-versatile"

# Novelty gate: if the new memory's max cosine similarity to any prior
# memory in scope is ≥ this threshold, the pipeline SKIPS the LLM re-summary
# — the new memory is a near-duplicate of something already captured, so
# re-running Groq wouldn't change the summary meaningfully.
#
# Embeddings are L2-normalised, so similarity = dot product ∈ [-1, 1];
# typical range for real text is ~[0, 1]. 0.92 is a conservative gate that
# catches paraphrases / restatements but still triggers on genuinely new
# information. Tune down to 0.85 if cost becomes an issue; tune up to 0.95
# if summaries feel stale.
L3_NOVELTY_SKIP_THRESHOLD: float = 0.92

# Minimum number of active memories in a namespace before L3.1 synthesis runs
L3_SYNTHESIS_THRESHOLD: int = 3

# Minimum number of *new* memories added since last synthesis before we re-run
L3_SYNTHESIS_MIN_NEW_MEMORIES: int = 2

# Maximum source memories fed into a single L3.1 synthesis call
L3_SYNTHESIS_MAX_SOURCES: int = 50

# ── Cross-namespace merge detection ───────────────────────────────────────
# Cosine similarity threshold between two namespace consolidated_summaries
# that triggers a "suggest_merge" entry in related_namespaces.
# Lower than the namespace-name AUTO_REDIRECT threshold (0.90) because
# summaries are longer prose; 0.75 catches "same topic, different name"
# without over-flagging loosely related namespaces.
NAMESPACE_MERGE_THRESHOLD: float = float(
    __import__("os").environ.get("KMV_NAMESPACE_MERGE_THRESHOLD", "0.75")
)

# Maximum number of namespaces with summaries before the pairwise comparison
# is skipped (pathological-tenant guard — O(N²) cost).
NAMESPACE_MERGE_MAX_NAMESPACES: int = 50

# ── Session prewarm ────────────────────────────────────────────────────────
# A namespace summary older than this many seconds is considered stale and
# will be refreshed when an agent token is issued (prewarm_namespace).
PREWARM_STALENESS_SECONDS: int = int(__import__("os").environ.get("KMV_PREWARM_STALENESS_S", "300"))

# ── In-process debounce state ──────────────────────────────────────────────
# Maps (user_id_str, namespace) → count of memories at last L3.1 synthesis run
_last_synthesis_count: dict[tuple[str, str], int] = {}

# Maps (user_id_str, namespace) → count of memories at last L3 summary run
_last_summary_count: dict[tuple[str, str], int] = {}

# Per-namespace asyncio locks coalesce concurrent L3 regen calls. Without
# these, 16 parallel writes to the same namespace all read the same
# `_last_summary_count` snapshot, all decide "yes, regen", and all fire
# Groq simultaneously — wasting LLM cost AND piling onto the policy row
# upsert. With the lock, the first concurrent writer runs the summary,
# updates `_last_summary_count`, and subsequent writers see the new count
# and short-circuit on the debounce check.
_l3_summary_locks: dict[tuple[str, str], asyncio.Lock] = {}

# Cache the embedding of the most recent summary text so the
# summary-coverage gate doesn't re-encode on every write. Keyed by the
# summary text itself so a stale entry self-invalidates as soon as the
# summary changes.
_summary_embedding_cache: dict[str, list[float]] = {}


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
    """Full compression pipeline for one newly written memory.

    Stages (each independent, each fire-and-forget w.r.t. failure):
      L2            — AAAK encoding of this memory (always, threshold=1)
      L3 namespace  — Groq LLM narrative summary of the namespace (threshold=2)
      L3 session    — Groq LLM summary over memories in this session + a
                      point-in-time cumulative summary of the namespace as of
                      the latest memory in the session. Only runs when the
                      memory has a session_id. (threshold=1 for session, ≥2
                      for cumulative — both use L3_SUMMARY_THRESHOLD.)
      L3.1          — CognitionOS concept synthesis of the namespace
                      (threshold=3, requires near-duplicate cluster)
    """
    try:
        from backend.plugins.cognition import PipelineContext, get_pipeline_stages

        context = PipelineContext(user_id=user_id, memory_id=memory_id, namespace=namespace)
        for stage in get_pipeline_stages():
            await stage.run(context)

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
        from kemory.compression.aaak import compression_ratio, encode_aaak
    except ImportError:
        logger.debug("compression_pipeline.aaak_unavailable")
        return

    mem_dict = _memory_to_dict(memory)
    encoded = encode_aaak([mem_dict])
    ratio = compression_ratio([mem_dict], encoded)

    # F14: Use a JSONB merge (`metadata = metadata || patch`) so a concurrent
    # enrichment write doesn't clobber our L2 fields and vice versa. Before
    # this fix, both this stage and enrichment did read-modify-write of the
    # whole `metadata` column — last writer won, so memories ended up with
    # only one of the two key sets (compression won OR enrichment won, never
    # both). The race was hidden when embeddings were broken (only one
    # background task actually committed), but exposed by the P1 fix.
    import json as _json

    from sqlalchemy import text as _sql

    patch = {
        "_compression_tier": "L2",
        "_aaak_ratio": ratio,
        "_compressed_at": datetime.now(UTC).isoformat(),
    }
    await db.execute(
        _sql(
            "UPDATE kemory_memories "
            "SET metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:patch AS jsonb) "
            "WHERE memory_id = :mid"
        ),
        {"patch": _json.dumps(patch), "mid": str(memory_id)},
    )
    logger.debug(
        "compression_pipeline.l2_promoted",
        memory_id=memory_id,
        ratio=ratio,
    )


# ── Novelty gate ───────────────────────────────────────────────────────────


async def _max_similarity_to_prior(
    db: AsyncSession,
    memory_id: str,
    user_id: str,
    namespace: str,
    *,
    session_id: str | None = None,
    up_to_ts: datetime | None = None,
) -> float | None:
    """Max cosine similarity of `memory_id` to any OTHER active non-concept
    memory in scope. Returns:

      * None   — the target memory has no embedding yet (background task
                 hasn't written one); caller should fall back to running the
                 pipeline, since we can't judge novelty.
      * -1.0   — scope has no prior memories at all; also a "run the
                 pipeline" signal (caller interprets None/-1 as "no gate").
      * float in [-1, 1] — actual max similarity.

    Scope options (at most one of):
      * session_id  — restrict to memories in the same session
      * up_to_ts    — restrict to memories with created_at ≤ ts

    Embeddings are L2-normalised per the `embedding` column comment in
    backend/models/memory.py, so similarity = dot product.
    """
    target_row = (
        await db.execute(select(Memory.embedding).where(Memory.memory_id == uuid.UUID(memory_id)))
    ).first()
    if target_row is None:
        return None
    target_vec = target_row[0]
    if not target_vec:
        return None  # Embedding not yet populated by background task.

    stmt = select(Memory.embedding).where(
        Memory.user_id == uuid.UUID(user_id),
        Memory.namespace == namespace,
        Memory.invalid_at == None,  # noqa: E711
        Memory.content_type != "concept",
        Memory.memory_id != uuid.UUID(memory_id),
        Memory.embedding.isnot(None),
    )
    if session_id is not None:
        stmt = stmt.where(Memory.session_id == session_id)
    if up_to_ts is not None:
        stmt = stmt.where(Memory.created_at <= up_to_ts)

    prior_rows = (await db.execute(stmt)).scalars().all()
    if not prior_rows:
        return -1.0

    # L2-normalised vectors → similarity = dot product. Pure Python is fine
    # at the volumes we deal with here (tens of memories per namespace);
    # if this grows, swap for numpy.
    best = -2.0
    for vec in prior_rows:
        if not vec or len(vec) != len(target_vec):
            continue
        sim = 0.0
        for a, b in zip(target_vec, vec, strict=False):
            sim += a * b
        if sim > best:
            best = sim
    return best if best > -2.0 else -1.0


async def _summary_already_covers(
    db: AsyncSession,
    memory_id: str,
    namespace: str,
) -> bool:
    """True iff the new memory's content is already represented in the
    existing namespace summary — regen would not add information.

    Compares the new memory's embedding against the existing summary's
    embedding. If similarity ≥ L3_SUMMARY_COVERS_THRESHOLD, the summary
    already covers this content and we skip the Groq call.

    Returns False (run regen) when:
      • no existing summary
      • new memory has no embedding yet
      • similarity below threshold

    The summary embedding is cached in-process keyed by the summary text,
    so a stale entry self-invalidates as soon as the summary changes.
    """
    from backend.models.memory import Memory
    from backend.models.namespace_policy import NamespacePolicy

    # New memory's embedding
    target_vec = (
        await db.execute(select(Memory.embedding).where(Memory.memory_id == uuid.UUID(memory_id)))
    ).scalar_one_or_none()
    if not target_vec:
        return False

    # Existing summary text
    summary_text = (
        await db.execute(
            select(NamespacePolicy.consolidated_summary).where(NamespacePolicy.namespace == namespace)
        )
    ).scalar_one_or_none()
    if not summary_text:
        return False

    # Encode summary (cached by exact text)
    summary_vec = _summary_embedding_cache.get(summary_text)
    if summary_vec is None:
        try:
            from kemory.embeddings.encoder import encode

            summary_vec = list(encode(summary_text))
            # Bound the cache so it doesn't grow without limit. We only need
            # the *current* summary per namespace; keep at most 256 entries.
            if len(_summary_embedding_cache) > 256:
                # Drop oldest by simple FIFO eviction.
                for k in list(_summary_embedding_cache.keys())[:64]:
                    _summary_embedding_cache.pop(k, None)
            _summary_embedding_cache[summary_text] = summary_vec
        except Exception:
            return False

    if len(target_vec) != len(summary_vec):
        return False

    sim = sum(a * b for a, b in zip(target_vec, summary_vec, strict=False))
    return sim >= L3_SUMMARY_COVERS_THRESHOLD


async def _has_sufficient_novelty(
    db: AsyncSession,
    memory_id: str,
    user_id: str,
    namespace: str,
    *,
    session_id: str | None = None,
    up_to_ts: datetime | None = None,
    stage_label: str = "l3",
) -> bool:
    """True if the pipeline should proceed; False if the new memory is a
    near-duplicate of something already captured.

    When embeddings aren't available (new memory or prior memories not yet
    embedded), we return True — "when in doubt, summarize". Correctness
    over optimization.
    """
    max_sim = await _max_similarity_to_prior(
        db,
        memory_id,
        user_id,
        namespace,
        session_id=session_id,
        up_to_ts=up_to_ts,
    )
    if max_sim is None or max_sim < 0:
        # No embedding yet, or no prior memories to compare against.
        return True
    is_novel = max_sim < L3_NOVELTY_SKIP_THRESHOLD
    if not is_novel:
        logger.info(
            f"{stage_label}.skipped_as_duplicate",
            namespace=namespace,
            session_id=session_id,
            max_similarity=round(max_sim, 4),
            threshold=L3_NOVELTY_SKIP_THRESHOLD,
        )
    return is_novel


async def _maybe_summarize_l3(
    db: AsyncSession,
    user_id: str,
    namespace: str,
    *,
    trigger_memory_id: str | None = None,
    force: bool = False,
) -> None:
    """Run L3 narrative summary (Groq LLM) if the namespace is ready.

    L3 is a faithful prose summary of all active non-concept memories in a
    namespace. Unlike L3.1 (CognitionOS concept synthesis), L3 does not
    extract opinions or pick sides — it just distils the content into a
    readable paragraph. Cheap (Groq llama-3.3-70b-versatile), runs often.

    `trigger_memory_id` is the memory whose write triggered this run; used
    for the novelty gate. `force=True` bypasses the gate (used by the
    backfill script). Writes result to NamespacePolicy.consolidated_summary
    with tier="L3". L3.1 will later overwrite with tier="L3.1" when its
    threshold is met.
    """
    import os

    if not os.environ.get("GROQ_API_KEY", "").strip():
        logger.debug("l3_summary.skipped", reason="no_groq_api_key", namespace=namespace)
        return

    # Count active non-concept memories in the namespace
    result = await db.execute(
        select(Memory)
        .where(
            Memory.user_id == uuid.UUID(user_id),
            Memory.namespace == namespace,
            Memory.invalid_at == None,  # noqa: E711
            Memory.content_type != "concept",
        )
        .order_by(Memory.created_at.desc())
    )
    source_memories = result.scalars().all()
    count = len(source_memories)

    if count < L3_SUMMARY_THRESHOLD:
        return

    # Per-namespace lock — coalesce concurrent regen calls into one. Under
    # bulk parallel ingest (e.g. 16 LME ingest workers all writing to the
    # same multi-session namespace), without this lock all 16 read the
    # same `_last_summary_count` snapshot, all pass the debounce, and all
    # fire Groq concurrently. With the lock the first writer runs the
    # summary and advances `_last_summary_count`; subsequent writers
    # acquire the lock, see the new count, and short-circuit.
    key = (user_id, namespace)
    lock = _l3_summary_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _l3_summary_locks[key] = lock

    # Skip immediately if another coroutine is already regenerating for
    # this namespace — they'll cover the work that's pending.
    if lock.locked() and not force:
        logger.debug(
            "l3_summary.skipped.lock_held",
            namespace=namespace,
        )
        return

    async with lock:
        # Re-check debounce inside the lock so we use the latest count.
        last_count = _last_summary_count.get(key, 0)
        if not force and count - last_count < L3_SUMMARY_MIN_NEW_MEMORIES and last_count > 0:
            return

        # F13 cosine gate: is the triggering memory a near-duplicate of any
        # prior memory in the corpus? If so, regen wouldn't add information.
        if not force and trigger_memory_id is not None:
            if not await _has_sufficient_novelty(
                db,
                trigger_memory_id,
                user_id,
                namespace,
                stage_label="l3_namespace",
            ):
                _last_summary_count[key] = count
                return

            # F13 extension: is the triggering memory already represented in
            # the existing summary? Cheaper than a full regen — single SBERT
            # encode of the summary (cached) + one dot product.
            if await _summary_already_covers(db, trigger_memory_id, namespace):
                logger.info(
                    "l3_summary.skipped.summary_covers",
                    namespace=namespace,
                    threshold=L3_SUMMARY_COVERS_THRESHOLD,
                )
                _last_summary_count[key] = count
                return

        await _do_summarize_l3(
            db,
            user_id,
            namespace,
            source_memories,
            count,
            key,
        )


async def _do_summarize_l3(
    db: AsyncSession,
    user_id: str,
    namespace: str,
    source_memories: list,
    count: int,
    key: tuple[str, str],
) -> None:
    """Generate the L3 summary and upsert it. Only called by
    `_maybe_summarize_l3` after debounce + novelty + coverage gates have
    decided this run is needed. Caller holds `_l3_summary_locks[key]`.
    """
    sources = source_memories[:L3_SUMMARY_MAX_SOURCES]

    # P3: tiny-namespace fallback. Groq over-elaborates on a handful of
    # short memories and can produce *more* text than the source. For small
    # namespaces (count < L3_GROQ_MIN_MEMORIES) emit a deterministic bullet
    # list — guaranteed compact, no LLM cost, no hallucination risk.
    if count < L3_GROQ_MIN_MEMORIES:
        summary_text = _bullet_list_summary(sources, namespace, scope="namespace")
        logger.info(
            "l3_summary.bullet_fallback",
            namespace=namespace,
            source_count=len(sources),
            threshold=L3_GROQ_MIN_MEMORIES,
            summary_chars=len(summary_text),
        )
    else:
        try:
            summary_text = await _summarize_with_groq(sources, namespace)
        except Exception as exc:
            logger.warning(
                "l3_summary.groq_failed",
                namespace=namespace,
                error=str(exc),
            )
            return

    if not summary_text:
        return

    # Upsert the summary on NamespacePolicy. Only write if the current tier
    # is "L3" or None — never downgrade an existing L3.1 summary.
    # ON CONFLICT keeps the row lock to microseconds.
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from backend.models.namespace_policy import NamespacePolicy

        now = datetime.now(UTC)
        stmt = (
            pg_insert(NamespacePolicy)
            .values(
                namespace=namespace,
                consolidated_summary=summary_text,
                consolidated_summary_tier="L3",
                consolidated_summary_updated_at=now,
                created_by=uuid.UUID(user_id),
            )
            .on_conflict_do_update(
                index_elements=[NamespacePolicy.namespace],
                set_={
                    "consolidated_summary": summary_text,
                    "consolidated_summary_tier": "L3",
                    "consolidated_summary_updated_at": now,
                },
                where=(
                    (NamespacePolicy.consolidated_summary_tier == None)  # noqa: E711
                    | (NamespacePolicy.consolidated_summary_tier == "L3")
                ),
            )
        )
        await db.execute(stmt)
    except Exception as exc:
        logger.debug(
            "l3_summary.upsert_failed",
            namespace=namespace,
            error=str(exc),
        )
        return

    _last_summary_count[key] = count

    logger.info(
        "l3_summary.generated",
        namespace=namespace,
        source_count=len(sources),
        summary_chars=len(summary_text),
    )


# ── Session-level L3 ───────────────────────────────────────────────────────

# Maps (user_id_str, namespace, session_id) → memory_count at last run
_last_session_summary_count: dict[tuple[str, str, str], int] = {}


async def _maybe_summarize_session_l3(
    db: AsyncSession,
    user_id: str,
    memory_id: str,
    namespace: str,
    *,
    force: bool = False,
) -> None:
    """Run the session-level L3 pipeline when the new memory has a session_id.

    Produces / updates two summaries on the `kemory_session_summary` row
    keyed by (user_id, namespace, session_id):

      session_summary    — faithful rollup over memories in this session only.
                           Answers "what happened in this session so far".
      cumulative_summary — faithful rollup over all active memories in the
                           namespace with created_at ≤ up_to_ts (the created_at
                           of the latest memory in the session). Answers "what
                           was the namespace state at this session's boundary".

    Each sub-summary is gated independently by a vector-similarity novelty
    check against its own scope — a new memory may be novel to its session
    but a near-duplicate of something already in the namespace (or vice
    versa). `force=True` bypasses the gate (used by backfill).

    Debounced per (user, namespace, session) — only runs when ≥1 new memory
    has arrived since the last pipeline run for that tuple.
    """
    import os

    if not os.environ.get("GROQ_API_KEY", "").strip():
        logger.debug("session_l3.skipped", reason="no_groq_api_key", namespace=namespace)
        return

    # Fetch the triggering memory to extract session_id + created_at anchor.
    result = await db.execute(select(Memory).where(Memory.memory_id == uuid.UUID(memory_id)))
    memory = result.scalar_one_or_none()
    if memory is None:
        return
    session_id = (memory.session_id or "").strip()
    if not session_id:
        return  # This memory isn't part of any session — nothing to do.

    up_to_ts = memory.created_at
    key = (user_id, namespace, session_id)

    # ── Gather session-scoped memories ─────────────────────────────
    session_rows = (
        (
            await db.execute(
                select(Memory)
                .where(
                    Memory.user_id == uuid.UUID(user_id),
                    Memory.namespace == namespace,
                    Memory.session_id == session_id,
                    Memory.invalid_at == None,  # noqa: E711
                    Memory.content_type != "concept",
                )
                .order_by(Memory.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    session_count = len(session_rows)

    # ── Gather cumulative (namespace-wide, up to up_to_ts) memories ─
    cumulative_rows = (
        (
            await db.execute(
                select(Memory)
                .where(
                    Memory.user_id == uuid.UUID(user_id),
                    Memory.namespace == namespace,
                    Memory.created_at <= up_to_ts,
                    Memory.invalid_at == None,  # noqa: E711
                    Memory.content_type != "concept",
                )
                .order_by(Memory.created_at.asc())
            )
        )
        .scalars()
        .all()
    )
    cumulative_count = len(cumulative_rows)

    # Debounce — only re-run if at least one new memory since last time.
    last_count = _last_session_summary_count.get(key, 0)
    if session_count <= last_count:
        return

    # ── Novelty gates (independent per sub-summary) ────────────────
    session_novel = force or await _has_sufficient_novelty(
        db,
        memory_id,
        user_id,
        namespace,
        session_id=session_id,
        stage_label="l3_session",
    )
    cumulative_novel = force or await _has_sufficient_novelty(
        db,
        memory_id,
        user_id,
        namespace,
        up_to_ts=up_to_ts,
        stage_label="l3_cumulative",
    )
    # If neither scope has enough novelty to warrant a re-summary, advance
    # the debounce counter and bail — skip both LLM calls.
    if not session_novel and not cumulative_novel:
        _last_session_summary_count[key] = session_count
        return

    # ── Generate summaries ─────────────────────────────────────────
    session_summary_text: str | None = None
    cumulative_summary_text: str | None = None

    if session_novel:
        session_sources = session_rows[:L3_SUMMARY_MAX_SOURCES]
        if session_count < L3_GROQ_MIN_MEMORIES:
            session_summary_text = _bullet_list_summary(
                session_sources,
                namespace,
                scope="session",
            )
            logger.info(
                "session_l3.session_bullet_fallback",
                namespace=namespace,
                session_id=session_id,
                source_count=session_count,
            )
        else:
            try:
                session_summary_text = await _summarize_with_groq(
                    session_sources,
                    namespace,
                    scope="session",
                )
            except Exception as exc:
                logger.warning(
                    "session_l3.session_summary_failed",
                    namespace=namespace,
                    session_id=session_id,
                    error=str(exc),
                )

    # Only produce a cumulative summary if there are ≥2 memories in the
    # namespace up to now AND the new memory was novel vs. that scope.
    if cumulative_novel and cumulative_count >= L3_SUMMARY_THRESHOLD:
        cumulative_sources = cumulative_rows[:L3_SUMMARY_MAX_SOURCES]
        if cumulative_count < L3_GROQ_MIN_MEMORIES:
            cumulative_summary_text = _bullet_list_summary(
                cumulative_sources,
                namespace,
                scope=f"cumulative-as-of-{up_to_ts.isoformat() if up_to_ts else 'now'}",
            )
            logger.info(
                "session_l3.cumulative_bullet_fallback",
                namespace=namespace,
                session_id=session_id,
                source_count=cumulative_count,
            )
        else:
            try:
                cumulative_summary_text = await _summarize_with_groq(
                    cumulative_sources,
                    namespace,
                    scope=f"cumulative-as-of-{up_to_ts.isoformat() if up_to_ts else 'now'}",
                )
            except Exception as exc:
                logger.warning(
                    "session_l3.cumulative_summary_failed",
                    namespace=namespace,
                    session_id=session_id,
                    error=str(exc),
                )

    if not session_summary_text and not cumulative_summary_text:
        return  # nothing to persist

    # ── Upsert the SessionSummary row ──────────────────────────────
    try:
        from backend.models.session_summary import SessionSummary

        existing = (
            await db.execute(
                select(SessionSummary).where(
                    SessionSummary.user_id == uuid.UUID(user_id),
                    SessionSummary.namespace == namespace,
                    SessionSummary.session_id == session_id,
                )
            )
        ).scalar_one_or_none()

        now = datetime.now(UTC)
        if existing is None:
            existing = SessionSummary(
                user_id=uuid.UUID(user_id),
                namespace=namespace,
                session_id=session_id,
                session_summary=session_summary_text,
                session_summary_tier="L3" if session_summary_text else None,
                session_memory_count=session_count,
                cumulative_summary=cumulative_summary_text,
                cumulative_summary_tier="L3" if cumulative_summary_text else None,
                cumulative_memory_count=cumulative_count,
                up_to_ts=up_to_ts,
            )
            db.add(existing)
        else:
            if session_summary_text:
                existing.session_summary = session_summary_text
                existing.session_summary_tier = "L3"
            existing.session_memory_count = session_count
            if cumulative_summary_text:
                existing.cumulative_summary = cumulative_summary_text
                existing.cumulative_summary_tier = "L3"
            existing.cumulative_memory_count = cumulative_count
            existing.up_to_ts = up_to_ts
            existing.updated_at = now
    except Exception as exc:
        logger.debug(
            "session_l3.upsert_failed",
            namespace=namespace,
            session_id=session_id,
            error=str(exc),
        )
        return

    _last_session_summary_count[key] = session_count

    logger.info(
        "session_l3.generated",
        namespace=namespace,
        session_id=session_id,
        session_count=session_count,
        cumulative_count=cumulative_count,
        session_chars=len(session_summary_text or ""),
        cumulative_chars=len(cumulative_summary_text or ""),
    )


def _bullet_list_summary(
    memories: list[Memory],
    namespace: str,
    *,
    scope: str = "namespace",
    per_item_chars: int = 200,
) -> str:
    """Deterministic, no-LLM fallback used when memory count is below
    L3_GROQ_MIN_MEMORIES. Produces a compact bullet list of the source
    memories (truncated per item) so the consolidated_summary slot is
    populated with something useful even when calling Groq would
    over-elaborate.

    Guaranteed to be ≤ source size — never causes expansion.
    """
    if not memories:
        return ""
    header = f"{scope.capitalize()} of '{namespace}' ({len(memories)} memor{'y' if len(memories) == 1 else 'ies'}):"
    bullets = []
    for m in memories:
        text = (m.content or "").strip().replace("\n", " ")
        if len(text) > per_item_chars:
            text = text[: per_item_chars - 1] + "…"
        bullets.append(f"- {text}")
    return header + "\n" + "\n".join(bullets)


async def _summarize_with_groq(
    memories: list[Memory],
    namespace: str,
    *,
    scope: str = "namespace",
) -> str:
    """Call Groq to produce a faithful narrative summary of a memory set.

    `scope` describes what the memories represent — "namespace", "session",
    or "cumulative (as of <ts>)". Shown to the LLM in the prompt so the
    produced prose frames itself correctly.
    """
    # PR #18 dropped the `groq` direct-SDK dep from pyproject.toml in
    # favour of routing all LLM traffic through core-ai-backend. This
    # function still exists (and the name is grandfathered through
    # callers) but the body now POSTs to core-ai-backend's
    # /v1/chat/completions, the same OpenAI-compat endpoint the
    # reranker and the L3.1 chat-fallback use.
    import os

    import httpx

    base_url = os.environ.get("CORE_AI_BACKEND_URL") or os.environ.get("AI_BACKEND_URL")
    if not base_url:
        raise RuntimeError("CORE_AI_BACKEND_URL not set — L3 narrative summary cannot run")

    memories_text = "\n".join(f"[{i + 1}] {(m.content or '').strip()[:500]}" for i, m in enumerate(memories))

    prompt = (
        f"You are summarizing the {scope} of memory records for namespace "
        f"'{namespace}'.\n\n"
        "Below are individual memory records. Produce a faithful narrative "
        "summary in plain prose (3-6 sentences). Rules:\n"
        "- Do NOT infer facts not present in the memories.\n"
        "- Do NOT pick sides, argue, or editorialize.\n"
        "- Preserve specific names, dates, numbers when present.\n"
        "- Organize chronologically where created_at implies an order.\n"
        "- If memories conflict, note both rather than choosing one.\n\n"
        f"Memories:\n{memories_text}\n\n"
        "Summary:"
    )

    payload = {
        "model": L3_SUMMARY_GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 512,
    }
    headers: dict[str, str] = {"Content-Type": "application/json"}
    token = os.environ.get("CORE_AI_BACKEND_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        return (data["choices"][0]["message"]["content"] or "").strip()


async def _maybe_synthesize_l3_1(
    db: AsyncSession,
    user_id: str,
    namespace: str,
) -> None:
    """Run L3.1 concept synthesis if the namespace is ready for it.

    Emits a structured `l3_1.skipped` log line for every silent-skip path
    (threshold not met, debounced, no clusters formed, LLM unreachable)
    so operators can distinguish "no clusters yet, working as designed"
    from "CoreAIBackend is offline".
    """
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
        logger.info(
            "l3_1.skipped",
            namespace=namespace,
            reason="below_threshold",
            count=count,
            threshold=L3_SYNTHESIS_THRESHOLD,
        )
        return

    # Debounce: only re-run if enough new memories have been added
    key = (user_id, namespace)
    last_count = _last_synthesis_count.get(key, 0)
    if count - last_count < L3_SYNTHESIS_MIN_NEW_MEMORIES and last_count > 0:
        logger.info(
            "l3_1.skipped",
            namespace=namespace,
            reason="debounced",
            count=count,
            last_run_count=last_count,
            min_new_required=L3_SYNTHESIS_MIN_NEW_MEMORIES,
        )
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
            "l3_1.skipped",
            namespace=namespace,
            reason="synthesis_exception",
            exception_class=type(exc).__name__,
            error=str(exc),
        )
        return

    # Surface degraded synthesis modes (raw_fallback, raw_passthrough,
    # synthesis_unavailable). These mean the concept row was written but
    # CoreAIBackendClient was not the one who wrote it — important signal
    # that L3.1 quality is degraded.
    synthesis_source = concept.get("source", "unknown")
    if synthesis_source in {"raw_fallback", "raw_passthrough"}:
        logger.warning(
            "l3_1.degraded",
            namespace=namespace,
            reason=synthesis_source,
            source_count=len(sources),
            note="CoreAIBackendClient unreachable or no cluster formed; concept row was written but quality is degraded",
        )
    if not concept.get("synthesis"):
        logger.warning(
            "l3_1.skipped",
            namespace=namespace,
            reason="empty_synthesis",
            source=synthesis_source,
            source_count=len(sources),
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
    # PR #17: org_id NOT NULL on kemory_memories. Inherit from one of the
    # source memories — the namespace is user-scoped so they all share an
    # org_id. Fall back to the legacy sentinel if for some reason the
    # source has no org_id (shouldn't happen post-014 backfill).
    src_org_id = ""
    if sources:
        src_org_id = (sources[0].get("org_id") or "") if isinstance(sources[0], dict) else ""
    if not src_org_id:
        from backend.config.settings import settings as _settings

        src_org_id = _settings.tenant_legacy_sentinel

    concept_memory = Memory(
        user_id=uuid.UUID(user_id),
        org_id=src_org_id,
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

    # Upsert the rolling namespace summary on NamespacePolicy so agents and
    # the dashboard can read a cross-session rollup without re-running
    # synthesis. Piggy-backs on the same L3.1 run — no extra LLM cost.
    # Atomic UPSERT (see L3 site above for rationale) — under concurrent
    # multi-session ingest, the previous SELECT-then-modify pattern
    # serialised on the policy row.
    try:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        from backend.models.namespace_policy import NamespacePolicy

        summary_text = concept.get("synthesis", "") or ""
        now = datetime.now(UTC)
        stmt = (
            pg_insert(NamespacePolicy)
            .values(
                namespace=namespace,
                consolidated_summary=summary_text,
                consolidated_summary_tier="L3.1",
                consolidated_summary_updated_at=now,
                created_by=uuid.UUID(user_id),
            )
            .on_conflict_do_update(
                index_elements=[NamespacePolicy.namespace],
                set_={
                    "consolidated_summary": summary_text,
                    "consolidated_summary_tier": "L3.1",
                    "consolidated_summary_updated_at": now,
                },
            )
        )
        await db.execute(stmt)
    except Exception as exc:
        logger.debug(
            "compression_pipeline.summary_upsert_failed",
            namespace=namespace,
            error=str(exc),
        )

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
    from kemory.compression.concept import synthesize_namespace_local
    from kemory.compression.llm_client import CoreAIBackendClient

    class _StaticAdapter:
        """Minimal StorageBackend adapter for the compression module.

        Implements find_similar as an in-memory cosine pass over the
        embeddings already attached to memory_dicts. The previous version
        returned [] unconditionally, which made every memory a singleton
        cluster — and singletons short-circuit to source='raw_passthrough'
        in concept.py without ever calling the LLM. That's why every L3.1
        synthesis logged 'CoreAIBackendClient unreachable or no cluster
        formed' regardless of whether the backend was reachable: there
        was never a cluster.

        Embeddings are normally generated in a fire-and-forget task after
        create_memory returns; L3.1 can fire before the embedding is
        persisted. To handle that race we compute embeddings on-demand
        for any memory that doesn't already have one, using the same
        encoder. The cost is bounded — at most one SBERT encode per
        memory per L3.1 run, and the whole run is gated by debounce +
        lock + summary-coverage upstream.
        """

        # Match concept.py's _GROUP_SIM_THRESHOLD.
        _SIM_THRESHOLD: float = 0.85

        def __init__(self, mems: list[dict]) -> None:
            self._mems = mems
            self._by_content: dict[str, dict] = {str(m.get("content", "")): m for m in mems}
            self._enc_cache: dict[str, list[float] | None] = {}

        def _embedding_for(self, mem: dict) -> list[float] | None:
            vec = mem.get("embedding")
            if vec:
                return list(vec)
            content = str(mem.get("content", ""))
            if not content:
                return None
            if content in self._enc_cache:
                return self._enc_cache[content]
            try:
                from kemory.embeddings.encoder import encode

                vec = list(encode(content))
            except Exception:
                vec = None
            self._enc_cache[content] = vec
            return vec

        async def list_episodes(self, *, org_id, limit=200, offset=0, include_invalid=False):
            return self._mems[offset : offset + limit]

        async def find_similar(self, *, content, org_id, limit=20):
            target = self._by_content.get(content)
            if not target:
                return []
            target_vec = self._embedding_for(target)
            if not target_vec:
                return []
            target_id = str(target.get("id", ""))
            scored: list[tuple[float, dict]] = []
            for m in self._mems:
                if str(m.get("id", "")) == target_id:
                    continue
                vec = self._embedding_for(m)
                if not vec or len(vec) != len(target_vec):
                    continue
                # Embeddings are L2-normalised → cosine = dot product.
                sim = sum(a * b for a, b in zip(target_vec, vec, strict=False))
                if sim >= self._SIM_THRESHOLD:
                    # _group_by_similarity in concept.py filters by
                    # hit.get("similarity_score") — without this field
                    # every hit scores 0.0 and fails the threshold,
                    # producing singleton groups regardless of how
                    # similar the embeddings actually are.
                    hit = dict(m)
                    hit["similarity_score"] = sim
                    scored.append((sim, hit))
            scored.sort(key=lambda t: t[0], reverse=True)
            return [m for _, m in scored[:limit]]

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
        # Carry the embedding so the L3.1 adapter's find_similar can
        # actually cluster (without it every memory becomes a singleton
        # group and L3.1 silently degrades to raw_passthrough).
        "embedding": memory.embedding,
    }


def _content_hash(content: str) -> str:
    """SHA-256 hex digest of normalised content."""
    import hashlib
    import unicodedata

    normalised = unicodedata.normalize("NFC", content).strip().lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


# ── Cross-namespace merge detection ───────────────────────────────────────


async def _check_namespace_content_similarity(
    user_id: str,
    current_namespace: str,
    db: AsyncSession,
) -> None:
    """Compare this namespace's consolidated_summary against all other
    namespace summaries for the same user. Pairs with cosine similarity
    >= NAMESPACE_MERGE_THRESHOLD are flagged in related_namespaces with
    action='suggest_merge' on both NamespacePolicy rows.

    Skips sibling pairs sharing the same ':'-prefix (e.g. project:alpha /
    project:beta) — they are structurally distinct, not accidental duplicates.

    Performance guard: skipped entirely when the user has >
    NAMESPACE_MERGE_MAX_NAMESPACES namespaces with summaries.
    """
    from backend.models.namespace_policy import NamespacePolicy

    # Scope to this user's namespaces via Memory (NamespacePolicy has no user_id).
    user_ns_result = await db.execute(
        select(Memory.namespace)
        .where(Memory.user_id == uuid.UUID(user_id), Memory.invalid_at.is_(None))
        .group_by(Memory.namespace)
    )
    user_namespaces = {row[0] for row in user_ns_result.all()}

    policy_result = await db.execute(
        select(NamespacePolicy).where(
            NamespacePolicy.namespace.in_(user_namespaces),
            NamespacePolicy.consolidated_summary.isnot(None),
        )
    )
    policies = policy_result.scalars().all()

    if len(policies) < 2:
        return
    if len(policies) > NAMESPACE_MERGE_MAX_NAMESPACES:
        logger.debug(
            "namespace_similarity.skipped.too_many",
            count=len(policies),
            user_id=user_id,
        )
        return

    current_policy = next((p for p in policies if p.namespace == current_namespace), None)
    if current_policy is None:
        return

    # Embed summaries, reusing the existing module-level cache.
    def _embed_summary(text: str) -> list[float]:
        cached = _summary_embedding_cache.get(text)
        if cached is not None:
            return cached
        from memory_vault.embeddings.encoder import encode as _encode

        vec = list(_encode(text))
        if len(_summary_embedding_cache) > 256:
            for k in list(_summary_embedding_cache.keys())[:64]:
                _summary_embedding_cache.pop(k, None)
        _summary_embedding_cache[text] = vec
        return vec

    def _are_siblings(a: str, b: str) -> bool:
        if ":" not in a or ":" not in b:
            return False
        return a.rsplit(":", 1)[0] == b.rsplit(":", 1)[0]

    def _already_flagged(policy: NamespacePolicy, target_ns: str) -> bool:
        return any(
            e.get("namespace") == target_ns and e.get("action") == "suggest_merge"
            for e in (policy.related_namespaces or [])
        )

    current_vec = _embed_summary(current_policy.consolidated_summary)
    now_iso = datetime.now(UTC).isoformat()
    any_updated = False

    for other in policies:
        if other.namespace == current_namespace:
            continue
        if _are_siblings(current_namespace, other.namespace):
            continue

        other_vec = _embed_summary(other.consolidated_summary)
        # L2-normalised vectors → cosine = dot product
        similarity = sum(a * b for a, b in zip(current_vec, other_vec, strict=False))

        if similarity < NAMESPACE_MERGE_THRESHOLD:
            continue

        entry_cur = {
            "namespace": other.namespace,
            "similarity": round(float(similarity), 4),
            "detected_at": now_iso,
            "action": "suggest_merge",
        }
        entry_oth = {
            "namespace": current_namespace,
            "similarity": round(float(similarity), 4),
            "detected_at": now_iso,
            "action": "suggest_merge",
        }

        if not _already_flagged(current_policy, other.namespace):
            new_list = list(current_policy.related_namespaces or [])
            new_list.append(entry_cur)
            current_policy.related_namespaces = new_list[-20:]
            any_updated = True

        if not _already_flagged(other, current_namespace):
            new_list = list(other.related_namespaces or [])
            new_list.append(entry_oth)
            other.related_namespaces = new_list[-20:]
            any_updated = True

        if any_updated:
            logger.info(
                "namespace_similarity.merge_candidate",
                namespace_a=current_namespace,
                namespace_b=other.namespace,
                similarity=round(float(similarity), 4),
            )

    if any_updated:
        await db.flush()


# ── Session prewarm ────────────────────────────────────────────────────────


async def prewarm_namespace(
    user_id: str,
    namespace: str,
    db: AsyncSession,
) -> None:
    """Force-run L3 summarisation for a namespace if the summary is stale
    or absent. Bypasses the novelty/debounce gates — the purpose here is
    to guarantee a fresh summary exists when an agent's token is issued,
    not to react to a specific memory write.

    Called from _bg_prewarm_context in agents.py via asyncio.create_task.
    """
    from backend.models.namespace_policy import NamespacePolicy

    policy_result = await db.execute(select(NamespacePolicy).where(NamespacePolicy.namespace == namespace))
    policy = policy_result.scalar_one_or_none()

    updated_at = policy.consolidated_summary_updated_at if policy else None
    is_stale = updated_at is None or (
        (datetime.now(UTC) - updated_at).total_seconds() > PREWARM_STALENESS_SECONDS
    )
    if not is_stale:
        logger.debug(
            "prewarm.skip.fresh",
            namespace=namespace,
            updated_at=updated_at.isoformat() if updated_at else None,
        )
        return

    source_result = await db.execute(
        select(Memory)
        .where(
            Memory.user_id == uuid.UUID(user_id),
            Memory.namespace == namespace,
            Memory.invalid_at.is_(None),
            Memory.content_type != "concept",
        )
        .order_by(Memory.created_at.desc())
    )
    source_memories = source_result.scalars().all()
    count = len(source_memories)

    if count < L3_SUMMARY_THRESHOLD:
        logger.debug("prewarm.skip.below_threshold", namespace=namespace, count=count)
        return

    key = (user_id, namespace)
    await _do_summarize_l3(db, user_id, namespace, source_memories, count, key)
    logger.info("prewarm.summarized", namespace=namespace, source_count=count)
