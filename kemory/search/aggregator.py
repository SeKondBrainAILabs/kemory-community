"""
kemory/search/aggregator.py
============================
Numeric / list aggregation skill for the memory vault.

This module is the third stage of the ``/api/v1/memories/aggregate``
pipeline:

    hybrid_search()  →  aggregator.aggregate()  →  structured response

It addresses a class of question that is common in agent memory but
that bare LLM synthesis gets badly wrong: "how many bike-related
expenses did I have", "total hours spent driving on my road trips",
"list every distinct citrus fruit I used in cocktails". The failure
mode is well documented (Wang et al. 2022, "self-consistency"; LLM
arithmetic is unreliable past short contexts) — the model under-counts
or hallucinates list items when forced to aggregate inside a single
generation pass.

The fix follows the standard "tool-use" decomposition:

    1. **Recall**  — hybrid search returns candidate memories.
    2. **Extract** — LLM (via ``core-ai-backend``) extracts a structured
       list, one entry per relevant fact, as JSON. Each entry carries
       its source memory_id so we keep provenance.
    3. **Aggregate** — Python ``len()`` / ``sum()`` / dedupe operates
       on the extracted JSON. This is the part the LLM does badly
       and Python does perfectly.
    4. **Format**  — LLM produces a natural-language final answer
       conditioned on the Python-computed aggregate.

The LLM call goes through ``core-ai-backend`` exclusively (same
pattern as ``kemory/search/reranker.py``). Memory Vault never calls
Groq / OpenAI / Anthropic directly. If the backend is unset the
aggregator returns ``None`` and the caller is expected to fall back
to a plain ``hybrid_search`` response (no aggregation block).

Story: KMV-AGG-01 (LongMemEval-S motivated; multi-session counting
       category was 75% with bare synthesis, target ≥85% with this
       skill engaged).
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)


# ── Config ───────────────────────────────────────────────────────────


# core-ai-backend base URL. Same env var contract as ``reranker.py``.
_AI_BACKEND_URL: str = (os.getenv("CORE_AI_BACKEND_URL") or os.getenv("AI_BACKEND_URL", "")).rstrip("/")

# Model that core-ai-backend should use for extraction + formatting.
# Default matches the reranker so the two services share a model;
# overridable via env when a benchmark needs a stronger reader.
_AGG_MODEL: str = os.getenv(
    "KMV_AGG_MODEL",
    os.getenv("KMV_SYNTHESIS_MODEL", "llama-3.3-70b-versatile"),
)

# Maximum candidates fed to the extractor. 30 matches the
# multi-session topK from the LongMemEval harness — the category
# where this skill matters most. Cap is here (not the caller's
# concern) because the extraction prompt has its own token budget.
_MAX_CANDIDATES: int = int(os.getenv("KMV_AGG_MAX_CANDIDATES", "30"))

# Per-snippet character cap going into the extraction prompt. Mirror
# of the reranker's _SNIPPET_CHARS so multi-thousand-token memories
# don't blow the context window.
_SNIPPET_CHARS: int = int(os.getenv("KMV_AGG_SNIPPET_CHARS", "600"))

# Wall-clock for the chat-completions call. Two LLM round-trips
# (extract + format) + httpx overhead, generous for a 30-snippet
# extract on a 70b reader.
_TIMEOUT_S: float = float(os.getenv("KMV_AGG_TIMEOUT_S", "120"))


# ── Prompt templates ────────────────────────────────────────────────


# Note: "Output ONLY the JSON object" is repeated three times because
# llama-3.3-70b leaks markdown fences ~30% of the time at T=0; we
# strip fences in _parse_json_object below as a belt-and-braces.
_EXTRACTION_PROMPT = """\
You are an aggregation assistant. The user has asked an aggregation
question over their memory history. Read the memories below carefully
and extract EVERY distinct item, event, value, or fact relevant to
the question — and ONLY those. Do not add items that aren't in the
memories.

Question: {query}

Memories:
{memories_block}

Output ONLY a JSON object with this exact shape, nothing else:

{{
  "type": "count|sum|list|duration|other",
  "items": [
    {{
      "memory_id": "<the memory_id from the snippet header>",
      "extracted": "<one short phrase describing the item>",
      "value": <number or null — populate only for sum/duration questions>
    }},
    ...
  ]
}}

