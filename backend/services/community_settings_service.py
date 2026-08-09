"""Persisted, community-only runtime settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from backend.config.settings import settings


class CommunityRuntimeSettings(BaseModel):
    groq_configured: bool
    openai_configured: bool
    voyage_configured: bool
    cohere_configured: bool
    embedding_provider: Literal["fastembed", "openai", "voyage", "cohere"]
    embedding_model: str
    groq_model: str
    artifact_max_bytes: int
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class CommunityRuntimeSettingsUpdate(BaseModel):
    groq_api_key: str | None = Field(default=None, max_length=512)
    clear_groq_api_key: bool = False
    openai_api_key: str | None = Field(default=None, max_length=512)
    clear_openai_api_key: bool = False
    voyage_api_key: str | None = Field(default=None, max_length=512)
    clear_voyage_api_key: bool = False
    cohere_api_key: str | None = Field(default=None, max_length=512)
    clear_cohere_api_key: bool = False
    embedding_provider: Literal["fastembed", "openai", "voyage", "cohere"]
    embedding_model: str = Field(min_length=1, max_length=200)
    groq_model: str = Field(min_length=1, max_length=200)
    artifact_max_bytes: int = Field(ge=1_048_576, le=1_073_741_824)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]


_ENV_KEYS = {
    "embedding_provider": "KEMORY_EMBEDDING_PROVIDER",
    "embedding_model": "EMBEDDING_MODEL",
    "groq_model": "KMV_SYNTHESIS_MODEL",
    "artifact_max_bytes": "KEMORY_ARTIFACT_MAX_BYTES",
    "log_level": "LOG_LEVEL",
}

_SECRET_KEYS = {
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "voyage": "VOYAGE_API_KEY",
    "cohere": "COHERE_API_KEY",
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


def get_community_runtime_settings() -> CommunityRuntimeSettings:
    saved = _runtime_values()
    return CommunityRuntimeSettings(
        groq_configured=bool(os.environ.get("GROQ_API_KEY", "").strip() or saved.get("groq_api_key")),
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
            os.environ.get("KMV_SYNTHESIS_MODEL") or saved.get("groq_model") or "llama-3.3-70b-versatile"
        ),
        artifact_max_bytes=int(
            os.environ.get("KEMORY_ARTIFACT_MAX_BYTES") or saved.get("artifact_max_bytes") or 50 * 1024 * 1024
        ),
        log_level=str(os.environ.get("LOG_LEVEL") or saved.get("log_level") or settings.log_level).upper(),
    )


def load_community_runtime_settings() -> CommunityRuntimeSettings:
    """Apply persisted values before community services initialize."""
    saved = _runtime_values()
    for provider, env_name in _SECRET_KEYS.items():
        field = f"{provider}_api_key"
        if saved.get(field) and not os.environ.get(env_name):
            os.environ[env_name] = str(saved[field])
    for field, env_name in _ENV_KEYS.items():
        if field in saved and not os.environ.get(env_name):
            os.environ[env_name] = str(saved[field])

    runtime = get_community_runtime_settings()
    settings.log_level = runtime.log_level
    settings.kemory_embedding_provider = runtime.embedding_provider
    settings.embedding_model = runtime.embedding_model
    settings.kmv_synthesis_model = runtime.groq_model
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
        field
        for provider in _SECRET_KEYS
        for field in (f"{provider}_api_key", f"clear_{provider}_api_key")
    }
    values = update.model_dump(exclude=secret_fields)
    saved.update(values)

    for provider, env_name in _SECRET_KEYS.items():
        field = f"{provider}_api_key"
        clear_field = f"clear_{provider}_api_key"
        value = getattr(update, field)
        if getattr(update, clear_field):
            saved.pop(field, None)
            os.environ.pop(env_name, None)
        elif value is not None and value.strip():
            saved[field] = value.strip()
            os.environ[env_name] = value.strip()

    for field, env_name in _ENV_KEYS.items():
        os.environ[env_name] = str(values[field])

    settings.log_level = update.log_level
    settings.kemory_embedding_provider = update.embedding_provider
    settings.embedding_model = update.embedding_model
    settings.kmv_synthesis_model = update.groq_model
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
