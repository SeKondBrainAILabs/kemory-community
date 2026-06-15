"""
kemory/search/temporal.py
================================
Time-Aware Query Expansion for S9N Memory Vault v2.0.

Local Edition: pure-regex, zero LLM calls, < 1 ms latency.
Cloud Edition: Groq extraction (implemented in V2-F09b).

The module provides two public functions:

``has_temporal_reference(query)``
    Fast regex gate — returns True if the query likely contains a time
    reference.  Used to decide whether to invoke the extractor.

``extract_time_range(query, now)``
    Attempts to extract a ``TimeRange`` (start/end date pair) from the query.
    Returns ``None`` if no recognisable pattern is found or extraction fails.

The result of ``extract_time_range`` is passed to
``LocalStorageBackend.search_episodes(temporal_range=...)`` which filters
results to memories whose ``temporal_anchor`` or ``created_at`` falls within
the range.

Failure Mode: All methods are safe to call unconditionally; they never raise,
never block, and never call external services.  If the pattern is ambiguous
the function returns None and search proceeds unfiltered.

Story: KMV-V2-E08 — Time-Aware Query Expansion
"""

from __future__ import annotations

import calendar
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Temporal detection patterns (from spec §8.9)
# ---------------------------------------------------------------------------

TEMPORAL_PATTERNS: list[str] = [
    r"\b(yesterday|today)\b",
    r"\blast\s+(week|month|year)\b",
    r"\bthis\s+(week|month|year)\b",
    r"\b(in\s+)?(january|february|march|april|may|june|july|august|"
    r"september|october|november|december)\b",
    r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b",
    r"\b(before|after|since|until|during)\s+",
    r"\b\d+\s+(days?|weeks?|months?|years?)\s+ago\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in TEMPORAL_PATTERNS]

_MONTH_MAP = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_DATE_RE = re.compile(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b")
_RELATIVE_AGO_RE = re.compile(r"\b(\d+)\s+(days?|weeks?|months?|years?)\s+ago\b", re.IGNORECASE)
_MONTH_YEAR_RE = re.compile(
    r"\b(in\s+)?(january|february|march|april|may|june|july|august|"
    r"september|october|november|december)"
    r"(?:\s+(\d{4}))?\b",
    re.IGNORECASE,
)
_BEFORE_AFTER_RE = re.compile(
    r"\b(before|after|since|until)\s+(\d{4}[-/]\d{1,2}[-/]\d{1,2})\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimeRange:
    """
    A closed date interval [start, end] (both inclusive).

    Both ``start`` and ``end`` are ``datetime.date`` objects.
    Use ``to_iso()`` to get ``(start_str, end_str)`` for SQL comparisons.
    """

    start: date
    end: date

    def to_iso(self) -> tuple[str, str]:
        """Return ``(start_iso, end_iso)`` as ISO 8601 date strings."""
        return self.start.isoformat(), self.end.isoformat()

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"TimeRange.start ({self.start}) must be <= end ({self.end})")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def has_temporal_reference(query: str) -> bool:
    """
    Return True if *query* appears to contain a temporal reference.

    This is a fast gate check (all regexes pre-compiled at import time).
    It can produce false positives — use ``extract_time_range`` to confirm.

    Story: KMV-V2-E08
    """
    return any(pattern.search(query) for pattern in _COMPILED)


def extract_time_range(
    query: str,
    now: date | None = None,
) -> TimeRange | None:
    """
    Extract a ``TimeRange`` from *query* using regex patterns (Local Edition).

    Patterns are tried in priority order.  Returns the first successful match,
    or ``None`` if no pattern matches or an error occurs.

    Parameters
    ----------
    query:
        The user's search query.
    now:
        Reference date for relative expressions like "yesterday".
        Defaults to ``date.today()``.

    Returns
    -------
    TimeRange | None
        The extracted range, or ``None`` if the query has no temporal
        references or the references cannot be resolved.

    Story: KMV-V2-E08
    """
    if now is None:
        now = date.today()

    try:
        return _extract(query, now)
    except Exception as exc:  # never block a search on extractor errors
        logger.debug("Temporal extraction failed (safe to ignore): %s", exc)
        return None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extract(query: str, now: date) -> TimeRange | None:
    """Try all extraction strategies in priority order."""
    ql = query.lower()

    # 1. "before / after / since / until YYYY-MM-DD"
    m = _BEFORE_AFTER_RE.search(query)
    if m:
        preposition = m.group(1).lower()
        pivot = _parse_iso_date(m.group(2))
        if pivot:
            return _from_preposition(preposition, pivot, now)

    # 2. Explicit ISO date "YYYY-MM-DD"
    m = _DATE_RE.search(query)
    if m:
        d = _parse_iso_date(m.group(0))
        if d:
            return TimeRange(d, d)

    # 3. Relative keywords: yesterday / today
    if re.search(r"\byesterday\b", ql):
        yesterday = now - timedelta(days=1)
        return TimeRange(yesterday, yesterday)
    if re.search(r"\btoday\b", ql):
        return TimeRange(now, now)

    # 4. "N days/weeks/months/years ago"
    m = _RELATIVE_AGO_RE.search(query)
    if m:
        n = int(m.group(1))
        unit = m.group(2).rstrip("s")
        return _n_units_ago(n, unit, now)

    # 5. "last week / month / year"
    m = re.search(r"\blast\s+(week|month|year)\b", ql)
    if m:
        return _last_unit(m.group(1), now)

    # 6. "this week / month / year"
    m = re.search(r"\bthis\s+(week|month|year)\b", ql)
    if m:
        return _this_unit(m.group(1), now)

    # 7. "in January 2025" or "in January"
    m = _MONTH_YEAR_RE.search(query)
    if m:
        month_num = _MONTH_MAP.get(m.group(2).lower())
        if month_num:
            year = int(m.group(3)) if m.group(3) else now.year
            return _month_range(year, month_num)

    return None


def _parse_iso_date(s: str) -> date | None:
    """Parse a date string in YYYY-MM-DD or YYYY/MM/DD format."""
    try:
        parts = re.split(r"[-/]", s)
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def _from_preposition(prep: str, pivot: date, now: date) -> TimeRange:
    """Build a TimeRange from before/after/since/until + a pivot date."""
    if prep in ("before", "until"):
        # Interpret "before" as last 5 years as start floor to avoid empty ranges
        start = date(pivot.year - 5, 1, 1)
        return TimeRange(start, pivot - timedelta(days=1))
    if prep in ("after", "since"):
        return TimeRange(pivot + timedelta(days=1), now)
    return TimeRange(pivot, pivot)


def _n_units_ago(n: int, unit: str, now: date) -> TimeRange:
    """Resolve "N {unit} ago" to a TimeRange."""
    if unit == "day":
        d = now - timedelta(days=n)
        return TimeRange(d, d)
    if unit == "week":
        start = now - timedelta(weeks=n)
        end = start + timedelta(days=6)
        return TimeRange(start, min(end, now))
    if unit == "month":
        # Subtract n months approximately
        total_months = now.month - n
        year = now.year + total_months // 12
        month = total_months % 12 or 12
        if total_months % 12 == 0:
            year -= 1
        month = max(1, min(12, month))
        return _month_range(year, month)
    if unit == "year":
        return _year_range(now.year - n)
    return TimeRange(now - timedelta(days=n * 30), now)


def _last_unit(unit: str, now: date) -> TimeRange:
    if unit == "week":
        monday = now - timedelta(days=now.weekday() + 7)
        return TimeRange(monday, monday + timedelta(days=6))
    if unit == "month":
        first_this = date(now.year, now.month, 1)
        last_prev = first_this - timedelta(days=1)
        first_prev = date(last_prev.year, last_prev.month, 1)
        return TimeRange(first_prev, last_prev)
    if unit == "year":
        return _year_range(now.year - 1)
    return TimeRange(now - timedelta(days=7), now)


def _this_unit(unit: str, now: date) -> TimeRange:
    if unit == "week":
        monday = now - timedelta(days=now.weekday())
        return TimeRange(monday, now)
    if unit == "month":
        return TimeRange(date(now.year, now.month, 1), now)
    if unit == "year":
        return TimeRange(date(now.year, 1, 1), now)
    return TimeRange(now - timedelta(days=7), now)


def _month_range(year: int, month: int) -> TimeRange:
    _, last_day = calendar.monthrange(year, month)
    return TimeRange(date(year, month, 1), date(year, month, last_day))


def _year_range(year: int) -> TimeRange:
    return TimeRange(date(year, 1, 1), date(year, 12, 31))