Rules:
- Use "count" for "how many ..."
- Use "sum"   for "what's the total / sum / cost / amount of ..."
- Use "list"  for "what / which X did I ... " questions
- Use "duration" for "how long / how many days/weeks/months/hours ..."
- Use "other" if the question doesn't fit any of the above; the
  caller will fall back to plain synthesis.
- Deduplicate: same item mentioned in multiple memories is ONE entry.
- Numbers in `value` should be plain (no $ or units). Use null when
  the question is a count or list.
- Do NOT include items where you are unsure they're relevant.
- Output ONLY the JSON object. No preamble, no markdown fences.
"""


_FORMAT_PROMPT = """\
You are answering an aggregation question about the user's history.
The Python aggregator has already computed the structured result
below — use ONLY that result, do not recount.

Question: {query}
Aggregate result: {aggregate_text}
Items: {items_text}

Give a concise one-sentence answer using the aggregate result.
Do not show your work; do not list every item; do not say "based
on the memories". Just the answer.
"""


# ── Public API ──────────────────────────────────────────────────────


async def aggregate(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    max_candidates: int = _MAX_CANDIDATES,
) -> dict[str, Any] | None:
    """Run the extract → aggregate → format pipeline.

    Parameters
    ----------
    query:
        The user's natural-language aggregation question.
    candidates:
        Output of ``hybrid_search`` (list of memory dicts). Must
        contain at least ``memory_id`` and ``content`` per entry.
    max_candidates:
        Cap on how many candidates are fed to the extractor.

    Returns
    -------
    dict or None
        On success, a dict shaped::

            {
                "type": "count" | "sum" | "list" | "duration" | "other",
                "answer": "<natural-language answer>",
                "value": <number, list, or None>,
                "items": [{"memory_id": ..., "extracted": ..., "value": ...}, ...],
                "source_memory_ids": [<uuid>, ...],
            }

        Returns ``None`` if the AI backend is unreachable, the
        extraction LLM returned unparseable JSON, or there are no
        candidates. Callers should fall back to plain hybrid_search
        results in that case.
    """
    if not candidates:
        logger.debug("aggregator.no_candidates", query=query)
        return None

    if not _AI_BACKEND_URL:
        logger.info("aggregator.backend_unconfigured")
        return None

    capped = candidates[:max_candidates]

    # ── Stage 2: extract ──
    extraction = await _extract_items(query, capped)
    if extraction is None:
        return None

    agg_type: str = extraction.get("type") or "other"
    items: list[dict[str, Any]] = extraction.get("items") or []

    if agg_type == "other":
        # The extractor itself decided this isn't an aggregation
        # question. Bail out so the caller falls back to synthesise().
        logger.debug("aggregator.type_other", query=query)
        return None

    # ── Stage 3: aggregate (the Python part the LLM gets wrong) ──
    aggregate_text, value = _python_aggregate(agg_type, items)

    # ── Stage 4: format ──
    answer = await _format_answer(query, aggregate_text, items)
    if answer is None:
        # Format failed; fall back to a deterministic answer string.
        answer = aggregate_text

    source_memory_ids = [i["memory_id"] for i in items if i.get("memory_id")]
    return {
        "type": agg_type,
        "answer": answer,
        "value": value,
        "items": items,
        "source_memory_ids": source_memory_ids,
    }


# ── Stage 2: LLM extract ────────────────────────────────────────────


async def _extract_items(
    query: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Call core-ai-backend to extract structured items as JSON."""
    memories_block = _format_memories(candidates)
    prompt = _EXTRACTION_PROMPT.format(
        query=query,
        memories_block=memories_block,
    )

    raw = await _chat_completion(prompt, max_tokens=1024, temperature=0.0)
    if not raw:
        return None

    obj = _parse_json_object(raw)
    if obj is None:
        logger.warning("aggregator.extract_unparseable", preview=raw[:200])
        return None

    # Defensive: if LLM returns malformed item entries, drop them
    # rather than crashing downstream.
    items = obj.get("items")
    if not isinstance(items, list):
        logger.warning("aggregator.extract_no_items_list")
        return None
    obj["items"] = [i for i in items if isinstance(i, dict) and "memory_id" in i]
    return obj


