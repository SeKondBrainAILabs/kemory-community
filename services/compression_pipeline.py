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
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import _get_session_factory
from backend.models.memory import Memory

logger = structlog.get_logger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────

# Minimum number of active memories in a namespace before L3 narrative summary runs
L3_SUMMARY_THRESHOLD: int = 2

# Minimum number of *new* memories added since last L3 summary before we re-run
L3_SUMMARY_MIN_NEW_MEMORIES: int = 1

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

# ── In-process debounce state ──────────────────────────────────────────────
# Maps (user_id_str, namespace) → count of memories at last L3.1 synthesis run
_last_synthesis_count: dict[tuple[str, str], int] = {}

# Maps (user_id_str, namespace) → count of memories at last L3 summary run
_last_summary_count: dict[tuple[str, str], int] = {}


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
        async with _get_session_factory()() as db:
            await _promote_to_l2(db, memory_id)
            await db.commit()

        async with _get_session_factory()() as db:
            await _maybe_summarize_l3(db, user_id, namespace, trigger_memory_id=memory_id)
            await db.commit()

        # Session-level L3 only runs if this memory has a session_id.
        async with _get_session_factory()() as db:
            await _maybe_summarize_session_l3(db, user_id, memory_id, namespace)
            await db.commit()

        async with _get_session_factory()() as db:
            await _maybe_synthesize_l3_1(db, user_id, namespace)
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
    result = await db.execute(
        select(Memory).where(Memory.memory_id == uuid.UUID(memory_id))
    )
    memory = result.scalar_one_or_none()
    if memory is None:
        return

    # Already at L2 or above — skip
    existing_tier = (memory.meta or {}).get("_compression_tier", "L1")
    if existing_tier != "L1":
        return

    try:
        from memory_vault.compression.aaak import encode_aaak, compression_ratio
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
        "_compressed_at": datetime.now(timezone.utc).isoformat(),
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
    target_row = (await db.execute(
        select(Memory.embedding).where(Memory.memory_id == uuid.UUID(memory_id))
    )).first()
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
        for a, b in zip(target_vec, vec):
            sim += a * b
        if sim > best:
            best = sim
    return best if best > -2.0 else -1.0


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
        db, memory_id, user_id, namespace,
        session_id=session_id, up_to_ts=up_to_ts,
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
        select(Memory).where(
            Memory.user_id == uuid.UUID(user_id),
            Memory.namespace == namespace,
            Memory.invalid_at == None,  # noqa: E711
            Memory.content_type != "concept",
        ).order_by(Memory.created_at.desc())
    )
    source_memories = result.scalars().all()
    count = len(source_memories)

    if count < L3_SUMMARY_THRESHOLD:
        return

    # Novelty gate — skip if the triggering memory is a near-duplicate of
    # something already captured. The count-based debounce below would miss
    # this case: if every write adds a restatement, the count advances but
    # the summary doesn't need to change.
    if not force and trigger_memory_id is not None:
        if not await _has_sufficient_novelty(
            db, trigger_memory_id, user_id, namespace,
            stage_label="l3_namespace",
        ):
            # Move the debounce counter forward anyway so we don't retry
            # this same duplicate on the very next write.
            _last_summary_count[(user_id, namespace)] = count
            return

    # Debounce: only re-run if enough new memories have been added
    key = (user_id, namespace)
    last_count = _last_summary_count.get(key, 0)
    if count - last_count < L3_SUMMARY_MIN_NEW_MEMORIES and last_count > 0:
        return

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
    try:
        from backend.models.namespace_policy import NamespacePolicy
        policy = (
            await db.execute(
                select(NamespacePolicy).where(NamespacePolicy.namespace == namespace)
            )
        ).scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if policy is None:
            policy = NamespacePolicy(
                namespace=namespace,
                consolidated_summary=summary_text,
                consolidated_summary_tier="L3",
                consolidated_summary_updated_at=now,
                created_by=uuid.UUID(user_id),
            )
            db.add(policy)
        elif (policy.consolidated_summary_tier or "L3") == "L3":
            # Only overwrite L3 with L3 — don't downgrade an L3.1
            policy.consolidated_summary = summary_text
            policy.consolidated_summary_tier = "L3"
            policy.consolidated_summary_updated_at = now
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
    result = await db.execute(
        select(Memory).where(Memory.memory_id == uuid.UUID(memory_id))
    )
    memory = result.scalar_one_or_none()
    if memory is None:
        return
    session_id = (memory.session_id or "").strip()
    if not session_id:
        return  # This memory isn't part of any session — nothing to do.

    up_to_ts = memory.created_at
    key = (user_id, namespace, session_id)

    # ── Gather session-scoped memories ─────────────────────────────
    session_rows = (await db.execute(
        select(Memory).where(
            Memory.user_id == uuid.UUID(user_id),
            Memory.namespace == namespace,
            Memory.session_id == session_id,
            Memory.invalid_at == None,  # noqa: E711
            Memory.content_type != "concept",
        ).order_by(Memory.created_at.asc())
    )).scalars().all()
    session_count = len(session_rows)

    # ── Gather cumulative (namespace-wide, up to up_to_ts) memories ─
    cumulative_rows = (await db.execute(
        select(Memory).where(
            Memory.user_id == uuid.UUID(user_id),
            Memory.namespace == namespace,
            Memory.created_at <= up_to_ts,
            Memory.invalid_at == None,  # noqa: E711
            Memory.content_type != "concept",
        ).order_by(Memory.created_at.asc())
    )).scalars().all()
    cumulative_count = len(cumulative_rows)

    # Debounce — only re-run if at least one new memory since last time.
    last_count = _last_session_summary_count.get(key, 0)
    if session_count <= last_count:
        return

    # ── Novelty gates (independent per sub-summary) ────────────────
    session_novel = force or await _has_sufficient_novelty(
        db, memory_id, user_id, namespace,
        session_id=session_id,
        stage_label="l3_session",
    )
    cumulative_novel = force or await _has_sufficient_novelty(
        db, memory_id, user_id, namespace,
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
                session_sources, namespace, scope="session",
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
                    session_sources, namespace, scope="session",
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
                cumulative_sources, namespace,
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
                    cumulative_sources, namespace,
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
        existing = (await db.execute(
            select(SessionSummary).where(
                SessionSummary.user_id == uuid.UUID(user_id),
                SessionSummary.namespace == namespace,
                SessionSummary.session_id == session_id,
            )
        )).scalar_one_or_none()

        now = datetime.now(timezone.utc)
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
    try:
        from groq import AsyncGroq  # type: ignore[import]
    except ImportError:
        raise RuntimeError("groq package not installed. pip install groq")

    import os
    client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))

    memories_text = "\n".join(
        f"[{i+1}] {(m.content or '').strip()[:500]}"
        for i, m in enumerate(memories)
    )

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

    response = await client.chat.completions.create(
        model=L3_SUMMARY_GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=512,
    )
    return (response.choices[0].message.content or "").strip()


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
        .values(invalid_at=datetime.now(timezone.utc))
    )

    # Create the new concept memory
    concept_meta = {
        "_compression_tier": "L3.1",
        "_source_memory_ids": source_ids,
        "_synthesis_source": concept.get("source", "unknown"),
        "_synthesized_at": datetime.now(timezone.utc).isoformat(),
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

    # Upsert the rolling namespace summary on NamespacePolicy so agents and
    # the dashboard can read a cross-session rollup without re-running
    # synthesis. Piggy-backs on the same L3.1 run — no extra LLM cost.
    try:
        from backend.models.namespace_policy import NamespacePolicy
        policy = (
            await db.execute(
                select(NamespacePolicy).where(NamespacePolicy.namespace == namespace)
            )
        ).scalar_one_or_none()
        summary_text = concept.get("synthesis", "") or ""
        now = datetime.now(timezone.utc)
        if policy is None:
            policy = NamespacePolicy(
                namespace=namespace,
                consolidated_summary=summary_text,
                consolidated_summary_tier="L3.1",
                consolidated_summary_updated_at=now,
                created_by=uuid.UUID(user_id),
            )
            db.add(policy)
        else:
            policy.consolidated_summary = summary_text
            policy.consolidated_summary_tier = "L3.1"
            policy.consolidated_summary_updated_at = now
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
    from memory_vault.compression.concept import synthesize_namespace_local
    from memory_vault.compression.llm_client import CoreAIBackendClient

    class _StaticAdapter:
        """Minimal StorageBackend adapter for the compression module."""
        def __init__(self, mems: list[dict]) -> None:
            self._mems = mems

        async def list_episodes(self, *, org_id, limit=200, offset=0, include_invalid=False):
            return self._mems[offset: offset + limit]

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
