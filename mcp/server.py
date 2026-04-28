"""
S9N Memory Vault — MCP Server (JSON-RPC Interface)

Exposes the MCP tools via a JSON-RPC 2.0 compatible HTTP endpoint.
Agents connect to this endpoint to discover and invoke tools.

Endpoints:
- POST /mcp/v1/tools/list     — List available tools
- POST /mcp/v1/tools/call     — Call a tool

Spec reference: Section 11 (MCP Tools)
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.mcp.tools import (
    TOOL_DEFINITIONS,
    handle_tool_call,
)

router = APIRouter(prefix="/mcp/v1", tags=["MCP Server"])


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


# ─── Endpoints ────────────────────────────────────────────────────


@router.post(
    "/tools/list",
    response_model=ToolListResponse,
    summary="List available MCP tools",
)
async def list_tools(
    auth: AuthContext = Depends(require_auth),
):
    """
    List all available MCP tools with their schemas.

    This is the discovery endpoint — agents call this first to learn
    what tools are available and what arguments they accept.
    """
    return ToolListResponse(tools=[tool.model_dump() for tool in TOOL_DEFINITIONS])


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

    The tool is executed with the authenticated agent's identity.
    All permission checks are handled by the Gatekeeper.
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
