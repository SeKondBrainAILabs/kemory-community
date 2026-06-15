"""
kemory/compression/llm_client.py
========================================
Thin HTTP client for ``core-ai-backend`` — the SeKondBrain LLM proxy.

Memory Vault never calls Groq/OpenAI/Anthropic directly. All LLM calls for
concept synthesis go through ``core-ai-backend`` which handles model selection,
prompt chains, and provider routing.

Configured via two env vars:

- ``CORE_AI_BACKEND_URL``  — base URL (e.g. ``http://core-ai-backend:8000``)
- ``CORE_AI_BACKEND_TOKEN`` — bearer token for service-to-service auth

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
    """A synthesized concept produced by core-ai-backend (or fallback)."""

    name: str
    synthesis: str
    source_memory_ids: list[str] = field(default_factory=list)
    directional: bool = False
    positions_merged: int = 0
    synthesis_unavailable: bool = False  # True when core-ai-backend was unreachable
    source: str = "core_ai_backend"  # "core_ai_backend" | "raw_fallback"

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
    """Async HTTP client for core-ai-backend concept synthesis endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("CORE_AI_BACKEND_URL", "")).rstrip("/")
        self.token = token or os.environ.get("CORE_AI_BACKEND_TOKEN", "")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    async def synthesize_concept(
        self,
        memories: list[dict[str, Any]],
    ) -> Concept:
        """Single concept synthesis (no merge mode — non-directional group)."""
        if not memories:
            return Concept(name="empty", synthesis="", source="raw_fallback", synthesis_unavailable=True)

        if not self.enabled:
            return self._fallback(memories, directional=False)

        payload = {
            "task": "concept_synthesis",
            "memories": [self._strip_memory(m) for m in memories],
        }
        result = await self._post("/v1/synthesize/concept", payload)
        if result is None:
            # The bespoke /v1/synthesize/* routes were retired upstream
            # (every call returns 404). Fall back to core-ai-backend's
            # chat/completions — same backend, just a different endpoint.
            # Memory Vault still doesn't call any LLM provider directly.
            chat_fallback = await self._synthesize_via_chat(
                memories,
                directional=False,
            )
            if chat_fallback is not None:
                return chat_fallback
            return self._fallback(memories, directional=False)
        return Concept(
            name=result.get("name", "concept"),
            synthesis=result.get("synthesis", ""),
            source_memory_ids=[str(m.get("id", "")) for m in memories if m.get("id")],
            directional=False,
            positions_merged=len(memories),
            source="core_ai_backend",
        )

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

        payload = {
            "task": "merge_directional",
            "merge_mode": mode,
            "memories": [self._strip_memory(m) for m in memories],
        }
        result = await self._post("/v1/synthesize/merge_directional", payload)
        if result is None:
            chat_fallback = await self._synthesize_via_chat(
                memories,
                directional=True,
                mode=mode,
            )
            if chat_fallback is not None:
                return chat_fallback
            return self._fallback(memories, directional=True, mode=mode)
        return Concept(
            name=result.get("name", "concept"),
            synthesis=result.get("synthesis", ""),
            source_memory_ids=[str(m.get("id", "")) for m in memories if m.get("id")],
            directional=True,
            positions_merged=len(memories),
            source="core_ai_backend",
        )

    # ── Internals ─────────────────────────────────────────────────────

    def _strip_memory(self, mem: dict[str, Any]) -> dict[str, Any]:
        """Send only the fields core-ai-backend needs (id, content, created_at)."""
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
        """When core-ai-backend is unreachable, return raw group as-is."""
        logger.warning(
            "core_ai_backend.unavailable",
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
        """Fallback synthesis via core-ai-backend's /v1/chat/completions.

        The original /v1/synthesize/concept and /v1/synthesize/merge_directional
        endpoints have been retired upstream — every call returns 404, which
        previously caused L3.1 to silently degrade to raw_passthrough.

        This fallback still routes through core-ai-backend (architectural
        invariant: Memory Vault never calls Groq/OpenAI/Anthropic directly —
        the org's LLM provider is configured on the backend, not here). It
        just uses the OpenAI-compatible /v1/chat/completions instead of the
        retired bespoke synthesis routes.

        Returns None on any failure; caller falls through to raw_fallback.
        """
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
                source="core_ai_backend",
            )
        except Exception as exc:
            logger.warning(
                "core_ai_backend.chat_fallback_parse_failed: %s — %s",
                type(exc).__name__,
                str(exc)[:200],
            )
            return None

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """POST to core-ai-backend, return parsed JSON or None on failure."""
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not installed — core-ai-backend client disabled")
            return None
        headers: dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.base_url + path, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except Exception as exc:
            logger.warning("core_ai_backend.request_failed: %s %s — %s", "POST", path, exc)
            return None
