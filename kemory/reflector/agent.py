"""
kemory/reflector/agent.py
================================
Reflector Agent — consolidates episodic memories into semantic summaries.

**Local Edition**: Groups episodes by content overlap, produces a
concatenated summary string, no LLM needed.

**LLM mode**: Calls the configured Groq, llama.cpp, or Vertex AI model to
generate a natural language reflection over the provided episodes.

Story: KMV-V2-E06 — Reflector Agent
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReflectionResult:
    """
    A consolidated reflection over a set of episodic memories.

    Attributes
    ----------
    summary:
        Natural language summary of the episode set.
    themes:
        List of inferred topic/theme strings (e.g. ``["Python", "testing"]``).
    source_episode_ids:
        IDs of the episodes that were consolidated.
    source:
        Extraction path: ``"local"`` or ``"groq"``.
    """

    summary: str = ""
    themes: list[str] = field(default_factory=list)
    source_episode_ids: list[str] = field(default_factory=list)
    source: str = "local"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def reflect(
    episodes: list[dict[str, Any]],
    use_groq: bool | None = None,
) -> ReflectionResult:
    """
    Generate a reflection over a list of episode dicts.

    Parameters
    ----------
    episodes:
        List of episode dicts (as returned by ``search_episodes`` or
        ``list_episodes``).  Each must have at minimum ``id`` and
        ``content`` keys.
    use_groq:
        Backward-compatible LLM override. ``None`` auto-detects the configured
        Community provider.

    Returns
    -------
    ReflectionResult
        Consolidated summary and themes.

    Story: KMV-V2-E06
    """
    if not episodes:
        return ReflectionResult()

    if use_groq is None:
        from kemory.llm import llm_enabled

        use_groq = llm_enabled()

    if use_groq:
        try:
            return await _groq_reflect(episodes)
        except Exception as exc:
            logger.warning("Reflector: LLM reflection failed, falling back to local: %s", exc)

    return _local_reflect(episodes)


# ---------------------------------------------------------------------------
# Local Edition
# ---------------------------------------------------------------------------

# Common stopwords to skip when extracting themes
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "shall",
        "can",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "with",
        "by",
        "from",
        "and",
        "or",
        "but",
        "not",
        "it",
        "this",
        "that",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "my",
        "your",
        "his",
        "her",
        "our",
        "their",
        "its",
        "s",
        "t",
        "re",
        "ve",
        "ll",
    }
)


def _local_reflect(episodes: list[dict[str, Any]]) -> ReflectionResult:
    """Heuristic reflection: summarise by concatenation + keyword themes."""
    ids = [ep["id"] for ep in episodes if ep.get("id")]
    contents = [ep.get("content", "") for ep in episodes]

    # Summary: join first sentence of each episode
    summaries = []
    for content in contents:
        first = content.split(".")[0].strip()
        if first and len(first) >= 10:
            summaries.append(first)

    summary = ". ".join(summaries[:5])
    if summary and not summary.endswith("."):
        summary += "."

    # Themes: top-N words by frequency (excluding stopwords)
    word_freq: dict[str, int] = {}
    for content in contents:
        for word in re.findall(r"\b[a-zA-Z]{4,}\b", content.lower()):
            if word not in _STOPWORDS:
                word_freq[word] = word_freq.get(word, 0) + 1

    themes = [w for w, _ in sorted(word_freq.items(), key=lambda x: -x[1])[:5]]

    return ReflectionResult(
        summary=summary,
        themes=themes,
        source_episode_ids=ids,
        source="local",
    )


# ---------------------------------------------------------------------------
# Community LLM provider
# ---------------------------------------------------------------------------

_GROQ_REFLECTION_PROMPT = """\
You are a memory reflection agent. Given the following memory episodes from a
conversation, generate a concise reflection that:
1. Summarises the key information in 1-2 sentences
2. Lists 3-5 key themes or topics

Return ONLY valid JSON:
{{
  "summary": "...",
  "themes": ["theme1", "theme2", ...]
}}

Episodes:
{episodes_text}

JSON:"""


async def _groq_reflect(episodes: list[dict[str, Any]]) -> ReflectionResult:
    """Generate reflection through the configured Community LLM."""
    import json

    from kemory.llm import assistant_text, chat_completion, llm_provider

    episodes_text = "\n".join(f"- {ep.get('content', '')[:200]}" for ep in episodes[:10])
    ids = [ep["id"] for ep in episodes if ep.get("id")]

    response = await chat_completion(
        {
            "model": os.environ.get(
                "KEMORY_LLM_MODEL",
                os.environ.get("KMV_SYNTHESIS_MODEL", "llama-3.1-8b-instant"),
            ),
            "messages": [
                {
                    "role": "user",
                    "content": _GROQ_REFLECTION_PROMPT.format(episodes_text=episodes_text),
                }
            ],
            "temperature": 0.3,
            "max_tokens": 256,
            "response_format": {"type": "json_object"},
        }
    )
    raw = assistant_text(response) or "{}"
    raw = re.sub(r"^```(?:json)?\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw.strip())
    data = json.loads(raw)

    return ReflectionResult(
        summary=data.get("summary", ""),
        themes=data.get("themes") or [],
        source_episode_ids=ids,
        source=llm_provider(),
    )
