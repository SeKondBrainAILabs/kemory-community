"""
kemory/search/ranking.py
=================================
Hybrid retrieval ranking function (MV2-E05).

Computes a blended score from multiple signals:
- vector_sim: Cosine similarity from embeddings
- recency_score: Exponential decay based on age
- access_freq: Normalized access frequency
- graph_proximity: Edge weight from graph traversal
- utility_salience: From access tracking (MV2-E07)

Story: MV2-S05.1 — Define Ranking Function
Story: MV2-S05.2 — Graph Proximity Signal
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC
from typing import Any

# Default weights (must sum to 1.0)
DEFAULT_WEIGHTS = {
    "vector_sim": 0.35,
    "recency": 0.20,
    "access_freq": 0.15,
    "graph_proximity": 0.15,
    "utility_salience": 0.15,
}


@dataclass
class RankingSignals:
    """Raw signals for a single search result."""

    vector_sim: float = 0.0  # 0-1, from cosine similarity
    recency_days: float = 0.0  # Days since creation
    access_count: int = 0  # Total access count
    graph_proximity: float = 0.0  # 0-1, from graph edge weight
    utility_salience: float = 0.0  # 0-1, from MV2-E07


def compute_rank_score(
    signals: RankingSignals,
    weights: dict[str, float] | None = None,
    max_access_count: int = 100,
) -> float:
    """
    Compute the blended ranking score from multiple signals.

    Formula:
        score = w1*vector_sim + w2*recency + w3*access_freq + w4*graph + w5*salience

    Parameters
    ----------
    signals:
        Raw ranking signals for one result.
    weights:
        Custom weight dict. Defaults to DEFAULT_WEIGHTS.
    max_access_count:
        Normalization ceiling for access frequency.

    Returns
    -------
    float
        Blended score in [0.0, 1.0].

    Story: MV2-S05.1
    """
    w = weights or DEFAULT_WEIGHTS

    # Normalize each signal to [0, 1]
    vector_score = max(0.0, min(1.0, signals.vector_sim))
    recency_score = math.exp(-0.05 * max(0.0, signals.recency_days))
    access_freq = min(1.0, signals.access_count / max(1, max_access_count))
    graph_score = max(0.0, min(1.0, signals.graph_proximity))
    salience_score = max(0.0, min(1.0, signals.utility_salience))

    blended = (
        w.get("vector_sim", 0.35) * vector_score
        + w.get("recency", 0.20) * recency_score
        + w.get("access_freq", 0.15) * access_freq
        + w.get("graph_proximity", 0.15) * graph_score
        + w.get("utility_salience", 0.15) * salience_score
    )

    return max(0.0, min(1.0, blended))


def rank_results(
    results: list[dict[str, Any]],
    weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """
    Re-rank search results using the hybrid ranking function.

    Each result dict should contain:
    - vector_sim (float, optional): cosine similarity from the dense pass.
      Preferred field for the vector-similarity signal — survives RRF merge.
    - score (float): fallback when vector_sim is absent. NOTE: when the input
      came through `_rrf_merge` this is the RRF score (~1/(60+rank)), NOT a
      cosine similarity, so reading it as vector_sim suppresses the signal.
      Kept as a fallback only for callers that bypass RRF.
    - created_at (str): ISO timestamp
    - access_count (int): number of accesses
    - decay_score (float): current decay score (used as utility_salience)

    Returns results sorted by blended score descending.
    """
    from datetime import datetime

    now = datetime.now(UTC)
    scored = []

    for r in results:
        # Parse recency
        days = 0.0
        created = r.get("created_at", "")
        if created:
            try:
                dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                days = (now - dt).total_seconds() / 86400.0
            except Exception:
                pass

        # Prefer the explicit vector_sim field (set by `_dense_pass` and
        # preserved through RRF merge). Fall back to `score` only for callers
        # that did not go through hybrid_search — for hybrid_search results
        # `score` holds the RRF rank-fusion value, not a cosine, and using it
        # as vector_sim collapses the signal to ~0.016 across the board.
        signals = RankingSignals(
            vector_sim=r.get("vector_sim", r.get("score", 0.0)) or 0.0,
            recency_days=days,
            access_count=r.get("access_count", 0) or 0,
            graph_proximity=r.get("graph_proximity", 0.0) or 0.0,
            utility_salience=r.get("decay_score", 0.0) or 0.0,
        )

        blended = compute_rank_score(signals, weights)
        scored.append({**r, "rank_score": blended})

    scored.sort(key=lambda x: x["rank_score"], reverse=True)
    return scored
