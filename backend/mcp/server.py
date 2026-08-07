"""Kemory Community MCP HTTP transport.

``POST /mcp/v1`` is the canonical JSON-RPC 2.0 endpoint. The existing
``/tools/list``, ``/tools/call``, ``/prompts/list``, and ``/prompts/get``
routes remain available for older clients.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.mcp.tools import (
    TOOL_DEFINITIONS,
    handle_tool_call,
)
from backend.models.agent import AgentRegistry
from backend.services.brief_service import BRIEF_VERSION, render_brief

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp/v1", tags=["MCP Server"])

_SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
_LATEST_PROTOCOL_VERSION = _SUPPORTED_PROTOCOL_VERSIONS[0]


# ─── Request/Response Schemas ─────────────────────────────────────


class ToolListResponse(BaseModel):
    """Response for tools/list."""

    tools: list[dict]


class ToolCallRequest(BaseModel):
    """Request body for tools/call."""

    name: str = Field(..., description="Name of the tool to call")
    arguments: dict = Field(default_factory=dict, description="Tool arguments")


class ToolCallResponse(BaseModel):
    """Response for tools/call."""

    content: list[dict]
    isError: bool = False


# ─── Shared handlers ─────────────────────────────────────────────


def _tool_list_payload() -> list[dict]:
    """Return the same canonical tool catalogue for every transport."""
    return [tool.model_dump() for tool in TOOL_DEFINITIONS]


async def _render_kemory_brief(auth: AuthContext, db: AsyncSession) -> str:
    agent_name = "connected-agent"
    agent_id_str = str(auth.agent_id) if auth.agent_id else ""
    if auth.agent_id:
        row = await db.execute(
            select(AgentRegistry.agent_name).where(AgentRegistry.agent_id == auth.agent_id)
        )
        agent_name = row.scalar_one_or_none() or agent_name

    return render_brief(
        agent_name=agent_name,
        agent_id=agent_id_str,
        client_name=agent_name,
    )


# ─── Endpoints ────────────────────────────────────────────────────


@router.post(
    "/tools/list",
    response_model=ToolListResponse,
    summary="List available MCP tools",
)
async def list_tools(
    auth: AuthContext = Depends(require_auth),  # noqa: ARG001 - auth gates discovery
):
    """
    List all available MCP tools with their schemas.

    This is the discovery endpoint — agents call this first to learn
    what tools are available and what arguments they accept.
    """
    return ToolListResponse(tools=_tool_list_payload())


@router.post(
    "/tools/call",
    response_model=ToolCallResponse,
    summary="Call an MCP tool",
)
async def call_tool(
    request: ToolCallRequest,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Call an MCP tool with the given arguments.

    The tool is executed with the authenticated local agent identity.
    """
    result = await handle_tool_call(
        tool_name=request.name,
        arguments=request.arguments,
        user_id=auth.user_id,
        agent_id=auth.agent_id,
        db=db,
    )
    return ToolCallResponse(
        content=result.content,
        isError=result.isError,
    )


# ─── JSON-RPC 2.0 transport ──────────────────────────────────────


