"""BlobStore adapter factory."""

from __future__ import annotations

import os

from backend.adapters.blob_store.base import BlobMetadata, BlobReadResult, BlobStore
from backend.adapters.blob_store.local_fs_backend import LocalFSBlobStore

_blob_store: BlobStore | None = None


def get_blob_backend_name() -> str:
    return os.environ.get("KMV_BLOB_BACKEND", "local_fs").strip().lower() or "local_fs"


def get_blob_store() -> BlobStore:
    global _blob_store
    if _blob_store is not None:
        return _blob_store
    backend = get_blob_backend_name()
    if backend == "local_fs":
        _blob_store = LocalFSBlobStore()
    else:
        raise ValueError("KMV_BLOB_BACKEND must be local_fs in Kemory Community.")
    return _blob_store


def reset_blob_store_for_tests() -> None:
    global _blob_store
    _blob_store = None


__all__ = [
    "BlobMetadata",
    "BlobReadResult",
    "BlobStore",
    "LocalFSBlobStore",
    "get_blob_backend_name",
    "get_blob_store",
    "reset_blob_store_for_tests",
]
