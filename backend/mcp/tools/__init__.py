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

from backend.mcp.tools import consolidation, memory, meta, namespaces, skills
from backend.mcp.tools._base import MCPToolDefinition, MCPToolResult

# ─── Aggregate ────────────────────────────────────────────────────────────

_SOURCE_TOOL_DEFINITIONS: list[MCPToolDefinition] = [
    *memory.DEFINITIONS,
    *namespaces.DEFINITIONS,
    *consolidation.DEFINITIONS,
    *skills.DEFINITIONS,
    *meta.DEFINITIONS,
]


def _canonical_tool(tool: MCPToolDefinition) -> MCPToolDefinition:
    if not tool.name.startswith("s9nmem_"):
        return tool
    return tool.model_copy(
        update={
            "name": "kemory_" + tool.name.removeprefix("s9nmem_"),
            "description": tool.description.replace("S9N Memory Vault", "Kemory"),
        }
    )


TOOL_DEFINITIONS: list[MCPToolDefinition] = [
    *[_canonical_tool(tool) for tool in _SOURCE_TOOL_DEFINITIONS],
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
for _name, _handler in list(HANDLERS.items()):
    if _name.startswith("s9nmem_"):
        HANDLERS["kemory_" + _name.removeprefix("s9nmem_")] = _handler
del _name, _handler


# ─── WS-6: scope hint for LLMs ────────────────────────────────────────────
# Appended to every tool description at load time so callers see the
# Community runtime boundary. Idempotent across module reloads.
_COMMUNITY_SCOPE_HINT = (
    "\n\nScope: this Kemory Community instance is a local single-user vault "
    "authenticated with X-API-Key. Data stays in the configured local "
    "Postgres/pgvector database and local artifact storage."
    "\n\nWhat to store (good vs bad examples):"
    "\n  GOOD: 'User prefers TypeScript with strict mode and pnpm.'"
    "\n  GOOD: 'Project uses Postgres 16 with pgvector and runs via Docker Compose.'"
    "\n  GOOD: 'User asked to refactor to async; in progress on branch X.'"
    "\n  BAD : 'The user said hello.'  (transient — not worth storing)"
    "\n  BAD : 'API key abc123.'       (NEVER store credentials)"
    "\n  BAD : 'The current time is 14:32.'  (non-durable — will go stale)"
)

for _tool in TOOL_DEFINITIONS:
    if _COMMUNITY_SCOPE_HINT not in _tool.description:
        _tool.description = _tool.description.rstrip() + _COMMUNITY_SCOPE_HINT
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

    Legacy ``s9nmem_*`` and ``kora_*`` names remain dispatch aliases.
    """
    if tool_name.startswith("kora_"):
        tool_name = "kemory_" + tool_name.removeprefix("kora_")
    if tool_name.startswith("s9nmem_"):
        tool_name = "kemory_" + tool_name.removeprefix("s9nmem_")

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
