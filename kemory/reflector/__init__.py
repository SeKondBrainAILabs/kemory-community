"""
kemory/reflector
======================
Reflector Agent — periodic memory consolidation and reflection.

Scans recent episodic memories for a session/org, identifies patterns,
and creates new semantic summary episodes.

- **Local Edition**: heuristic clustering by content similarity; no LLM.
- **Cloud Edition**: Groq ``llama-3.1-8b-instant``; activated when
  ``GROQ_API_KEY`` is present.

Story: KMV-V2-E06
"""

from kemory.reflector.agent import ReflectionResult, reflect

__all__ = ["ReflectionResult", "reflect"]
