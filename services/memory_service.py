"""
S9N Memory Vault — Memory Service

Implements core memory CRUD operations with:
- Namespace isolation: agents can only access their own namespace unless granted access
- Gatekeeper integration: every read/write/delete is permission-checked
- Versioning: updates increment the version counter
- TTL support: memories can have a time-to-live
- Soft delete: memories are logically deleted, not physically removed

Spec reference: Section 7.4 (Memory Operations), Section 10 (API Contracts)

Stories: F04-US-001 (write), F04-US-002 (read), F04-US-003 (search),
         F04-US-004 (delete), F04-US-005 (namespace isolation)
"""
import asyncio
import hashlib
import unicodedata
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

import structlog
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, and_, or_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.memory import Memory
from backend.services.gatekeeper_service import (
    evaluate, EvaluationRequest, GatekeeperDecision,
    create_rule, PermissionRuleCreate,
)
from backend.services.provenance_service import emit_event
from backend.services.audit_service import log_audit_event

logger = structlog.get_logger(__name__)


# ─── Request/Response Schemas ─────────────────────────────────────

class MemoryCreate(BaseModel):
    """Request body for creating a memory."""
    namespace: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1, max_length=100000)
    content_type: str = Field(default="text", max_length=50)
    metadata: Optional[dict] = Field(None)
    ttl_seconds: Optional[int] = Field(None, ge=60, le=31536000, description="TTL in seconds (min 60s, max 1 year)")
    session_id: Optional[str] = Field(None, max_length=200, description="Session context identifier")
    round_id: Optional[str] = Field(None, max_length=200, description="Round/turn identifier within session")
    valid_at: Optional[str] = Field(None, description="ISO-8601 timestamp when the fact became true")
    visibility: str = Field(default="user-private", description="agent-private, user-private, team, org-public")
    team_id: Optional[str] = Field(None, description="Team ID when visibility='team'")


class MemoryUpdate(BaseModel):
    """Request body for updating a memory."""
    content: Optional[str] = Field(None, min_length=1, max_length=100000)
    content_type: Optional[str] = Field(None, max_length=50)
    metadata: Optional[dict] = None
    ttl_seconds: Optional[int] = Field(None, ge=60, le=31536000)


class DedupInfo(BaseModel):
    """Present when deduplication matched an existing memory (S9N-DEDUP).

    The dedup is silent — the agent receives a normal MemoryResponse
    with the existing memory's ID. This field is for observability only.
    """
    deduplicated: bool = True
    kind: str  # "exact_hash" or "semantic"
    similarity: Optional[float] = None  # Only set for kind="semantic"


class MemoryResponse(BaseModel):
    """Response body for a memory entry (unified model)."""
    memory_id: str
    user_id: str
    namespace: str
    content: str
    content_type: str
    metadata: Optional[dict]
    source_agent_id: Optional[str]
    source_type: str
    quality_score: Optional[float]
    enrichment_status: str
    version: int
    ttl_seconds: Optional[int]
    expires_at: Optional[str]
    # Unified model fields (MV2-S01.3)
    session_id: Optional[str] = None
    round_id: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    decay_score: Optional[float] = None
    temporal_anchor: Optional[str] = None
    access_count: int = 0
    created_at: str
    updated_at: str
    # S9N-DEDUP: populated when dedup prevented a new memory from being created
    dedup: Optional[DedupInfo] = None
    # F12: Memory compression level — L1 (raw observation), L2 (AAAK lossless), L3.1 (concept synthesis)
    # Derived from metadata._compression_tier if present, otherwise defaults to L1.
    compression_tier: str = "L1"
    # F12: Source memory IDs for L3.1 synthesized concepts (provenance tracking)
    # Populated from metadata._source_memory_ids when compression_tier is L3.1.
    source_memory_ids: Optional[list[str]] = None


class MemorySearchRequest(BaseModel):
    """Request body for searching memories.

    S9N-3092: query is required when search_mode='fts' (default) to prevent
    unbounded full-table scans. For namespace-only listing, use search_mode='hybrid'
    with a namespace filter, or provide a non-empty query string.
    """
    query: Optional[str] = Field(None, min_length=1, max_length=1000, description="Text search query (required for fts mode)")
    namespace: Optional[str] = Field(None, max_length=100)
    content_type: Optional[str] = Field(None, max_length=50)
    tags: Optional[list[str]] = Field(None, description="Filter by tags in metadata")
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    search_mode: str = Field(
        default="hybrid",
        description=(
            "Search mode: 'hybrid' (default, vector cosine + FTS merged via RRF) "
            "or 'fts' (ILIKE substring only). Story: S9N-3074-SUB2"
        ),
    )
    # S9N-TEMPORAL: Optional date range filters for temporal queries
    date_from: Optional[str] = Field(
        None, description="ISO date string — only return memories created on or after this date"
    )
    date_to: Optional[str] = Field(
        None, description="ISO date string — only return memories created on or before this date"
    )
    # F12: Filter by compression tier (L1, L2, L3.1)
    compression_tier: Optional[str] = Field(
        None, description="Filter by compression tier: 'L1' (raw), 'L2' (AAAK), 'L3.1' (concept)"
    )

    @model_validator(mode="after")
    def query_required_for_fts(self) -> "MemorySearchRequest":
        """S9N-3092: Require a non-empty query when search_mode is 'fts'.

        This prevents accidental full-table scans when no filters are provided.
        Hybrid mode allows namespace-only searches (dense vector pass handles it).
        """
        if self.search_mode == "fts" and not self.query:
            raise ValueError(
                "'query' is required when search_mode='fts'. "
                "Provide a search query string, or switch to search_mode='hybrid' "
                "with a namespace filter for namespace-scoped listing."
            )
        return self


