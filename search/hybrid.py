"""
kemory/search/hybrid.py
==============================
Hybrid retrieval: vector cosine similarity + trigram FTS, merged via
Reciprocal Rank Fusion (RRF).

Architecture
------------
The search pipeline has three stages:

1. **Dense pass** — cosine similarity between the query embedding and stored
   ``embedding`` column values.  Only rows where ``embedding IS NOT NULL`` are
   considered.  Falls back gracefully when no rows are embedded yet.

2. **Sparse pass** — trigram-similarity ILIKE search on ``content`` (uses the
   GIN index added by migration 005).  Always runs; provides coverage for
   un-embedded rows and exact-match terms.

3. **RRF merge** — combines the two ranked lists using the standard formula::

       score(d) = Σ  1 / (k + rank_i(d))

   where k = 60 (Cormack et al., 2009 default).  The merged list is then
   re-ranked by the multi-signal blended scorer in ``ranking.py``.

Usage
-----
This module is called from ``backend/services/memory_service.py`` when
``MemorySearchRequest.search_mode == "hybrid"`` (new optional field added by
this migration).  The existing ``"fts"`` mode continues to use the original
ILIKE path unchanged, ensuring full backward compatibility.

Story: S9N-3074-SUB2
Author: sachmans <sachin@sachinduggal.com>
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from kemory.embeddings.encoder import encode
from kemory.search.ranking import rank_results

logger = structlog.get_logger(__name__)

# RRF constant — standard value from Cormack et al. (2009)
_RRF_K: int = 60

# Maximum candidates fetched from each pass before merging
_DENSE_CANDIDATES: int = 50
_SPARSE_CANDIDATES: int = 50


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def hybrid_search(
    db: AsyncSession,
    user_id: Any,
    query: str,
    namespace: str | None = None,
    content_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """
    Execute a hybrid vector + FTS search and return re-ranked results.

    Parameters
    ----------
    db:
        Active async SQLAlchemy session.
    user_id:
        UUID of the authenticated user (enforces row-level isolation).
    query:
        Natural-language query string.
    namespace:
        Optional namespace filter.
    content_type:
        Optional content type filter.
    limit:
        Number of results to return after merging and re-ranking.
    offset:
        Pagination offset applied *after* merging.

    Returns
    -------
    list[dict]
        Merged, re-ranked list of memory dicts enriched with ``rank_score``.
    """
    logger.debug(
        "hybrid_search.start",
        user_id=str(user_id),
        namespace=namespace,
        query_len=len(query),
    )

    # Run passes sequentially — SQLAlchemy async sessions are not safe for
    # concurrent use. The small latency cost (~20ms) is worth the stability.
    dense_results = await _dense_pass(db, user_id, query, namespace, content_type)
    sparse_results = await _sparse_pass(db, user_id, query, namespace, content_type)

    logger.debug(
        "hybrid_search.passes_done",
        dense=len(dense_results),
        sparse=len(sparse_results),
    )

    # Merge via RRF
    merged = _rrf_merge(dense_results, sparse_results)

    # S9N-COGOS: Graph-augmented recall via Cognition OS
    # Expands results with cross-session entity relationships from the concept graph.
    try:
        from backend.services.cognition_bridge import get_cognition_bridge

        bridge = get_cognition_bridge()
        if bridge.enabled and query:
            graph_results = await bridge.expand_recall(query, top_k=10)
            if graph_results:
                # Inject graph results with a graph_proximity boost
                for gr in graph_results:
                    mid = gr.get("entity_id") or gr.get("id", "")
                    if mid and mid not in {r.get("memory_id") for r in merged}:
                        merged.append(
                            {
                                "memory_id": mid,
                                "content": gr.get("content", ""),
                                "namespace": namespace or "",
                                "content_type": "text",
                                "metadata": gr.get("metadata", {}),
                                "source_type": "cognition_os",
                                "score": gr.get("score", 0.5),
                                "graph_proximity": 1.0,  # Boost graph results
                            }
                        )
                logger.debug("hybrid_search.cogos_expand", added=len(graph_results))
    except Exception as exc:
        logger.debug("hybrid_search.cogos_skipped", reason=str(exc))

    # Apply multi-signal re-ranking
    reranked = rank_results(merged)

    # Paginate
    page = reranked[offset : offset + limit]

    logger.debug("hybrid_search.done", returned=len(page))
    return page


# ---------------------------------------------------------------------------
# Dense pass (vector cosine similarity)
# ---------------------------------------------------------------------------


async def _dense_pass(
    db: AsyncSession,
    user_id: Any,
    query: str,
    namespace: str | None,
    content_type: str | None,
) -> list[dict[str, Any]]:
    """
    Compute cosine similarity between the query embedding and stored vectors.

    Uses Python-side dot-product (embeddings are L2-normalised, so dot == cosine).
    Falls back to an empty list if no rows have been embedded yet or if the
    sentence-transformers package is unavailable.
    """
    try:
        query_vec = encode(query)
    except Exception as exc:  # pragma: no cover
        logger.warning("hybrid_search.dense_pass.encode_failed", error=str(exc))
        return []

    # Fetch all embedded rows for this user (with optional filters)
    # We pull the embedding as a JSON string from the DB to avoid pgvector
    # dependency — the column is stored as FLOAT[] (plain Postgres array).
    from datetime import datetime

    from backend.models.memory import Memory

    now = datetime.now(UTC)
    stmt = select(Memory).where(
        Memory.user_id == user_id,
        Memory.invalid_at.is_(None),
        or_(Memory.expires_at.is_(None), Memory.expires_at > now),
        Memory.embedding.is_not(None),
    )
    if namespace:
        stmt = stmt.where(Memory.embedding.is_not(None), Memory.namespace == namespace)
    if content_type:
        stmt = stmt.where(Memory.content_type == content_type)

    stmt = stmt.limit(_DENSE_CANDIDATES)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    if not rows:
        return []

    # Score each row.
    #
    # We attach the cosine similarity to BOTH "score" (used by RRF for sorting
    # within this pass) and "vector_sim" (a stable field that survives the
    # RRF merge, so the downstream multi-signal re-ranker can read the real
    # cosine value rather than the tiny 1/(k+rank) RRF score).
    scored: list[dict[str, Any]] = []
    for row in rows:
        stored_vec: list[float] | None = row.embedding
        if not stored_vec or len(stored_vec) != len(query_vec):
            continue
        sim = _dot(query_vec, stored_vec)
        scored.append({**_row_to_dict(row), "score": sim, "vector_sim": sim})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Sparse pass (trigram FTS)
# ---------------------------------------------------------------------------


async def _sparse_pass(
    db: AsyncSession,
    user_id: Any,
    query: str,
    namespace: str | None,
    content_type: str | None,
) -> list[dict[str, Any]]:
    """
    Trigram-similarity ILIKE search using the GIN index from migration 005.
    Falls back to plain ILIKE if pg_trgm is unavailable.
    """
    from datetime import datetime

    from backend.models.memory import Memory

    now = datetime.now(UTC)

    # Escape LIKE special chars
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    stmt = select(Memory).where(
        Memory.user_id == user_id,
        Memory.invalid_at.is_(None),
        or_(Memory.expires_at.is_(None), Memory.expires_at > now),
        Memory.content.ilike(f"%{escaped}%", escape="\\"),
    )
    if namespace:
        stmt = stmt.where(Memory.namespace == namespace)
    if content_type:
        stmt = stmt.where(Memory.content_type == content_type)

    stmt = stmt.limit(_SPARSE_CANDIDATES)
    result = await db.execute(stmt)
    rows = result.scalars().all()

    # Assign a pseudo-score based on position (1.0 for first, decaying)
    return [{**_row_to_dict(row), "score": 1.0 / (1 + i)} for i, row in enumerate(rows)]


# ---------------------------------------------------------------------------
# RRF merge
# ---------------------------------------------------------------------------


def _rrf_merge(
    dense: list[dict[str, Any]],
    sparse: list[dict[str, Any]],
    k: int = _RRF_K,
) -> list[dict[str, Any]]:
    """
    Merge two ranked lists using Reciprocal Rank Fusion.

    Formula: score(d) = Σ  1 / (k + rank_i(d))

    Documents appearing in both lists receive contributions from both ranks.
    Documents appearing in only one list receive a single contribution.
    """
    rrf_scores: dict[str, float] = {}
    all_docs: dict[str, dict[str, Any]] = {}

    for rank, doc in enumerate(dense, start=1):
        mid = doc["memory_id"]
        rrf_scores[mid] = rrf_scores.get(mid, 0.0) + 1.0 / (k + rank)
        all_docs[mid] = doc

    for rank, doc in enumerate(sparse, start=1):
        mid = doc["memory_id"]
        rrf_scores[mid] = rrf_scores.get(mid, 0.0) + 1.0 / (k + rank)
        if mid not in all_docs:
            all_docs[mid] = doc

    # Attach RRF score and sort
    merged = []
    for mid, doc in all_docs.items():
        merged.append({**doc, "score": rrf_scores[mid]})

    merged.sort(key=lambda x: x["score"], reverse=True)
    return merged


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dot(a: list[float], b: list[float]) -> float:
    """Fast dot product (cosine sim for L2-normalised vectors)."""
    return sum(x * y for x, y in zip(a, b, strict=False))


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy Memory row to a plain dict."""
    return {
        "memory_id": str(row.memory_id),
        "namespace": row.namespace,
        "content": row.content,
        "content_type": row.content_type,
        # NB: column is named "metadata" in the DB but mapped to attribute
        # `meta` on the model — `row.metadata` would return the SQLAlchemy
        # Table.metadata object (silent name collision on declarative Base),
        # which then breaks downstream `.get(...)` access in MemoryResponse
        # construction and zeros out every hybrid search result.
        "metadata": row.meta,
        "source_agent_id": str(row.source_agent_id) if row.source_agent_id else None,
        "source_type": row.source_type,
        "quality_score": row.quality_score,
        "enrichment_status": row.enrichment_status,
        "version": row.version,
        "ttl_seconds": row.ttl_seconds,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "session_id": row.session_id,
        "round_id": row.round_id,
        "valid_at": row.valid_at.isoformat() if row.valid_at else None,
        "invalid_at": row.invalid_at.isoformat() if row.invalid_at else None,
        "decay_score": row.decay_score,
        "temporal_anchor": row.temporal_anchor,
        "access_count": row.access_count or 0,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
