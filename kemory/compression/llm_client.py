"""
kemory/compression/llm_client.py
========================================
Community LLM client backed by the user's Groq API key.

When unreachable, the client returns a synthetic ``Concept`` containing the
raw group with a ``synthesis_unavailable`` flag — agents still get data.

Story: KMV-COMPRESS-01 / S9N-3050
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Concept:
    """A synthesized concept produced by Groq (or a deterministic fallback)."""

    name: str
    synthesis: str
    source_memory_ids: list[str] = field(default_factory=list)
    directional: bool = False
    positions_merged: int = 0
    synthesis_unavailable: bool = False
    source: str = "groq"  # "groq" | "raw_fallback"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "synthesis": self.synthesis,
            "source_memory_ids": list(self.source_memory_ids),
            "directional": self.directional,
            "positions_merged": self.positions_merged,
            "synthesis_unavailable": self.synthesis_unavailable,
            "source": self.source,
        }


class CoreAIBackendClient:
    """Compatibility name for the community Groq concept client."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai")).rstrip(
            "/"
        )
        self.token = token or os.environ.get("GROQ_API_KEY", "")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.token)

    async def synthesize_concept(
        self,
        memories: list[dict[str, Any]],
    ) -> Concept:
        """Single concept synthesis (no merge mode — non-directional group)."""
        if not memories:
            return Concept(name="empty", synthesis="", source="raw_fallback", synthesis_unavailable=True)

        if not self.enabled:
            return self._fallback(memories, directional=False)

        result = await self._synthesize_via_chat(
            memories,
            directional=False,
        )
        return result or self._fallback(memories, directional=False)

    async def merge_directional(
        self,
        memories: list[dict[str, Any]],
        mode: str = "current",
    ) -> Concept:
        """Directional merge with mode = 'current' or 'aggregate'."""
        if mode not in {"current", "aggregate"}:
            raise ValueError(f"merge_mode must be 'current' or 'aggregate', got {mode!r}")

        if not memories:
            return Concept(name="empty", synthesis="", source="raw_fallback", synthesis_unavailable=True)

        if not self.enabled:
            return self._fallback(memories, directional=True, mode=mode)

        result = await self._synthesize_via_chat(
            memories,
            directional=True,
            mode=mode,
        )
        return result or self._fallback(memories, directional=True, mode=mode)

    # ── Internals ─────────────────────────────────────────────────────

    def _strip_memory(self, mem: dict[str, Any]) -> dict[str, Any]:
        """Return the synthesis-safe memory fields."""
        return {
            "id": mem.get("id"),
            "content": mem.get("content", ""),
            "created_at": mem.get("created_at"),
        }

    def _fallback(
        self,
        memories: list[dict[str, Any]],
        *,
        directional: bool,
        mode: str = "current",
    ) -> Concept:
        """When Groq is unavailable, return the raw group as-is."""
        logger.warning(
            "groq.unavailable",
            extra={"directional": directional, "mode": mode, "memory_count": len(memories)},
        )
        if directional and mode == "current" and memories:
            # Pick the chronologically latest as the "current" position
            sorted_mems = sorted(
                memories,
                key=lambda m: str(m.get("created_at", "")),
                reverse=True,
            )
            latest = sorted_mems[0]
            synthesis = str(latest.get("content", ""))
        else:
            # Aggregate fallback: concatenate all positions
            synthesis = "\n".join(str(m.get("content", "")) for m in memories)
        return Concept(
            name="raw_fallback",
            synthesis=synthesis,
            source_memory_ids=[str(m.get("id", "")) for m in memories if m.get("id")],
            directional=directional,
            positions_merged=len(memories),
            synthesis_unavailable=True,
            source="raw_fallback",
        )

    async def _synthesize_via_chat(
        self,
        memories: list[dict[str, Any]],
        *,
        directional: bool,
        mode: str | None = None,
    ) -> Concept | None:
        """Synthesize through Groq's OpenAI-compatible chat endpoint."""
        if not self.enabled:
            return None

        snippets = "\n\n".join(
            f"[Memory {i + 1}] {str(m.get('content', ''))[:400]}" for i, m in enumerate(memories[:20])
        )
        if directional:
            instr = (
                "Synthesise a single coherent concept from these memories. "
                f"Apply '{mode or 'current'}' merge: later memories supersede earlier "
                "ones when they conflict; combine non-conflicting facts."
            )
        else:
            instr = (
                "Synthesise a single coherent concept from these related memories. "
                "Preserve specific names, dates, and numbers."
            )
        prompt = (
            f"{instr}\n\nMEMORIES:\n{snippets}\n\n"
            "Return JSON with two string fields: 'name' (1-4 words, snake_case, "
            "describing the concept) and 'synthesis' (one paragraph, factual, "
            "no preamble). JSON only — no markdown fences."
        )
        model = os.environ.get("KMV_SYNTHESIS_MODEL", "llama-3.3-70b-versatile")

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 400,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        result = await self._post("/v1/chat/completions", payload)
        if result is None:
            return None
        try:
            choices = result.get("choices") or []
            if not choices:
                return None
            text = (choices[0].get("message") or {}).get("content")
            if not text:
                return None
            import json as _json

            data = _json.loads(text)
            return Concept(
                name=str(data.get("name", "concept"))[:120],
                synthesis=str(data.get("synthesis", "")),
                source_memory_ids=[str(m.get("id", "")) for m in memories if m.get("id")],
                directional=directional,
                positions_merged=len(memories),
                source="groq",
            )
        except Exception as exc:
            logger.warning(
                "groq.chat_fallback_parse_failed: %s - %s",
                type(exc).__name__,
                str(exc)[:200],
            )
            return None

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """POST to Groq, returning parsed JSON or None on failure."""
        from kemory.llm import chat_completion

        try:
            return await chat_completion(
                payload,
                timeout_seconds=self.timeout,
                api_key=self.token,
                base_url=self.base_url,
            )
        except Exception as exc:
            logger.warning("groq.request_failed: %s %s - %s", "POST", path, exc)
            return None