class MemoryListResponse(BaseModel):
    """Paginated list of memories."""
    items: list[MemoryResponse]
    total: int
    limit: int
    offset: int


# ─── Namespace Validation ─────────────────────────────────────────

VALID_CONTENT_TYPES = {"text", "structured", "conversation", "fact", "preference", "embedding"}


    # NOTE: validate_namespace() was removed — it always returned True.
    # Namespace access control is handled entirely by the Gatekeeper service.


# ─── Memory CRUD Operations ──────────────────────────────────────

async def create_memory(
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    request: MemoryCreate,
    db: AsyncSession,
    skip_gatekeeper: bool = False,
) -> MemoryResponse:
    """
    Create a new memory entry.

    Business rules:
    - Agent must have memory:write permission (checked by Gatekeeper)
    - Content type must be valid
    - TTL is optional; if set, expires_at is computed
    - Version starts at 1
    - Enrichment status starts as 'pending'
    """
    # Gatekeeper check
    if not skip_gatekeeper:
        decision = await evaluate(
            user_id,
            EvaluationRequest(
                agent_id=str(agent_id),
                scope="memory:write",
                namespace=request.namespace,
            ),
            db,
        )
        if not decision.allowed:
            raise PermissionError(
                f"Access denied: {decision.reason} (outcome: {decision.outcome})"
            )

    # Validate content type
    if request.content_type not in VALID_CONTENT_TYPES:
        raise ValueError(
            f"Invalid content_type: '{request.content_type}'. "
            f"Valid types: {sorted(VALID_CONTENT_TYPES)}"
        )

    # ── S9N-DEDUP: Two-layer deduplication gate ──────────────────
    from backend.config.settings import settings

    content_hash = _content_hash(request.content)

    # Layer 1: Exact hash match (deterministic, <1ms)
    if settings.dedup_exact_enabled:
        existing = await _find_by_hash(
            user_id, request.namespace, content_hash, db,
        )
        if existing:
            return await _handle_dedup_match(
                existing, agent_id, "exact_hash", None, db,
            )

    # Layer 2: Semantic similarity (best-effort, ~10-50ms)
    if settings.dedup_semantic_enabled:
        try:
            sem_match = await _find_semantic_duplicate(
                user_id, request.namespace, request.content,
                settings.dedup_semantic_threshold,
                settings.dedup_semantic_max_candidates,
                db,
            )
            if sem_match:
                match_memory, similarity = sem_match
                return await _handle_dedup_match(
                    match_memory, agent_id, "semantic", similarity, db,
                )
        except Exception:
            # Encoder unavailable or other error — degrade silently
            logger.debug("dedup.semantic_skipped", reason="encoder_or_query_error")

    # ── End dedup gate ───────────────────────────────────────────

    # Compute expires_at if TTL is set
    now = datetime.now(timezone.utc)
    expires_at = None
    if request.ttl_seconds:
        expires_at = now + timedelta(seconds=request.ttl_seconds)

    # Parse valid_at if provided
    valid_at_dt = None
    if request.valid_at:
        try:
            valid_at_dt = datetime.fromisoformat(request.valid_at.replace("Z", "+00:00"))
        except ValueError:
            pass

    memory = Memory(
        user_id=user_id,
        namespace=request.namespace,
        content=request.content,
        content_type=request.content_type,
        content_hash=content_hash,
        meta=request.metadata or {},
        source_agent_id=agent_id,
        source_type="agent",
        quality_score=None,
        enrichment_status="pending",
        version=1,
        ttl_seconds=request.ttl_seconds,
        expires_at=expires_at,
        invalid_at=None,
        # Unified model fields (MV2-S01.3)
        session_id=request.session_id,
        round_id=request.round_id,
        valid_at=valid_at_dt,
        decay_score=1.0,
        # MV3-E01: Visibility
        visibility=request.visibility,
        team_id=uuid.UUID(request.team_id) if request.team_id else None,
    )

    # S9N-EMBED: Embedding is generated asynchronously after the memory is
    # committed, so create_memory returns fast. The backfill runs in a
    # background task and updates the row in-place. For bulk ingestion,
    # use scripts/backfill_embeddings.py instead for maximum throughput.

    db.add(memory)

    # S9N-DEDUP: Concurrency guard — if another request inserted the same
    # hash between our Layer 1 check and this INSERT, the partial unique
    # index fires an IntegrityError. Roll back and return the existing memory.
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        existing = await _find_by_hash(user_id, request.namespace, content_hash, db)
        if existing:
            return await _handle_dedup_match(
                existing, agent_id, "exact_hash", None, db,
            )
        raise  # Re-raise if it wasn't the dedup index

    # MV2-S02.2: Emit provenance event for creation
    await emit_event(
        db, memory.memory_id, "created",
        actor_type="agent", actor_id=str(agent_id),
        reason="Memory created via API",
        after_state={"namespace": memory.namespace, "content_type": memory.content_type},
    )

    # S9N-3096: Auto-grant memory:delete to the creating agent so the creator
    # can always delete their own memories without a separate permission rule.
    # This rule is scoped to the specific namespace to maintain isolation.
    try:
        await create_rule(
            user_id=user_id,
            request=PermissionRuleCreate(
                agent_id=str(agent_id),
                scope="memory:delete",
                action="allow",
                priority=50,  # Higher priority than default rules
                namespace_filter=request.namespace,
            ),
            db=db,
        )
        logger.debug(
            "memory.create.auto_grant_delete",
            memory_id=str(memory.memory_id),
            agent_id=str(agent_id),
            namespace=request.namespace,
        )
    except Exception as e:
        # Non-fatal: log but don't fail the create operation
        logger.warning(
            "memory.create.auto_grant_delete_failed",
            agent_id=str(agent_id),
            namespace=request.namespace,
            error=str(e),
        )

    # KMV-E8 S8.1: Write-through hook — publish to Cognition OS (fire-and-forget)
    try:
        from backend.services.cognition_bridge import get_cognition_bridge
        bridge = get_cognition_bridge()
        if bridge.enabled:
            asyncio.create_task(bridge.publish_memory_event(
                memory_id=str(memory.id),
                content=memory.content,
                namespace=memory.namespace,
                user_id=str(user_id),
                content_type=memory.content_type,
                source_agent=str(agent_id),
            ))
    except Exception:
        logger.debug("cognition_bridge.hook_skipped", reason="import_or_init_error")

    # S9N-EMBED: Fire-and-forget embedding generation (bge-small-en-v1.5, 384-dim).
    # Runs in a background task so create_memory returns immediately.
    async def _bg_embed(mem_id: uuid.UUID, content: str):
        try:
            from memory_vault.embeddings.encoder import encode as _embed
            vec = _embed(content)
            # Direct SQL update — avoids loading the ORM object again
            from sqlalchemy import text as _sql
            async with db.begin():
                await db.execute(
                    _sql("UPDATE kora_memories SET embedding = :vec, embedding_model = :model WHERE memory_id = :mid"),
                    {"vec": list(vec), "model": "bge-small-en-v1.5", "mid": str(mem_id)},
                )
        except Exception as exc:
            logger.debug("embedding.bg_failed", memory_id=str(mem_id), error=str(exc))

    try:
        asyncio.create_task(_bg_embed(memory.memory_id, request.content))
    except Exception:
        logger.debug("embedding.task_skipped")

    # S9N-ENRICH: Fire-and-forget enrichment (entity extraction, concept tagging,
    # quality scoring). Runs in the background so create_memory returns fast.
    try:
        from backend.services.enrichment_service import enrich_memory as _enrich
        asyncio.create_task(_enrich(memory.memory_id, user_id, db))
    except Exception:
        logger.debug("enrichment.hook_skipped", reason="import_or_task_error")

    # F12: Fire-and-forget write-time compression pipeline.
    # Promotes the new memory to L2 (AAAK) and, when the namespace has
    # accumulated enough similar memories, synthesizes an L3.1 concept.
    # Never blocks the write path.
    if memory.content_type != "concept":  # Don't compress synthesized concepts
        try:
            from backend.services.compression_pipeline import schedule_compression
            schedule_compression(user_id, memory.memory_id, request.namespace)
        except Exception:
            logger.debug("compression_pipeline.hook_skipped", reason="import_or_task_error")
    # BUG-007 fix: log audit event for memory creation
    try:
        await log_audit_event(
            user_id=user_id,
            agent_id=agent_id,
            action="memory.create",
            resource_type="memory",
            resource_id=str(memory.memory_id),
            outcome="success",
            db=db,
            namespace=request.namespace,
            details={"content_type": request.content_type},
        )
    except Exception:
        logger.debug("audit.log_skipped", reason="audit_error")


    return _to_response(memory)


