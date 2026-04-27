"""
Kemory CLI — MCP stdio bridge.

Replaces the standalone ``mcp_bridge/server.py`` with one that:
  * Reads ``~/.kemory/credentials`` instead of an env-var API key.
  * Auto-refreshes the access token when it nears expiry.
  * Falls back to ``S9NMV_API_KEY`` if set, so existing API-key-based
    setups keep working unchanged.

The bridge subscribes to two stdio MCP methods (list_tools, call_tool) and
forwards them to ``$KEMORY_URL/mcp/v1/*``. Identical wire shape to the
old standalone bridge so no other code needs to change.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from kemory_cli.auth import get_valid_credentials
from kemory_cli.config import Credentials

logger = logging.getLogger("kemory.mcp_bridge")

server = Server("kemory")


def _resolve_url() -> str:
    """Resolve the kemory base URL.

    Priority:
      1. KEMORY_URL env var
      2. ~/.kemory/credentials kemory_url
      3. http://localhost:8100 (local dev)
    """
    if env := os.environ.get("KEMORY_URL"):
        return env
    creds = Credentials.load()
    if creds and creds.kemory_url:
        return creds.kemory_url
    return "http://localhost:8100"


def _build_headers() -> dict[str, str]:
    """Pick the right auth header.

    1. ``S9NMV_API_KEY`` (or legacy ``KORA_API_KEY``) → X-API-Key
    2. ``~/.kemory/credentials`` access_token → Authorization: Bearer
    3. neither → empty (calls will fail with a clear message)
    """
    headers: dict[str, str] = {"Content-Type": "application/json"}
    api_key = os.environ.get("S9NMV_API_KEY") or os.environ.get("KORA_API_KEY")
    if api_key:
        headers["X-API-Key"] = api_key
        return headers
    creds = get_valid_credentials()
    if creds:
        headers["Authorization"] = f"Bearer {creds.access_token}"
    return headers


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=_resolve_url(),
        headers=_build_headers(),
        timeout=30.0,
    )


@server.list_tools()
async def list_tools() -> list[Tool]:
    async with _client() as client:
        try:
            resp = await client.post("/mcp/v1/tools/list")
            resp.raise_for_status()
            data = resp.json()
            return [
                Tool(
                    name=t["name"],
                    description=t["description"],
                    inputSchema=t["inputSchema"],
                )
                for t in data["tools"]
            ]
        except httpx.HTTPError as exc:
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


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    headers = _build_headers()
    if "Authorization" not in headers and "X-API-Key" not in headers:
        return [TextContent(
            type="text",
            text=(
                "Kemory has no credentials. Run `kemory login` to authenticate, "
                "or set S9NMV_API_KEY for API-key auth."
            ),
        )]

    async with _client() as client:
        try:
            resp = await client.post(
                "/mcp/v1/tools/call",
                json={"name": name, "arguments": arguments},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("isError"):
                return [TextContent(type="text", text=f"Vault error: {data['content'][0]['text']}")]
            return [
                TextContent(type="text", text=item["text"])
                for item in data["content"]
                if item.get("type") == "text"
            ]
        except httpx.HTTPStatusError as exc:
            return [TextContent(type="text", text=f"HTTP {exc.response.status_code}: {exc.response.text}")]
        except httpx.ConnectError:
            return [TextContent(type="text", text=f"Cannot connect to kemory at {_resolve_url()}.")]
        except Exception as exc:  # pragma: no cover — defensive
            return [TextContent(type="text", text=f"Bridge error: {type(exc).__name__}: {exc}")]


async def _main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def serve() -> None:
    """Entry point invoked by ``kemory mcp serve``."""
    asyncio.run(_main())


if __name__ == "__main__":  # pragma: no cover
    serve()
