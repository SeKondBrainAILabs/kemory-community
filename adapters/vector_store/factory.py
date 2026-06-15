"""Factory for selecting the configured vector-store backend."""

from __future__ import annotations

import logging
import os
from typing import Any

from backend.adapters.vector_store.base import VectorStore
from backend.adapters.vector_store.pgvector_backend import PgvectorBackend
from backend.adapters.vector_store.weaviate_backend import WeaviateBackend

logger = logging.getLogger(__name__)

VALID_VECTOR_BACKENDS = ("weaviate", "pgvector")


def resolve_vector_backend(value: str | None = None) -> str:
    """Resolve KMV_VECTOR_BACKEND, defaulting to hosted-compatible Weaviate."""
    if value is None:
        value = os.environ.get("KMV_VECTOR_BACKEND")
        if value is None:
            logger.warning("KMV_VECTOR_BACKEND is not set; defaulting to 'weaviate'.")
            return "weaviate"

    resolved = value.strip().lower()
    if resolved not in VALID_VECTOR_BACKENDS:
        raise ValueError(f"Invalid KMV_VECTOR_BACKEND: {value!r}. Must be one of: {VALID_VECTOR_BACKENDS}")
    return resolved


def create_vector_store(
    backend: str | None = None,
    *,
    postgres_engine: Any | None = None,
    weaviate_url: str = "http://localhost:8080",
    weaviate_client: Any | None = None,
    dimension: int = 384,
) -> VectorStore:
    resolved = resolve_vector_backend(backend)
    if resolved == "pgvector":
        if postgres_engine is None:
            raise ValueError("postgres_engine is required when KMV_VECTOR_BACKEND=pgvector")
        return PgvectorBackend(engine=postgres_engine, dimension=dimension)
    return WeaviateBackend(weaviate_url=weaviate_url, client=weaviate_client)