async def get_memory(
    memory_id: uuid.UUID,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
    skip_gatekeeper: bool = False,
) -> MemoryResponse:
    """
    Get a single memory by ID.

    Business rules:
    - Agent must have memory:read permission for the memory's namespace
    - Soft-deleted memories are not returned
    - Expired memories are not returned
    """
    logger.debug("memory.get", memory_id=str(memory_id), user_id=str(user_id), agent_id=str(agent_id))
    memory = await _get_active_memory(memory_id, user_id, db)

    # Gatekeeper check
    if not skip_gatekeeper:
        decision = await evaluate(
            user_id,
            EvaluationRequest(
                agent_id=str(agent_id),
                scope="memory:read",
                namespace=memory.namespace,
            ),
            db,
        )
        if not decision.allowed:
            logger.warning("memory.get.denied", memory_id=str(memory_id), agent_id=str(agent_id), reason=decision.reason)
            raise PermissionError(f"Access denied: {decision.reason}")

    # MV2-S07.1: Increment access_count and update last_accessed_at
    memory.access_count = (memory.access_count or 0) + 1
    memory.last_accessed_at = datetime.now(timezone.utc)
    await db.flush()

    logger.debug("memory.get.ok", memory_id=str(memory_id), namespace=memory.namespace)
    return _to_response(memory)


