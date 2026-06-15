"""Vector-store adapter interface and factory."""

from backend.adapters.vector_store.base import SearchHit, VectorStore
from backend.adapters.vector_store.factory import create_vector_store, resolve_vector_backend
from backend.adapters.vector_store.pgvector_backend import PgvectorBackend
from backend.adapters.vector_store.weaviate_backend import WeaviateBackend

__all__ = [
    "PgvectorBackend",
    "SearchHit",
    "VectorStore",
    "WeaviateBackend",
    "create_vector_store",
    "resolve_vector_backend",
]
