"""
kemory/embeddings/encoder.py
====================================
Sentence embedding encoder for bge-small-en-v1.5 (384-dim, L2-normalised).

Two interchangeable backends, selected at runtime:

* **Remote (preferred in-cluster)** — when ``EMBEDDING_SERVICE_URL`` is set,
  ``encode()`` POSTs to the shared ``core-embedding-service`` ``/embed``
  endpoint. The service loads the model once and is scaled independently, so
  kemory pods never hold a ~600MB-1GB sentence-transformers model in-process.
  This is what keeps the kemory pod's resident memory small (it was the
  dominant consumer — two model copies per pod under ``uvicorn --workers``).

* **Local (fallback)** — when no service URL is configured, the model is
  lazy-loaded in-process via FastEmbed/ONNX and reused as a module-level
  singleton.

Both backends serve the SAME model (``BAAI/bge-small-en-v1.5``), so vectors are
interchangeable across the cutover — existing stored embeddings remain valid.

Story: KMV-V2-S01.2 — Integrate bge-small-en-v1.5 ONNX embedding service
       (remote backend added 2026-06-03 to drop the in-process model)

Usage::

    from kemory.embeddings.encoder import encode, EMBEDDING_DIM
    vec = encode("The user prefers dark mode")
    assert len(vec) == EMBEDDING_DIM  # 384
"""

from __future__ import annotations

import logging
import math
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

MODEL_ID = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

# ---------------------------------------------------------------------------
# Remote backend configuration (core-embedding-service)
# ---------------------------------------------------------------------------
# Primary env var, with a legacy/alias accepted for convenience. Trailing
# slashes are stripped so callers can set either ".../" or "...".
_SERVICE_URL = (os.getenv("EMBEDDING_SERVICE_URL") or os.getenv("CORE_EMBEDDING_SERVICE_URL") or "").rstrip(
    "/"
)
# Connect/read timeouts (seconds) and bounded retries on transient failure.
_CONNECT_TIMEOUT = float(os.getenv("EMBEDDING_SERVICE_CONNECT_TIMEOUT", "2"))
_READ_TIMEOUT = float(os.getenv("EMBEDDING_SERVICE_READ_TIMEOUT", "8"))
_MAX_ATTEMPTS = max(1, int(os.getenv("EMBEDDING_SERVICE_RETRIES", "2")))
# /embed enforces 1 <= len(text) <= 32768; clamp defensively.
_MAX_TEXT_CHARS = 32768

_model: Any = None
_model_lock = threading.Lock()
_client: Any = None
_client_lock = threading.Lock()


def _remote_enabled() -> bool:
    return bool(_SERVICE_URL)


def _provider() -> str:
    return os.getenv("KEMORY_EMBEDDING_PROVIDER", "fastembed").strip().lower()


def _model_id() -> str:
    return os.getenv("EMBEDDING_MODEL", MODEL_ID).strip() or MODEL_ID


def _get_client() -> Any:
    """Lazy module-level httpx.Client singleton for the embedding service."""
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        import httpx

        _client = httpx.Client(
            base_url=_SERVICE_URL,
            timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
            headers={"User-Agent": "kemory-encoder"},
        )
        logger.info("Embedding backend: remote core-embedding-service at %s", _SERVICE_URL)
        return _client


def _encode_remote(text: str) -> list[float]:
    """Embed *text* via the shared core-embedding-service /embed endpoint."""
    import httpx

    payload = {"text": text[:_MAX_TEXT_CHARS] or " ", "model": _model_id(), "normalize": True}
    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = client.post("/embed", json=payload)
            resp.raise_for_status()
            data = resp.json()
            vector = data["vector"]
            if len(vector) != EMBEDDING_DIM:
                raise RuntimeError(f"embedding service returned {len(vector)} dims, expected {EMBEDDING_DIM}")
            return vector
        except (httpx.HTTPError, KeyError, ValueError, RuntimeError) as exc:
            last_exc = exc
            logger.warning(
                "Embedding service call failed (attempt %d/%d): %s",
                attempt,
                _MAX_ATTEMPTS,
                exc,
            )
    raise RuntimeError(
        f"core-embedding-service unreachable after {_MAX_ATTEMPTS} attempts: {last_exc}"
    ) from last_exc


