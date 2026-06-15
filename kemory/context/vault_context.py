"""
kemory/context/vault_context.py
======================================
Stable Context Generation — vault_context v2.

Builds a structured, token-budgeted context string for agent system prompts.

**Three sections**:
- **Key Knowledge** (Reflections): semantic episodes with content_type=reflection,
  sorted by ``created_at`` DESC, top 10.
- **Recent Context** (Observations): episodic episodes, sorted by
  ``created_at`` DESC, top 15.
- **How-To Knowledge** (Procedural): procedural episodes, sorted by
  ``access_count`` DESC then ``created_at`` DESC, top 10.

**Hash-based caching**:
  1. Fetch the top-20 episode IDs (by recency + type priority).
  2. Compute ``context_hash = sha256(sorted(ids))``.
  3. If hash unchanged → return cached string.
  4. If hash changed → rebuild and update cache.

**Token budget** (character approximation at 4 chars/token):
  50% reflections, 30% observations, 20% procedural.

Story: KMV-V2-E09 — Stable Context (vault_context v2)
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Characters per token approximation
_CHARS_PER_TOKEN: int = 4

# Top-N per section
_TOP_REFLECTIONS = 10
_TOP_OBSERVATIONS = 15
_TOP_PROCEDURAL = 10

# Budget fractions
_BUDGET_REFLECTIONS = 0.50
_BUDGET_OBSERVATIONS = 0.30
_BUDGET_PROCEDURAL = 0.20


def _parse_extra(ep: dict[str, Any]) -> dict[str, Any]:
    """Safely parse the extra_json field of an episode."""
    raw = ep.get("extra_json") or ep.get("extra") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        # Handle double-encoded JSON (string inside JSON)
        if isinstance(parsed, str):
            parsed = json.loads(parsed)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _memory_type(ep: dict[str, Any]) -> str:
    """Return the memory_type from episode extra metadata."""
    extra = _parse_extra(ep)
    return extra.get("memory_type", "")


def _content_type(ep: dict[str, Any]) -> str:
    """Return the content_type from episode extra metadata."""
    extra = _parse_extra(ep)
    return extra.get("content_type", "")


def _access_count(ep: dict[str, Any]) -> int:
    """Return access_count from episode, defaulting to 0."""
    return int(ep.get("access_count") or 0)


def _partition_episodes(
    episodes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Partition episodes into (reflections, observations, procedural).

    Reflections: memory_type == "semantic" and content_type == "reflection"
      OR source_agent == "reflector"
      OR content starts with "[Reflection]"
    Procedural: memory_type == "procedural"
    Observations: memory_type == "episodic" (or default for unclassified)
    """
    reflections: list[dict[str, Any]] = []
    procedural: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []

    for ep in episodes:
        mt = _memory_type(ep)
        ct = _content_type(ep)
        content = ep.get("content", "")
        source_agent = ep.get("source_agent", "")

        if (
            (mt == "semantic" and ct == "reflection")
            or source_agent == "reflector"
            or content.startswith("[Reflection]")
        ):
            reflections.append(ep)
        elif mt == "procedural":
            procedural.append(ep)
        else:
            observations.append(ep)

    return reflections, observations, procedural


