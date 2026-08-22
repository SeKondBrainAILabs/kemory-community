"""MCP surface for Community Ask."""

from __future__ import annotations

from typing import Any

from backend.mcp.tools._base import MCPToolDefinition, MCPToolResult

ASK_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "answer": {"type": ["string", "null"]},
        "synthesized": {"type": "boolean"},
        "not_synthesized_reason": {"type": ["string", "null"]},
        "evidence": {"type": "array", "items": {"type": "object"}},
        "items": {"type": "array", "items": {"type": "object"}},
        "counts": {"type": "object"},
    },
    "required": ["query", "synthesized", "evidence", "items", "counts"],
}

DEFINITIONS = [
    MCPToolDefinition(
        name="s9nmem_ask",
        description=(
            "Ask a question of this local Kemory vault. Searches memories, captured chats, "
            "and inline text artifacts, then uses the configured Groq model to synthesize an "
            "answer grounded in the returned evidence. Retrieval items are always returned, "
            "including when Groq is not configured. Use recall_memory for raw memory-only "
            "retrieval without a model call."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Question to answer from local evidence."},
                "types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["memory", "chat", "file"]},
                    "description": "Optional local surfaces to search; defaults to all three.",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                "token_budget": {"type": "integer", "minimum": 500, "maximum": 32000},
                "synthesize": {"type": "boolean", "default": True},
            },
            "required": ["query"],
        },
        outputSchema=ASK_OUTPUT_SCHEMA,
    )
]


async def _handle_ask(args, user_id, agent_id, db):
    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        return MCPToolResult(
            content=[{"type": "text", "text": "Validation error: query is required."}],
            isError=True,
        )

    from backend.services.ask_service import AskRequest, ask

    result = await ask(
        db,
        user_id=user_id,
        agent_id=agent_id,
        request=AskRequest(
            query=query,
            types=args.get("types"),
            limit=args.get("limit", 10),
            token_budget=args.get("token_budget"),
            synthesize=args.get("synthesize", True),
        ),
    )
    payload = result.model_dump(mode="json")
    if result.synthesized and result.answer:
        text = result.answer
    elif result.items:
        text = (
            f"No synthesized answer ({result.not_synthesized_reason or 'unavailable'}). "
            f"Retrieved {len(result.items)} evidence item(s); inspect structuredContent."
        )
    else:
        text = "No local Kemory evidence matched the question."
    return MCPToolResult(
        content=[{"type": "text", "text": text}],
        structuredContent=payload,
    )


HANDLERS = {"s9nmem_ask": _handle_ask}