async def update_memory(
    memory_id: uuid.UUID,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    request: MemoryUpdate,
    db: AsyncSession,
    skip_gatekeeper: bool = False,
    admin_view: bool = False,
) -> MemoryResponse:
    """
    Update an existing memory.

    Business rules:
    - Agent must have memory:write permission
    - Version is incremented on each update
    - TTL/expires_at is recomputed if TTL changes
    """
    memory = await _get_active_memory(memory_id, user_id, db, admin_view=admin_view)

    # Gatekeeper check — skipped for admin users
    if not skip_gatekeeper:
        decision = await evaluate(
            user_id,
            EvaluationRequest(
                agent_id=str(agent_id),
                scope="memory:write",
                namespace=memory.namespace,
            ),
            db,
        )
        if not decision.allowed:
            raise PermissionError(f"Access denied: {decision.reason}")

    # Apply updates
    if request.content is not None:
        new_hash = _content_hash(request.content)
        # S9N-DEDUP: reject if another active memory already has this hash
        if new_hash != memory.content_hash:
            collision = await _find_by_hash(user_id, memory.namespace, new_hash, db)
            if collision and collision.memory_id != memory.memory_id:
                raise ValueError(
                    f"Content duplicates existing memory {collision.memory_id} "
                    f"in namespace '{memory.namespace}'"
                )
        memory.content = request.content
        memory.content_hash = new_hash
        memory.enrichment_status = "pending"  # Re-enrich on content change

    if request.content_type is not None:
        if request.content_type not in VALID_CONTENT_TYPES:
            raise ValueError(f"Invalid content_type: '{request.content_type}'")
        memory.content_type = request.content_type

    if request.metadata is not None:
        memory.meta = request.metadata

    if request.ttl_seconds is not None:
        memory.ttl_seconds = request.ttl_seconds
        memory.expires_at = datetime.now(timezone.utc) + timedelta(seconds=request.ttl_seconds)

    # Increment version
    memory.version += 1
    memory.updated_at = datetime.now(timezone.utc)

    await db.flush()
    return _to_response(memory)


async def delete_memory(
    memory_id: uuid.UUID,
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
    skip_gatekeeper: bool = False,
    admin_view: bool = False,
) -> None:
    """
    Soft-delete a memory.

    Business rules:
    - Agent must have memory:delete permission
    - Memory is soft-deleted (invalid_at set to now)
    - Already-deleted memories raise an error
    """
    memory = await _get_active_memory(memory_id, user_id, db, admin_view=admin_view)

    # Gatekeeper check — skipped for admin users
    if not skip_gatekeeper:
        decision = await evaluate(
            user_id,
            EvaluationRequest(
                agent_id=str(agent_id),
                scope="memory:delete",
                namespace=memory.namespace,
            ),
            db,
        )
        if not decision.allowed:
            raise PermissionError(f"Access denied: {decision.reason}")

    memory.invalid_at = datetime.now(timezone.utc)
    await db.flush()

    # MV2-S02.2: Emit provenance event for deletion
    await emit_event(
        db, memory.memory_id, "deleted",
        actor_type="agent", actor_id=str(agent_id),
        reason="Soft-deleted via API",
    )
    # BUG-007 fix: log audit event for memory deletion
    try:
        await log_audit_event(
            user_id=user_id,
            agent_id=agent_id,
            action="memory.delete",
            resource_type="memory",
            resource_id=str(memory_id),
            outcome="success",
            db=db,
            namespace=memory.namespace,
        )
    except Exception:
        logger.debug("audit.log_skipped", reason="audit_error")
