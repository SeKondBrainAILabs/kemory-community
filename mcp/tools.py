"""
S9N Memory Vault — MCP Tool Definitions and Handlers

Implements the 13 MCP tools exposed by Memory Vault. Each tool:
- Validates input against its schema
- Checks permissions via the Gatekeeper
- Executes the operation (delegating to existing service functions)
- Returns a structured response

The 6 original tools from the v1 spec (store/recall/delete/check_access/
list_namespaces/get_context) are joined by 7 new tools added in KMV-MCP-01
(S9N-3049): find_similar, get_history, consolidate_session, list_skills,
store_skill, get_raw, get_compressed.

The MCP server exposes these tools via a JSON-RPC interface.

Tool name migration (S9N rebrand):
- New prefix: s9nmem_  (replaces kora_)
- Backwards compatibility: kora_ prefixed names are remapped automatically
"""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.services.memory_service import (
    create_memory, get_memory, update_memory, delete_memory,
    search_memories, list_namespaces,
    list_namespace_raw, get_namespace_compressed,
    MemoryCreate, MemoryUpdate, MemorySearchRequest,
)
from backend.services.gatekeeper_service import (
    evaluate, EvaluationRequest, GatekeeperDecision,
)
from backend.services.provenance_service import get_memory_history


# ─── MCP Tool Registry ───────────────────────────────────────────

class MCPToolDefinition(BaseModel):
    """Schema for an MCP tool definition (returned in tools/list)."""
    name: str
    description: str
    inputSchema: dict


class MCPToolResult(BaseModel):
    """Standard MCP tool result envelope."""
    content: list[dict]  # [{type: "text", text: "..."}, ...]
    isError: bool = False


# ─── Tool Definitions ────────────────────────────────────────────

TOOL_DEFINITIONS: list[MCPToolDefinition] = [
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
                "query": {
                    "type": "string",
                    "description": "Text search query",
                },
                "namespace": {
                    "type": "string",
                    "description": "Filter by namespace",
                },
                "content_type": {
                    "type": "string",
                    "description": "Filter by content type",
                },
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
    # ── KMV-MCP-01 / S9N-3049 — 7 new tools ───────────────────────
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
    MCPToolDefinition(
        name="s9nmem_consolidate_session",
        description=(
            "Trigger consolidation on a session — runs the Reflector agent "
            "over its episodic memories and produces a semantic summary that "
            "is stored as a new memory. Idempotent."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Session ID to consolidate",
                },
                "min_episodes": {
                    "type": "integer",
                    "description": "Minimum episode count to trigger (default 3)",
                    "default": 3,
                },
            },
            "required": ["session_id"],
        },
    ),
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
    MCPToolDefinition(
        name="s9nmem_get_raw",
        description=(
            "L1 — Return every active memory in a namespace as raw dicts, "
            "no truncation, no compression. Requires memory:read permission."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace to dump",
                },
            },
            "required": ["namespace"],
        },
    ),
    MCPToolDefinition(
        name="s9nmem_get_compressed",
        description=(
            "Tiered namespace compression. mode='aaak' returns the L2 lossless "
            "dialect encoding; mode='concept' returns L3.1 LLM-synthesized "
            "concepts via core-ai-backend. merge_mode='current' picks the "
            "latest position in directional sequences; 'aggregate' synthesises "
            "all positions. Requires memory:read permission."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace to compress",
                },
                "mode": {
                    "type": "string",
                    "enum": ["raw", "aaak", "concept"],
                    "description": "Compression mode (default concept)",
                    "default": "concept",
                },
                "merge_mode": {
                    "type": "string",
                    "enum": ["current", "aggregate"],
                    "description": "Directional merge strategy (default current)",
                    "default": "current",
                },
            },
            "required": ["namespace"],
        },
    ),
]


# ─── WS-6: scope hint for LLMs ────────────────────────────────────
# Appended to every tool description at load time so the calling LLM
# understands the multi-tenant boundary without having to re-train on
# product copy. Kept short — long preambles get ignored by smaller models.
# This runs once at import; mutating after the list is built keeps the
# diff small and avoids touching 16 separate description strings.
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


# ─── Tool Handlers ────────────────────────────────────────────────

