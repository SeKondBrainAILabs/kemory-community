"""Community Groq chat-completions client."""

from __future__ import annotations

import os
from typing import Any

import httpx


def groq_enabled() -> bool:
    return bool(os.environ.get("GROQ_API_KEY", "").strip())


async def chat_completion(
    payload: dict[str, Any],
    *,
    timeout_seconds: float = 120.0,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any] | None:
    """Call Groq's OpenAI-compatible endpoint, or return None when unconfigured."""
    api_key = (api_key or os.environ.get("GROQ_API_KEY", "")).strip()
    if not api_key:
        return None
    base_url = (base_url or os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai")).rstrip("/")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(f"{base_url}/v1/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else None


def assistant_text(response: dict[str, Any] | None) -> str | None:
    if not response:
        return None
    choices = response.get("choices") or []
    if not choices:
        return None
    content = (choices[0].get("message") or {}).get("content")
    return content.strip() if isinstance(content, str) and content.strip() else None