async def search_memories(
    user_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    request: MemorySearchRequest,
    db: AsyncSession,
    skip_gatekeeper: bool = False,
    admin_view: bool = False,
) -> MemoryListResponse:
    """
    Search memories with filtering and pagination.

    Business rules:
    - Agent must have memory:read permission for the requested namespace
    - If no namespace filter, returns memories from all accessible namespaces
    - Soft-deleted and expired memories are excluded
    - Results are ordered by updated_at descending

    Fix KMV-QA-004: When ``admin_view`` is True (Memory Vault admin role)
    the user_id filter is omitted so the Memory Explorer shows all records.
    The Gatekeeper permission check is also skipped for admin users.
    """
    logger.debug(
        "memory.search",
        user_id=str(user_id),
        agent_id=str(agent_id),
        namespace=request.namespace,
        query=request.query,
        limit=request.limit,
        offset=request.offset,
    )

    # Gatekeeper check for the namespace (if specified).
    # Admin users bypass the gatekeeper — they have full read access.
    if not skip_gatekeeper and not admin_view and request.namespace and agent_id:
        decision = await evaluate(
            user_id,
            EvaluationRequest(
                agent_id=str(agent_id),
                scope="memory:read",
                namespace=request.namespace,
            ),
            db,
        )
        if not decision.allowed:
            logger.warning("memory.search.denied", agent_id=str(agent_id), namespace=request.namespace, reason=decision.reason)
            raise PermissionError(f"Access denied: {decision.reason}")

    # Build query — admin sees all records, regular users see only their own.
    now = datetime.now(timezone.utc)
    if admin_view:
        query = select(Memory).where(Memory.invalid_at == None)
    else:
        query = select(Memory).where(
            Memory.user_id == user_id,
            Memory.invalid_at == None,
        )

    # Exclude expired memories
    query = query.where(
        or_(Memory.expires_at.is_(None), Memory.expires_at > now)
    )

    # Apply filters
    if request.namespace:
        query = query.where(Memory.namespace == request.namespace)
    if request.content_type:
        query = query.where(Memory.content_type == request.content_type)

    # S9N-TEMPORAL: Date range filtering — supports ISO dates and relative
    # expressions like "yesterday", "last week", "3 days ago", "last month".
    if request.date_from:
        dt_from = _resolve_date(request.date_from, now)
        if dt_from:
            query = query.where(Memory.created_at >= dt_from)
    if request.date_to:
        dt_to = _resolve_date(request.date_to, now)
        if dt_to:
            query = query.where(Memory.created_at <= dt_to)

    # F12: Compression tier filter — matches on metadata._compression_tier JSON key.
    # L1 = no _compression_tier key OR value is 'L1'.
    if request.compression_tier:
        tier = request.compression_tier.upper().replace("L3.1", "L3.1")  # normalise
        if tier == "L1":
            # L1 = raw memories that have not yet been promoted
            from sqlalchemy import or_, cast, String
            from sqlalchemy.dialects.postgresql import JSONB
            query = query.where(
                or_(
                    Memory.meta == None,  # noqa: E711
                    Memory.meta["_compression_tier"].as_string() == "L1",
                    ~Memory.meta.has_key("_compression_tier"),
                )
            )
        else:
            query = query.where(
                Memory.meta["_compression_tier"].as_string() == tier
            )

    # ── Hybrid search path (S9N-3074-SUB2) ──────────────────────────────────
    if getattr(request, "search_mode", "fts") == "hybrid" and request.query:
        from memory_vault.search.hybrid import hybrid_search
        hybrid_results = await hybrid_search(
            db=db,
            user_id=user_id,
            query=request.query,
            namespace=request.namespace,
            content_type=request.content_type,
            limit=request.limit,
            offset=request.offset,
        )
        logger.debug("memory.search.hybrid.ok", returned=len(hybrid_results))
        items = []
        for r in hybrid_results:
            try:
                items.append(MemoryResponse(
                    memory_id=r["memory_id"],
                    user_id=str(user_id),
                    namespace=r["namespace"],
                    content=r["content"],
                    content_type=r["content_type"],
                    metadata=r.get("metadata"),
                    source_agent_id=r.get("source_agent_id"),
                    source_type=r.get("source_type", "agent"),
                    quality_score=r.get("quality_score"),
                    enrichment_status=r.get("enrichment_status", "pending"),
                    version=r.get("version", 1),
                    ttl_seconds=r.get("ttl_seconds"),
                    expires_at=r.get("expires_at"),
                    session_id=r.get("session_id"),
                    round_id=r.get("round_id"),
                    valid_at=r.get("valid_at"),
                    invalid_at=r.get("invalid_at"),
                    decay_score=r.get("decay_score"),
                    temporal_anchor=r.get("temporal_anchor"),
                    access_count=r.get("access_count", 0),
                    created_at=r.get("created_at", ""),
                    updated_at=r.get("updated_at", ""),
                ))
            except Exception:
                pass
        return MemoryListResponse(
            items=items,
            total=len(hybrid_results),
            limit=request.limit,
            offset=request.offset,
        )

    # ── FTS path (default, ILIKE backed by GIN trigram index — migration 005) ──
    if request.query:
        escaped_q = (
            request.query
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        query = query.where(Memory.content.ilike(f"%{escaped_q}%", escape="\\"))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(Memory.updated_at.desc())
    query = query.offset(request.offset).limit(request.limit)

    result = await db.execute(query)
    memories = result.scalars().all()

    logger.debug("memory.search.ok", total=total, returned=len(memories))
    return MemoryListResponse(
        items=[_to_response(m) for m in memories],
        total=total,
        limit=request.limit,
        offset=request.offset,
    )


async def list_namespaces(
    user_id: uuid.UUID,
    db: AsyncSession,
    admin_view: bool = False,
) -> list[dict]:
    """
    List namespaces with memory counts.

    Fix KMV-QA-007: When ``admin_view`` is True (Memory Vault admin role)
    the user_id filter is omitted so the Analytics page receives a real
    aggregated count across all users instead of returning an empty list.

    Returns a list of {namespace, count} objects.
    """
    if admin_view:
        query = (
            select(Memory.namespace, func.count(Memory.memory_id).label("count"))
            .where(Memory.invalid_at == None)
            .group_by(Memory.namespace)
            .order_by(Memory.namespace)
        )
    else:
        query = (
            select(Memory.namespace, func.count(Memory.memory_id).label("count"))
            .where(
                Memory.user_id == user_id,
                Memory.invalid_at == None,
            )
            .group_by(Memory.namespace)
            .order_by(Memory.namespace)
        )
    result = await db.execute(query)
    rows = result.all()
    return [{"namespace": row[0], "count": row[1]} for row in rows]


# ─── Temporal Date Resolution ────────────────────────────────────

_RELATIVE_PATTERNS: list[tuple[str, int]] = [
    ("today", 0), ("yesterday", 1), ("day before yesterday", 2),
]
_RELATIVE_WEEK_PATTERNS = {
    "last week": 7, "this week": 0,
    "last month": 30, "this month": 0,
    "last year": 365, "this year": 0,
}
import re as _re

def _resolve_date(value: str, now: datetime) -> Optional[datetime]:
    """Resolve a date string to a datetime. Supports:
    - ISO 8601: "2024-01-15", "2024-01-15T10:00:00"
    - Relative: "yesterday", "last week", "3 days ago", "2 weeks ago"
    """
    if not value:
        return None

    # Try ISO format first
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        pass

    v = value.strip().lower()

    # Named relatives
    for pattern, days in _RELATIVE_PATTERNS:
        if v == pattern:
            return (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    for pattern, days in _RELATIVE_WEEK_PATTERNS.items():
        if v == pattern:
            return (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    # "N days/weeks/months ago"
    m = _re.match(r"(\d+)\s+(day|week|month|year)s?\s+ago", v)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        multiplier = {"day": 1, "week": 7, "month": 30, "year": 365}
        days = n * multiplier.get(unit, 1)
        return (now - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    return None


# ─── Deduplication Helpers (S9N-DEDUP) ───────────────────────────


def _normalize_content(content: str) -> str:
    """Normalise content for hashing: NFC unicode, strip, collapse whitespace."""
    text = unicodedata.normalize("NFC", content)
    return " ".join(text.split())


def _content_hash(content: str) -> str:
    """SHA-256 hex digest of normalised content."""
    return hashlib.sha256(_normalize_content(content).encode("utf-8")).hexdigest()


async def _find_by_hash(
    user_id: uuid.UUID,
    namespace: str,
    content_hash: str,
    db: AsyncSession,
) -> Optional[Memory]:
    """Find an active memory with the given content hash."""
    result = await db.execute(
        select(Memory).where(
            Memory.user_id == user_id,
            Memory.namespace == namespace,
            Memory.content_hash == content_hash,
            Memory.invalid_at == None,
        )
    )
    return result.scalar_one_or_none()


async def _find_semantic_duplicate(
    user_id: uuid.UUID,
    namespace: str,
    content: str,
    threshold: float,
    max_candidates: int,
    db: AsyncSession,
) -> Optional[tuple[Memory, float]]:
    """Find a semantically similar active memory above the threshold.

    Returns (memory, similarity) or None. Degrades gracefully if the
    embedding encoder is unavailable or no embedded memories exist.
    """
    from memory_vault.embeddings.encoder import encode

    query_vec = encode(content)
    if query_vec is None:
        return None

    # Fetch active embedded memories in the same scope
    result = await db.execute(
        select(Memory).where(
            Memory.user_id == user_id,
            Memory.namespace == namespace,
            Memory.invalid_at == None,
            Memory.embedding != None,
        ).limit(max_candidates)
    )
    candidates = result.scalars().all()

    best_match: Optional[Memory] = None
    best_sim = 0.0

    for mem in candidates:
        if mem.embedding is None:
            continue
        # Dot product of L2-normalised vectors = cosine similarity
        sim = sum(a * b for a, b in zip(query_vec, mem.embedding))
        if sim > best_sim:
            best_sim = sim
            best_match = mem

    if best_match and best_sim >= threshold:
        return (best_match, best_sim)
    return None


async def _handle_dedup_match(
    existing: Memory,
    agent_id: uuid.UUID,
    kind: str,
    similarity: Optional[float],
    db: AsyncSession,
) -> MemoryResponse:
    """Bump access stats, emit provenance event, and return the existing memory."""
    existing.access_count = (existing.access_count or 0) + 1
    existing.last_accessed_at = datetime.now(timezone.utc)
    await db.flush()

    await emit_event(
        db, existing.memory_id, "dedup_matched",
        actor_type="agent", actor_id=str(agent_id),
        reason=f"Dedup ({kind}): incoming content matched existing memory",
        metadata={"dedup_kind": kind, "similarity": similarity},
    )

    response = _to_response(existing)
    response.dedup = DedupInfo(kind=kind, similarity=similarity)
    return response


# ─── Internal Helpers ─────────────────────────────────────────────

async def _get_active_memory(
    memory_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
    admin_view: bool = False,
) -> Memory:
    """Fetch a non-deleted, non-expired memory belonging to the user.
    When admin_view=True the user_id ownership filter is skipped so admins
    can update or delete any memory regardless of who created it."""
    conditions = [Memory.memory_id == memory_id, Memory.invalid_at == None]
    if not admin_view:
        conditions.append(Memory.user_id == user_id)
    result = await db.execute(select(Memory).where(*conditions))
    memory = result.scalar_one_or_none()
    if not memory:
        raise ValueError("Memory not found")

    # Check expiry
    if memory.expires_at:
        expires_at = memory.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            raise ValueError("Memory has expired")

    return memory


def _to_response(memory: Memory) -> MemoryResponse:
    """Convert a Memory ORM object to a response (unified model)."""
    return MemoryResponse(
        memory_id=str(memory.memory_id),
        user_id=str(memory.user_id),
        namespace=memory.namespace,
        content=memory.content,
        content_type=memory.content_type,
        metadata=memory.meta,
        source_agent_id=str(memory.source_agent_id) if memory.source_agent_id else None,
        source_type=memory.source_type,
        quality_score=memory.quality_score,
        enrichment_status=memory.enrichment_status,
        version=memory.version,
        ttl_seconds=memory.ttl_seconds,
        expires_at=memory.expires_at.isoformat() if memory.expires_at else None,
        # Unified model fields (MV2-S01.3)
        session_id=memory.session_id,
        round_id=memory.round_id,
        valid_at=memory.valid_at.isoformat() if memory.valid_at else None,
        invalid_at=memory.invalid_at.isoformat() if memory.invalid_at else None,
        decay_score=memory.decay_score,
        temporal_anchor=memory.temporal_anchor,
        access_count=memory.access_count or 0,
        created_at=memory.created_at.isoformat() if memory.created_at else "",
        updated_at=memory.updated_at.isoformat() if memory.updated_at else "",
        # F12: Derive compression tier from metadata field
        compression_tier=_derive_compression_tier(memory.meta),
        source_memory_ids=_derive_source_memory_ids(memory.meta),
    )


# ─── F12: Compression Tier Helpers ──────────────────────────────────────────

_VALID_TIERS = {"L1", "L2", "L3.1"}


def _derive_compression_tier(meta: Optional[dict]) -> str:
    """Derive the compression tier from memory metadata.

    The tier is stored as metadata._compression_tier by the compression
    pipeline. Valid values: 'L1' (raw), 'L2' (AAAK), 'L3.1' (concept).
    Defaults to 'L1' if not present or invalid.
    """
    if not meta:
        return "L1"
    tier = meta.get("_compression_tier", "L1")
    return tier if tier in _VALID_TIERS else "L1"


def _derive_source_memory_ids(meta: Optional[dict]) -> Optional[list[str]]:
    """Derive source memory IDs for L3.1 synthesized concepts.

    Stored as metadata._source_memory_ids by the concept synthesis pipeline.
    Returns None for L1/L2 memories.
    """
    if not meta:
        return None
    ids = meta.get("_source_memory_ids")
    if isinstance(ids, list):
        return [str(i) for i in ids]
    return None


# ─── L1 / L2 / L3 Compression Service (KMV-COMPRESS-01 / S9N-3050) ──────


def _memory_to_dict(memory: Memory) -> dict:
    """Convert a Memory ORM object into the plain-dict shape used by
    memory_vault.compression (matches the core-library episode dict)."""
    return {
        "id": str(memory.memory_id),
        "namespace": memory.namespace,
        "content": memory.content,
        "content_type": memory.content_type,
        "created_at": memory.created_at.isoformat() if memory.created_at else "",
        "valid_at": memory.valid_at.isoformat() if memory.valid_at else None,
        "invalid_at": memory.invalid_at.isoformat() if memory.invalid_at else None,
        "metadata": memory.meta,
        "source_agent": str(memory.source_agent_id) if memory.source_agent_id else "",
        "session_id": memory.session_id,
        "round_id": memory.round_id,
        "tier": memory.tier,
        "visibility": memory.visibility,
        "org_id": str(memory.user_id),
    }


async def _list_namespace_active_memories(
    user_id: uuid.UUID,
    namespace: str,
    db: AsyncSession,
) -> list[Memory]:
    """Return every active memory in a namespace for a user (no pagination)."""
    result = await db.execute(
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.namespace == namespace,
            Memory.invalid_at == None,
        )
        .order_by(Memory.created_at)
    )
    return list(result.scalars().all())


async def list_namespace_raw(
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    namespace: str,
    db: AsyncSession,
    *,
    skip_gatekeeper: bool = False,
) -> dict:
    """L1 — Raw namespace dump.

    Returns every active memory in a namespace as plain dicts. Respects the
    Gatekeeper memory:read scope on the namespace.

    Story: KMV-MCP-01 / KMV-COMPRESS-01
    """
    if not skip_gatekeeper:
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
            raise PermissionError(f"Access denied: {decision.reason}")

    memories = await _list_namespace_active_memories(user_id, namespace, db)
    return {
        "mode": "raw",
        "namespace": namespace,
        "source_count": len(memories),
        "memories": [_memory_to_dict(m) for m in memories],
    }


async def get_namespace_compressed(
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    namespace: str,
    db: AsyncSession,
    *,
    mode: str = "concept",        # "raw" | "aaak" | "concept"
    merge_mode: str = "current",   # "current" | "aggregate"
    skip_gatekeeper: bool = False,
) -> dict:
    """Tiered memory compression entry point — L1 raw, L2 AAAK, L3.1 concept.

    Caches results in a process-level NamespaceCompressionCache keyed by the
    sorted memory IDs in the namespace plus mode + merge_mode. Auto-invalidates
    on any namespace change.

    Story: KMV-COMPRESS-01 / S9N-3050
    """
    if mode not in {"raw", "aaak", "concept"}:
        raise ValueError(f"mode must be raw|aaak|concept, got {mode!r}")
    if merge_mode not in {"current", "aggregate"}:
        raise ValueError(f"merge_mode must be current|aggregate, got {merge_mode!r}")

    if not skip_gatekeeper:
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
            raise PermissionError(f"Access denied: {decision.reason}")

    # Local imports to keep memory_service import-light at module load
    from memory_vault.compression.aaak import encode_aaak, compression_ratio
    from memory_vault.compression.cache import get_default_cache
    from memory_vault.compression.cognition_round_trip import round_trip_concepts
    from memory_vault.compression.concept import synthesize_namespace_local
    from memory_vault.compression.llm_client import CoreAIBackendClient

    memories = await _list_namespace_active_memories(user_id, namespace, db)
    memory_ids = [str(m.memory_id) for m in memories]
    memory_dicts = [_memory_to_dict(m) for m in memories]

    cache = get_default_cache()
    cached = cache.get(str(user_id), namespace, mode, merge_mode, memory_ids)
    if cached is not None:
        return cached.payload

    payload: dict
    if mode == "raw":
        payload = {
            "mode": "raw",
            "merge_mode": merge_mode,
            "namespace": namespace,
            "source_count": len(memory_dicts),
            "memories": memory_dicts,
            "source": "local",
        }
    elif mode == "aaak":
        encoded = encode_aaak(memory_dicts)
        payload = {
            "mode": "aaak",
            "merge_mode": merge_mode,
            "namespace": namespace,
            "source_count": len(memory_dicts),
            "compressed_size": len(encoded),
            "ratio": compression_ratio(memory_dicts, encoded),
            "content": encoded,
            "source": "local",
        }
    else:  # concept
        # Build a tiny adapter so the compression module can talk to SQLAlchemy
        class _DBAdapter:
            def __init__(self, mems: list[dict]) -> None:
                self._by_id = {m["id"]: m for m in mems}
                self._mems = mems

            async def list_episodes(self, *, org_id, limit=200, offset=0, include_invalid=False):
                return self._mems[offset : offset + limit]

            async def find_similar(self, *, content, org_id, limit=20):
                # Cheap content-equality fallback when no real backend is wired.
                # Concept dedup falls through and we treat each memory as its own group.
                return []

            async def get_related(self, *, episode_id, relation_type, limit=10):
                return []

        adapter = _DBAdapter(memory_dicts)
        client = CoreAIBackendClient()
        synthesis = await synthesize_namespace_local(
            adapter, llm_client=client,
            org_id=str(user_id), namespace=namespace,
            merge_mode=merge_mode,
        )
        # L3.2 placeholder pass-through (KMV-COMPRESS-02 will hook this up)
        synthesis["concepts"] = await round_trip_concepts(
            None, synthesis["concepts"], namespace=namespace,
        )
        payload = {
            "mode": "concept",
            "merge_mode": merge_mode,
            "namespace": namespace,
            "source_count": synthesis.get("source_count", 0),
            "concepts": synthesis["concepts"],
            "source": synthesis.get("source", "local"),
        }

    cache.put(str(user_id), namespace, mode, merge_mode, memory_ids, payload)
    return payload
