"""
kemory/observer
=====================
Observer Agent — dual-mode episode enrichment.

Extracts structured metadata (facts, temporal_anchor, memory_type,
content_type) from raw episode content.

- **Local Edition**: regex + heuristic extraction; zero LLM calls.
- **Cloud Edition**: Groq ``llama-3.1-8b-instant``; activated when
  ``GROQ_API_KEY`` is present in environment.

Story: KMV-V2-E05
"""

from kemory.observer.extractor import ObserverResult, observe

__all__ = ["ObserverResult", "observe"]
