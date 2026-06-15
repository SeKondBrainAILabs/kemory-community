"""
MCP tools — memory CRUD + semantic search.

Tools in this module:
  s9nmem_store_memory   — write a memory
  s9nmem_recall_memory  — text/namespace search
  s9nmem_delete_memory  — soft-delete by id
  s9nmem_find_similar   — cosine-similarity neighbour lookup
"""

from __future__ import annotations

import uuid

from backend.mcp.tools._base import MCPToolDefinition, MCPToolResult
from backend.services.cross_agent_context import (
    format_cross_agent_section,
    get_cross_agent_context,
)
from backend.services.gatekeeper_service import (
    EvaluationRequest,
    evaluate,
)
from backend.services.memory_service import (
    MemoryCreate,
    MemorySearchRequest,
    create_memory,
    delete_memory,
    search_memories,
)
from backend.config.settings import settings


def _skip_gatekeeper() -> bool:
    return settings.kmv_identity == "local_single_user"

DEFINITIONS: list[MCPToolDefinition] = [
    MCPToolDefinition(
        name="s9nmem_store_memory",
        description=(
            "Store a new memory in the user's S9N Memory Vault. The memory is associated with "
            "a namespace and can include metadata, content type, and an optional TTL. "
            "Requires memory:write permission."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Target namespace (e.g., 'shared', 'agent_name:private')",
                },
                "content": {
                    "type": "string",
                    "description": "The memory content to store",
                },
                "content_type": {
                    "type": "string",
                    "enum": ["text", "structured", "conversation", "fact", "preference", "embedding"],
                    "description": "Type of memory content",
                    "default": "text",
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional structured metadata (tags, categories, etc.)",
                },
                "ttl_seconds": {
                    "type": "integer",
                    "description": "Optional time-to-live in seconds (min 60, max 31536000)",
                },
            },
            "required": ["namespace", "content"],
        },
    ),
    MCPToolDefinition(
        name="s9nmem_recall_memory",
        description=(
            "Search and retrieve memories from the user's S9N Memory Vault. Supports text search, "
            "namespace filtering, content type filtering, and pagination. "
            "Requires memory:read permission."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text search query"},
                "namespace": {"type": "string", "description": "Filter by namespace"},
                "content_type": {"type": "string", "description": "Filter by content type"},
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results (default 20, max 100)",
                    "default": 20,
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset",
                    "default": 0,
                },
            },
            "required": [],
        },
    ),
    MCPToolDefinition(
        name="s9nmem_delete_memory",
        description=(
            "Soft-delete a memory from the user's S9N Memory Vault by its ID. "
            "Requires memory:delete permission."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "UUID of the memory to delete",
                },
            },
            "required": ["memory_id"],
        },
    ),
    MCPToolDefinition(
        name="s9nmem_find_similar",
        description=(
            "Find memories near-duplicate to a given content string via cosine "
            "similarity. Useful for deduplication and contradiction discovery. "
            "Requires memory:read permission."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Reference text to find similar memories for",
                },
                "namespace": {
                    "type": "string",
                    "description": "Optional namespace to search within",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max similar memories to return (default 10)",
                    "default": 10,
                },
            },
            "required": ["content"],
        },
    ),
]


async def _handle_store_memory(args, user_id, agent_id, db):
    request = MemoryCreate(
        namespace=args["namespace"],
        content=args["content"],
        content_type=args.get("content_type", "text"),
        metadata=args.get("metadata"),
        ttl_seconds=args.get("ttl_seconds"),
    )
    # WS-2: pull the request-scoped org_id (set by require_auth) so the row
    # is tagged with the caller's tenant rather than falling through to the
    # legacy sentinel. Without this, MCP-stored memories were ending up
    # with org_id="legacy" — a tenant leak.
    from backend.core.tenancy import current_org_id

    org_id = current_org_id() or None
    memory = await create_memory(
        user_id,
        agent_id,
        request,
        db,
        org_id=org_id,
        skip_gatekeeper=_skip_gatekeeper(),
    )
    return MCPToolResult(
        content=[
            {
                "type": "text",
                "text": (
                    f"Memory stored successfully.\n"
                    f"ID: {memory.memory_id}\n"
                    f"Namespace: {memory.namespace}\n"
                    f"Version: {memory.version}\n"
                    f"Content type: {memory.content_type}"
                ),
            }
        ],
    )


async def _handle_recall_memory(args, user_id, agent_id, db):
    request = MemorySearchRequest(
        query=args.get("query"),
        namespace=args.get("namespace"),
        content_type=args.get("content_type"),
        limit=args.get("limit", 20),
        offset=args.get("offset", 0),
    )
    result = await search_memories(user_id, agent_id, request, db, skip_gatekeeper=_skip_gatekeeper())

    if not result.items:
        return MCPToolResult(
            content=[{"type": "text", "text": "No memories found matching your query."}],
        )

    lines = [f"Found {result.total} memories (showing {len(result.items)}):\n"]
    for i, item in enumerate(result.items, 1):
        lines.append(
            f"--- Memory {i} ---\n"
            f"ID: {item.memory_id}\n"
            f"Namespace: {item.namespace}\n"
            f"Type: {item.content_type}\n"
            f"Content: {item.content[:500]}{'...' if len(item.content) > 500 else ''}\n"
            f"Version: {item.version} | Quality: {item.quality_score or 'N/A'}\n"
        )

    namespaces = {item.namespace for item in result.items if item.namespace}
    if not namespaces and args.get("namespace"):
        namespaces = {args["namespace"]}
    cross = await get_cross_agent_context(
        user_id=user_id,
        current_agent_id=agent_id,
        namespaces=namespaces,
        db=db,
    )
    section = format_cross_agent_section(cross)
    if section:
        lines.append(section)

    return MCPToolResult(
        content=[{"type": "text", "text": "\n".join(lines)}],
    )


async def _handle_delete_memory(args, user_id, agent_id, db):
    memory_id = uuid.UUID(args["memory_id"])
    await delete_memory(memory_id, user_id, agent_id, db, skip_gatekeeper=_skip_gatekeeper())
    return MCPToolResult(
        content=[{"type": "text", "text": f"Memory {args['memory_id']} deleted successfully."}],
    )


async def _handle_find_similar(args, user_id, agent_id, db):
    namespace = args.get("namespace")
    if not _skip_gatekeeper():
        decision = await evaluate(
            user_id,
            EvaluationRequest(
                agent_id=str(agent_id),
                scope="memory:read",
                namespace=namespace,
            ),
            db,
        )
        if not decision.allowed:
            raise PermissionError(decision.reason)

    request = MemorySearchRequest(
        query=args["content"],
        namespace=namespace,
        limit=args.get("limit", 10),
        offset=0,
    )
    result = await search_memories(user_id, agent_id, request, db, skip_gatekeeper=True)
    if not result.items:
        return MCPToolResult(
            content=[{"type": "text", "text": "No similar memories found."}],
        )
    lines = [f"Found {len(result.items)} similar memories:\n"]
    for i, item in enumerate(result.items, 1):
        snippet = item.content[:200] + ("..." if len(item.content) > 200 else "")
        lines.append(f"{i}. [{item.namespace}/{item.content_type}] id={item.memory_id}\n   {snippet}")
    return MCPToolResult(
        content=[{"type": "text", "text": "\n".join(lines)}],
    )


HANDLERS: dict[str, object] = {
    "s9nmem_store_memory": _handle_store_memory,
    "s9nmem_recall_memory": _handle_recall_memory,
    "s9nmem_delete_memory": _handle_delete_memory,
    "s9nmem_find_similar": _handle_find_similar,
}
