"""
kemory/search/chain_of_note.py
======================================
Chain-of-Note (CoN) structured search output for S9N Memory Vault v2.0.

Dual-Mode implementation:
- **Local Edition**: returns metadata-only enrichment. ``summary`` and
  ``chain_of_note`` fields are ``None``.  Relevance score is approximated
  from result rank.
- **Cloud Edition** (Groq): generates natural-language CoN using
  ``llama-3.1-8b-instant``.  Implemented in V2-E05 (Observer Agent / Cloud
  routing).

The output format matches the spec §8.10 schema exactly so that agents can
rely on a stable JSON contract regardless of the underlying mode.

Usage::

    from kemory.search.chain_of_note import format_results

    results = await service.recall("What languages does the user prefer?", org_id)
    response = format_results(
        query="What languages does the user prefer?",
        results=results,
        time_range=None,
    )
    # response is a dict ready for JSON serialisation

Story: KMV-V2-E09b — Chain-of-Note + JSON Output
"""

from __future__ import annotations

from typing import Any


def format_results(
    query: str,
    results: list[dict[str, Any]],
    time_range: tuple[str, str] | None = None,
    *,
    summary: str | None = None,
    chain_of_notes: list[str | None] | None = None,
) -> dict[str, Any]:
    """
    Structure raw search results into the standard CoN JSON response format.

    Parameters
    ----------
    query:
        The original user search query.
    results:
        List of episode dicts as returned by ``LocalStorageBackend.search_episodes``.
    time_range:
        Optional ``(start_iso, end_iso)`` pair from temporal expansion, or
        ``None`` if no temporal filter was applied.
    summary:
        Overall summary of the result set.  Passed by Cloud Edition after Groq
        generation; ``None`` for Local Edition.
    chain_of_notes:
        Per-result relevance notes, parallel list with ``results``.  Each
        element is a string from Groq or ``None`` for Local Edition.

    Returns
    -------
    dict[str, Any]
        Standard CoN response dict matching spec §8.10, suitable for JSON
        serialisation.

    Story: KMV-V2-E09b
    """
    formatted_results = []
    for i, ep in enumerate(results):
        note: str | None = None
        if chain_of_notes and i < len(chain_of_notes):
            note = chain_of_notes[i]

        formatted_results.append(_format_item(ep, rank=i + 1, chain_of_note=note))

    return {
        "query": query,
        "time_range": _format_time_range(time_range),
        "result_count": len(results),
        "summary": summary,
        "results": formatted_results,
    }


def _format_item(
    ep: dict[str, Any],
    rank: int,
    chain_of_note: str | None,
) -> dict[str, Any]:
    """Format a single episode dict into a CoN result item."""
    extra = ep.get("extra_json") or "{}"
    try:
        import json as _json

        extra_data: dict[str, Any] = _json.loads(extra) if isinstance(extra, str) else {}
    except Exception:
        extra_data = {}

    return {
        "memory_id": ep.get("id"),
        "content": ep.get("content"),
        "memory_type": extra_data.get("memory_type"),
        "content_type": extra_data.get("content_type"),
        "created_at": ep.get("created_at"),
        "relevance_score": _rank_to_score(rank),
        "chain_of_note": chain_of_note,
    }


def _rank_to_score(rank: int) -> float:
    """
    Approximate relevance score from rank position.

    Uses smooth exponential decay so top results are clearly differentiated.
    Scores range from ~1.0 (rank 1) down to ~0.1 (rank 10+).

    In Cloud Edition, this is replaced by the actual Groq-generated score.
    """
    return round(max(0.1, 1.0 - 0.09 * (rank - 1)), 2)


def _format_time_range(time_range: tuple[str, str] | None) -> dict[str, str] | None:
    """Convert ``(start, end)`` tuple to dict or None."""
    if time_range is None:
        return None
    return {"start": time_range[0], "end": time_range[1]}