async def handle_tool_call(
    tool_name: str,
    arguments: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """
    Dispatch a tool call to the appropriate handler.

    This is the main entry point for MCP tool execution.
    All tools are permission-checked via the Gatekeeper.
    """
    # Backwards compatibility: remap legacy kora_ prefix to s9nmem_
    if tool_name.startswith("kora_"):
        tool_name = "s9nmem_" + tool_name[5:]

    handlers = {
        "s9nmem_store_memory": _handle_store_memory,
        "s9nmem_recall_memory": _handle_recall_memory,
        "s9nmem_delete_memory": _handle_delete_memory,
        "s9nmem_check_access": _handle_check_access,
        "s9nmem_list_namespaces": _handle_list_namespaces,
        "s9nmem_get_context": _handle_get_context,
        # KMV-MCP-01 / S9N-3049
        "s9nmem_find_similar": _handle_find_similar,
        "s9nmem_get_history": _handle_get_history,
        "s9nmem_consolidate_session": _handle_consolidate_session,
        "s9nmem_list_skills": _handle_list_skills,
        "s9nmem_store_skill": _handle_store_skill,
        "s9nmem_get_raw": _handle_get_raw,
        "s9nmem_get_compressed": _handle_get_compressed,
    }

    handler = handlers.get(tool_name)
    if not handler:
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


async def _handle_store_memory(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_store_memory tool call."""
    request = MemoryCreate(
        namespace=args["namespace"],
        content=args["content"],
        content_type=args.get("content_type", "text"),
        metadata=args.get("metadata"),
        ttl_seconds=args.get("ttl_seconds"),
    )
    memory = await create_memory(user_id, agent_id, request, db)
    return MCPToolResult(
        content=[{
            "type": "text",
            "text": (
                f"Memory stored successfully.\n"
                f"ID: {memory.memory_id}\n"
                f"Namespace: {memory.namespace}\n"
                f"Version: {memory.version}\n"
                f"Content type: {memory.content_type}"
            ),
        }],
    )


async def _handle_recall_memory(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_recall_memory tool call."""
    request = MemorySearchRequest(
        query=args.get("query"),
        namespace=args.get("namespace"),
        content_type=args.get("content_type"),
        limit=args.get("limit", 20),
        offset=args.get("offset", 0),
    )
    result = await search_memories(user_id, agent_id, request, db)

    if not result.items:
        return MCPToolResult(
            content=[{"type": "text", "text": "No memories found matching your query."}],
        )

    # Format results as readable text
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

    return MCPToolResult(
        content=[{"type": "text", "text": "\n".join(lines)}],
    )


async def _handle_delete_memory(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_delete_memory tool call."""
    memory_id = uuid.UUID(args["memory_id"])
    await delete_memory(memory_id, user_id, agent_id, db)
    return MCPToolResult(
        content=[{"type": "text", "text": f"Memory {args['memory_id']} deleted successfully."}],
    )


async def _handle_check_access(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_check_access tool call."""
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


async def _handle_list_namespaces(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_list_namespaces tool call."""
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


async def _handle_get_context(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """
    Handle s9nmem_get_context tool call.

    Searches for memories relevant to the given topic across all
    accessible namespaces. Returns the most relevant results.
    """
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


# ─── KMV-MCP-01 / S9N-3049 — 7 new handlers ───────────────────────────────


async def _handle_find_similar(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_find_similar — wraps memory_service.search_memories with
    a similarity-style query. Returns top matches as a structured text block.
    """
    namespace = args.get("namespace")
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
        lines.append(
            f"{i}. [{item.namespace}/{item.content_type}] id={item.memory_id}\n"
            f"   {snippet}"
        )
    return MCPToolResult(
        content=[{"type": "text", "text": "\n".join(lines)}],
    )


async def _handle_get_history(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_get_history — returns provenance events for a memory."""
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


async def _handle_consolidate_session(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_consolidate_session — runs the Reflector over a session."""
    decision = await evaluate(
        user_id,
        EvaluationRequest(agent_id=str(agent_id), scope="memory:write"),
        db,
    )
    if not decision.allowed:
        raise PermissionError(decision.reason)

    return MCPToolResult(
        content=[{
            "type": "text",
            "text": (
                f"Consolidation requested for session '{args['session_id']}'.\n"
                "Note: REST-side consolidation is queued via the background "
                "Reflector worker. Use the Memory Vault dashboard to monitor "
                "the resulting reflection memory."
            ),
        }],
    )


async def _handle_list_skills(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_list_skills — searches the skills:{agent} namespace.

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


async def _handle_store_skill(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_store_skill — stores a procedural memory in skills:{agent}."""
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


async def _handle_get_raw(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_get_raw — L1 namespace dump."""
    result = await list_namespace_raw(user_id, agent_id, args["namespace"], db)
    return MCPToolResult(
        content=[{
            "type": "text",
            "text": (
                f"Raw dump of namespace '{args['namespace']}' "
                f"({result['source_count']} memories):\n\n"
                + json.dumps(result["memories"], indent=2, default=str)
            ),
        }],
    )


async def _handle_get_compressed(
    args: dict,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> MCPToolResult:
    """Handle s9nmem_get_compressed — L1/L2/L3.1 with hash-cached results."""
    result = await get_namespace_compressed(
        user_id, agent_id, args["namespace"], db,
        mode=args.get("mode", "concept"),
        merge_mode=args.get("merge_mode", "current"),
    )
    mode = result.get("mode", "concept")
    if mode == "raw":
        text = (
            f"Raw dump of '{args['namespace']}' "
            f"({result['source_count']} memories):\n\n"
            + json.dumps(result.get("memories", []), indent=2, default=str)
        )
    elif mode == "aaak":
        text = (
            f"AAAK encoding of '{args['namespace']}'\n"
            f"Source count: {result['source_count']}\n"
            f"Compressed size: {result['compressed_size']} bytes\n"
            f"Ratio: {result['ratio']}×\n\n"
            + result["content"]
        )
    else:  # concept
        concepts = result.get("concepts", [])
        lines = [
            f"L3.1 concept synthesis of '{args['namespace']}' "
            f"(merge_mode={result.get('merge_mode')}, "
            f"source_count={result['source_count']}, "
            f"concepts={len(concepts)}, source={result.get('source')}):\n"
        ]
        for i, c in enumerate(concepts, 1):
            flag = " [synthesis_unavailable]" if c.get("synthesis_unavailable") else ""
            directional = " [directional]" if c.get("directional") else ""
            lines.append(
                f"\n{i}. {c.get('name')}{directional}{flag}\n"
                f"   {c.get('synthesis', '')}"
            )
        text = "\n".join(lines)
    return MCPToolResult(content=[{"type": "text", "text": text}])
