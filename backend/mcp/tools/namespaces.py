"""
MCP tools — namespace listing and contextual retrieval.

Tools in this module:
  kemory_list_namespaces — enumerate namespaces + memory counts
  kemory_get_context — topic-relevant memories with optional LLM synthesis
  kemory_get_session_context — rolling digest plus latest raw exchanges
  kemory_rehydrate_session_sources — expand digest provenance to raw sources
  kemory_get_user_context — cross-namespace summary for session-start injection
"""

from __future__ import annotations

from backend.mcp.tools._base import MCPToolDefinition, MCPToolResult
from backend.services.cross_agent_context import (
    format_cross_agent_section,
    get_cross_agent_context,
)
from backend.services.memory_service import (
    MemorySearchRequest,
    list_namespaces,
    search_memories,
)
from backend.services.session_digest_service import get_session_context, rehydrate_session_sources
from backend.services.user_context_service import get_user_context

_SESSION_CONTEXT_DEFINITION = MCPToolDefinition(
    name="kemory_get_session_context",
    description=(
        "Get prompt-ready context for one namespace session. Older exchanges are "
        "folded into a readable rolling digest while the latest exchanges remain "
        "raw. AAAK is never returned because it is a storage/export format."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string"},
            "session_id": {"type": "string"},
            "chat_id": {"type": "string"},
            "topic": {"type": "string"},
            "raw_tail_count": {"type": "integer", "default": 3},
            "token_budget": {"type": "integer", "default": 900},
            "max_relevant_memories": {"type": "integer", "default": 5},
            "model": {"type": "string"},
            "include_expansion_hooks": {"type": "boolean", "default": False},
        },
        "required": ["namespace", "session_id"],
    },
)

_REHYDRATE_SESSION_SOURCES_DEFINITION = MCPToolDefinition(
    name="kemory_rehydrate_session_sources",
    description=(
        "Expand rolling-digest provenance IDs to exact raw memories or chat turns. "
        "The operation is read-only and includes whole items only; it never returns AAAK."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "namespace": {"type": "string"},
            "session_id": {"type": "string"},
            "source_exchange_ids": {"type": "array", "items": {"type": "string"}},
            "source_memory_ids": {"type": "array", "items": {"type": "string"}},
            "source_turn_ids": {"type": "array", "items": {"type": "string"}},
            "query": {"type": "string"},
            "trigger": {"type": "string", "enum": ["explicit", "heuristic"], "default": "explicit"},
            "token_budget": {"type": "integer", "default": 700},
            "max_items": {"type": "integer", "default": 3},
            "model": {"type": "string"},
        },
        "required": ["namespace", "session_id"],
    },
)

_USER_CONTEXT_DEFINITION = MCPToolDefinition(
    name="s9nmem_get_user_context",
    description=(
        "Get a cross-namespace memory overview for the user. "
        "Ideal for session-start context injection — gives the agent a single "
        "block covering all of the user's memory namespaces.\n\n"
        "depth='l3' (default): returns per-namespace L3/L3.1 summaries already "
        "computed by the compression pipeline — fast, no LLM call.\n"
        "depth='l4': adds one LLM synthesis pass across all namespace summaries "
        "via core-ai-backend — richer but slower; synthesis=null if backend "
        "is unavailable.\n\n"
        "Optional 'namespaces' list restricts which namespaces are included."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "depth": {
                "type": "string",
                "enum": ["l3", "l4"],
                "description": (
                    "'l3' = stored summaries only (fast, no LLM). "
                    "'l4' = LLM synthesis across all summaries (slower)."
                ),
                "default": "l3",
            },
            "namespaces": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of namespace names to include. Default: all namespaces for the user."
                ),
            },
        },
        "required": [],
    },
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
    _SESSION_CONTEXT_DEFINITION,
    _REHYDRATE_SESSION_SOURCES_DEFINITION,
    _USER_CONTEXT_DEFINITION,
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
            content=[
                {
                    "type": "text",
                    "text": f"No contextual memories found for topic: '{topic}'",
                }
            ],
        )

    # S9N-3074-SUB3: attempt LLM synthesis via reranker
    synthesised: str | None = None
    try:
        from kemory.search.reranker import synthesise

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

    namespaces = {item.namespace for item in result.items if item.namespace}
    if not namespaces and namespace:
        namespaces = {namespace}
    cross = await get_cross_agent_context(
        user_id=user_id,
        current_agent_id=agent_id,
        namespaces=namespaces,
        db=db,
    )
    cross_section = format_cross_agent_section(cross)

    if synthesised:
        text = synthesised + ("\n" + cross_section if cross_section else "")
        return MCPToolResult(content=[{"type": "text", "text": text}])

    # Fallback: format as context block
    lines = [f"Context for '{topic}' ({len(result.items)} memories):\n"]
    for item in result.items:
        lines.append(
            f"[{item.content_type}] ({item.namespace}) "
            f"{item.content[:300]}{'...' if len(item.content) > 300 else ''}\n"
        )
    if cross_section:
        lines.append(cross_section)

    return MCPToolResult(
        content=[{"type": "text", "text": "\n".join(lines)}],
    )