# ── Stage 3: Python aggregation ─────────────────────────────────────


def _python_aggregate(
    agg_type: str,
    items: list[dict[str, Any]],
) -> tuple[str, Any]:
    """Aggregate items algorithmically. Returns (text_for_format, value)."""
    if agg_type == "count":
        # Dedupe on the extracted phrase (case-insensitive).
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for it in items:
            key = str(it.get("extracted", "")).strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(it)
        n = len(unique)
        return f"Count = {n}", n

    if agg_type == "sum":
        total = 0.0
        for it in items:
            v = it.get("value")
            try:
                total += float(v)
            except (TypeError, ValueError):
                continue
        # Render as int when no fractional component (matches the
        # way users phrase the answer: "$185" not "$185.00").
        rendered = int(total) if total == int(total) else round(total, 2)
        return f"Sum = {rendered}", rendered

    if agg_type == "duration":
        # Same as sum but the units are in the question, not the
        # value. The format step interprets unit; we just total.
        total = 0.0
        for it in items:
            v = it.get("value")
            try:
                total += float(v)
            except (TypeError, ValueError):
                continue
        rendered = int(total) if total == int(total) else round(total, 2)
        return f"Total duration = {rendered}", rendered

    if agg_type == "list":
        # Dedupe; preserve order.
        seen2: set[str] = set()
        unique2: list[str] = []
        for it in items:
            key2 = str(it.get("extracted", "")).strip().lower()
            if key2 and key2 not in seen2:
                seen2.add(key2)
                unique2.append(str(it.get("extracted")).strip())
        return "List: " + ", ".join(unique2), unique2

    return "Result: unable to aggregate", None


# ── Stage 4: LLM format ─────────────────────────────────────────────


async def _format_answer(
    query: str,
    aggregate_text: str,
    items: list[dict[str, Any]],
) -> str | None:
    """Convert the Python-computed aggregate into a natural-language answer."""
    items_preview = ", ".join(str(i.get("extracted", ""))[:60] for i in items[:10])
    prompt = _FORMAT_PROMPT.format(
        query=query,
        aggregate_text=aggregate_text,
        items_text=items_preview,
    )
    return await _chat_completion(prompt, max_tokens=128, temperature=0.0)


# ── Helpers ─────────────────────────────────────────────────────────


async def _chat_completion(
    prompt: str,
    *,
    max_tokens: int,
    temperature: float,
) -> str | None:
    """OpenAI-compatible chat completion against core-ai-backend.

    Returns the assistant content, or None on any error. Same envelope
    as ``reranker._call_ai_backend`` so the two skills share infra
    expectations.
    """
    if not _AI_BACKEND_URL:
        return None
    url = f"{_AI_BACKEND_URL}/v1/chat/completions"
    payload = {
        "model": _AGG_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
            choices = data.get("choices") or []
            if not choices:
                return None
            content = (choices[0].get("message") or {}).get("content")
            if not content:
                return None
            return content.strip()
    except Exception as exc:
        logger.warning("aggregator.backend_error", error=str(exc))
        return None


def _format_memories(candidates: list[dict[str, Any]]) -> str:
    """Render memory candidates with the snippet header the prompt expects."""
    lines: list[str] = []
    for i, c in enumerate(candidates, 1):
        mid = c.get("memory_id") or c.get("id") or f"unknown-{i}"
        content = (c.get("content") or "")[:_SNIPPET_CHARS]
        date = (
            (c.get("metadata") or {}).get("session_date", "")
            if isinstance(
                c.get("metadata"),
                dict,
            )
            else ""
        )
        date_tag = f" | {date}" if date else ""
        lines.append(f"[Memory {i} | {mid}{date_tag}]\n{content}")
    return "\n\n".join(lines)


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    """Extract a JSON object from a possibly-fenced LLM response."""
    # Strip code fences if present.
    m = _JSON_FENCE_RE.search(raw)
    candidate = m.group(1) if m else raw

    # Find the outermost {...} in case the LLM still leaked prose.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(candidate[start : end + 1])
    except json.JSONDecodeError:
        return None
