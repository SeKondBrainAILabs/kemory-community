"""
Cross‑agent context — surfaces recent memories saved by *other* agents
in the same namespace, so the answering AI can compound on what
sibling AIs already noted.

Embedded in every `s9nmem_recall_memory` / `s9nmem_get_context` response.
The brief instructs the AI to mention these naturally when relevant.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.agent import AgentRegistry
from backend.models.memory import Memory

logger = structlog.get_logger(__name__)

# Conservative cap so the payload stays small (≈30 tokens per item).
DEFAULT_LIMIT = 5
SNIPPET_CHARS = 160


@dataclass
class CrossAgentItem:
    memory_id: str
    namespace: str
    agent_name: str
    content_snippet: str
    created_at: str

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "namespace": self.namespace,
            "agent": self.agent_name,
            "snippet": self.content_snippet,
            "at": self.created_at,
        }


async def get_cross_agent_context(
    *,
    user_id: uuid.UUID,
    current_agent_id: uuid.UUID | None,
    namespaces: Iterable[str],
    db: AsyncSession,
    limit: int = DEFAULT_LIMIT,
) -> list[CrossAgentItem]:
    """Return up to `limit` recent memories saved by other agents in the
    given namespaces.

    `current_agent_id` may be None (e.g. when the caller is a human via
    Bearer token, not an agent) — in that case all agent‑authored
    memories qualify.
    """
    ns_list = [n for n in namespaces if n]
    if not ns_list:
        return []

    stmt = (
        select(Memory, AgentRegistry.agent_name)
        .join(AgentRegistry, Memory.source_agent_id == AgentRegistry.agent_id, isouter=True)
        .where(Memory.user_id == user_id)
        .where(Memory.namespace.in_(ns_list))
        .where(Memory.source_agent_id.is_not(None))
    )
    if current_agent_id is not None:
        stmt = stmt.where(Memory.source_agent_id != current_agent_id)
    stmt = stmt.order_by(Memory.created_at.desc()).limit(limit)

    # Cross‑agent context is an enrichment, not load‑bearing — never let a
    # query error break the recall response the user actually asked for.
    items: list[CrossAgentItem] = []
    try:
        result = await db.execute(stmt)
        for memory, agent_name in result.all():
            content = memory.content or ""
            snippet = content[:SNIPPET_CHARS] + ("…" if len(content) > SNIPPET_CHARS else "")
            items.append(
                CrossAgentItem(
                    memory_id=str(memory.memory_id),
                    namespace=memory.namespace,
                    agent_name=agent_name or "unknown-agent",
                    content_snippet=snippet,
                    created_at=memory.created_at.isoformat() if memory.created_at else "",
                )
            )
    except Exception as exc:  # noqa: BLE001 — intentional broad guard
        logger.debug("cross_agent_context.skipped", reason=str(exc))
        return []
    return items


def format_cross_agent_section(items: list[CrossAgentItem]) -> str:
    """Render as a human‑readable section appended to the recall text."""
    if not items:
        return ""
    lines = ["", "=== Cross‑agent context (recent memories from other AIs in the same namespace) ==="]
    for item in items:
        when = item.created_at[:10] if item.created_at else ""
        lines.append(f"- [{when}] {item.agent_name} → {item.namespace}: {item.content_snippet}")
    return "\n".join(lines)
