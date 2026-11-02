"""Community LLM adapters for Groq, llama.cpp, and Vertex AI."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

LLM_PROVIDERS = {"groq", "llama_cpp", "vertex"}


def llm_provider() -> str:
    provider = os.environ.get("KEMORY_LLM_PROVIDER", "groq").strip().lower()
    return provider if provider in LLM_PROVIDERS else "groq"


def _api_key(provider: str, override: str | None = None) -> str:
    if override is not None:
        return override.strip()
    generic = os.environ.get("KEMORY_LLM_API_KEY", "").strip()
    if generic:
        return generic
    if provider == "groq":
        return os.environ.get("GROQ_API_KEY", "").strip()
    if provider == "vertex":
        return os.environ.get("GOOGLE_API_KEY", "").strip()
    return os.environ.get("LLAMA_CPP_API_KEY", "").strip()


def _base_url(provider: str, override: str | None = None) -> str:
    if override:
        return override.rstrip("/")
    generic = os.environ.get("KEMORY_LLM_BASE_URL", "").strip()
    if generic:
        return generic.rstrip("/")
    if provider == "groq":
        return os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai").rstrip("/")
    return os.environ.get("LLAMA_CPP_BASE_URL", "http://host.docker.internal:8080").rstrip("/")


def llm_enabled(provider: str | None = None, api_key: str | None = None) -> bool:
    selected = provider or llm_provider()
    if selected == "llama_cpp":
        return bool(_base_url(selected))
    return bool(_api_key(selected, api_key))


def groq_enabled() -> bool:
    """Backward-compatible alias used by older synthesis call sites."""
    return llm_enabled()


def _chat_completions_url(base_url: str) -> str:
    suffix = "/chat/completions" if base_url.endswith("/v1") else "/v1/chat/completions"
    return f"{base_url}{suffix}"


async def _vertex_chat_completion(
    payload: dict[str, Any],
    *,
    api_key: str,
) -> dict[str, Any] | None:
    """Call Vertex AI Express through Google's supported Gen AI SDK."""
    if not api_key:
        return None

    from google import genai
    from google.genai import types

    messages = payload.get("messages") or []
    system_parts: list[str] = []
    contents: list[Any] = []
    for message in messages:
        role = str(message.get("role") or "user")
        raw_content = message.get("content", "")
        text = raw_content if isinstance(raw_content, str) else json.dumps(raw_content)
        if role == "system":
            system_parts.append(text)
            continue
        contents.append(
            types.Content(
                role="model" if role == "assistant" else "user",
                parts=[types.Part.from_text(text=text)],
            )
        )

    config_values: dict[str, Any] = {}
    if system_parts:
        config_values["system_instruction"] = "\n\n".join(system_parts)
    if payload.get("temperature") is not None:
        config_values["temperature"] = payload["temperature"]
    if payload.get("max_tokens") is not None:
        config_values["max_output_tokens"] = payload["max_tokens"]
    response_format = payload.get("response_format") or {}
    if response_format.get("type") in {"json_object", "json_schema"}:
        config_values["response_mime_type"] = "application/json"

    async with genai.Client(vertexai=True, api_key=api_key).aio as client:
        response = await client.models.generate_content(
            model=str(payload.get("model") or "gemini-2.5-flash"),
            contents=contents,
            config=types.GenerateContentConfig(**config_values),
        )
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        return None
    return {"choices": [{"message": {"content": text.strip()}}]}


async def chat_completion(
    payload: dict[str, Any],
    *,
    timeout_seconds: float = 120.0,
    api_key: str | None = None,
    base_url: str | None = None,
    provider: str | None = None,
) -> dict[str, Any] | None:
    """Call the configured Community LLM and normalize its response."""
    selected = provider or llm_provider()
    if selected not in LLM_PROVIDERS:
        raise ValueError(f"Unsupported Community LLM provider: {selected}")

    token = _api_key(selected, api_key)
    if selected == "vertex":
        return await _vertex_chat_completion(payload, api_key=token)
    if selected == "groq" and not token:
        return None

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(
            _chat_completions_url(_base_url(selected, base_url)),
            json=payload,
            headers=headers,
        )
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
