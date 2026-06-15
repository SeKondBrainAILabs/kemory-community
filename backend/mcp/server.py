"""
S9N Memory Vault — MCP Server (JSON-RPC Interface)

Exposes the MCP tools via a JSON-RPC 2.0 compatible HTTP endpoint.
Agents connect to this endpoint to discover and invoke tools.

Endpoints:
- POST /mcp/v1/tools/list     — List available tools
- POST /mcp/v1/tools/call     — Call a tool

Spec reference: Section 11 (MCP Tools)
"""

from fastapi import APIRouter, Depends, HTTPException, status
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

    agent_name = "connected-agent"
    agent_id_str = str(auth.agent_id) if auth.agent_id else ""
    if auth.agent_id:
        row = await db.execute(
            select(AgentRegistry.agent_name).where(AgentRegistry.agent_id == auth.agent_id)
        )
        agent_name = row.scalar_one_or_none() or agent_name

    content = render_brief(
        agent_name=agent_name,
        agent_id=agent_id_str,
        client_name=agent_name,
    )
    return PromptGetResponse(
        name=_KEMORY_BRIEF.name,
        version=_KEMORY_BRIEF.version,
        description=_KEMORY_BRIEF.description,
        content=content,
    )
