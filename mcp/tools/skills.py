"""
MCP tools — agent skills (procedural memory).

Tools in this module:
  s9nmem_list_skills  — enumerate stored procedures
  s9nmem_store_skill  — record a learned procedure
"""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from backend.mcp.tools._base import MCPToolDefinition, MCPToolResult
from backend.services.memory_service import (
    MemoryCreate,
    MemorySearchRequest,
    create_memory,
    search_memories,
)


DEFINITIONS: list[MCPToolDefinition] = [
    MCPToolDefinition(
        name="s9nmem_list_skills",
        description=(
            "List all stored agent skills — learned procedures with name, "
            "trigger, and steps. Requires memory:read permission."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "source_agent": {
                    "type": "string",
                    "description": "Optional filter by agent that learned the skill",
                },
            },
            "required": [],
        },
    ),
    MCPToolDefinition(
        name="s9nmem_store_skill",
        description=(
            "Store a learned skill (procedural memory) with name, trigger, "
            "and ordered steps. Requires memory:write permission."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill identifier (e.g., 'deploy-to-staging')",
                },
                "trigger": {
                    "type": "string",
                    "description": "When this skill applies (e.g., 'user asks to deploy')",
                },
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered list of steps in the procedure",
                },
                "visibility": {
                    "type": "string",
                    "enum": ["agent-private", "user-private", "team", "org-public"],
                    "description": "Visibility tier (default user-private)",
                    "default": "user-private",
                },
            },
            "required": ["name", "trigger", "steps"],
        },
    ),
]


async def _handle_list_skills(args, user_id, agent_id, db):
    """Searches the skills:{agent} namespace.

    Uses search_mode='hybrid' to allow listing without a query string
    (S9N-3092 requires query for fts mode but permits empty query for
    hybrid mode when a namespace or content_type filter is provided).
    """
    source_agent = args.get("source_agent")
    namespace = f"skills:{source_agent}" if source_agent else None
    request = MemorySearchRequest(
        query=None,
        namespace=namespace,
        content_type="skill",
        limit=100,
        offset=0,
        search_mode="hybrid",
    )
    result = await search_memories(user_id, agent_id, request, db, skip_gatekeeper=True)
    if not result.items:
        return MCPToolResult(
            content=[{"type": "text", "text": "No stored skills found."}],
        )
    lines = [f"{len(result.items)} stored skills:\n"]
    for item in result.items:
        try:
            skill = json.loads(item.content)
            lines.append(
                f"- {skill.get('name', 'unknown')} (v{skill.get('version', 1)})"
                f" — trigger: {skill.get('trigger', '')}"
            )
        except (json.JSONDecodeError, TypeError):
            lines.append(f"- {item.namespace}/{item.memory_id}")
    return MCPToolResult(
        content=[{"type": "text", "text": "\n".join(lines)}],
    )


async def _handle_store_skill(args, user_id, agent_id, db):
    skill_payload = {
        "name": args["name"],
        "trigger": args["trigger"],
        "steps": args["steps"],
        "version": 1,
    }
    namespace = f"skills:{agent_id}"
    request = MemoryCreate(
        namespace=namespace,
        content=json.dumps(skill_payload),
        content_type="skill",
        metadata={
            "skill_name": args["name"],
            "memory_type": "procedural",
            "visibility": args.get("visibility", "user-private"),
        },
    )
    memory = await create_memory(user_id, agent_id, request, db)
    return MCPToolResult(
        content=[{
            "type": "text",
            "text": (
                f"Skill stored successfully.\n"
                f"ID: {memory.memory_id}\n"
                f"Name: {args['name']}\n"
                f"Namespace: {namespace}\n"
                f"Visibility: {args.get('visibility', 'user-private')}"
            ),
        }],
    )


HANDLERS: dict[str, object] = {
    "s9nmem_list_skills": _handle_list_skills,
    "s9nmem_store_skill": _handle_store_skill,
}
