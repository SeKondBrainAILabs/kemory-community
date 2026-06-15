"""
kemory/compression/grouping.py
====================================
Cosine-similarity grouping helper for L3.1 concept synthesis.

Background
----------
``synthesize_namespace_local`` (in ``concept.py``) clusters memories into
candidate concept groups by calling ``backend.find_similar(content=...)``
for each memory. The hits become the seed for an LLM synthesis call.
If ``find_similar`` returns ``[]`` for everything, every memory ends up
as its own singleton group, which short-circuits to
``source="raw_passthrough"`` — the LLM is never invoked, no concept is
ever produced, and the feature silently degrades to a passthrough of
the raw memories.

This was the actual production behaviour until 2026-05-04 because the
``_DBAdapter`` inside ``backend/services/memory_service.get_namespace_compressed``
hard-coded ``find_similar`` to return ``[]``. Fixing that adapter requires
a real cosine implementation; this module is the helper both adapters
(``_DBAdapter`` for L3.1, ``_DBAdapterCog`` for L4 cognition) call so the
logic lives in one tested place rather than as duplicated closures.

The threshold (0.65) is calibrated empirically against bge-small-en-v1.5
on real stored memories:

  - dedup gate         0.92  →  "this IS the same memory"
  - concept grouping   0.65  →  "these BELONG TOGETHER as a concept"
  - recall ranker      0.50  →  "this is RELEVANT to the query"

The first cut (0.85, kemory#29) was wrong — empirical test on staging
2026-05-06 confirmed even two paraphrased memories about the same topic
("For Python use ruff..." vs "When writing Python use ruff...") scored
below 0.85, so every group ended up as a singleton and L3.1 never
synthesized anything beyond raw passthrough. bge-small typically scores
related-but-paraphrased content in 0.6-0.75 range, so 0.65 lets clear
paraphrases cluster while still excluding unrelated-on-the-same-domain
memories. If we see false-positive merges in production, raise to 0.70.
Lower than 0.60 risks merging "Python ruff prefs" with "TypeScript biome
prefs" because they share programming-language tokens.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog

logger = structlog.get_logger(__name__)

# Default threshold — exposed as a constant so tests, callers, and
# operators can introspect/override it.
DEFAULT_SIMILARITY_THRESHOLD: float = 0.65


def cosine_find_similar(
    query_content: str,
    memories: list[dict],
    *,
    encoder: Callable[[str], list[float]],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    limit: int = 20,
) -> list[dict]:
    """Return memories whose stored embedding has cosine ≥ ``threshold``
    against the query content's freshly-encoded embedding.

    Parameters
    ----------
    query_content:
        Text whose nearest neighbours we want.
    memories:
        Plain memory dicts (as produced by ``_memory_to_dict``). Must
        carry an ``embedding`` field — a list[float] of the same shape
        the encoder produces. Memories without an embedding are skipped.
    encoder:
        Callable that turns a string into a list[float]. Pass
        ``kemory.embeddings.encoder.encode`` in production. Tests
        can pass a deterministic stub. We accept this as a parameter
        rather than importing inline so unit tests don't need the
        sentence-transformers model on disk.
    threshold:
        Cosine score above which a memory is considered "in the same
        concept group". Default 0.85 — see module docstring for rationale.
    limit:
        Maximum number of neighbours to return. Sorted by cosine
        descending before truncation.

    Returns
    -------
    list[dict]
        The matching memory dicts, highest-cosine first. Each dict has
        an extra ``score`` key carrying the cosine similarity — needed
        by ``concept.py::_group_by_similarity`` so the caller's secondary
        threshold check can see the real score (it reads ``hit.get('score')``).
        Excludes any memory whose ``content`` exactly equals
        ``query_content`` (that's the query memory itself in the
        typical caller's loop).

    Failure mode
    ------------
    If the encoder raises, we log at ``warning`` and return ``[]`` —
    grouping degrades to singletons rather than crashing the whole
    compression call. This mirrors the dedup-gate visibility pattern
    (PR #26): operator-visible signal that L3.1 quality dropped, but
    the request still completes.
    """
    try:
        query_vec = encoder(query_content)
    except Exception as exc:
        logger.warning(
            "concept.group.encoder_failed",
            error_class=type(exc).__name__,
            error=str(exc),
        )
        return []

    hits: list[tuple[float, dict]] = []
    for mem in memories:
        mem_vec = mem.get("embedding")
        if not mem_vec or len(mem_vec) != len(query_vec):
            continue
        if mem.get("content") == query_content:
            continue
        sim = sum(a * b for a, b in zip(query_vec, mem_vec, strict=False))
        if sim >= threshold:
            hits.append((sim, mem))

    hits.sort(key=lambda x: x[0], reverse=True)
    # Attach score on the returned dicts so callers (e.g.
    # concept.py::_group_by_similarity) can read it via hit.get("score").
    # The original memory dicts came from _memory_to_dict and have no
    # score key, so without this their secondary threshold check sees 0.0.
    return [{**m, "score": float(sim)} for sim, m in hits[:limit]]
