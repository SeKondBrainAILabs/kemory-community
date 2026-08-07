"""
kemory/search/reranker.py
================================
LLM-backed re-ranker and synthesiser for ``kora_get_context``.

This module handles the third stage of the hybrid retrieval pipeline:
given a ranked list of candidate memory snippets, it calls Groq to produce a
single, coherent natural-language answer.

Design decisions
----------------
* The re-ranker is **optional** — if the AI backend is unavailable or the
  caller opts out, the raw ranked list is returned unchanged.
* The prompt is intentionally minimal: we pass the topic and the top-N
  snippets and ask for a concise synthesis.  The full prompt template is
  stored in ``House_Rules_Contracts/PROMPTS_CONTRACT.md`` (entry: KMV-RERANK-01).
* The AI call uses the local user's ``GROQ_API_KEY``. If it is unset, the
  reranker returns ``None`` and ``get_context`` falls through to raw context.

Story: S9N-3074-SUB3
Author: sachmans <sachin@sachinduggal.com>
"""

from __future__ import annotations

import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Maximum number of memory snippets to include in the synthesis prompt
_MAX_SNIPPETS: int = int(os.getenv("KMV_RERANK_MAX_SNIPPETS", "10"))

# Maximum characters per snippet sent to the LLM
_SNIPPET_CHARS: int = int(os.getenv("KMV_RERANK_SNIPPET_CHARS", "400"))

# Model to use for synthesis (overridable via env).
_SYNTHESIS_MODEL: str = os.getenv("KMV_SYNTHESIS_MODEL", "llama-3.3-70b-versatile")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def synthesise(
    topic: str,
    candidates: list[dict[str, Any]],
    *,
    max_snippets: int = _MAX_SNIPPETS,
) -> str | None:
    """
    Synthesise a natural-language answer from a ranked list of memory snippets.

    Parameters
    ----------
    topic:
        The user's question or topic string (from ``kora_get_context``).
    candidates:
        Ranked list of memory dicts (output of ``hybrid_search`` or
        ``rank_results``).  Must contain at minimum a ``content`` key.
    max_snippets:
        Maximum number of snippets to include in the prompt.

    Returns
    -------
    str or None
        The synthesised answer, or ``None`` if the AI backend is unavailable
        or returns an empty response.
    """
    if not candidates:
        return None

    snippets = candidates[:max_snippets]
    prompt = _build_prompt(topic, snippets)

    try:
        answer = await _call_ai_backend(prompt)
        logger.debug("reranker.synthesise.ok", topic=topic[:80], answer_len=len(answer or ""))
        return answer
    except Exception as exc:
        logger.warning("reranker.synthesise.failed", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _build_prompt(topic: str, snippets: list[dict[str, Any]], max_snippets: int = _MAX_SNIPPETS) -> str:
    """
    Build the synthesis prompt.

    Prompt ID: KMV-RERANK-01 (see PROMPTS_CONTRACT.md)
    """
    # Enforce snippet limit inside the builder so callers don't need to pre-slice
    limited = snippets[:max_snippets]
    snippet_block = "\n\n".join(
        f"[Memory {i + 1} | ns={s.get('namespace', '?')} | type={s.get('content_type', '?')}]\n"
        f"{s.get('content', '')[:_SNIPPET_CHARS]}"
        for i, s in enumerate(limited)
    )

    return (
        "You are a memory synthesis assistant. "
        "Given the following memory snippets retrieved from a user's personal memory vault, "
        "answer the question concisely and accurately. "
        "If the answer cannot be determined from the snippets, say 'I don't know'.\n\n"
        f"QUESTION: {topic}\n\n"
        f"MEMORY SNIPPETS:\n{snippet_block}\n\n"
        "ANSWER (one or two sentences, factual, no preamble):"
    )


# ---------------------------------------------------------------------------
# AI backend call
# ---------------------------------------------------------------------------


async def _call_ai_backend(prompt: str) -> str | None:
    """
    Call the community Groq backend to generate a synthesis response.
    """
    return await _call_internal_backend(prompt)


async def _call_internal_backend(prompt: str) -> str | None:
    """POST to the user-configured Groq service."""
    from kemory.llm import assistant_text, chat_completion

    payload = {
        "model": os.getenv("KMV_SYNTHESIS_MODEL", _SYNTHESIS_MODEL),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 256,
        "temperature": 0.1,
    }

    # Local llama.cpp routes (Brain on CPU) routinely take 20–30s for
    # 256-token completions on a 70B model. 30s caused regular timeouts;
    # 120s is comfortable headroom while still bounded enough that a
    # stuck call doesn't hang the request indefinitely.
    return assistant_text(await chat_completion(payload, timeout_seconds=120.0))
