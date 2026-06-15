"""
kemory/embeddings
=======================
Embedding utilities for S9N Memory Vault v2.0.

Story: KMV-V2-S01.2 — Integrate bge-small-en-v1.5 ONNX embedding service
"""

from kemory.embeddings.encoder import EMBEDDING_DIM, encode

__all__ = ["encode", "EMBEDDING_DIM"]
