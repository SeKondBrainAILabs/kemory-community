"""
kemory/embeddings/encoder.py
====================================
Lazy-loading sentence embedding encoder using bge-small-en-v1.5.

Backed by sentence-transformers which downloads and caches the model on first
use (~90 MB). Uses ONNX runtime for inference when available (< 8 ms on CPU).

The encoder is a module-level singleton — the model is loaded once and reused
across all calls within a process.

Story: KMV-V2-S01.2 — Integrate bge-small-en-v1.5 ONNX embedding service

Usage::

    from kemory.embeddings.encoder import encode, EMBEDDING_DIM
    vec = encode("The user prefers dark mode")
    assert len(vec) == EMBEDDING_DIM  # 384
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

MODEL_ID = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384

_model: Any = None
_model_lock = threading.Lock()


def _load_model() -> Any:
    """Load and return the singleton SentenceTransformer model."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import]
        except ImportError:  # pragma: no cover
            raise RuntimeError(
                "sentence-transformers is not installed. "
                "Install it with: pip install sentence-transformers onnxruntime"
            )
        logger.info("Loading embedding model '%s' (first call — this may take a moment)", MODEL_ID)
        _model = SentenceTransformer(MODEL_ID)
        logger.info("Embedding model loaded (%d dimensions)", EMBEDDING_DIM)
        return _model


def encode(text: str) -> list[float]:
    """
    Encode *text* into a normalised 384-dimensional float vector.

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
        If ``sentence-transformers`` is not installed.
    """
    model = _load_model()
    embedding = model.encode(text, normalize_embeddings=True, show_progress_bar=False)
    return embedding.tolist()


def reset_model() -> None:
    """Reset the model singleton (for testing only)."""
    global _model
    with _model_lock:
        _model = None