def _sort_reflections(eps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort reflections by created_at DESC."""
    return sorted(eps, key=lambda e: e.get("created_at") or "", reverse=True)


def _sort_observations(eps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort observations by created_at DESC."""
    return sorted(eps, key=lambda e: e.get("created_at") or "", reverse=True)


def _sort_procedural(eps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort procedural memories by access_count DESC, then created_at DESC."""
    return sorted(
        eps,
        key=lambda e: (_access_count(e), e.get("created_at") or ""),
        reverse=True,
    )


def _truncate_to_chars(text: str, max_chars: int) -> str:
    """Truncate text to max_chars, appending '...' if truncated."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _format_section(
    label: str,
    episodes: list[dict[str, Any]],
    max_chars: int,
) -> str:
    """Format a single context section, respecting the character budget."""
    if not episodes:
        return f"### {label}\n_(none)_\n"

    lines: list[str] = [f"### {label}"]
    remaining = max_chars

    for ep in episodes:
        content = ep.get("content", "").strip()
        created = ep.get("created_at", "")[:16] if ep.get("created_at") else ""

        if created:
            line = f"- [{created}] {content}"
        else:
            line = f"- {content}"

        # Each line costs its length + newline
        line_cost = len(line) + 1
        if remaining <= 0:
            break
        if line_cost > remaining:
            # Truncate the content to fit
            available = remaining - (len(f"- [{created}] ") + 1 if created else len("- ") + 1)
            if available > 10:
                short = _truncate_to_chars(content, available)
                line = f"- [{created}] {short}" if created else f"- {short}"
                lines.append(line)
            break
        lines.append(line)
        remaining -= line_cost

    return "\n".join(lines) + "\n"


def build_context_string(
    reflections: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    procedural: list[dict[str, Any]],
    token_budget: int = 2000,
) -> str:
    """
    Build the structured context string from pre-sorted episode lists.

    Parameters
    ----------
    reflections:
        Sorted reflection episodes (top N already sliced).
    observations:
        Sorted observation episodes (top N already sliced).
    procedural:
        Sorted procedural episodes (top N already sliced).
    token_budget:
        Total token budget (default 2000 tokens ≈ 8000 chars).

    Returns
    -------
    str
        Formatted context string.
    """
    total_chars = token_budget * _CHARS_PER_TOKEN
    refl_chars = int(total_chars * _BUDGET_REFLECTIONS)
    obs_chars = int(total_chars * _BUDGET_OBSERVATIONS)
    proc_chars = int(total_chars * _BUDGET_PROCEDURAL)

    header = "## Your Memory Context\n\n"
    refl_section = _format_section("Key Knowledge (Reflections)", reflections, refl_chars)
    obs_section = _format_section("Recent Context (Observations)", observations, obs_chars)
    proc_section = _format_section("How-To Knowledge (Procedural)", procedural, proc_chars)

    return header + refl_section + "\n" + obs_section + "\n" + proc_section


def _compute_hash(episode_ids: list[str]) -> str:
    """SHA-256 of the sorted episode IDs."""
    payload = ",".join(sorted(episode_ids))
    return hashlib.sha256(payload.encode()).hexdigest()


class VaultContext:
    """
    Stateful vault_context builder with hash-based caching.

    Maintains a cached context string that is only regenerated when the
    underlying set of episodes changes (hash-based stability check).

    Parameters
    ----------
    token_budget:
        Total token budget for the context string. Default 2000.

    Story: KMV-V2-E09
    """

    def __init__(self, token_budget: int = 2000) -> None:
        self._token_budget = token_budget
        self._cache: dict[str, tuple[str, str]] = {}  # org_id → (hash, context_str)

    async def get_context(
        self,
        episodes: list[dict[str, Any]],
        org_id: str = "default",
    ) -> str:
        """
        Return the stable context string for *org_id*, rebuilding only if
        the episode set has changed.

        Parameters
        ----------
        episodes:
            Full list of valid episodes for this org (pre-fetched by caller).
        org_id:
            Organisation scope — used as the cache key.

        Returns
        -------
        str
            Formatted context string ready for system prompt injection.
        """
        # Take the top-20 IDs for hash stability check
        top_ids = [ep["id"] for ep in episodes[:20] if ep.get("id")]
        current_hash = _compute_hash(top_ids)

        cached = self._cache.get(org_id)
        if cached and cached[0] == current_hash:
            logger.debug("VaultContext cache hit for org=%s", org_id)
            return cached[1]

        context_str = self._build(episodes)
        self._cache[org_id] = (current_hash, context_str)
        logger.debug("VaultContext rebuilt for org=%s (hash=%s)", org_id, current_hash[:8])
        return context_str

    def invalidate(self, org_id: str) -> None:
        """Force cache invalidation for *org_id*."""
        self._cache.pop(org_id, None)

    def _build(self, episodes: list[dict[str, Any]]) -> str:
        """Partition, sort, slice, and format all sections."""
        reflections, observations, procedural = _partition_episodes(episodes)

        reflections = _sort_reflections(reflections)[:_TOP_REFLECTIONS]
        observations = _sort_observations(observations)[:_TOP_OBSERVATIONS]
        procedural = _sort_procedural(procedural)[:_TOP_PROCEDURAL]

        return build_context_string(
            reflections=reflections,
            observations=observations,
            procedural=procedural,
            token_budget=self._token_budget,
        )


async def build_context(
    episodes: list[dict[str, Any]],
    token_budget: int = 2000,
) -> str:
    """
    Stateless helper: build a vault context string from a list of episodes.

    Use this when you don't need cross-call caching (e.g. in tests or
    one-shot contexts).  For production use, prefer :class:`VaultContext`.

    Parameters
    ----------
    episodes:
        Valid episodes to include in the context.
    token_budget:
        Total token budget. Default 2000.

    Returns
    -------
    str
        Formatted context string.

    Story: KMV-V2-E09
    """
    vc = VaultContext(token_budget=token_budget)
    return await vc.get_context(episodes, org_id="_stateless")
