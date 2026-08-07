import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from backend.api.routes import memories as memory_routes
from backend.core import auth as auth_module
from backend.main import app
from backend.services.memory_service import MemoryAggregateRequest


def _auth_context() -> SimpleNamespace:
    return SimpleNamespace(
        user_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        auth_method="api_key",
        scopes=[],
        org_id=str(uuid.uuid4()),
    )


def test_community_boot_mounts_only_local_runtime_routes():
    def route_paths(routes):
        for route in routes:
            path = getattr(route, "path", None)
            if path:
                yield path
            nested = getattr(route, "routes", None)
            if nested:
                yield from route_paths(nested)
            original_router = getattr(route, "original_router", None)
            if original_router is not None:
                yield from route_paths(original_router.routes)

    paths = set(route_paths(app.routes))

    assert "/health/ready" in paths
    assert "/api/v1/memories" in paths
    assert "/api/v1/chats" in paths
    assert "/api/v1/community/export" in paths
    assert "/mcp/v1" in paths

    hosted_prefixes = (
        "/api/v1/agents",
        "/api/v1/admin",
        "/api/v1/audit",
        "/api/v1/extension/keys",
        "/api/v1/gatekeeper",
        "/api/v1/graph",
        "/api/v1/me",
        "/api/v1/pair",
        "/api/v1/permissions",
        "/api/v1/teams",
    )
    for prefix in hosted_prefixes:
        assert not any(path == prefix or path.startswith(f"{prefix}/") for path in paths)


@pytest.mark.asyncio
async def test_auth_context_accepts_only_x_api_key(monkeypatch):
    identity_provider = SimpleNamespace(
        verify_api_key=AsyncMock(return_value=_auth_context()),
        verify_bearer=AsyncMock(side_effect=AssertionError("Bearer auth must not execute")),
    )
    monkeypatch.setattr(auth_module, "get_identity_provider", lambda: identity_provider)

    assert "credentials" not in inspect.signature(auth_module.get_auth_context).parameters
    assert await auth_module.get_auth_context(x_api_key=None) is None
    result = await auth_module.get_auth_context(x_api_key="local-secret")

    assert result.auth_method == "api_key"
    identity_provider.verify_api_key.assert_awaited_once_with("local-secret")
    identity_provider.verify_bearer.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_api_key_has_community_auth_error():
    with pytest.raises(HTTPException) as exc_info:
        await auth_module.require_auth(auth=None)

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Authentication required. Provide the X-API-Key header."
    assert "WWW-Authenticate" not in (exc_info.value.headers or {})


@pytest.mark.asyncio
async def test_memory_routes_bypass_gatekeeper_in_local_mode(monkeypatch):
    auth = _auth_context()
    db = object()

    aggregate = AsyncMock(return_value={"ok": "aggregate"})
    list_namespaces = AsyncMock(return_value=[{"namespace": "notes", "count": 1}])
    namespace_summary = AsyncMock(return_value={"namespace": "notes"})
    compressed = AsyncMock(return_value={"mode": "concept", "concepts": []})
    monkeypatch.setattr(memory_routes, "aggregate_memories", aggregate)
    monkeypatch.setattr(memory_routes, "list_namespaces", list_namespaces)
    monkeypatch.setattr(memory_routes, "get_namespace_summary", namespace_summary)
    monkeypatch.setattr(memory_routes, "get_namespace_compressed", compressed)

    request = MemoryAggregateRequest(query="How many notes?", namespace="notes")
    await memory_routes.aggregate_memories_endpoint(request=request, auth=auth, db=db)
    await memory_routes.list_namespaces_endpoint(auth=auth, db=db)
    await memory_routes.get_namespace_summary_endpoint(namespace="notes", auth=auth, db=db)
    await memory_routes.get_namespace_compressed_endpoint(
        namespace="notes",
        mode="concept",
        merge_mode="current",
        auth=auth,
        db=db,
    )

    assert aggregate.await_args.kwargs["skip_gatekeeper"] is True
    assert list_namespaces.await_args.kwargs["skip_gatekeeper"] is True
    assert namespace_summary.await_args.kwargs["skip_gatekeeper"] is True
    assert compressed.await_args.kwargs["skip_gatekeeper"] is True


@pytest.mark.asyncio
async def test_cognition_compression_mode_is_not_available():
    with pytest.raises(HTTPException) as exc_info:
        await memory_routes.get_namespace_compressed_endpoint(
            namespace="notes",
            mode="cognition",
            merge_mode="current",
            auth=_auth_context(),
            db=object(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail.endswith("aaak, concept, raw")


@pytest.mark.asyncio
async def test_session_summary_does_not_evaluate_gatekeeper(monkeypatch):
    from backend.services import gatekeeper_service

    evaluate = AsyncMock(side_effect=AssertionError("Gatekeeper must not execute"))
    monkeypatch.setattr(gatekeeper_service, "evaluate", evaluate)
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = SimpleNamespace(execute=AsyncMock(return_value=result))

    with pytest.raises(HTTPException) as exc_info:
        await memory_routes.get_session_summary_endpoint(
            namespace="notes",
            session_id="session-1",
            auth=_auth_context(),
            db=db,
        )

    assert exc_info.value.status_code == 404
    evaluate.assert_not_awaited()
