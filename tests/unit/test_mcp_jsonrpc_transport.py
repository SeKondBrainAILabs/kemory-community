"""Focused contract tests for the MCP JSON-RPC HTTP transport."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.auth import require_auth
from backend.mcp.server import (
    _LATEST_PROTOCOL_VERSION,
    ToolCallRequest,
    _jsonrpc_dispatch,
    call_tool,
    jsonrpc_endpoint,
    list_tools,
    router,
)
from backend.mcp.tools._base import MCPToolResult


@pytest.fixture
def auth():
    return SimpleNamespace(user_id=uuid.uuid4(), agent_id=uuid.uuid4())


@pytest.fixture
def db():
    return AsyncMock()


def request(method: str, *, request_id=1, params: dict | None = None) -> dict:
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def response_json(response) -> dict | list:
    return json.loads(response.body)


async def test_initialize_negotiates_version_and_preserves_string_id(auth, db):
    response = await _jsonrpc_dispatch(
        request(
            "initialize",
            request_id="init-7",
            params={"protocolVersion": "2025-03-26"},
        ),
        auth,
        db,
    )

    assert response["id"] == "init-7"
    assert response["result"]["protocolVersion"] == "2025-03-26"
    assert response["result"]["serverInfo"]["name"] == "kemory-community"


async def test_initialize_falls_back_for_unsupported_version(auth, db):
    response = await _jsonrpc_dispatch(
        request("initialize", params={"protocolVersion": "2099-01-01"}),
        auth,
        db,
    )

    assert response["result"]["protocolVersion"] == _LATEST_PROTOCOL_VERSION


async def test_tools_list_advertises_only_canonical_names(auth, db):
    response = await _jsonrpc_dispatch(request("tools/list"), auth, db)
    names = [tool["name"] for tool in response["result"]["tools"]]

    assert names
    assert len(names) == len(set(names))
    assert all(name.startswith("kemory_") for name in names)
    assert not any(name.startswith(("s9nmem_", "kora_")) for name in names)


@pytest.mark.parametrize("alias", ["s9nmem_test_transport", "kora_test_transport"])
async def test_legacy_tool_aliases_are_accepted_at_call_dispatch(alias, auth, db):
    expected = MCPToolResult(content=[{"type": "text", "text": "ok"}])
    handler = AsyncMock(return_value=expected)

    with patch.dict("backend.mcp.tools.HANDLERS", {"kemory_test_transport": handler}):
        response = await _jsonrpc_dispatch(
            request("tools/call", params={"name": alias, "arguments": {"value": 1}}),
            auth,
            db,
        )

    assert response["result"] == {"content": expected.content, "isError": False}
    handler.assert_awaited_once_with(
        {"value": 1},
        auth.user_id,
        auth.agent_id,
        db,
    )


async def test_unknown_tool_is_an_mcp_tool_error(auth, db):
    response = await _jsonrpc_dispatch(
        request(
            "tools/call",
            params={"name": "kemory_does_not_exist", "arguments": {}},
        ),
        auth,
        db,
    )

    assert response["result"]["isError"] is True
    assert "Unknown tool" in response["result"]["content"][0]["text"]


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (None, -32600),
        ({"jsonrpc": "1.0", "id": 3, "method": "ping"}, -32600),
        ({"jsonrpc": "2.0", "id": {"bad": "id"}, "method": "ping"}, -32600),
        ({"jsonrpc": "2.0", "id": 3}, -32600),
        (request("tools/list", params=[]), -32602),
        (request("tools/call", params={}), -32602),
        (
            request(
                "tools/call",
                params={"name": "kemory_recall_memory", "arguments": []},
            ),
            -32602,
        ),
        (request("not/a/method"), -32601),
    ],
)
async def test_jsonrpc_errors(message, code, auth, db):
    response = await _jsonrpc_dispatch(message, auth, db)
    assert response["error"]["code"] == code


async def test_unexpected_tool_failure_becomes_internal_error(auth, db):
    with patch("backend.mcp.server.handle_tool_call", AsyncMock(side_effect=RuntimeError)):
        response = await _jsonrpc_dispatch(
            request("tools/call", params={"name": "kemory_recall_memory"}),
            auth,
            db,
        )

    assert response["error"] == {"code": -32603, "message": "Internal error"}


async def test_parse_error_and_empty_batch_have_standard_errors(auth, db):
    broken_request = AsyncMock()
    broken_request.json.side_effect = ValueError("bad json")
    parse_response = await jsonrpc_endpoint(broken_request, auth, db)

    empty_batch_request = AsyncMock()
    empty_batch_request.json.return_value = []
    batch_response = await jsonrpc_endpoint(empty_batch_request, auth, db)

    assert response_json(parse_response)["error"]["code"] == -32700
    assert response_json(batch_response)["error"]["code"] == -32600


async def test_notification_returns_202(auth, db):
    notification = AsyncMock()
    notification.json.return_value = {"jsonrpc": "2.0", "method": "notifications/initialized"}

    response = await jsonrpc_endpoint(notification, auth, db)
    assert response.status_code == 202


async def test_legacy_routes_share_the_tool_handlers(auth, db):
    listed = await list_tools(auth)
    expected = MCPToolResult(content=[{"type": "text", "text": "legacy-ok"}])

    with patch("backend.mcp.server.handle_tool_call", AsyncMock(return_value=expected)) as handler:
        called = await call_tool(
            ToolCallRequest(name="kemory_recall_memory", arguments={"query": "x"}),
            auth,
            db,
        )

    assert listed.tools
    assert all(tool["name"].startswith("kemory_") for tool in listed.tools)
    assert called.content == expected.content
    handler.assert_awaited_once()


def test_jsonrpc_route_keeps_local_auth_dependency():
    route = next(route for route in router.routes if route.path == "/mcp/v1")
    dependencies = {dependency.call for dependency in route.dependant.dependencies}

    assert require_auth in dependencies
    assert {route.path for route in router.routes} >= {
        "/mcp/v1",
        "/mcp/v1/tools/list",
        "/mcp/v1/tools/call",
    }
