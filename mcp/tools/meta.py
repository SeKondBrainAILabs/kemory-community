"""
MCP tools — meta queries about access and provenance.

Tools in this module:
  s9nmem_check_access — Gatekeeper evaluation without performing the action
  s9nmem_get_history  — provenance event log for a memory
"""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from backend.mcp.tools._base import MCPToolDefinition, MCPToolResult
from backend.services.gatekeeper_service import EvaluationRequest, evaluate
from backend.services.memory_service import get_memory
from backend.services.provenance_service import get_memory_history


DEFINITIONS: list[MCPToolDefinition] = [
    MCPToolDefinition(
        name="s9nmem_check_access",
        description=(
            "Check if the current agent has permission to perform an action. "
            "Returns the Gatekeeper evaluation result without performing the action."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "Permission scope to check (e.g., 'memory:read', 'memory:write')",
                },
                "namespace": {
                    "type": "string",
                    "description": "Optional namespace to check against",
                },
            },
            "required": ["scope"],
        },
    ),
    MCPToolDefinition(
        name="s9nmem_get_history",
        description=(
            "Return the full provenance history of a memory — every state "
            "change with actor, reason, and before/after snapshots. "
            "Requires memory:read permission."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "UUID of the memory whose history you want",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max events to return, newest-first (default 50)",
                    "default": 50,
                },
            },
            "required": ["memory_id"],
        },
    ),
]


async def _handle_check_access(args, user_id, agent_id, db):
    decision = await evaluate(
        user_id,
        EvaluationRequest(
            agent_id=str(agent_id),
            scope=args["scope"],
            namespace=args.get("namespace"),
        ),
        db,
    )
    status_text = "ALLOWED" if decision.allowed else "DENIED"
    return MCPToolResult(
        content=[{
            "type": "text",
            "text": (
                f"Access check result: {status_text}\n"
                f"Scope: {args['scope']}\n"
                f"Outcome: {decision.outcome}\n"
                f"Reason: {decision.reason}"
            ),
        }],
    )


async def _handle_get_history(args, user_id, agent_id, db):
    memory_id = uuid.UUID(args["memory_id"])
    # Verify the agent has read access to this memory's namespace
    memory = await get_memory(memory_id, user_id, agent_id, db)
    events = await get_memory_history(db, memory_id, limit=args.get("limit", 50))
    if not events:
        return MCPToolResult(
            content=[{"type": "text", "text": f"No history events for memory {args['memory_id']}."}],
        )
    lines = [
        f"History for memory {memory.memory_id} (namespace: {memory.namespace}):\n"
    ]
    for ev in events:
        lines.append(
            f"- [{ev['created_at']}] {ev['event_type']} "
            f"by {ev['actor_type']}:{ev.get('actor_id') or 'system'} "
            f"— {ev.get('reason') or '(no reason)'}"
        )
    return MCPToolResult(
        content=[{"type": "text", "text": "\n".join(lines)}],
    )


HANDLERS: dict[str, object] = {
    "s9nmem_check_access": _handle_check_access,
    "s9nmem_get_history": _handle_get_history,
}
