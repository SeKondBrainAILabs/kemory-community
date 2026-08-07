"""
Kemory CLI — MCP stdio bridge.

Replaces the standalone ``mcp_bridge/server.py`` with one that:
  * Reads ``~/.kemory/credentials`` instead of an env-var API key.
  * Falls back to ``KEMORY_API_KEY`` (or the legacy aliases
    ``S9NMV_API_KEY`` / ``KORA_API_KEY``) if set, so existing API-key-based
    setups keep working unchanged.

The bridge subscribes to two stdio MCP methods (list_tools, call_tool) and
forwards them as JSON-RPC 2.0 to ``$KEMORY_URL/mcp/v1``.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
from typing import Any

import httpx

from kemory_cli.config import Credentials

logger = logging.getLogger("kemory.mcp_bridge")

# Process-local flag so the legacy-alias deprecation log fires once per
# bridge process, not once per MCP tool call.
_legacy_alias_warned = False
_request_ids = itertools.count(1)

# Active environment for this bridge process. Set by ``serve(env)`` from the
# ``kemory --env <env> mcp serve`` invocation the MCP host runs; credential
# lookups below load ``credentials-<env>``. Defaults to the active env
# (KEMORY_ENV or prod) when serve() isn't given one.
_ENV: str | None = None


def _resolve_url() -> str:
    """Resolve the kemory base URL.

    Priority:
      1. KEMORY_URL env var
      2. ~/.kemory/credentials kemory_url
      3. http://localhost:8111 (community Docker default)
    """
    if env := os.environ.get("KEMORY_URL"):
        return env
    creds = Credentials.load(_ENV)
    if creds and creds.kemory_url:
        return creds.kemory_url
    return "http://localhost:8111"


def _build_headers() -> dict[str, str]:
    """Pick the right auth header.

    1. ``KEMORY_API_KEY`` (or legacy aliases ``S9NMV_API_KEY``, ``KORA_API_KEY``) → X-API-Key
    2. local ``~/.kemory/credentials`` access_token -> X-API-Key
    3. non-local cached access_token -> Authorization: Bearer (compatibility)
    4. neither -> empty (calls will fail with a clear message)

    P1 #9: KEMORY_API_KEY is the canonical name. Legacy aliases are
    accepted (with a one-time deprecation log on first use) so existing
    integrations don't break on upgrade. Drop the aliases in v0.3.
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    api_key = (
        os.environ.get("KEMORY_API_KEY") or os.environ.get("S9NMV_API_KEY") or os.environ.get("KORA_API_KEY")
    )
    # Warn once if the caller is on a legacy alias.
    if api_key and not os.environ.get("KEMORY_API_KEY"):
        global _legacy_alias_warned
        if not _legacy_alias_warned:
            logger.warning(
                "Using deprecated env var (S9NMV_API_KEY / KORA_API_KEY). "
                "Switch to KEMORY_API_KEY — legacy aliases will be removed in v0.3."
            )
            _legacy_alias_warned = True
    if api_key:
        headers["X-API-Key"] = api_key
        return headers
    creds = Credentials.load(_ENV)
    if creds:
        if creds.issuer == "local" or creds.client_id == "local":
            headers["X-API-Key"] = creds.access_token
        else:
            headers["Authorization"] = f"Bearer {creds.access_token}"
    return headers


class _JsonRpcError(Exception):
    """A JSON-RPC error object returned by an otherwise successful request."""

    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