async def _handle_get_user_context(args, user_id, agent_id, db):
    """Calls get_user_context() service directly — no HTTP round-trip."""
    depth = args.get("depth", "l3")
    namespaces_filter: list[str] | None = args.get("namespaces") or None

    if depth not in ("l3", "l4"):
        return MCPToolResult(
            content=[{"type": "text", "text": f"Invalid depth '{depth}'. Use 'l3' or 'l4'."}],
            isError=True,
        )

    result = await get_user_context(
        user_id,
        db,
        depth=depth,
        namespaces_filter=namespaces_filter,
    )

    ns_list = result.get("namespaces", [])
    lines = [f"User context (depth={depth}, {len(ns_list)} namespace(s)):\n"]
    for ns in ns_list:
        tier = ns.get("tier") or "none"
        count = ns.get("memory_count", 0)
        summary = (ns.get("summary") or "(no summary yet)").strip()
        if len(summary) > 400:
            summary = summary[:397] + "..."
        lines.append(f"[{ns['namespace']}] tier={tier} memories={count}\n  {summary}\n")

    if result.get("synthesis"):
        lines.append(f"\nL4 synthesis:\n{result['synthesis']}")

    return MCPToolResult(
        content=[{"type": "text", "text": "\n".join(lines)}],
    )


async def _handle_get_session_context(args, user_id, agent_id, db):
    namespace = args.get("namespace")
    session_id = args.get("session_id")
    if not namespace or not session_id:
        missing = "namespace" if not namespace else "session_id"
        return MCPToolResult(
            content=[{"type": "text", "text": f"Validation error: {missing} is required."}],
            isError=True,
        )

    result = await get_session_context(
        user_id,
        agent_id,
        namespace,
        session_id,
        db,
        chat_id=args.get("chat_id"),
        topic=args.get("topic"),
        raw_tail_count=args.get("raw_tail_count", 3),
        token_budget=args.get("token_budget", 900),
        max_relevant_memories=args.get("max_relevant_memories", 5),
        model=args.get("model"),
        include_expansion_hooks=bool(args.get("include_expansion_hooks", False)),
    )
    digest = result["digest"]
    context = result["context"]
    rehydration = result.get("rehydration") or {}
    footer = (
        "\n\nContext metadata:\n"
        f"- source_exchanges={result['source_exchange_count']}\n"
        f"- digest_compacted_exchanges={digest['compacted_exchange_count']}\n"
        f"- digest_tokens={digest['token_count']}/{digest['token_budget']} "
        f"({digest['token_count_method']})\n"
        f"- context_tokens={context['token_count']} ({context['token_count_method']})\n"
        f"- rehydration_suggested={rehydration.get('suggested', False)}"
    )
    hooks = result.get("expansion_hooks")
    if hooks:
        digest_hook = hooks.get("digest", {})
        footer += (
            "\n\nExpansion hooks:\n"
            "- tool=kemory_rehydrate_session_sources\n"
            f"- source_exchange_ids={digest_hook.get('source_exchange_ids', [])}\n"
            f"- source_memory_ids={digest_hook.get('source_memory_ids', [])}\n"
            f"- source_turn_ids={digest_hook.get('source_turn_ids', [])}"
        )
    return MCPToolResult(content=[{"type": "text", "text": context["text"] + footer}])


async def _handle_rehydrate_session_sources(args, user_id, agent_id, db):
    namespace = args.get("namespace")
    session_id = args.get("session_id")
    if not namespace or not session_id:
        missing = "namespace" if not namespace else "session_id"
        return MCPToolResult(
            content=[{"type": "text", "text": f"Validation error: {missing} is required."}],
            isError=True,
        )

    result = await rehydrate_session_sources(
        user_id,
        namespace,
        session_id,
        db,
        source_memory_ids=args.get("source_memory_ids"),
        source_turn_ids=args.get("source_turn_ids"),
        source_exchange_ids=args.get("source_exchange_ids"),
        query=args.get("query"),
        token_budget=args.get("token_budget", 700),
        max_items=args.get("max_items", 3),
        model=args.get("model"),
        trigger=args.get("trigger", "explicit"),
    )
    header = (
        f"Rehydrated session sources for namespace='{namespace}' session_id='{session_id}'\n"
        f"trigger={result['trigger']['mode']} expanded={result['expanded_count']} "
        f"omitted={result['omitted_count']} tokens={result['token_count']}/{result['token_budget']}\n"
        "AAAK is not returned; raw sources are exact and read-only.\n"
    )
    text = result.get("text") or "(no raw sources fit the requested token budget)"
    return MCPToolResult(content=[{"type": "text", "text": header + "\n" + text}])


HANDLERS: dict[str, object] = {
    "s9nmem_list_namespaces": _handle_list_namespaces,
    "s9nmem_get_context": _handle_get_context,
    "kemory_get_session_context": _handle_get_session_context,
    "kemory_rehydrate_session_sources": _handle_rehydrate_session_sources,
    "s9nmem_get_user_context": _handle_get_user_context,
}
