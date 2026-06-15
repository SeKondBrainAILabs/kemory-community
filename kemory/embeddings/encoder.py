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

    payload = {"text": text[:_MAX_TEXT_CHARS] or " ", "model": MODEL_ID, "normalize": True}
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
        logger.info("Loading embedding model '%s' (first call — this may take a moment)", MODEL_ID)
        _model = TextEmbedding(model_name=MODEL_ID)
        logger.info("Embedding model loaded (%d dimensions)", EMBEDDING_DIM)
        return _model


def _encode_local(text: str) -> list[float]:
    model = _load_model()
    embedding = next(model.embed([text[:_MAX_TEXT_CHARS] or " "]))
    return embedding.tolist()


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
    if _remote_enabled():
        return _encode_remote(text)
    return _encode_local(text)


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
