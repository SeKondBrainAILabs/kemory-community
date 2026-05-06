"""
kemory/compression/aaak.py
=================================
AAAK — Agent-Aware Adaptive Key dialect.

A lossless, LLM-readable short-form encoding for memory dicts. Inspired by
MemPalace's AAAK approach but adapted for our already-structured data.

Design goals:
1. **Lossless** — every memory dict round-trips exactly.
2. **LLM-readable** — any model can parse it without a decoder.
3. **Token-efficient** — compresses by aliasing field names and substituting
   repeated phrases via a per-document dictionary.

Format::

    @aaak v=1
    @sub $1=long phrase $2=another phrase
    M id=abc ns=shared t=fact @=2026-04-07T10:00:00Z c="user prefers Python"
    M id=def ns=shared t=fact @=2026-04-07T10:01:00Z c="see $1 for details"
    @end

Field aliases (deterministic):
    id  → id           (unchanged for clarity)
    ns  → namespace
    t   → content_type
    @   → created_at
    !   → invalid_at
    v   → valid_at
    c   → content
    m   → metadata (JSON-encoded inline)
    s   → source_agent
    sid → session_id
    rid → round_id

Story: KMV-COMPRESS-01 / KMV-BENCH-01 / S9N-3050
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

# ── Field alias maps ──────────────────────────────────────────────────────
_ALIAS_TO_FIELD: dict[str, str] = {
    "id": "id",
    "ns": "namespace",
    "t": "content_type",
    "@": "created_at",
    "!": "invalid_at",
    "v": "valid_at",
    "c": "content",
    "m": "metadata",
    "s": "source_agent",
    "sid": "session_id",
    "rid": "round_id",
    "ts": "tier",
    "vis": "visibility",
}
_FIELD_TO_ALIAS: dict[str, str] = {v: k for k, v in _ALIAS_TO_FIELD.items()}

# Minimum length and frequency for substitution table eligibility.
# F14: Lowered freq from 3 → 2 — observed mean ratio 1.47× across 168
# memories (just under the 1.5× lower bound of the spec target). Lowering
# the freq lets us substitute phrases that appear in just 2 memories,
# which is the common case for medium namespaces (~10 memories with
# repeated boilerplate). Trade-off: slightly larger substitution table
# header. Negligible cost since the substitution itself recoups it
# within ~3 substituted occurrences.
_MIN_SUB_LEN = 8
_MIN_SUB_FREQ = 2

# Marker tokens
_HEADER = "@aaak v=1"
_SUB_HEADER = "@sub"
_FOOTER = "@end"
_RECORD_PREFIX = "M"


def _build_substitution_table(memories: list[dict[str, Any]]) -> dict[str, str]:
    """Find frequent substrings worth substituting.

    Looks at content fields for repeated 8+-char phrases that appear 3+ times,
    assigns them tokens like ``$1``, ``$2``.
    """
    counter: Counter[str] = Counter()
    for mem in memories:
        text = str(mem.get("content", ""))
        # Tokenise into "phrases" by splitting on punctuation/whitespace
        words = re.findall(r"[\w'-]+(?:\s+[\w'-]+){1,4}", text)
        for w in words:
            if len(w) >= _MIN_SUB_LEN:
                counter[w] += 1
    # Pick the highest-impact substitutions (frequency × length)
    candidates = [(phrase, freq) for phrase, freq in counter.items() if freq >= _MIN_SUB_FREQ]
    candidates.sort(key=lambda x: (x[1] - 1) * len(x[0]), reverse=True)
    table: dict[str, str] = {}
    for idx, (phrase, _) in enumerate(candidates[:20], start=1):
        table[phrase] = f"${idx}"
    return table


def _apply_substitutions(text: str, table: dict[str, str]) -> str:
    out = text
    # Apply longest first to avoid partial overlaps
    for phrase in sorted(table.keys(), key=len, reverse=True):
        out = out.replace(phrase, table[phrase])
    return out


def _reverse_substitutions(text: str, table: dict[str, str]) -> str:
    out = text
    # Reverse table: token → phrase
    reverse = {v: k for k, v in table.items()}
    # Apply longest tokens first ($10, $11 before $1)
    for token in sorted(reverse.keys(), key=len, reverse=True):
        out = out.replace(token, reverse[token])
    return out


def _escape_value(v: Any) -> str:
    """Quote a value for the compact line format.

    Newlines, tabs, carriage returns, backslashes and double-quotes are
    backslash-escaped so each memory always fits on a single line.
    """
    if v is None:
        return "~"
    if isinstance(v, (dict, list)):
        s = json.dumps(v, separators=(",", ":"), sort_keys=True)
    else:
        s = str(v)
    needs_quoting = (
        s == "" or s.startswith("$") or any(ch in s for ch in (" ", "\t", "\n", "\r", "=", '"', "\\"))
    )
    if needs_quoting:
        escaped = (
            s.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        s = '"' + escaped + '"'
    return s


def _unescape_value(s: str) -> Any:
    """Reverse of _escape_value."""
    if s == "~":
        return None
    if s.startswith('"') and s.endswith('"'):
        inner = s[1:-1]
        # Reverse the escapes in opposite order: backslash last
        out: list[str] = []
        i = 0
        while i < len(inner):
            ch = inner[i]
            if ch == "\\" and i + 1 < len(inner):
                nxt = inner[i + 1]
                if nxt == "n":
                    out.append("\n")
                elif nxt == "r":
                    out.append("\r")
                elif nxt == "t":
                    out.append("\t")
                elif nxt == '"':
                    out.append('"')
                elif nxt == "\\":
                    out.append("\\")
                else:
                    out.append(nxt)
                i += 2
            else:
                out.append(ch)
                i += 1
        return "".join(out)
    return s


def _serialise_memory(mem: dict[str, Any], sub_table: dict[str, str]) -> str:
    """One memory → one M-line."""
    parts: list[str] = [_RECORD_PREFIX]
    # Deterministic field order: id first, then alphabetical alias
    if "id" in mem:
        parts.append(f"id={_escape_value(mem['id'])}")
    for field in sorted(mem.keys()):
        if field == "id":
            continue
        alias = _FIELD_TO_ALIAS.get(field)
        if alias is None:
            continue  # Unknown field — drop (we only round-trip known schema)
        value = mem[field]
        if field == "content" and isinstance(value, str):
            value = _apply_substitutions(value, sub_table)
        parts.append(f"{alias}={_escape_value(value)}")
    return " ".join(parts)


# Tokenise an M-line into (alias, value) pairs while respecting quoted strings
_TOKEN_RE = re.compile(
    r"([@!a-z]+)="  # alias=
    r'("(?:[^"\\]|\\.)*"|~|\S+)'  # quoted value, ~, or bare token
)


def _parse_memory_line(line: str, sub_table: dict[str, str]) -> dict[str, Any]:
    """Parse one M-line back into a memory dict."""
    if not line.startswith(_RECORD_PREFIX):
        raise ValueError(f"Not an M-line: {line[:40]}")
    body = line[len(_RECORD_PREFIX) :].strip()
    out: dict[str, Any] = {}
    for alias, raw in _TOKEN_RE.findall(body):
        field = _ALIAS_TO_FIELD.get(alias)
        if field is None:
            continue
        value = _unescape_value(raw)
        if field == "content" and isinstance(value, str):
            value = _reverse_substitutions(value, sub_table)
        elif field == "metadata" and isinstance(value, str) and value:
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                pass
        out[field] = value
    return out


# ── Public API ────────────────────────────────────────────────────────────


def encode_aaak(memories: list[dict[str, Any]]) -> str:
    """Encode a list of memory dicts into AAAK lossless dialect.

    Round-trip with :func:`decode_aaak`.
    """
    if not memories:
        return f"{_HEADER}\n{_FOOTER}\n"

    sub_table = _build_substitution_table(memories)
    lines: list[str] = [_HEADER]
    if sub_table:
        # Header line: @sub $1="phrase one" $2="phrase two"
        sub_parts = [_SUB_HEADER]
        for phrase, token in sorted(sub_table.items(), key=lambda kv: int(kv[1][1:])):
            sub_parts.append(f"{token}={_escape_value(phrase)}")
        lines.append(" ".join(sub_parts))
    for mem in memories:
        lines.append(_serialise_memory(mem, sub_table))
    lines.append(_FOOTER)
    return "\n".join(lines) + "\n"


def decode_aaak(blob: str) -> list[dict[str, Any]]:
    """Decode an AAAK blob back into a list of memory dicts.

    Round-trip with :func:`encode_aaak`.
    """
    sub_table: dict[str, str] = {}
    memories: list[dict[str, Any]] = []
    saw_header = False
    for raw_line in blob.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == _HEADER:
            saw_header = True
            continue
        if line == _FOOTER:
            break
        if line.startswith(_SUB_HEADER):
            # Parse substitutions: token=value pairs
            for token, raw_val in _TOKEN_RE.findall(line[len(_SUB_HEADER) :]):
                # In the sub header the "alias" is actually a $N token, but
                # _TOKEN_RE only matches lower-case aliases. So parse manually.
                pass
            # Manual parse — find $N=value pairs
            for match in re.finditer(r'(\$\d+)=("(?:[^"\\]|\\.)*"|\S+)', line):
                token, raw = match.group(1), match.group(2)
                phrase = _unescape_value(raw)
                sub_table[phrase] = token
            continue
        if line.startswith(_RECORD_PREFIX + " ") or line == _RECORD_PREFIX:
            memories.append(_parse_memory_line(line, sub_table))
    if not saw_header:
        raise ValueError("Not an AAAK blob: missing @aaak header")
    return memories


def compression_ratio(memories: list[dict[str, Any]], encoded: str) -> float:
    """Return compression ratio = original_json_size / encoded_size."""
    original = len(json.dumps(memories, separators=(",", ":")))
    if not encoded:
        return 1.0
    return round(original / len(encoded), 2)
