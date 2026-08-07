"""Focused tests for the stdio bridge's JSON-RPC client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kemory_cli.config import Credentials
from kemory_cli.mcp_bridge import _build_headers, _jsonrpc, _JsonRpcError, _resolve_url


def client_with_response(response_body) -> MagicMock:
    client = MagicMock()

    async def post(_path, *, json):
        response = MagicMock()
        response.raise_for_status.return_value = None
        body = response_body(json) if callable(response_body) else response_body
        response.json.return_value = body
        return response

    client.post = AsyncMock(side_effect=post)
    return client


async def test_jsonrpc_posts_standard_envelope_to_single_endpoint():
    client = client_with_response(
        lambda sent: {
            "jsonrpc": "2.0",
            "id": sent["id"],
            "result": {"tools": [{"name": "kemory_recall_memory"}]},
        }
    )

    result = await _jsonrpc(client, "tools/list")
    path = client.post.call_args.args[0]
    sent = client.post.call_args.kwargs["json"]

    assert path == "/mcp/v1"
    assert sent["jsonrpc"] == "2.0"
    assert sent["method"] == "tools/list"
    assert "params" not in sent
    assert result["tools"][0]["name"].startswith("kemory_")


async def test_jsonrpc_sends_tool_call_params_and_unwraps_result():
    client = client_with_response(
        lambda sent: {
            "jsonrpc": "2.0",
            "id": sent["id"],
            "result": {"content": [{"type": "text", "text": "ok"}], "isError": False},
        }
    )

    result = await _jsonrpc(
        client,
        "tools/call",
        {"name": "s9nmem_recall_memory", "arguments": {"query": "x"}},
    )

    sent = client.post.call_args.kwargs["json"]
    assert sent["params"]["name"] == "s9nmem_recall_memory"
    assert result["content"][0]["text"] == "ok"


async def test_jsonrpc_surfaces_protocol_error():
    client = client_with_response(
        lambda sent: {
            "jsonrpc": "2.0",
            "id": sent["id"],
            "error": {"code": -32601, "message": "Method not found"},
        }
    )

    with pytest.raises(_JsonRpcError, match="-32601: Method not found") as error:
        await _jsonrpc(client, "missing")

    assert error.value.code == -32601


@pytest.mark.parametrize(
    "body",
    [
        {"jsonrpc": "1.0", "id": 1, "result": {}},
        {"jsonrpc": "2.0", "id": "wrong", "result": {}},
        {"jsonrpc": "2.0", "id": 1},
    ],
)
async def test_jsonrpc_rejects_malformed_responses(body):
    client = client_with_response(body)

    with pytest.raises(_JsonRpcError):
        await _jsonrpc(client, "ping")


def test_local_cached_credential_is_forwarded_as_api_key():
    credentials = Credentials(
        access_token="local-secret",
        refresh_token="",
        expires_at=9999999999,
        issuer="local",
        client_id="local",
        kemory_url="http://localhost:8111",
        env="local",
    )

    with (
        patch.dict("os.environ", {}, clear=True),
        patch("kemory_cli.mcp_bridge.Credentials.load", return_value=credentials),
    ):
        headers = _build_headers()

    assert headers["X-API-Key"] == "local-secret"
    assert "Authorization" not in headers


def test_bridge_defaults_to_community_docker_port():
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("kemory_cli.mcp_bridge.Credentials.load", return_value=None),
    ):
        assert _resolve_url() == "http://localhost:8111"
