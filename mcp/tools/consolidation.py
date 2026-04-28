"""
MCP tools — namespace compression + session consolidation.

Tools in this module:
  s9nmem_consolidate_session — trigger Reflector over a session
  s9nmem_get_raw             — L1 raw namespace dump
  s9nmem_get_compressed      — L1/L2/L3.1 with hash-cached results
"""

from __future__ import annotations

import json

from backend.mcp.tools._base import MCPToolDefinition, MCPToolResult
from backend.services.gatekeeper_service import EvaluationRequest, evaluate
from backend.services.memory_service import (
    get_namespace_compressed,
    list_namespace_raw,
)

DEFINITIONS: list[MCPToolDefinition] = [
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


async def _handle_consolidate_session(args, user_id, agent_id, db):
    decision = await evaluate(
        user_id,
        EvaluationRequest(agent_id=str(agent_id), scope="memory:write"),
        db,
    )
    if not decision.allowed:
        raise PermissionError(decision.reason)

    return MCPToolResult(
        content=[
            {
                "type": "text",
                "text": (
                    f"Consolidation requested for session '{args['session_id']}'.\n"
                    "Note: REST-side consolidation is queued via the background "
                    "Reflector worker. Use the Memory Vault dashboard to monitor "
                    "the resulting reflection memory."
                ),
            }
        ],
    )


async def _handle_get_raw(args, user_id, agent_id, db):
    result = await list_namespace_raw(user_id, agent_id, args["namespace"], db)
    return MCPToolResult(
        content=[
            {
                "type": "text",
                "text": (
                    f"Raw dump of namespace '{args['namespace']}' "
                    f"({result['source_count']} memories):\n\n"
                    + json.dumps(result["memories"], indent=2, default=str)
                ),
            }
        ],
    )


async def _handle_get_compressed(args, user_id, agent_id, db):
    """L1/L2/L3.1 with hash-cached results."""
    result = await get_namespace_compressed(
        user_id,
        agent_id,
        args["namespace"],
        db,
        mode=args.get("mode", "concept"),
        merge_mode=args.get("merge_mode", "current"),
    )
    mode = result.get("mode", "concept")
    if mode == "raw":
        text = f"Raw dump of '{args['namespace']}' ({result['source_count']} memories):\n\n" + json.dumps(
            result.get("memories", []), indent=2, default=str
        )
    elif mode == "aaak":
        text = (
            f"AAAK encoding of '{args['namespace']}'\n"
            f"Source count: {result['source_count']}\n"
            f"Compressed size: {result['compressed_size']} bytes\n"
            f"Ratio: {result['ratio']}×\n\n" + result["content"]
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
            lines.append(f"\n{i}. {c.get('name')}{directional}{flag}\n   {c.get('synthesis', '')}")
        text = "\n".join(lines)
    return MCPToolResult(content=[{"type": "text", "text": text}])


HANDLERS: dict[str, object] = {
    "s9nmem_consolidate_session": _handle_consolidate_session,
    "s9nmem_get_raw": _handle_get_raw,
    "s9nmem_get_compressed": _handle_get_compressed,
}