def _jsonrpc_error(request_id: Any, code: int, message: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


@router.post(
    "",
    summary="MCP Streamable HTTP transport (JSON-RPC 2.0)",
    response_class=JSONResponse,
)
async def jsonrpc_endpoint(
    request: Request,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Dispatch MCP requests over the standard single HTTP endpoint."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_jsonrpc_error(None, -32700, "Parse error"))

    if isinstance(body, list):
        if not body:
            return JSONResponse(_jsonrpc_error(None, -32600, "Invalid Request"))
        responses = []
        for item in body:
            response = await _jsonrpc_dispatch(item, auth, db)
            if response is not None:
                responses.append(response)
        if not responses:
            return Response(status_code=status.HTTP_202_ACCEPTED)
        return JSONResponse(responses)

    response = await _jsonrpc_dispatch(body, auth, db)
    if response is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return JSONResponse(response)


async def _jsonrpc_dispatch(
    request: Any,
    auth: AuthContext,
    db: AsyncSession,
) -> dict | None:
    """Dispatch one JSON-RPC message; valid notifications return ``None``."""
    if not isinstance(request, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request")

    request_id = request.get("id")
    if "id" in request and (
        isinstance(request_id, bool) or not isinstance(request_id, (str, int, type(None)))
    ):
        return _jsonrpc_error(None, -32600, "Invalid Request")
    if request.get("jsonrpc") != "2.0":
        return _jsonrpc_error(request_id, -32600, "Invalid Request")

    method = request.get("method")
    if not isinstance(method, str) or not method:
        return _jsonrpc_error(request_id, -32600, "Invalid Request")

    params = request.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return _jsonrpc_error(request_id, -32602, "Invalid params")

    # MCP notifications have no id and do not produce a response.
    if "id" not in request:
        return None

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def error(code: int, message: str) -> dict:
        return _jsonrpc_error(request_id, code, message)

    try:
        if method == "initialize":
            requested = params.get("protocolVersion")
            negotiated = requested if requested in _SUPPORTED_PROTOCOL_VERSIONS else _LATEST_PROTOCOL_VERSION
            return ok(
                {
                    "protocolVersion": negotiated,
                    "capabilities": {"tools": {}, "prompts": {}},
                    "serverInfo": {"name": "kemory-community", "version": "0.1.0"},
                }
            )

        if method == "ping":
            return ok({})

        if method == "tools/list":
            return ok({"tools": _tool_list_payload()})

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments", {})
            if not isinstance(name, str) or not name:
                return error(-32602, "Invalid params: 'name' is required")
            if not isinstance(arguments, dict):
                return error(-32602, "Invalid params: 'arguments' must be an object")

            result = await handle_tool_call(
                tool_name=name,
                arguments=arguments,
                user_id=auth.user_id,
                agent_id=auth.agent_id,
                db=db,
            )
            return ok({"content": result.content, "isError": result.isError})

        if method == "prompts/list":
            return ok(
                {
                    "prompts": [
                        {
                            "name": _KEMORY_BRIEF.name,
                            "description": _KEMORY_BRIEF.description,
                        }
                    ]
                }
            )

        if method == "prompts/get":
            if params.get("name") != _KEMORY_BRIEF.name:
                return error(-32602, "prompt_not_found")
            content = await _render_kemory_brief(auth, db)
            return ok(
                {
                    "description": _KEMORY_BRIEF.description,
                    "messages": [{"role": "user", "content": {"type": "text", "text": content}}],
                }
            )

        if method == "resources/list":
            return ok({"resources": []})
        if method == "resources/templates/list":
            return ok({"resourceTemplates": []})

        return error(-32601, f"Method not found: {method}")
    except Exception:
        logger.exception("MCP JSON-RPC dispatch failed for %s", method)
        return error(-32603, "Internal error")


# ─── Prompts ──────────────────────────────────────────────────────
#
# Standard MCP `prompts/list` and `prompts/get`. Only one prompt is
# exposed today — `kemory_brief` — the versioned connection brief the
# AI is told to refresh on every reconnect.


class PromptDefinition(BaseModel):
    name: str
    description: str
    version: str


class PromptListResponse(BaseModel):
    prompts: list[PromptDefinition]


class PromptGetResponse(BaseModel):
    name: str
    version: str
    description: str
    content: str


_KEMORY_BRIEF = PromptDefinition(
    name="kemory_brief",
    description=(
        "Kemory connection brief — how to use Kemory as your default memory "
        "store, including the first‑connect smoke test and cross‑agent context "
        "behavior. Refresh on every reconnect."
    ),
    version=BRIEF_VERSION,
)


@router.post(
    "/prompts/list",
    response_model=PromptListResponse,
    summary="List available MCP prompts",
)
async def list_prompts(
    auth: AuthContext = Depends(require_auth),  # noqa: ARG001 — auth gates discovery
):
    return PromptListResponse(prompts=[_KEMORY_BRIEF])


class PromptGetRequest(BaseModel):
    name: str = Field(..., description="Prompt name (e.g. 'kemory_brief')")


@router.post(
    "/prompts/get",
    response_model=PromptGetResponse,
    summary="Fetch a versioned MCP prompt by name",
)
async def get_prompt(
    request: PromptGetRequest,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    if request.name != _KEMORY_BRIEF.name:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="prompt_not_found")

    content = await _render_kemory_brief(auth, db)
    return PromptGetResponse(
        name=_KEMORY_BRIEF.name,
        version=_KEMORY_BRIEF.version,
        description=_KEMORY_BRIEF.description,
        content=content,
    )
