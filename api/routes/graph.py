"""
S9N Memory Vault — Graph API Routes (F12)

Provides the Access Graph endpoint that returns pre-aggregated node/edge
data for the interactive Agent-Memory-Namespace graph visualization.

Endpoint:
  GET /api/v1/graph/access-map  — Returns graph data for the dashboard

Story: F12-US-003, F12-US-004
"""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.auth import require_auth, AuthContext
from backend.models.memory import Memory
from backend.models.agent import AgentRegistry as Agent

router = APIRouter(prefix="/api/v1/graph", tags=["Graph"])


# ─── Response Schemas ────────────────────────────────────────────────────────

class GraphNode(BaseModel):
    """A node in the access graph."""
    id: str
    type: str          # "agent" | "namespace" | "memory"
    label: str
    # Optional extra data per node type
    status: str | None = None           # agent status
    compression_tier: str | None = None  # memory compression tier
    namespace: str | None = None         # memory's namespace
    memory_count: int | None = None      # namespace memory count
    total_reads: int | None = None       # agent reads
    total_writes: int | None = None      # agent writes
    denied_requests: int | None = None   # agent denied


class GraphEdge(BaseModel):
    """A directed edge in the access graph."""
    source: str   # node id
    target: str   # node id
    relation: str  # "writes_to" | "reads_from" | "synthesized_from" | "in_namespace"


class AccessMapResponse(BaseModel):
    """Full graph payload for the Access Graph page."""
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    total_agents: int
    total_namespaces: int
    total_memories: int


# ─── Route ───────────────────────────────────────────────────────────────────

@router.get(
    "/access-map",
    response_model=AccessMapResponse,
    summary="Get agent-memory-namespace access graph",
)
async def get_access_map(
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
) -> AccessMapResponse:
    """
    Returns a graph data structure showing relationships between:
    - Agents (who wrote/read memories)
    - Namespaces (memory compartments)
    - Memories (individual records, sampled for large datasets)

    Edges represent:
    - Agent → Namespace (writes_to / reads_from based on source_agent_id)
    - Memory → Namespace (in_namespace)
    - Memory → Memory (synthesized_from, for L3.1 concepts)

    The graph is scoped to the authenticated user's memories.
    For large vaults, memories are sampled (max 200 per namespace).
    """
    user_id = auth.user_id

    # ── 1. Fetch all active memories for this user ────────────────
    mem_result = await db.execute(
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.invalid_at == None,  # noqa: E711  active only
        )
        .order_by(Memory.created_at.desc())
        .limit(500)  # Safety cap — graph becomes unreadable beyond ~500 nodes
    )
    memories = mem_result.scalars().all()

    # ── 2. Fetch all agents (platform-level, not scoped to user) ──
    agent_result = await db.execute(
        select(Agent).where(Agent.status != "revoked").limit(100)
    )
    agents = agent_result.scalars().all()

    # ── 3. Build namespace summary ─────────────────────────────────
    ns_counts: dict[str, int] = {}
    for m in memories:
        ns_counts[m.namespace] = ns_counts.get(m.namespace, 0) + 1

    # ── 4. Assemble nodes ─────────────────────────────────────────
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # Agent nodes
    agent_ids_in_graph: set[str] = set()
    for agent in agents:
        aid = str(agent.agent_id)
        nodes.append(GraphNode(
            id=f"agent:{aid}",
            type="agent",
            label=agent.agent_name,
            status=agent.status,
            total_reads=agent.total_reads,
            total_writes=agent.total_writes,
            denied_requests=agent.denied_requests,
        ))
        agent_ids_in_graph.add(aid)

    # Namespace nodes
    for ns, count in ns_counts.items():
        nodes.append(GraphNode(
            id=f"ns:{ns}",
            type="namespace",
            label=ns,
            memory_count=count,
        ))

    # Memory nodes (sampled — max 200 total to keep graph readable)
    memory_sample = memories[:200]
    for mem in memory_sample:
        meta = mem.meta or {}
        tier = meta.get("_compression_tier", "L1")
        if tier not in {"L1", "L2", "L3.1"}:
            tier = "L1"
        nodes.append(GraphNode(
            id=f"mem:{mem.memory_id}",
            type="memory",
            label=mem.content[:60] + ("…" if len(mem.content) > 60 else ""),
            compression_tier=tier,
            namespace=mem.namespace,
        ))
        # Memory → Namespace edge
        edges.append(GraphEdge(
            source=f"mem:{mem.memory_id}",
            target=f"ns:{mem.namespace}",
            relation="in_namespace",
        ))
        # Agent → Namespace edge (if we know the source agent)
        if mem.source_agent_id:
            aid = str(mem.source_agent_id)
            # Only add edge if agent is in our graph
            if aid in agent_ids_in_graph:
                edges.append(GraphEdge(
                    source=f"agent:{aid}",
                    target=f"ns:{mem.namespace}",
                    relation="writes_to",
                ))
        # L3.1 provenance edges: Memory → source memories
        source_ids = meta.get("_source_memory_ids")
        if isinstance(source_ids, list):
            for src_id in source_ids[:5]:  # cap at 5 edges per concept
                edges.append(GraphEdge(
                    source=f"mem:{mem.memory_id}",
                    target=f"mem:{src_id}",
                    relation="synthesized_from",
                ))

    # Deduplicate edges (same source/target/relation can appear multiple times)
    seen_edges: set[tuple] = set()
    unique_edges: list[GraphEdge] = []
    for edge in edges:
        key = (edge.source, edge.target, edge.relation)
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append(edge)

    return AccessMapResponse(
        nodes=nodes,
        edges=unique_edges,
        total_agents=len(agents),
        total_namespaces=len(ns_counts),
        total_memories=len(memories),
    )
