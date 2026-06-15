"""
kemory/compression/cache.py
===================================
Hash-based cache for namespace compression results.

Mirrors the cache pattern in :mod:`kemory.context.vault_context` —
the cache key is a SHA-256 of the sorted memory IDs in the namespace plus
the mode/merge_mode, so any change to the namespace contents invalidates
the entry automatically.

Story: KMV-COMPRESS-01 / S9N-3050
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


def compute_cache_key(memory_ids: list[str], mode: str, merge_mode: str) -> str:
    """Deterministic cache key for a (namespace state, mode, merge_mode) tuple."""
    sorted_ids = sorted(str(i) for i in memory_ids)
    payload = "|".join(sorted_ids) + f"||{mode}::{merge_mode}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class CacheEntry:
    key: str
    mode: str
    merge_mode: str
    payload: dict[str, Any]
    source_count: int


@dataclass
class NamespaceCompressionCache:
    """Per-process in-memory cache. Keyed by ``(user_id, namespace)``."""

    _entries: dict[tuple[str, str], CacheEntry] = field(default_factory=dict)

    def get(
        self,
        user_id: str,
        namespace: str,
        mode: str,
        merge_mode: str,
        memory_ids: list[str],
    ) -> CacheEntry | None:
        """Return the cached entry if its key matches the current namespace state."""
        entry = self._entries.get((user_id, namespace))
        if entry is None:
            return None
        expected_key = compute_cache_key(memory_ids, mode, merge_mode)
        if entry.key != expected_key:
            return None
        if entry.mode != mode or entry.merge_mode != merge_mode:
            return None
        return entry

    def put(
        self,
        user_id: str,
        namespace: str,
        mode: str,
        merge_mode: str,
        memory_ids: list[str],
        payload: dict[str, Any],
    ) -> CacheEntry:
        key = compute_cache_key(memory_ids, mode, merge_mode)
        entry = CacheEntry(
            key=key,
            mode=mode,
            merge_mode=merge_mode,
            payload=payload,
            source_count=len(memory_ids),
        )
        self._entries[(user_id, namespace)] = entry
        return entry

    def invalidate(self, user_id: str, namespace: str) -> None:
        self._entries.pop((user_id, namespace), None)

    def clear(self) -> None:
        self._entries.clear()


# Module-level singleton (per process). Mirrors VaultContext singleton pattern.
_default_cache = NamespaceCompressionCache()


def get_default_cache() -> NamespaceCompressionCache:
    return _default_cache
