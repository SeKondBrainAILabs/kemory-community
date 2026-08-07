"""
backend/services/user_context_service.py
==========================================
User-level cross-namespace context aggregation.

get_user_context() aggregates consolidated_summary data across all
namespaces owned by a user, providing a single injectable context block
for agent session start.

depth="l3" (default): reads stored NamespacePolicy.consolidated_summary
    values — no LLM call, sub-100ms response.

depth="l4": l3 + one cross-namespace synthesis pass via Groq.
    Returns synthesis=None if Groq is unconfigured or unreachable.

The l4 synthesis is NOT stored automatically; callers decide whether to
persist it (e.g. as a memory in a 'user:model' namespace).

Story: KMV-CTX-01
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog

from backend.config.settings import settings

logger = structlog.get_logger(__name__)


async def get_user_context(
    user_id: uuid.UUID,
    db,  # AsyncSession — loose type avoids circular import at module load
    *,
    depth: str = "l3",
    namespaces_filter: list[str] | None = None,
) -> dict:
    """Aggregate namespace summaries for a user into a single context block.

    Calls list_namespaces(user_id, db) with no agent_id — this bypasses the
    Gatekeeper filter loop and returns all namespaces owned by the user,
    which is correct here: the user is requesting their own context.

    Args:
        user_id: Authenticated user's UUID.
        db: Active AsyncSession.
        depth: "l3" = stored summaries only. "l4" = add LLM synthesis pass.
        namespaces_filter: Optional list of namespace names to include.
            Default (None) = all namespaces.

    Returns dict with shape:
        {
            "user_id": str,
            "depth": str,
            "namespaces": [{"namespace", "summary", "tier", "memory_count", "updated_at"}, ...],
            "synthesis": str | None,
            "generated_at": ISO str,
        }
    """
    from backend.services.memory_service import list_namespaces

    all_ns = await list_namespaces(user_id, db)

    if namespaces_filter:
        ns_set = set(namespaces_filter)
        all_ns = [n for n in all_ns if n["namespace"] in ns_set]

    namespaces_out = [
        {
            "namespace": ns["namespace"],
            "summary": ns["consolidated_summary"],
            "tier": ns["consolidated_summary_tier"],
            "memory_count": ns["count"],
            "updated_at": ns["consolidated_summary_updated_at"],
        }
        for ns in all_ns
    ]

    synthesis: str | None = None
    if depth == "l4":
        synthesis = await _synthesize_l4(namespaces_out, user_id)

    return {
        "user_id": str(user_id),
        "depth": depth,
        "namespaces": namespaces_out,
        "synthesis": synthesis,
        "generated_at": datetime.now(UTC).isoformat(),
    }


async def _synthesize_l4(
    namespaces: list[dict],
    user_id: uuid.UUID,
) -> str | None:
    """One LLM synthesis pass across all non-null namespace summaries.

    Routes through the user-configured Groq endpoint. Returns None on any
    failure — graceful degradation, no exception propagated to caller.
    """
    from kemory.llm import assistant_text, chat_completion

    summaries = [n for n in namespaces if n.get("summary")]
    if not summaries:
        return None

    blocks = "\n\n".join(
        f"[{ns['namespace']}] (tier={ns['tier'] or 'none'}):\n{ns['summary']}" for ns in summaries
    )
    prompt = (
        "You are synthesizing a cross-namespace memory overview for a user.\n\n"
        "Below are summaries from different memory namespaces. Produce a coherent "
        "3-7 sentence synthesis describing the user's overall context, goals, and "
        "active projects. Rules:\n"
        "- Do NOT infer facts not present in the summaries.\n"
        "- Preserve specific names, projects, dates, and preferences.\n"
        "- Note connections between namespaces where clearly evident.\n"
        "- If namespaces appear to conflict, surface the tension rather than "
        "resolving it.\n\n"
        f"Namespace summaries:\n{blocks}\n\n"
        "Synthesis:"
    )

    payload = {
        "model": settings.kmv_synthesis_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 768,
    }
    try:
        return assistant_text(await chat_completion(payload, timeout_seconds=120.0))
    except Exception as exc:
        logger.warning(
            "user_context.l4.failed",
            error=str(exc),
            user_id=str(user_id),
        )
        return None
