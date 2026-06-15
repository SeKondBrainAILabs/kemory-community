"""
kemory/observer/extractor.py
====================================
Dual-mode Observer Agent for episode enrichment.

**Local Edition** (default):
- Extracts facts via regex sentence splitting + heuristics
- Detects temporal anchors via existing temporal patterns
- Classifies memory_type / content_type via keyword rules

**Cloud Edition** (when GROQ_API_KEY is set):
- Calls Groq ``llama-3.1-8b-instant`` with a structured prompt
- Falls back to Local Edition on any Groq error

Story: KMV-V2-E05 — Observer Agent (Dual-Mode)
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Circuit breaker for Groq API calls (KMV-V2-E05 spec: 5 failures in 60s)
# ---------------------------------------------------------------------------

_groq_failure_count: int = 0
_groq_circuit_open_until: float = 0.0
_GROQ_MAX_FAILURES: int = 5
_GROQ_COOLDOWN_SECONDS: float = 60.0

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ObserverResult:
    """
    Structured metadata extracted from episode content.

    Attributes
    ----------
    facts:
        List of atomic fact strings extracted from content.  Used for
        key-expansion in FTS5 search (V2-E07).
    temporal_anchor:
        ISO date string (YYYY-MM-DD) if a specific date is detected in
        content, else ``None``.
    memory_type:
        High-level memory category: ``"episodic"``, ``"semantic"``,
        ``"procedural"``, or ``None``.
    content_type:
        Fine-grained content category: ``"observation"``, ``"fact"``,
        ``"preference"``, ``"instruction"``, or ``None``.
    source:
        Which extraction path was used: ``"local"`` or ``"groq"``.
    """

    facts: list[str] = field(default_factory=list)
    temporal_anchor: str | None = None
    memory_type: str | None = None
    content_type: str | None = None
    source: str = "local"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def observe(content: str, use_groq: bool | None = None) -> ObserverResult:
    """
    Enrich episode content with structured metadata.

    Parameters
    ----------
    content:
        Raw episode text.
    use_groq:
        Override Groq usage.  ``None`` = auto-detect from ``GROQ_API_KEY``
        environment variable.

    Returns
    -------
    ObserverResult
        Extracted metadata.

    Story: KMV-V2-E05
    """
    if content is None or not str(content).strip():
        return ObserverResult()

    if use_groq is None:
        use_groq = bool(os.environ.get("GROQ_API_KEY", "").strip())

    if use_groq:
        global _groq_failure_count, _groq_circuit_open_until

        # Circuit breaker: skip Groq if tripped
        if _groq_failure_count >= _GROQ_MAX_FAILURES:
            if time.monotonic() < _groq_circuit_open_until:
                logger.debug("Observer: circuit open, using local edition")
                return _local_observe(content)
            # Cooldown expired — allow probe
            _groq_failure_count = 0

        try:
            result = await _groq_observe(content)
            _groq_failure_count = 0  # Reset on success
            return result
        except Exception as exc:
            _groq_failure_count += 1
            if _groq_failure_count >= _GROQ_MAX_FAILURES:
                _groq_circuit_open_until = time.monotonic() + _GROQ_COOLDOWN_SECONDS
                logger.warning(
                    "Observer: circuit breaker tripped (%d failures), falling back to local for %ds",
                    _groq_failure_count,
                    _GROQ_COOLDOWN_SECONDS,
                )
            else:
                logger.warning(
                    "Observer: Groq extraction failed (%d/%d), falling back to local: %s",
                    _groq_failure_count,
                    _GROQ_MAX_FAILURES,
                    exc,
                )

    return _local_observe(content)


# ---------------------------------------------------------------------------
# Local Edition
# ---------------------------------------------------------------------------

# ISO date pattern: YYYY-MM-DD
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

# Named month patterns (used for temporal anchor when no ISO date present)
_MONTH_YEAR_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+(\d{4})\b",
    re.IGNORECASE,
)
_MONTH_NAMES = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}

# Memory type keywords
_EPISODIC_CUES = re.compile(
    r"\b(today|yesterday|last\s+\w+|on\s+\w+day|just\s+now|earlier|recently"
    r"|at\s+\d+:\d+|this\s+morning|this\s+evening|this\s+afternoon)\b",
    re.IGNORECASE,
)
_PROCEDURAL_CUES = re.compile(
    r"\b(always|never|every\s+time|whenever|should|must|don'?t|do\s+not"
    r"|step\s+\d+|first\s+\w+\s+then|remember\s+to)\b",
    re.IGNORECASE,
)

# Content type keywords
_PREFERENCE_CUES = re.compile(
    r"\b(prefer(?:s|red)?|like[sd]?|love[sd]?|hate[sd]?|dislike[sd]?"
    r"|favour(?:s|ed)?|enjoy[sed]?|want[sed]?\s+to)\b",
    re.IGNORECASE,
)
_INSTRUCTION_CUES = re.compile(
    r"\b(please|make\s+sure|ensure|always|never|do\s+not|don'?t\s+forget"
    r"|remember\s+to|you\s+should|must)\b",
    re.IGNORECASE,
)


def _local_observe(content: str) -> ObserverResult:
    """Extract metadata from content using regex heuristics."""
    facts = _extract_facts(content)
    temporal_anchor = _extract_temporal_anchor(content)
    memory_type = _classify_memory_type(content)
    content_type = _classify_content_type(content)
    return ObserverResult(
        facts=facts,
        temporal_anchor=temporal_anchor,
        memory_type=memory_type,
        content_type=content_type,
        source="local",
    )


def _extract_facts(content: str) -> list[str]:
    """
    Split content into atomic fact strings.

    Splits on sentence boundaries, filters short fragments, and
    deduplicates.  Returns at most 10 facts.
    """
    # Split on ". ", "! ", "? " or newlines
    sentences = re.split(r"(?<=[.!?])\s+|\n+", content.strip())
    facts = []
    seen: set[str] = set()
    for s in sentences:
        s = s.strip().rstrip(".!?").strip()
        if len(s) >= 10 and s not in seen:
            facts.append(s)
            seen.add(s)
    return facts[:10]


def _extract_temporal_anchor(content: str) -> str | None:
    """Return the first ISO date or month-year anchor found in content."""
    # Try ISO date first
    m = _ISO_DATE_RE.search(content)
    if m:
        return m.group(1)
    # Try month + year
    m2 = _MONTH_YEAR_RE.search(content)
    if m2:
        month_name = m2.group(1).lower()
        year = m2.group(2)
        month_num = _MONTH_NAMES.get(month_name, "01")
        return f"{year}-{month_num}-01"
    return None


def _classify_memory_type(content: str) -> str | None:
    """Classify into episodic / semantic / procedural, or None."""
    if _EPISODIC_CUES.search(content):
        return "episodic"
    if _PROCEDURAL_CUES.search(content):
        return "procedural"
    # Default for factual statements
    if len(content.split()) >= 5:
        return "semantic"
    return None


def _classify_content_type(content: str) -> str | None:
    """Classify into observation / fact / preference / instruction, or None."""
    if _INSTRUCTION_CUES.search(content):
        return "instruction"
    if _PREFERENCE_CUES.search(content):
        return "preference"
    # Fact: contains verbs like "is", "are", "was", "has"
    if re.search(r"\b(is|are|was|were|has|have|had)\b", content, re.IGNORECASE):
        return "fact"
    return "observation"


# ---------------------------------------------------------------------------
# Cloud Edition (Groq)
# ---------------------------------------------------------------------------

_GROQ_PROMPT = """\
Extract structured metadata from the following memory episode.
Return ONLY valid JSON with these fields:
- facts: list of 1-5 atomic fact strings (each ≤ 20 words)
- temporal_anchor: ISO date string YYYY-MM-DD if a specific date is mentioned, else null
- memory_type: one of "episodic", "semantic", "procedural", or null
- content_type: one of "observation", "fact", "preference", "instruction", or null

Memory: {content}

JSON:"""


async def _groq_observe(content: str) -> ObserverResult:
    """Extract metadata via Groq llama-3.1-8b-instant."""
    import json

    try:
        from groq import AsyncGroq  # type: ignore[import]
    except ImportError:
        raise RuntimeError("groq package not installed. pip install groq")

    api_key = os.environ.get("GROQ_API_KEY", "")
    client = AsyncGroq(api_key=api_key)

    response = await client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "user", "content": _GROQ_PROMPT.format(content=content[:2000])},
        ],
        temperature=0.0,
        max_tokens=256,
    )
    raw = response.choices[0].message.content or "{}"

    # Parse JSON — strip markdown fences if present
    raw = re.sub(r"^```(?:json)?\n?", "", raw.strip())
    raw = re.sub(r"\n?```$", "", raw.strip())
    data = json.loads(raw)

    return ObserverResult(
        facts=data.get("facts") or [],
        temporal_anchor=data.get("temporal_anchor"),
        memory_type=data.get("memory_type"),
        content_type=data.get("content_type"),
        source="groq",
    )
