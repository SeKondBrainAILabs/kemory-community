"""Persisted, community-only runtime settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from backend.config.settings import settings


class CommunityRuntimeSettings(BaseModel):
    llm_provider: Literal["groq", "llama_cpp", "vertex"]
    llm_configured: bool
    llm_api_key_configured: bool
    llm_api_keys_configured: dict[Literal["groq", "llama_cpp", "vertex"], bool]
    llm_model: str
    llm_base_url: str
    # Compatibility fields for clients from before the generic LLM selector.
    groq_configured: bool
    groq_model: str
    openai_configured: bool
    voyage_configured: bool
    cohere_configured: bool
    embedding_provider: Literal["fastembed", "openai", "voyage", "cohere"]
    embedding_model: str
    artifact_max_bytes: int
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class CommunityRuntimeSettingsUpdate(BaseModel):
    llm_api_key: str | None = Field(default=None, max_length=2048)
    clear_llm_api_key: bool = False
    llm_provider: Literal["groq", "llama_cpp", "vertex"] = "groq"
    llm_model: str = Field(default="llama-3.3-70b-versatile", min_length=1, max_length=200)
    llm_base_url: str = Field(default="https://api.groq.com/openai", max_length=2048)
    # Accepted while pre-release clients migrate to the generic fields.
    groq_api_key: str | None = Field(default=None, max_length=512)
    clear_groq_api_key: bool = False
    groq_model: str | None = Field(default=None, min_length=1, max_length=200)
    openai_api_key: str | None = Field(default=None, max_length=512)
    clear_openai_api_key: bool = False
    voyage_api_key: str | None = Field(default=None, max_length=512)
    clear_voyage_api_key: bool = False
    cohere_api_key: str | None = Field(default=None, max_length=512)
    clear_cohere_api_key: bool = False
    embedding_provider: Literal["fastembed", "openai", "voyage", "cohere"]
    embedding_model: str = Field(min_length=1, max_length=200)
    artifact_max_bytes: int = Field(ge=1_048_576, le=1_073_741_824)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class CommunityLlmTestRequest(BaseModel):
    llm_provider: Literal["groq", "llama_cpp", "vertex"]
    llm_model: str = Field(min_length=1, max_length=200)
    llm_base_url: str = Field(default="", max_length=2048)
    llm_api_key: str | None = Field(default=None, max_length=2048)


class CommunityLlmTestResult(BaseModel):
    provider: Literal["groq", "llama_cpp", "vertex"]
    model: str
    response: str


_ENV_KEYS = {
    "llm_provider": "KEMORY_LLM_PROVIDER",
    "llm_model": "KEMORY_LLM_MODEL",
    "llm_base_url": "KEMORY_LLM_BASE_URL",
    "embedding_provider": "KEMORY_EMBEDDING_PROVIDER",
    "embedding_model": "EMBEDDING_MODEL",
    "artifact_max_bytes": "KEMORY_ARTIFACT_MAX_BYTES",
    "log_level": "LOG_LEVEL",
}

_EMBEDDING_SECRET_KEYS = {
    "openai": "OPENAI_API_KEY",
    "voyage": "VOYAGE_API_KEY",
    "cohere": "COHERE_API_KEY",
}

_LLM_SECRET_KEYS = {
    "groq": "GROQ_API_KEY",
    "llama_cpp": "LLAMA_CPP_API_KEY",
    "vertex": "GOOGLE_API_KEY",
}

_LLM_DEFAULTS = {
    "groq": {
        "model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai",
    },
    "llama_cpp": {
        "model": "local-model",
        "base_url": "http://host.docker.internal:8080",
    },
    "vertex": {
        "model": "gemini-2.5-flash",
        "base_url": "",
    },
}


def _config_path() -> Path:
    configured = settings.kemory_community_config.strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".kemory-community" / "config.json"


def _load_document() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _runtime_values() -> dict:
    saved = _load_document().get("runtime_settings")
    return saved if isinstance(saved, dict) else {}


def _selected_llm_provider(saved: dict) -> str:
    provider = str(os.environ.get("KEMORY_LLM_PROVIDER") or saved.get("llm_provider") or "groq")
    return provider if provider in _LLM_DEFAULTS else "groq"


def _llm_key(saved: dict, provider: str) -> str:
    if provider == _selected_llm_provider(saved):
        generic = os.environ.get("KEMORY_LLM_API_KEY", "").strip()
        if generic:
            return generic
    provider_env = _LLM_SECRET_KEYS[provider]
    return str(os.environ.get(provider_env, "").strip() or saved.get(f"{provider}_api_key") or "")


def get_community_runtime_settings() -> CommunityRuntimeSettings:
    saved = _runtime_values()
    llm_provider = _selected_llm_provider(saved)
    defaults = _LLM_DEFAULTS[llm_provider]
    llm_model = str(
        os.environ.get("KEMORY_LLM_MODEL")
        or os.environ.get("KMV_SYNTHESIS_MODEL")
        or saved.get("llm_model")
        or saved.get("groq_model")
        or defaults["model"]
    )
    llm_base_url = str(
        os.environ.get("KEMORY_LLM_BASE_URL")
        or (
            os.environ.get("GROQ_BASE_URL")
            if llm_provider == "groq"
            else os.environ.get("LLAMA_CPP_BASE_URL")
            if llm_provider == "llama_cpp"
            else ""
        )
        or saved.get("llm_base_url")
        or defaults["base_url"]
    )
    llm_key = _llm_key(saved, llm_provider)
    return CommunityRuntimeSettings(
        llm_provider=llm_provider,
        llm_configured=bool(llm_base_url) if llm_provider == "llama_cpp" else bool(llm_key),
        llm_api_key_configured=bool(llm_key),
        llm_api_keys_configured={
            provider: bool(_llm_key(saved, provider)) for provider in _LLM_SECRET_KEYS
        },
        llm_model=llm_model,
        llm_base_url=llm_base_url,
        groq_configured=bool(
            os.environ.get("GROQ_API_KEY", "").strip() or saved.get("groq_api_key")
        ),
        openai_configured=bool(os.environ.get("OPENAI_API_KEY", "").strip() or saved.get("openai_api_key")),
        voyage_configured=bool(os.environ.get("VOYAGE_API_KEY", "").strip() or saved.get("voyage_api_key")),
        cohere_configured=bool(os.environ.get("COHERE_API_KEY", "").strip() or saved.get("cohere_api_key")),
        embedding_provider=str(
            os.environ.get("KEMORY_EMBEDDING_PROVIDER") or saved.get("embedding_provider") or "fastembed"
        ),
        embedding_model=str(
            os.environ.get("EMBEDDING_MODEL") or saved.get("embedding_model") or "BAAI/bge-small-en-v1.5"
        ),
        groq_model=str(
            (
                os.environ.get("KMV_SYNTHESIS_MODEL")
                if llm_provider == "groq"
                else saved.get("groq_model")
            )
            or (llm_model if llm_provider == "groq" else _LLM_DEFAULTS["groq"]["model"])
        ),
        artifact_max_bytes=int(
            os.environ.get("KEMORY_ARTIFACT_MAX_BYTES") or saved.get("artifact_max_bytes") or 50 * 1024 * 1024
        ),
        log_level=str(os.environ.get("LOG_LEVEL") or saved.get("log_level") or settings.log_level).upper(),
    )


def load_community_runtime_settings() -> CommunityRuntimeSettings:
    """Apply persisted values before community services initialize."""
    saved = _runtime_values()
    provider = _selected_llm_provider(saved)
    selected_key = _llm_key(saved, provider)
    if selected_key and not os.environ.get("KEMORY_LLM_API_KEY"):
        os.environ["KEMORY_LLM_API_KEY"] = selected_key
    for embedding_provider, env_name in _EMBEDDING_SECRET_KEYS.items():
        field = f"{embedding_provider}_api_key"
        if saved.get(field) and not os.environ.get(env_name):
            os.environ[env_name] = str(saved[field])
    for provider_name, env_name in _LLM_SECRET_KEYS.items():
        field = f"{provider_name}_api_key"
        if saved.get(field) and not os.environ.get(env_name):
            os.environ[env_name] = str(saved[field])
    for field, env_name in _ENV_KEYS.items():
        if field in saved and not os.environ.get(env_name):
            os.environ[env_name] = str(saved[field])

    runtime = get_community_runtime_settings()
    settings.log_level = runtime.log_level
    settings.kemory_embedding_provider = runtime.embedding_provider
    settings.embedding_model = runtime.embedding_model
    settings.kmv_synthesis_model = runtime.llm_model
    os.environ["KMV_SYNTHESIS_MODEL"] = runtime.llm_model
    settings.kemory_artifact_max_bytes = runtime.artifact_max_bytes
    return runtime


def update_community_runtime_settings(
    update: CommunityRuntimeSettingsUpdate,
) -> CommunityRuntimeSettings:
    previous = get_community_runtime_settings()
    path = _config_path()
    document = _load_document()
    saved = _runtime_values()
    secret_fields = {
        "llm_api_key",
        "clear_llm_api_key",
        "groq_api_key",
        "clear_groq_api_key",
        *(
            field
            for provider in _EMBEDDING_SECRET_KEYS
            for field in (f"{provider}_api_key", f"clear_{provider}_api_key")
        ),
    }
    values = update.model_dump(exclude=secret_fields)
    values["llm_model"] = update.groq_model or update.llm_model
    values.pop("groq_model", None)
    saved.update(values)

    for provider, env_name in _EMBEDDING_SECRET_KEYS.items():
        field = f"{provider}_api_key"
        clear_field = f"clear_{provider}_api_key"
        value = getattr(update, field)
        if getattr(update, clear_field):
            saved.pop(field, None)
            os.environ.pop(env_name, None)
        elif value is not None and value.strip():
            saved[field] = value.strip()
            os.environ[env_name] = value.strip()

    provider = update.llm_provider
    provider_field = f"{provider}_api_key"
    provider_env = _LLM_SECRET_KEYS[provider]
    replacement = update.llm_api_key
    if provider == "groq" and not replacement:
        replacement = update.groq_api_key
    if update.clear_llm_api_key or (provider == "groq" and update.clear_groq_api_key):
        saved.pop(provider_field, None)
        os.environ.pop(provider_env, None)
        os.environ.pop("KEMORY_LLM_API_KEY", None)
    elif replacement is not None and replacement.strip():
        saved[provider_field] = replacement.strip()
        os.environ[provider_env] = replacement.strip()
        os.environ["KEMORY_LLM_API_KEY"] = replacement.strip()
    elif previous.llm_provider != provider:
        os.environ.pop("KEMORY_LLM_API_KEY", None)
        selected_key = _llm_key(saved, provider)
        if selected_key:
            os.environ["KEMORY_LLM_API_KEY"] = selected_key

    for field, env_name in _ENV_KEYS.items():
        os.environ[env_name] = str(values[field])
    os.environ["KMV_SYNTHESIS_MODEL"] = str(values["llm_model"])

    settings.log_level = update.log_level
    settings.kemory_embedding_provider = update.embedding_provider
    settings.embedding_model = update.embedding_model
    settings.kmv_synthesis_model = str(values["llm_model"])
    settings.kemory_artifact_max_bytes = update.artifact_max_bytes
    if (
        previous.embedding_provider != update.embedding_provider
        or previous.embedding_model != update.embedding_model
    ):
        from kemory.embeddings.encoder import reset_model

        reset_model()
    document["runtime_settings"] = saved
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return get_community_runtime_settings()


async def test_community_llm(request: CommunityLlmTestRequest) -> CommunityLlmTestResult:
    """Verify draft LLM settings without persisting or exposing credentials."""
    from kemory.llm import assistant_text, chat_completion

    saved = _runtime_values()
    api_key = request.llm_api_key.strip() if request.llm_api_key is not None else _llm_key(
        saved, request.llm_provider
    )
    response = await chat_completion(
        {
            "model": request.llm_model,
            "messages": [
                {
                    "role": "user",
                    "content": "Reply with exactly: Kemory ready",
                }
            ],
            "temperature": 0,
            "max_tokens": 16,
        },
        timeout_seconds=30.0,
        api_key=api_key,
        base_url=request.llm_base_url or None,
        provider=request.llm_provider,
    )
    text = assistant_text(response)
    if text is None:
        raise RuntimeError("The provider returned no chat completion")
    return CommunityLlmTestResult(
        provider=request.llm_provider,
        model=request.llm_model,
        response=text,
    )
