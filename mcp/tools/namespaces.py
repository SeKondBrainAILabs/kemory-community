"""
MCP tools — namespace listing and contextual retrieval.

Tools in this module:
  s9nmem_list_namespaces — enumerate namespaces + memory counts
  s9nmem_get_context     — topic-relevant memories with optional LLM synthesis
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.mcp.tools._base import MCPToolDefinition, MCPToolResult
from backend.services.memory_service import (
    MemorySearchRequest,
    list_namespaces,
    search_memories,
)


DEFINITIONS: list[MCPToolDefinition] = [
    MCPToolDefinition(
        name="s9nmem_list_namespaces",
        description=(
            "List all namespaces in the user's S9N Memory Vault with memory counts. "
            "Useful for discovering available data before searching."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    MCPToolDefinition(
        name="s9nmem_get_context",
        description=(
            "Get contextual memories relevant to a conversation or topic. "
            "Searches across all accessible namespaces (or a specific namespace) "
            "and returns the most relevant memories, optionally synthesised by the "
            "AI backend. Requires memory:read permission."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "The topic or conversation context to find relevant memories for",
                },
                "namespace": {
                    "type": "string",
                    # S9N-3075: expose namespace so callers can scope to a specific namespace
                    "description": "Optional namespace to search within (e.g. 'shared', 'lme_bench_ku-001')",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of contextual memories to return (default 10)",
                    "default": 10,
                },
                "content_types": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional filter for specific content types",
                },
            },
            "required": ["topic"],
        },
    ),
]


async def _handle_list_namespaces(args, user_id, agent_id, db):
    namespaces = await list_namespaces(user_id, db)
    if not namespaces:
        return MCPToolResult(
            content=[{"type": "text", "text": "No namespaces found. The vault is empty."}],
        )

    lines = ["Available namespaces:\n"]
    for ns in namespaces:
        lines.append(f"  - {ns['namespace']}: {ns['count']} memories")

    return MCPToolResult(
        content=[{"type": "text", "text": "\n".join(lines)}],
    )


async def _handle_get_context(args, user_id, agent_id, db):
    """Searches for memories relevant to the given topic across all
    accessible namespaces. Returns the most relevant results."""
    max_results = args.get("max_results", 10)
    content_types = args.get("content_types")
    topic = args["topic"]
    # S9N-3075: read namespace from args (was previously ignored — caused empty results
    # for all benchmark namespaces because the tool searched the wrong scope)
    namespace: str | None = args.get("namespace")
    content_type_filter = content_types[0] if content_types and len(content_types) == 1 else None

    # S9N-3074-SUB2: attempt hybrid search first for richer cross-session recall
    # S9N-3075: pass namespace so benchmark / isolated namespaces are searched correctly
    request = MemorySearchRequest(
        query=topic,
        namespace=namespace,
        content_type=content_type_filter,
        limit=max_results,
        offset=0,
        search_mode="hybrid",
    )
    result = await search_memories(user_id, agent_id, request, db, skip_gatekeeper=True)

    # S9N-3075: if hybrid returns empty (e.g. no embeddings yet — migration 005 not yet
    # deployed on the target environment), fall back to FTS so the tool remains useful
    # before the vector index is populated.
    if not result.items:
        fts_request = MemorySearchRequest(
            query=topic,
            namespace=namespace,
            content_type=content_type_filter,
            limit=max_results,
            offset=0,
            search_mode="fts",
        )
        result = await search_memories(user_id, agent_id, fts_request, db, skip_gatekeeper=True)

    if not result.items:
        return MCPToolResult(
            content=[{
                "type": "text",
                "text": f"No contextual memories found for topic: '{topic}'",
            }],
        )

    # S9N-3074-SUB3: attempt LLM synthesis via reranker
    synthesised: str | None = None
    try:
        from memory_vault.search.reranker import synthesise
        candidates = [
            {
                "content": item.content,
                "namespace": item.namespace,
                "content_type": item.content_type,
            }
            for item in result.items
        ]
        synthesised = await synthesise(topic, candidates)
    except Exception:
        pass  # fall back to raw context block

    if synthesised:
        return MCPToolResult(
            content=[{"type": "text", "text": synthesised}],
        )

    # Fallback: format as context block
    lines = [f"Context for '{topic}' ({len(result.items)} memories):\n"]
    for item in result.items:
        lines.append(
            f"[{item.content_type}] ({item.namespace}) "
            f"{item.content[:300]}{'...' if len(item.content) > 300 else ''}\n"
        )

    return MCPToolResult(
        content=[{"type": "text", "text": "\n".join(lines)}],
    )


HANDLERS: dict[str, object] = {
    "s9nmem_list_namespaces": _handle_list_namespaces,
    "s9nmem_get_context": _handle_get_context,
}
