import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.config.settings import settings
from backend.core.body_size_limit import _limit_for
from backend.main import app
from backend.services.community_settings_service import (
    CommunityRuntimeSettingsUpdate,
    get_community_runtime_settings,
    load_community_runtime_settings,
    update_community_runtime_settings,
)
from kemory import llm
from kemory.compression.llm_client import CoreAIBackendClient
from kemory.embeddings import encoder


def test_release_routes_include_settings_update_and_artifact_workspace():
    def visit(routes):
        for route in routes:
            if path := getattr(route, "path", None):
                yield path, tuple(sorted(getattr(route, "methods", None) or []))
            if nested := getattr(route, "routes", None):
                yield from visit(nested)
            if original := getattr(route, "original_router", None):
                yield from visit(original.routes)

    routes = set(visit(app.routes))

    assert ("/api/v1/artifacts", ("GET",)) in routes
    assert ("/api/v1/community/settings", ("PUT",)) in routes


def test_artifact_limit_applies_to_every_upload_route(monkeypatch):
    monkeypatch.setattr(settings, "kemory_artifact_max_bytes", 7_000_000)

    assert _limit_for("/api/v1/artifacts/upload") == 7_000_000
    assert _limit_for("/api/v1/memories/abc/artifacts/upload") == 7_000_000
    assert _limit_for("/api/v1/chats/abc/artifacts/upload") == 7_000_000
    assert _limit_for("/api/v1/memories") == settings.max_request_body_bytes


def test_runtime_settings_persist_without_returning_groq_secret(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"version": 1, "ports": {"api": 8111}}))
    monkeypatch.setattr(settings, "kemory_community_config", str(config_path))
    for env_name in (
        "GROQ_API_KEY",
        "KEMORY_EMBEDDING_PROVIDER",
        "EMBEDDING_MODEL",
        "KMV_SYNTHESIS_MODEL",
        "KEMORY_ARTIFACT_MAX_BYTES",
        "LOG_LEVEL",
    ):
        monkeypatch.delenv(env_name, raising=False)

    result = update_community_runtime_settings(
        CommunityRuntimeSettingsUpdate(
            groq_api_key="gsk_test_only",
            embedding_provider="fastembed",
            embedding_model="BAAI/bge-small-en-v1.5",
            groq_model="llama-3.3-70b-versatile",
            artifact_max_bytes=64 * 1024 * 1024,
            log_level="DEBUG",
        )
    )

    document = json.loads(config_path.read_text())
    assert document["ports"] == {"api": 8111}
    assert document["runtime_settings"]["groq_api_key"] == "gsk_test_only"
    assert result.groq_configured is True
    assert "groq_api_key" not in result.model_dump()
    assert settings.kemory_artifact_max_bytes == 64 * 1024 * 1024
    assert config_path.stat().st_mode & 0o777 == 0o600

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    loaded = load_community_runtime_settings()
    assert loaded.groq_configured is True
    assert get_community_runtime_settings().log_level == "DEBUG"


@pytest.mark.asyncio
async def test_groq_client_uses_openai_compatible_endpoint(monkeypatch):
    post = AsyncMock(
        return_value=SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"choices": [{"message": {"content": "  hello  "}}]},
        )
    )

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return SimpleNamespace(post=post)

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_only")
    monkeypatch.setenv("GROQ_BASE_URL", "https://groq.invalid/openai")
    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeClient)

    response = await llm.chat_completion({"model": "llama", "messages": []})

    assert llm.assistant_text(response) == "hello"
    assert post.await_args.args[0] == "https://groq.invalid/openai/v1/chat/completions"
    assert post.await_args.kwargs["headers"]["Authorization"] == "Bearer gsk_test_only"


def test_legacy_concept_client_is_enabled_only_by_groq_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert CoreAIBackendClient().enabled is False
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test_only")
    assert CoreAIBackendClient().enabled is True


def test_openai_embedding_opt_in_requests_384_dimensions(monkeypatch):
    vector = [0.0] * encoder.EMBEDDING_DIM
    calls = []

    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"data": [{"embedding": vector}]},
        )

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return SimpleNamespace(post=post)

        def __exit__(self, *_args):
            return None

    monkeypatch.setenv("KEMORY_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setattr("httpx.Client", FakeClient)

    assert encoder.encode_batch(["hello"]) == [vector]
    assert calls[0][1]["json"]["dimensions"] == encoder.EMBEDDING_DIM


@pytest.mark.parametrize(
    ("provider", "api_key_name", "response", "expected_path"),
    [
        ("voyage", "VOYAGE_API_KEY", {"data": [{"embedding": [1.0] * 512}]}, "/embeddings"),
        ("cohere", "COHERE_API_KEY", {"embeddings": {"float": [[1.0] * 512]}}, "/embed"),
    ],
)
def test_cloud_embedding_opt_ins_adapt_supported_512_vectors(
    monkeypatch, provider, api_key_name, response, expected_path
):
    calls = []

    def post(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: response)

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return SimpleNamespace(post=post)

        def __exit__(self, *_args):
            return None

    monkeypatch.setenv("KEMORY_EMBEDDING_PROVIDER", provider)
    monkeypatch.setenv("EMBEDDING_MODEL", "test-model")
    monkeypatch.setenv(api_key_name, "test-only")
    monkeypatch.setattr("httpx.Client", FakeClient)

    vectors = encoder.encode_batch(["hello"])

    assert len(vectors[0]) == encoder.EMBEDDING_DIM
    assert sum(value * value for value in vectors[0]) == pytest.approx(1.0)
    assert calls[0][0][0].endswith(expected_path)
    assert calls[0][1]["json"]["output_dimension"] == 512
