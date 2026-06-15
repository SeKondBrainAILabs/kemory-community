"""
kemory/compression/concept.py
=====================================
L3.1 — Local concept compression.

Groups near-duplicate memories via existing :func:`StorageBackend.find_similar`,
detects directional sequences via existing ``supersedes`` graph edges, and calls
``core-ai-backend`` for the actual LLM synthesis.

L3.2 (Cognition OS round-trip) is a separate placeholder module — see
``compression/cognition_round_trip.py``.

Story: KMV-COMPRESS-01 / S9N-3050
"""

from __future__ import annotations

import logging
from typing import Any

from kemory.compression.llm_client import Concept, CoreAIBackendClient

logger = logging.getLogger(__name__)

# Cosine similarity threshold for grouping near-duplicates
# Secondary cluster threshold applied AFTER backend.find_similar returns.
# Must match the primary threshold in
# kemory.compression.grouping.DEFAULT_SIMILARITY_THRESHOLD — both
# need to be aligned or the backend's "is similar" decision gets re-overridden
# here and groups silently degrade to singletons. Calibrated empirically to
# bge-small-en-v1.5 paraphrase scores; see grouping.py for rationale + history.
_GROUP_SIM_THRESHOLD = 0.65
# Minimum number of contradictory memories to qualify as a "directional sequence"
_DIRECTIONAL_MIN_POSITIONS = 2
# Number of near-duplicate memories that always count as directional
_DIRECTIONAL_MIN_DUPLICATES = 4


async def synthesize_namespace_local(
    backend: Any,
    llm_client: CoreAIBackendClient | None,
    org_id: str,
    namespace: str,
    *,
    merge_mode: str = "current",
) -> dict[str, Any]:
    """L3.1 entry point.

    Walks the namespace, groups duplicates, applies merge_mode, returns
    a list of synthesized concepts plus metadata.
    """
    if llm_client is None:
        llm_client = CoreAIBackendClient()

    memories = await _list_namespace_memories(backend, org_id, namespace)
    if not memories:
        return {
            "namespace": namespace,
            "merge_mode": merge_mode,
            "concepts": [],
            "source": "local",
            "source_count": 0,
        }

    groups = await _group_by_similarity(backend, memories)
    concepts: list[dict[str, Any]] = []
    for group in groups:
        if len(group) == 1:
            mem = group[0]
            concepts.append(
                Concept(
                    name=str(mem.get("id", ""))[:8] or "concept",
                    synthesis=str(mem.get("content", "")),
                    source_memory_ids=[str(mem.get("id", ""))],
                    directional=False,
                    positions_merged=1,
                    source="raw_passthrough",
                ).to_dict()
            )
            continue

        directional = await _is_directional_sequence(backend, group)
        if directional:
            concept = await llm_client.merge_directional(group, mode=merge_mode)
        else:
            concept = await llm_client.synthesize_concept(group)
        concepts.append(concept.to_dict())

    return {
        "namespace": namespace,
        "merge_mode": merge_mode,
        "concepts": concepts,
        "source": "local",
        "source_count": len(memories),
    }


# ── Internals ─────────────────────────────────────────────────────────────


async def _list_namespace_memories(backend: Any, org_id: str, namespace: str) -> list[dict[str, Any]]:
    """Pull every active memory in a namespace, no pagination cap."""
    # list_episodes is the existing core-library entry point. The unified
    # storage stores namespace inside extra_json/metadata, so we filter
    # client-side after fetching for the org.
    out: list[dict[str, Any]] = []
    offset = 0
    page = 200
    while True:
        batch = await backend.list_episodes(
            org_id=org_id,
            limit=page,
            offset=offset,
            include_invalid=False,
        )
        if not batch:
            break
        for ep in batch:
            if _episode_namespace(ep) == namespace:
                out.append(ep)
        if len(batch) < page:
            break
        offset += page
    return out


def _episode_namespace(ep: dict[str, Any]) -> str:
    """Extract the namespace from a heterogeneous episode dict."""
    if "namespace" in ep and ep["namespace"]:
        return str(ep["namespace"])
    extra = ep.get("extra") or ep.get("extra_json") or {}
    if isinstance(extra, str):
        try:
            import json as _json

            extra = _json.loads(extra)
        except Exception:
            extra = {}
    if isinstance(extra, dict) and extra.get("namespace"):
        return str(extra["namespace"])
    return "shared"


async def _group_by_similarity(backend: Any, memories: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Cluster memories by content similarity using existing find_similar.

    Falls back to single-element groups if find_similar is unavailable.
    """
    by_id: dict[str, dict[str, Any]] = {str(m.get("id")): m for m in memories if m.get("id")}
    seen: set[str] = set()
    groups: list[list[dict[str, Any]]] = []

    for mem in memories:
        mid = str(mem.get("id"))
        if not mid or mid in seen:
            continue
        group = [mem]
        seen.add(mid)
        try:
            similar = await backend.find_similar(
                content=mem.get("content", ""),
                org_id=mem.get("org_id"),
                limit=20,
            )
        except Exception as exc:
            logger.debug("find_similar.unavailable: %s", exc)
            similar = []

        for hit in similar:
            hit_id = str(hit.get("id"))
            if not hit_id or hit_id == mid or hit_id in seen:
                continue
            score = hit.get("similarity_score") or hit.get("score") or 0.0
            if score >= _GROUP_SIM_THRESHOLD and hit_id in by_id:
                group.append(by_id[hit_id])
                seen.add(hit_id)
        groups.append(group)
    return groups


async def _is_directional_sequence(backend: Any, group: list[dict[str, Any]]) -> bool:
    """A group is directional if either:

    1. It contains 2+ memories linked by ``supersedes`` graph edges, OR
    2. It has 4+ near-duplicates with overlapping content (heuristic).
    """
    if len(group) >= _DIRECTIONAL_MIN_DUPLICATES:
        return True
    if len(group) < _DIRECTIONAL_MIN_POSITIONS:
        return False

    # Check for supersedes edges between any pair in the group
    ids = [str(m.get("id")) for m in group if m.get("id")]
    for ep_id in ids:
        try:
            related = await backend.get_related(
                episode_id=ep_id,
                relation_type="supersedes",
                limit=10,
            )
        except Exception:
            related = []
        related_ids = {str(r.get("id")) for r in related if r}
        if related_ids & set(ids):
            return True
    return False
