"""
MCP tool registry — aggregates one DEFINITIONS list and HANDLERS dict from
each family submodule (memory, namespaces, consolidation, skills, meta).

Public surface (preserved from the pre-split tools.py module):
  TOOL_DEFINITIONS  — list[MCPToolDefinition], used by /mcp/v1/tools/list
  handle_tool_call  — async dispatcher used by /mcp/v1/tools/call
  MCPToolResult     — return type
  MCPToolDefinition — schema type

Splitting the original 948-LOC file into family modules (P3 #17) made
each tool's definition + handler co-located and unit-testable in
isolation. This file is the single seam every consumer imports through;
new tools land in the relevant family module and the registry picks them
up automatically.
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.mcp.tools._base import MCPToolDefinition, MCPToolResult
from backend.mcp.tools import consolidation, memory, meta, namespaces, skills


# ─── Aggregate ────────────────────────────────────────────────────────────

TOOL_DEFINITIONS: list[MCPToolDefinition] = [
    *memory.DEFINITIONS,
    *namespaces.DEFINITIONS,
    *consolidation.DEFINITIONS,
    *skills.DEFINITIONS,
    *meta.DEFINITIONS,
]

# Family handlers merge into a single dispatch dict. New tools added in any
# family module are picked up here automatically because we re-import each
# module's HANDLERS and dict-spread.
HANDLERS: dict[str, object] = {
    **memory.HANDLERS,
    **namespaces.HANDLERS,
    **consolidation.HANDLERS,
    **skills.HANDLERS,
    **meta.HANDLERS,
}


# ─── WS-6: scope hint for LLMs ────────────────────────────────────────────
# Appended to every tool description at load time so the calling LLM
# understands the multi-tenant boundary without having to re-train on
# product copy. Idempotent — re-import does not double-append because each
# tool only gets the hint when its description doesn't already contain it.
_TENANT_SCOPE_HINT = (
    "\n\nScope: memories are isolated per-organisation and per-user. You "
    "cannot read or write outside your org, and (by default) you cannot "
    "see other users' private memories within your org. Use the "
    "visibility option (private/team/org) to share with teammates."
    "\n\nWhat to store (good vs bad examples):"
    "\n  GOOD: 'User prefers TypeScript with strict mode and pnpm.'"
    "\n  GOOD: 'Project uses Postgres 16, FalkorDB 1.4, deploy via Tilt.'"
    "\n  GOOD: 'User asked to refactor to async; in progress on branch X.'"
    "\n  BAD : 'The user said hello.'  (transient — not worth storing)"
    "\n  BAD : 'API key abc123.'       (NEVER store credentials)"
    "\n  BAD : 'The current time is 14:32.'  (non-durable — will go stale)"
)

for _tool in TOOL_DEFINITIONS:
    if _TENANT_SCOPE_HINT not in _tool.description:
        _tool.description = _tool.description.rstrip() + _TENANT_SCOPE_HINT
del _tool


# ─── Dispatcher ───────────────────────────────────────────────────────────


async def handle_tool_call(
    tool_name: str,
    arguments: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Dispatch a tool call to the appropriate family handler.

    All tools are permission-checked via the Gatekeeper inside the handler.
    Backwards-compat: legacy `kora_` prefix is rewritten to `s9nmem_`.
    """
    if tool_name.startswith("kora_"):
        tool_name = "s9nmem_" + tool_name[5:]

    handler = HANDLERS.get(tool_name)
    if handler is None:
        return MCPToolResult(
            content=[{"type": "text", "text": f"Unknown tool: {tool_name}"}],
            isError=True,
        )

    try:
        return await handler(arguments, user_id, agent_id, db)
    except PermissionError as e:
        return MCPToolResult(
            content=[{"type": "text", "text": f"Permission denied: {str(e)}"}],
            isError=True,
        )
    except ValueError as e:
        return MCPToolResult(
            content=[{"type": "text", "text": f"Validation error: {str(e)}"}],
            isError=True,
        )
    except Exception as e:
        return MCPToolResult(
            content=[{"type": "text", "text": f"Internal error: {str(e)}"}],
            isError=True,
        )


__all__ = [
    "TOOL_DEFINITIONS",
    "HANDLERS",
    "MCPToolDefinition",
    "MCPToolResult",
    "handle_tool_call",
]
