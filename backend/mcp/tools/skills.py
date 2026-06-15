"""
MCP tools — agent skills (procedural memory).

Tools in this module:
  s9nmem_list_skills  — enumerate stored procedures
  s9nmem_store_skill  — record a learned procedure
"""

from __future__ import annotations

import json

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
    # When the MCP call is authenticated via an OAuth user token (e.g. via
    # `kemory login`), there is no agent_id — the request is bound to a user.
    # The previous code f-stringed `agent_id` directly, producing the literal
    # namespace "skills:None" which (a) is not actually agent-scoped, (b)
    # collides across all OAuth-token callers, and (c) is invisible to
    # `_handle_list_skills` when filtered by source_agent. Fall back to a
    # deterministic per-user scope (`skills:user-<user_id>`) so the data is
    # actually addressable. API-key callers (with a real agent_id) are
    # unchanged.
    scope = agent_id if agent_id is not None else f"user-{user_id}"
    skill_payload = {
        "name": args["name"],
        "trigger": args["trigger"],
        "steps": args["steps"],
        "version": 1,
    }
    namespace = f"skills:{scope}"
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
    # Stamp the row with the caller's org_id from the tenant context — exactly
    # as _handle_store_memory does. Without this, create_memory falls back to
    # the "legacy" sentinel, and every tenant-scoped read (recall, list_skills)
    # filters on the caller's REAL org_id, so the skill is written but
    # permanently invisible. This is why stored skills never appeared in
    # s9nmem_list_skills. (Fixed 2026-06-01.)
    from backend.core.tenancy import current_org_id

    org_id = current_org_id() or None
    memory = await create_memory(user_id, agent_id, request, db, org_id=org_id)
    return MCPToolResult(
        content=[
            {
                "type": "text",
                "text": (
                    f"Skill stored successfully.\n"
                    f"ID: {memory.memory_id}\n"
                    f"Name: {args['name']}\n"
                    f"Namespace: {namespace}\n"
                    f"Visibility: {args.get('visibility', 'user-private')}"
                ),
            }
        ],
    )


HANDLERS: dict[str, object] = {
    "s9nmem_list_skills": _handle_list_skills,
    "s9nmem_store_skill": _handle_store_skill,
}