def _load_model() -> Any:
    """Load and return the singleton SentenceTransformer model (local backend)."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from fastembed import TextEmbedding  # type: ignore[import]
        except ImportError:  # pragma: no cover
            raise RuntimeError(
                "In-process embedding model requested but fastembed is not installed. "
                "Set EMBEDDING_SERVICE_URL to use an embedding service, "
                "or install the local fallback with: pip install 'kemory[local-embeddings]'"
            )
        model_id = _model_id()
        logger.info("Loading embedding model '%s' (first call - this may take a moment)", model_id)
        _model = TextEmbedding(model_name=model_id)
        logger.info("Embedding model loaded (%d dimensions)", EMBEDDING_DIM)
        return _model


def _encode_local(text: str) -> list[float]:
    return _encode_local_batch([text])[0]


_LOCAL_BATCH_SIZE = max(1, int(os.getenv("EMBEDDING_LOCAL_BATCH_SIZE", "32")))


def _validate_vectors(vectors: list[list[float]], expected_count: int, backend: str) -> list[list[float]]:
    """Reject reordered/truncated batch output before it reaches pgvector."""
    if len(vectors) != expected_count:
        raise RuntimeError(f"{backend} encoder returned {len(vectors)} vectors for {expected_count} texts")
    for index, vector in enumerate(vectors):
        if len(vector) != EMBEDDING_DIM:
            raise RuntimeError(
                f"{backend} encoder returned {len(vector)} dims at index {index}, expected {EMBEDDING_DIM}"
            )
    return vectors


def _encode_local_batch(texts: list[str]) -> list[list[float]]:
    """Encode an ordered text batch in one FastEmbed traversal."""
    model = _load_model()
    inputs = [text[:_MAX_TEXT_CHARS] or " " for text in texts]
    vectors = [embedding.tolist() for embedding in model.embed(inputs, batch_size=_LOCAL_BATCH_SIZE)]
    return _validate_vectors(vectors, len(texts), "local")


def _encode_cloud_batch(texts: list[str], provider: str) -> list[list[float]]:
    """Use a user-configured cloud provider while preserving pgvector's 384 dimensions."""
    import httpx

    inputs = [text[:_MAX_TEXT_CHARS] or " " for text in texts]
    model = _model_id()
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") + "/embeddings"
        payload = {"model": model, "input": inputs, "dimensions": EMBEDDING_DIM}
        parser = lambda data: [item["embedding"] for item in data["data"]]
    elif provider == "voyage":
        api_key = os.getenv("VOYAGE_API_KEY", "").strip()
        url = os.getenv("VOYAGE_BASE_URL", "https://api.voyageai.com/v1").rstrip("/") + "/embeddings"
        payload = {"model": model, "input": inputs, "output_dimension": 512}
        parser = lambda data: [item["embedding"] for item in data["data"]]
    elif provider == "cohere":
        api_key = os.getenv("COHERE_API_KEY", "").strip()
        url = os.getenv("COHERE_BASE_URL", "https://api.cohere.com/v2").rstrip("/") + "/embed"
        payload = {
            "model": model,
            "texts": inputs,
            "input_type": "search_document",
            "embedding_types": ["float"],
            "output_dimension": 512,
        }
        parser = lambda data: data["embeddings"]["float"]
    else:
        raise RuntimeError(f"Unsupported embedding provider: {provider}")

    if not api_key:
        raise RuntimeError(f"{provider.upper()}_API_KEY is required for embedding provider '{provider}'")
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        response.raise_for_status()
        vectors = parser(response.json())
    if provider in {"voyage", "cohere"}:
        vectors = [_truncate_and_normalize(vector) for vector in vectors]
    return _validate_vectors(vectors, len(inputs), provider)


def _truncate_and_normalize(vector: list[float]) -> list[float]:
    """Adapt providers whose Matryoshka dimensions do not include 384."""
    if len(vector) < EMBEDDING_DIM:
        raise RuntimeError(
            f"cloud encoder returned {len(vector)} dims, expected at least {EMBEDDING_DIM}"
        )
    resized = vector[:EMBEDDING_DIM]
    norm = math.sqrt(sum(value * value for value in resized))
    if norm == 0:
        raise RuntimeError("cloud encoder returned a zero-length embedding")
    return [value / norm for value in resized]


def encode_batch(texts: list[str]) -> list[list[float]]:
    """Encode texts in order, returning exactly one 384-dim vector per text.

    FastEmbed receives the full list so it can batch the ONNX work. The remote
    service currently exposes only ``/embed``; that path reuses its persistent
    client while preserving the same count, order, and dimension contract.
    """
    if not texts:
        return []
    provider = _provider()
    if provider != "fastembed":
        return _encode_cloud_batch(texts, provider)
    if _remote_enabled():
        vectors = [_encode_remote(text) for text in texts]
        return _validate_vectors(vectors, len(texts), "remote")
    return _encode_local_batch(texts)


def encode(text: str) -> list[float]:
    """
    Encode *text* into a normalised 384-dimensional float vector.

    Routes to the remote ``core-embedding-service`` when ``EMBEDDING_SERVICE_URL``
    is configured, otherwise uses the in-process FastEmbed model.

    Parameters
    ----------
    text:
        The input string to embed.

    Returns
    -------
    list[float]
        A length-384 list of floats (L2-normalised, ready for cosine similarity).

    Raises
    ------
    RuntimeError
        If the remote backend is enabled but unreachable, or (local backend)
        ``fastembed`` is not installed. Callers treat embedding
        failures as non-fatal and backfill on the next enrichment pass.
    """
    return encode_batch([text])[0]


def reset_model() -> None:
    """Reset the model + client singletons (for testing only)."""
    global _model, _client
    with _model_lock:
        _model = None
    with _client_lock:
        if _client is not None:
            try:
                _client.close()
            except Exception:  # pragma: no cover - best effort
                pass
        _client = None
