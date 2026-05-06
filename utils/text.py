"""
Shared text utilities — content normalisation and hashing.

Why this lives in kemory/utils/ rather than in either service:

The backend HTTP layer (``backend/services/memory_service.py``) and the
library service (``kemory/service/memory_service.py``) intentionally
serve different consumers — backend is REST-shaped with Pydantic models
and Gatekeeper hooks; library is StorageBackend-shaped for dual-mode
embedding. They are NOT going to merge into a single module.

But they share a small, dedup-correctness-critical primitive: the
content-hash function. Two implementations of *that* would silently
produce different keys for the same content, fragmenting deduplication
across call paths. This module is the canonical implementation; both
services import from here.

Phase 1 of the [P0 #1 consolidation](https://www.notion.so/35023d8c237581948d41c7b12d6816d3).
Phase 2 (delegating backend storage calls through the library's
StorageBackend interface) is tracked as a follow-up.
"""

from __future__ import annotations

import hashlib
import unicodedata


def normalize_content(content: str) -> str:
    """Normalise content for hashing: NFC unicode, strip, collapse whitespace.

    Stable across Python versions and OS locales because it relies only on
    the standard ``unicodedata.normalize`` and Python's whitespace splitter.
    Do NOT lowercase here — case is meaningful for memories like proper
    nouns, code identifiers, and language-sensitive content.
    """
    text = unicodedata.normalize("NFC", content)
    return " ".join(text.split())


def content_hash(content: str) -> str:
    """Stable SHA-256 hex digest of normalised content.

    Used as the canonical dedup key. Any change to this function is a
    breaking change — every previously-stored memory's hash drifts and
    the unique constraint on ``(user_id, namespace, content_hash)`` no
    longer prevents duplicates of new writes. If this ever has to change,
    plan a backfill.
    """
    return hashlib.sha256(normalize_content(content).encode("utf-8")).hexdigest()