async def _jsonrpc(
    client: httpx.AsyncClient,
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send one JSON-RPC request to the canonical MCP endpoint."""
    request_id = next(_request_ids)
    payload: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        payload["params"] = params

    response = await client.post("/mcp/v1", json=payload)
    response.raise_for_status()
    body = response.json()

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        raise _JsonRpcError(-32603, "Invalid JSON-RPC response")
    if body.get("id") != request_id:
        raise _JsonRpcError(-32603, "Mismatched JSON-RPC response id")
    if "error" in body:
        error = body.get("error") or {}
        code = error.get("code", -32603)
        if not isinstance(code, int) or isinstance(code, bool):
            code = -32603
        raise _JsonRpcError(
            code,
            str(error.get("message", "Unknown JSON-RPC error")),
        )
    result = body.get("result")
    if not isinstance(result, dict):
        raise _JsonRpcError(-32603, "JSON-RPC response is missing an object result")
    return result


def _client() -> httpx.AsyncClient:
    """HTTP client used for every MCP tool call.

    The read timeout must cover the slowest synchronous server path —
    store operations run embedding generation + vector indexing inline
    before the HTTP response returns. The previous 30s default produced
    false-negative "Bridge error: ReadTimeout" messages while the write
    had actually succeeded server-side; naive retries on that would
    silently create duplicate memories. Connect timeout stays short so
    we still fail fast if the API is unreachable. Override with
    KEMORY_HTTP_TIMEOUT (seconds) if needed.
    """
    read_timeout = float(os.environ.get("KEMORY_HTTP_TIMEOUT", "120"))
    return httpx.AsyncClient(
        base_url=_resolve_url(),
        headers=_build_headers(),
        timeout=httpx.Timeout(read_timeout, connect=10.0),
    )


async def list_tools() -> list[Any]:
    from mcp.types import Tool

    async with _client() as client:
        try:
            result = await _jsonrpc(client, "tools/list")
            return [
                Tool(
                    name=t["name"],
                    description=t["description"],
                    inputSchema=t["inputSchema"],
                )
                for t in result["tools"]
            ]
        except (httpx.HTTPError, _JsonRpcError, KeyError, TypeError) as exc:
            logger.warning("list_tools failed: %s", exc)
            return [
                Tool(
                    name="kemory_unreachable",
                    description=(
                        f"Kemory at {_resolve_url()} is not reachable. "
                        "Run `kemory login` (if you haven't yet) or check the URL."
                    ),
                    inputSchema={"type": "object", "properties": {}},
                )
            ]


async def call_tool(name: str, arguments: dict[str, Any]) -> list[Any]:
    from mcp.types import TextContent

    headers = _build_headers()
    if "Authorization" not in headers and "X-API-Key" not in headers:
        return [
            TextContent(
                type="text",
                text=(
                    "Kemory has no credentials. Run `kemory login` to authenticate, "
                    "or set KEMORY_API_KEY for API-key auth."
                ),
            )
        ]

    async with _client() as client:
        try:
            result = await _jsonrpc(
                client,
                "tools/call",
                {"name": name, "arguments": arguments},
            )
            if result.get("isError"):
                return [
                    TextContent(
                        type="text",
                        text=f"Vault error: {result['content'][0]['text']}",
                    )
                ]
            return [
                TextContent(type="text", text=item["text"])
                for item in result["content"]
                if item.get("type") == "text"
            ]
        except _JsonRpcError as exc:
            return [TextContent(type="text", text=f"Vault error: {exc}")]
        except httpx.HTTPStatusError as exc:
            return [TextContent(type="text", text=f"HTTP {exc.response.status_code}: {exc.response.text}")]
        except httpx.ConnectError:
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Cannot connect to kemory at {_resolve_url()}.\n"
                        f"Hints:\n"
                        f"  • Is the URL correct? Try `kemory doctor`.\n"
                        f"  • Set KEMORY_URL=<url> if you need to override.\n"
                        f"  • For local dev, run `docker compose up -d kemory-api`."
                    ),
                )
            ]
        except httpx.TimeoutException as exc:
            # The backend may have completed the operation already — embedding
            # + vector indexing on store paths can outrun the client read
            # timeout. Don't surface this as an opaque failure: a caller that
            # blindly retries would create duplicates.
            return [
                TextContent(
                    type="text",
                    text=(
                        f"Bridge timeout after {_resolve_url()} did not respond in time "
                        f"({type(exc).__name__}). The server MAY have completed the "
                        f"operation — for writes, verify with kemory_list_namespaces "
                        f"or kemory_recall_memory BEFORE retrying so you don't create a "
                        f"duplicate. Raise KEMORY_HTTP_TIMEOUT (seconds) if this is "
                        f"recurring."
                    ),
                )
            ]
        except Exception as exc:  # pragma: no cover — defensive
            return [TextContent(type="text", text=f"Bridge error: {type(exc).__name__}: {exc}")]


async def _main() -> None:
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
    except ImportError as exc:
        raise RuntimeError(
            "The MCP stdio bridge requires the CLI extra. "
            "Install it with: pip install 'kemory-community[cli]'"
        ) from exc

    server = Server("kemory")
    server.list_tools()(list_tools)
    server.call_tool()(call_tool)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def serve(env: str | None = None) -> None:
    """Entry point invoked by ``kemory mcp serve``. ``env`` selects which
    ``credentials-<env>`` the bridge forwards (default: active env)."""
    global _ENV
    _ENV = env
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    serve()
