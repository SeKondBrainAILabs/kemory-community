"""
S9N Memory Vault — Memory Service (HTTP layer).

This module is the REST-shaped layer. Its consumers are FastAPI route
handlers (``backend/api/routes/memories.py``) and the MCP tool dispatcher
(``backend/mcp/tools.py``). It speaks Pydantic request/response models,
calls the Gatekeeper for permission checks, and emits audit events.

It is intentionally distinct from ``memory_vault/service/memory_service.py``
which is the library-shaped layer (StorageBackend interface, dual-mode for
SQLite local and Postgres platform). The two services serve different
consumers and have different APIs by design.

The dedup-critical content-hash primitive lives in
``memory_vault/utils/text.py`` so both layers compute identical hashes
for the same content. Phase 2 of the consolidation work — delegating
backend storage calls through the library's StorageBackend interface —
is tracked as a follow-up to P0 #1 in the codebase review epic.

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
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.memory import Memory
from backend.services.audit_service import log_audit_event
from backend.services.gatekeeper_service import (
    EvaluationRequest,
    PermissionRuleCreate,
    create_rule,
    evaluate,
)
from backend.services.provenance_service import emit_event

# Canonical dedup primitives — both this layer and memory_vault.MemoryService
# import from here so writes via either path produce identical content_hashes.
# See memory_vault/utils/text.py for why. The _normalize_content alias is
# re-exported (not used directly here) so the cross-layer-equivalence test
# in tests/test_shared_text_utils.py can verify identity.
from memory_vault.utils.text import content_hash as _content_hash
from memory_vault.utils.text import normalize_content as _normalize_content  # noqa: F401

logger = structlog.get_logger(__name__)


# ─── Request/Response Schemas ─────────────────────────────────────


class MemoryCreate(BaseModel):
    """Request body for creating a memory."""

    namespace: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1, max_length=100000)
    content_type: str = Field(default="text", max_length=50)
    metadata: dict | None = Field(None)
    ttl_seconds: int | None = Field(
        None, ge=60, le=31536000, description="TTL in seconds (min 60s, max 1 year)"
    )
    session_id: str | None = Field(None, max_length=200, description="Session context identifier")
    round_id: str | None = Field(None, max_length=200, description="Round/turn identifier within session")
    valid_at: str | None = Field(None, description="ISO-8601 timestamp when the fact became true")
    visibility: str = Field(
        default="user-private", description="agent-private, user-private, team, org-public"
    )
    team_id: str | None = Field(None, description="Team ID when visibility='team'")
    namespace_description: str | None = Field(
        None,
        max_length=500,
        description=(
            "Optional description of the namespace; used by the matcher to detect "
            "related namespaces and persisted on NamespacePolicy."
        ),
    )
    allow_duplicate: bool = Field(
        default=False,
        description=(
            "If True, skip the related-namespace matcher and create the namespace "
            "as-requested even if similar ones exist."
        ),
    )


class MemoryUpdate(BaseModel):
    """Request body for updating a memory."""

    content: str | None = Field(None, min_length=1, max_length=100000)
    content_type: str | None = Field(None, max_length=50)
    metadata: dict | None = None
    ttl_seconds: int | None = Field(None, ge=60, le=31536000)


class DedupInfo(BaseModel):
    """Present when deduplication matched an existing memory (S9N-DEDUP).

    The dedup is silent — the agent receives a normal MemoryResponse
    with the existing memory's ID. This field is for observability only.
    """

    deduplicated: bool = True
    kind: str  # "exact_hash" or "semantic"
    similarity: float | None = None  # Only set for kind="semantic"


class MemoryResponse(BaseModel):
    """Response body for a memory entry (unified model)."""

    memory_id: str
    user_id: str
    namespace: str
    content: str
    content_type: str
    metadata: dict | None
    source_agent_id: str | None
    source_type: str
    quality_score: float | None
    enrichment_status: str
    version: int
    ttl_seconds: int | None
    expires_at: str | None
    # Unified model fields (MV2-S01.3)
    session_id: str | None = None
    round_id: str | None = None
    valid_at: str | None = None
    invalid_at: str | None = None
    decay_score: float | None = None
    temporal_anchor: str | None = None
    access_count: int = 0
    created_at: str
    updated_at: str
    # F12: Compression tier — L1 raw / L2 AAAK / L3.1 concept synthesis.
    # Pipeline stores it in meta["_compression_tier"]; we lift to the top
    # level so clients don't have to reach into metadata (and so TS types
    # line up with MemoryResponse.compression_tier).
    compression_tier: str = "L1"
    # S9N-DEDUP: populated when dedup prevented a new memory from being created
    dedup: DedupInfo | None = None
    # F12: Source memory IDs for L3.1 synthesized concepts (provenance tracking)
    # Populated from metadata._source_memory_ids when compression_tier is L3.1.
    source_memory_ids: list[str] | None = None
    # Populated when the namespace matcher AUTO_REDIRECTed the write to a
    # different namespace than the one requested. The caller can compare
    # `redirected_from` against the namespace they sent to detect a silent
    # merge — important for benchmarks and bulk-ingest tools that depend
    # on namespace isolation. Only set when the matcher actually changed
    # the target; absent (None) on REUSE-by-exact-match or CREATE_NEW.
    redirected_from: str | None = None


class MemorySearchRequest(BaseModel):
    """Request body for searching memories.

    S9N-3092: query is required when search_mode='fts' (default) to prevent
    unbounded full-table scans. For namespace-only listing, use search_mode='hybrid'
    with a namespace filter, or provide a non-empty query string.
    """

    query: str | None = Field(
        None, min_length=1, max_length=1000, description="Text search query (required for fts mode)"
    )
    namespace: str | None = Field(None, max_length=100)
    content_type: str | None = Field(None, max_length=50)
    tags: list[str] | None = Field(None, description="Filter by tags in metadata")
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
    date_from: str | None = Field(
        None, description="ISO date string — only return memories created on or after this date"
    )
    date_to: str | None = Field(
        None, description="ISO date string — only return memories created on or before this date"
    )
    # F12: Filter by memory compression tier (L1 raw / L2 AAAK / L3.1 concept).
    # Tier is stored in meta["_compression_tier"]; this filter is applied
    # client-side after the SQL pass so it works on both raw and hybrid paths.
    compression_tier: str | None = Field(
        None,
        description="Filter by memory compression tier: L1 / L2 / L3.1",
    )
    # KMV-S8.3: Graph-augmented recall — expand results via Cognition OS concept graph
    use_graph: bool = Field(
        default=False,
        description=(
            "When True, expand search results via Cognition OS concept graph traversal. "
            "Related entities are retrieved from the graph and merged with local vault results. "
            "Gracefully degrades to standard search if Cognition OS is unavailable. "
            "Story: KMV-S8.3"
        ),
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
    org_id: str | None = None,
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
            raise PermissionError(f"Access denied: {decision.reason} (outcome: {decision.outcome})")

    # Validate content type
    if request.content_type not in VALID_CONTENT_TYPES:
        raise ValueError(
            f"Invalid content_type: '{request.content_type}'. Valid types: {sorted(VALID_CONTENT_TYPES)}"
        )

    # ── Related-namespace matcher (pre-create) ───────────────────
    # Detect near-duplicate namespaces before we commit. >=0.90 ⇒ silent
    # redirect; 0.60..0.90 ⇒ raise RelatedNamespaceConflict so the router
    # returns 409 (unless allow_duplicate=True); <0.60 ⇒ create fresh and
    # eagerly seed a NamespacePolicy row so description/summary can attach.
    redirected_from: str | None = None
    if not request.allow_duplicate:
        try:
            from backend.services.namespace_matcher import (
                RelatedNamespaceConflict,
                ResolutionAction,
                apply_resolution,
                resolve_namespace,
            )

            resolution = await resolve_namespace(
                user_id,
                request.namespace,
                request.namespace_description,
                db,
            )
            if resolution.action == ResolutionAction.SUGGEST:
                raise RelatedNamespaceConflict(request.namespace, resolution.candidates)
            if resolution.action in (ResolutionAction.REUSE, ResolutionAction.AUTO_REDIRECT):
                # Capture the original requested namespace BEFORE rewriting
                # so the response can surface the silent redirect to the
                # caller. Only set for AUTO_REDIRECT (REUSE means the names
                # were identical after normalization, which isn't surprising).
                if (
                    resolution.action == ResolutionAction.AUTO_REDIRECT
                    and resolution.namespace != request.namespace
                ):
                    redirected_from = request.namespace
                # Rewrite the request to the existing namespace before dedup/write
                request = request.model_copy(update={"namespace": resolution.namespace})
                await apply_resolution(resolution, request.namespace_description, db, user_id)
            else:
                await apply_resolution(resolution, request.namespace_description, db, user_id)
        except RelatedNamespaceConflict:
            raise
        except Exception as exc:
            logger.debug("namespace_matcher.skipped", reason=str(exc))

    # ── S9N-DEDUP: Two-layer deduplication gate ──────────────────
    from backend.config.settings import settings

    content_hash = _content_hash(request.content)

    # Layer 1: Exact hash match (deterministic, <1ms)
    if settings.dedup_exact_enabled:
        existing = await _find_by_hash(
            user_id,
            request.namespace,
            content_hash,
            db,
        )
        if existing:
            return await _handle_dedup_match(
                existing,
                agent_id,
                "exact_hash",
                None,
                db,
            )

    # Layer 2: Semantic similarity (best-effort, ~10-50ms)
    if settings.dedup_semantic_enabled:
        try:
            sem_match = await _find_semantic_duplicate(
                user_id,
                request.namespace,
                request.content,
                settings.dedup_semantic_threshold,
                settings.dedup_semantic_max_candidates,
                db,
            )
            if sem_match:
                match_memory, similarity = sem_match
                return await _handle_dedup_match(
                    match_memory,
                    agent_id,
                    "semantic",
                    similarity,
                    db,
                )
        except Exception:
            # Encoder unavailable or other error — degrade silently
            logger.debug("dedup.semantic_skipped", reason="encoder_or_query_error")

    # ── End dedup gate ───────────────────────────────────────────

    # Compute expires_at if TTL is set
    now = datetime.now(UTC)
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

    # PR #17: org_id is NOT NULL on kemory_memories. Use the auth
    # context's org_id, falling back to the migration legacy sentinel
    # for callers that haven't been org-aware yet (MCP tools, internal
    # scripts).
    if not org_id:
        from backend.config.settings import settings as _settings

        org_id = _settings.tenant_legacy_sentinel

    memory = Memory(
        user_id=user_id,
        org_id=org_id,
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
                existing,
                agent_id,
                "exact_hash",
                None,
                db,
            )
        raise  # Re-raise if it wasn't the dedup index

    # MV2-S02.2: Emit provenance event for creation
    await emit_event(
        db,
        memory.memory_id,
        "created",
        actor_type="agent",
        actor_id=str(agent_id),
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
            org_id=org_id,
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
    # Cognition bridge is HTTP, no DB dependency, safe to schedule directly.
    try:
        from backend.services.cognition_bridge import get_cognition_bridge

        bridge = get_cognition_bridge()
        if bridge.enabled:
            asyncio.create_task(
                bridge.publish_memory_event(
                    memory_id=str(memory.memory_id),  # PK is memory_id, not id
                    content=memory.content,
                    namespace=memory.namespace,
                    user_id=str(user_id),
                    content_type=memory.content_type,
                    source_agent=str(agent_id),
                )
            )
    except Exception:
        logger.debug("cognition_bridge.hook_skipped", reason="import_or_init_error")

    # F14: Background tasks must NOT reuse the request-scoped `db` session —
    # FastAPI's Depends(get_db) closes it as soon as create_memory returns,
    # which means any later use throws InvalidRequestError silently and the
    # task fails. Each fire-and-forget task below opens its own session via
    # _get_session_factory(); that's the same pattern compression_pipeline
    # uses successfully today.
    from backend.core.database import _get_session_factory as _db_factory

    # S9N-EMBED: Fire-and-forget embedding generation (bge-small-en-v1.5, 384-dim).
    async def _bg_embed(mem_id: uuid.UUID, content: str) -> None:
        try:
            from sqlalchemy import text as _sql

            from memory_vault.embeddings.encoder import encode as _embed

            vec = _embed(content)
            async with _db_factory()() as own_db:
                async with own_db.begin():
                    await own_db.execute(
                        _sql(
                            "UPDATE kemory_memories "
                            "SET embedding = :vec, embedding_model = :model "
                            "WHERE memory_id = :mid"
                        ),
                        {
                            "vec": list(vec),
                            "model": "bge-small-en-v1.5",
                            "mid": str(mem_id),
                        },
                    )
        except Exception as exc:
            logger.warning(
                "embedding.bg_failed",
                memory_id=str(mem_id),
                error=str(exc),
            )

    try:
        asyncio.create_task(
            _bg_embed(memory.memory_id, request.content),
            name=f"embed:{memory.memory_id}",
        )
    except Exception:
        logger.debug("embedding.task_skipped")

    # S9N-ENRICH: Fire-and-forget enrichment (entity extraction, concept tagging,
    # quality scoring). Runs in the background so create_memory returns fast.
    # enrich_memory only flushes — we own the commit here; without it the
    # quality_score / enrichment_status / enrichment metadata get rolled back
    # when the session context exits.
    async def _bg_enrich(mem_id: uuid.UUID, uid: uuid.UUID) -> None:
        try:
            from backend.services.enrichment_service import enrich_memory as _enrich

            async with _db_factory()() as own_db:
                await _enrich(mem_id, uid, own_db)
                await own_db.commit()
        except Exception as exc:
            logger.warning(
                "enrichment.bg_failed",
                memory_id=str(mem_id),
                error=str(exc),
            )

    try:
        asyncio.create_task(
            _bg_enrich(memory.memory_id, user_id),
            name=f"enrich:{memory.memory_id}",
        )
    except Exception:
        logger.debug("enrichment.hook_skipped", reason="import_or_task_error")
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

    # F12: Fire-and-forget compression pipeline (L1→L2 AAAK, L3 Groq summary,
    # L3.1 CognitionOS concept synthesis) + namespace summary rollup.
    try:
        from backend.services.compression_pipeline import schedule_compression

        schedule_compression(user_id, memory.memory_id, request.namespace)
    except Exception:
        logger.debug("compression.hook_skipped", reason="import_or_task_error")

    response = _to_response(memory)
    if redirected_from is not None:
        response.redirected_from = redirected_from
        logger.info(
            "namespace_matcher.auto_redirect",
            requested=redirected_from,
            resolved_to=request.namespace,
            memory_id=str(memory.memory_id),
        )
    return response


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
            logger.warning(
                "memory.get.denied", memory_id=str(memory_id), agent_id=str(agent_id), reason=decision.reason
            )
            raise PermissionError(f"Access denied: {decision.reason}")

    # MV2-S07.1: Increment access_count and update last_accessed_at
    memory.access_count = (memory.access_count or 0) + 1
    memory.last_accessed_at = datetime.now(UTC)
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
        memory.expires_at = datetime.now(UTC) + timedelta(seconds=request.ttl_seconds)

    # Increment version
    memory.version += 1
    memory.updated_at = datetime.now(UTC)

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

    memory.invalid_at = datetime.now(UTC)
    await db.flush()

    # MV2-S02.2: Emit provenance event for deletion
    await emit_event(
        db,
        memory.memory_id,
        "deleted",
        actor_type="agent",
        actor_id=str(agent_id),
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
            logger.warning(
                "memory.search.denied",
                agent_id=str(agent_id),
                namespace=request.namespace,
                reason=decision.reason,
            )
            raise PermissionError(f"Access denied: {decision.reason}")

    # Build query — admin sees all records, regular users see only their own.
    now = datetime.now(UTC)
    if admin_view:
        query = select(Memory).where(Memory.invalid_at == None)
    else:
        query = select(Memory).where(
            Memory.user_id == user_id,
            Memory.invalid_at == None,
        )

    # Exclude expired memories
    query = query.where(or_(Memory.expires_at.is_(None), Memory.expires_at > now))

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

    # F12 compression_tier filter is applied client-side via _tier_from_meta()
    # after the SQL pass — keeps it consistent across both fts and hybrid paths.

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
                items.append(
                    MemoryResponse(
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
                        compression_tier=_tier_from_meta(r.get("metadata")),
                    )
                )
            except Exception:
                pass
        # KMV-S8.3: Graph-augmented recall for hybrid path
        if request.use_graph and request.query:
            graph_items = await _expand_with_graph(
                query=request.query,
                existing_ids={item.memory_id for item in items},
            )
            items = items + graph_items
            logger.debug(
                "memory.search.hybrid.graph_expanded",
                vault_count=len(items) - len(graph_items),
                graph_count=len(graph_items),
            )

        # F12: filter by compression tier after assembly so it applies to
        # both vault + graph items regardless of which SQL path ran.
        if request.compression_tier:
            items = [i for i in items if i.compression_tier == request.compression_tier]

        return MemoryListResponse(
            items=items,
            total=len(hybrid_results) + (len(items) - len(hybrid_results)),
            limit=request.limit,
            offset=request.offset,
        )

    # ── FTS path (default, ILIKE backed by GIN trigram index — migration 005) ──
    if request.query:
        escaped_q = request.query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
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

    vault_items = [_to_response(m) for m in memories]
    logger.debug("memory.search.ok", total=total, returned=len(vault_items))

    # KMV-S8.3: Graph-augmented recall — expand via Cognition OS concept graph
    if request.use_graph and request.query:
        graph_items = await _expand_with_graph(
            query=request.query,
            existing_ids={item.memory_id for item in vault_items},
        )
        vault_items = vault_items + graph_items
        logger.debug(
            "memory.search.graph_expanded",
            vault_count=len(vault_items) - len(graph_items),
            graph_count=len(graph_items),
        )

    # F12: filter by compression tier after assembly (FTS path).
    if request.compression_tier:
        vault_items = [i for i in vault_items if i.compression_tier == request.compression_tier]

    return MemoryListResponse(
        items=vault_items,
        total=total + (len(vault_items) - len(memories)),
        limit=request.limit,
        offset=request.offset,
    )


async def _expand_with_graph(
    query: str,
    existing_ids: set[str],
    top_k: int = 5,
) -> list["MemoryResponse"]:
    """
    KMV-S8.3: Expand a recall query via the Cognition OS concept graph.

    Calls CognitionBridge.expand_recall() to retrieve related entities from the
    knowledge graph that are semantically related to the query but may not appear
    verbatim in the local vault. Results are converted to synthetic MemoryResponse
    objects tagged with source='cognition_os' so callers can distinguish them.

    Gracefully returns an empty list if:
    - Cognition OS is not configured (bridge.enabled is False)
    - The network call fails or times out
    - The bridge circuit-breaker is open
    """
    try:
        from backend.services.cognition_bridge import get_cognition_bridge

        bridge = get_cognition_bridge()
        if not bridge.enabled:
            return []
        graph_results = await bridge.expand_recall(query=query, top_k=top_k)
    except Exception as exc:
        logger.debug("memory.search.graph_expand_failed", error=str(exc))
        return []

    now_str = datetime.now(timezone.utc).isoformat()
    items: list[MemoryResponse] = []
    for r in graph_results:
        entity_id = r.get("entity_id", "")
        # Skip if already present in vault results (entity_id == memory_id for vault memories)
        if entity_id in existing_ids:
            continue
        items.append(
            MemoryResponse(
                memory_id=entity_id or f"cog-{len(items)}",
                user_id="cognition_os",
                namespace="cognition_os",
                content=r.get("content") or r.get("title", ""),
                content_type="fact",
                metadata={
                    "source": "cognition_os",
                    "score": r.get("score", 0.0),
                    "title": r.get("title", ""),
                },
                source_agent_id=None,
                source_type="cognition_os",
                quality_score=r.get("score"),
                enrichment_status="done",
                version=1,
                ttl_seconds=None,
                expires_at=None,
                created_at=now_str,
                updated_at=now_str,
                # Cognition OS entities are synthesized concepts — L3.1 tier.
                compression_tier="L3.1",
            )
        )
    return items


async def list_namespaces(
    user_id: uuid.UUID,
    db: AsyncSession,
    admin_view: bool = False,
    agent_id: uuid.UUID | None = None,
) -> list[dict]:
    """
    List namespaces with memory counts + policy metadata.

    When ``agent_id`` is provided and ``admin_view`` is False, each namespace
    is filtered by the Gatekeeper on scope ``memory:read`` — namespaces the
    agent has no read rule for are omitted from the response. This closes
    the ACL leak where agents could enumerate namespaces they couldn't read.

    Each returned dict includes description, consolidated_summary, tier,
    updated_at timestamp, and related_namespaces from NamespacePolicy.
    """
    if admin_view:
        query = (
            select(Memory.namespace, func.count(Memory.memory_id).label("count"))
            .where(Memory.invalid_at == None)  # noqa: E711
            .group_by(Memory.namespace)
            .order_by(Memory.namespace)
        )
    else:
        query = (
            select(Memory.namespace, func.count(Memory.memory_id).label("count"))
            .where(
                Memory.user_id == user_id,
                Memory.invalid_at == None,  # noqa: E711
            )
            .group_by(Memory.namespace)
            .order_by(Memory.namespace)
        )
    result = await db.execute(query)
    rows = result.all()
    namespaces = [(row[0], row[1]) for row in rows]

    # Pull policy metadata in one shot
    from backend.models.namespace_policy import NamespacePolicy

    policy_rows = (await db.execute(select(NamespacePolicy))).scalars().all()
    policy_by_ns = {p.namespace: p for p in policy_rows}

    # Permission-aware filtering: if we have an agent_id (not admin), ask the
    # gatekeeper for memory:read on each namespace.
    filtered: list[tuple[str, int]] = []
    if agent_id is not None and not admin_view:
        for ns, count in namespaces:
            try:
                decision = await evaluate(
                    user_id,
                    EvaluationRequest(
                        agent_id=str(agent_id),
                        scope="memory:read",
                        namespace=ns,
                    ),
                    db,
                )
                if decision.allowed:
                    filtered.append((ns, count))
            except Exception:
                # Fail closed on evaluation errors to preserve isolation
                continue
    else:
        filtered = namespaces

    output: list[dict] = []
    for ns, count in filtered:
        policy = policy_by_ns.get(ns)
        output.append(
            {
                "namespace": ns,
                "count": count,
                "description": getattr(policy, "description", None),
                "consolidated_summary": getattr(policy, "consolidated_summary", None),
                "consolidated_summary_tier": getattr(policy, "consolidated_summary_tier", None),
                "consolidated_summary_updated_at": (
                    policy.consolidated_summary_updated_at.isoformat()
                    if policy and policy.consolidated_summary_updated_at
                    else None
                ),
                "related_namespaces": getattr(policy, "related_namespaces", None) or [],
            }
        )
    return output


async def get_namespace_summary(
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    namespace: str,
    db: AsyncSession,
    skip_gatekeeper: bool = False,
) -> dict:
    """
    Fetch the consolidated cross-session summary for a single namespace.

    Returns the L3.1 rollup from NamespacePolicy.consolidated_summary when
    present; otherwise falls back to the most recent concept memory (L3.0
    fallback) in the namespace. If neither exists, returns an empty summary
    with tier=None so clients can render "not yet consolidated".
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
            raise PermissionError(f"Access denied: {decision.reason} (outcome: {decision.outcome})")

    from backend.models.namespace_policy import NamespacePolicy

    policy = (
        await db.execute(select(NamespacePolicy).where(NamespacePolicy.namespace == namespace))
    ).scalar_one_or_none()

    tier: str | None = None
    summary: str | None = None
    updated_at: str | None = None

    if policy and policy.consolidated_summary:
        summary = policy.consolidated_summary
        tier = policy.consolidated_summary_tier or "L3.1"
        updated_at = (
            policy.consolidated_summary_updated_at.isoformat()
            if policy.consolidated_summary_updated_at
            else None
        )
    else:
        # Fallback: latest L3.0 concept memory in the namespace
        concept = (
            await db.execute(
                select(Memory)
                .where(
                    Memory.user_id == user_id,
                    Memory.namespace == namespace,
                    Memory.content_type == "concept",
                    Memory.invalid_at.is_(None),
                )
                .order_by(Memory.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if concept is not None:
            summary = concept.content
            tier = "L3.0"
            updated_at = concept.created_at.isoformat() if concept.created_at else None

    return {
        "namespace": namespace,
        "description": getattr(policy, "description", None) if policy else None,
        "consolidated_summary": summary,
        "consolidated_summary_tier": tier,
        "consolidated_summary_updated_at": updated_at,
        "related_namespaces": (getattr(policy, "related_namespaces", None) or []) if policy else [],
    }


# ─── Temporal Date Resolution ────────────────────────────────────

_RELATIVE_PATTERNS: list[tuple[str, int]] = [
    ("today", 0),
    ("yesterday", 1),
    ("day before yesterday", 2),
]
_RELATIVE_WEEK_PATTERNS = {
    "last week": 7,
    "this week": 0,
    "last month": 30,
    "this month": 0,
    "last year": 365,
    "this year": 0,
}
import re as _re


def _resolve_date(value: str, now: datetime) -> datetime | None:
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


# NOTE: _normalize_content and _content_hash now imported from
# memory_vault.utils.text (see top-of-file imports). Kept as private aliases
# above to avoid touching every callsite in this 1276-LOC module — those
# get migrated as part of P3 #16 when the file is split.


async def _find_by_hash(
    user_id: uuid.UUID,
    namespace: str,
    content_hash: str,
    db: AsyncSession,
) -> Memory | None:
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
) -> tuple[Memory, float] | None:
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
        select(Memory)
        .where(
            Memory.user_id == user_id,
            Memory.namespace == namespace,
            Memory.invalid_at == None,
            Memory.embedding != None,
        )
        .limit(max_candidates)
    )
    candidates = result.scalars().all()

    best_match: Memory | None = None
    best_sim = 0.0

    for mem in candidates:
        if mem.embedding is None:
            continue
        # Dot product of L2-normalised vectors = cosine similarity
        sim = sum(a * b for a, b in zip(query_vec, mem.embedding, strict=False))
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
    similarity: float | None,
    db: AsyncSession,
) -> MemoryResponse:
    """Bump access stats, emit provenance event, and return the existing memory."""
    existing.access_count = (existing.access_count or 0) + 1
    existing.last_accessed_at = datetime.now(UTC)
    await db.flush()

    await emit_event(
        db,
        existing.memory_id,
        "dedup_matched",
        actor_type="agent",
        actor_id=str(agent_id),
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
            expires_at = expires_at.replace(tzinfo=UTC)
        if datetime.now(UTC) > expires_at:
            raise ValueError("Memory has expired")

    return memory


def _tier_from_meta(meta: dict | None) -> str:
    """Extract compression tier from Memory.meta._compression_tier.

    Values are normalised to the public tier names: L1 / L2 / L3.1.
    Unknown or missing tiers default to 'L1' (raw).
    """
    if not meta:
        return "L1"
    tier = str(meta.get("_compression_tier") or "L1")
    return tier if tier in {"L1", "L2", "L3.1"} else "L1"


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
        compression_tier=_tier_from_meta(memory.meta),
    )


# Compression-tier helpers: see `_tier_from_meta` and `_source_ids_from_meta`
# above — both layers (HTTP + library) read meta["_compression_tier"] /
# meta["_source_memory_ids"] from the compression pipeline.

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
            Memory.invalid_at.is_(None),
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
    mode: str = "concept",  # "raw" | "aaak" | "concept" | "cognition"
    merge_mode: str = "current",  # "current" | "aggregate"
    skip_gatekeeper: bool = False,
) -> dict:
    """Tiered memory compression entry point — L1 raw, L2 AAAK, L3.1 concept, L4 cognition.

    Caches results in a process-level NamespaceCompressionCache keyed by the
    sorted memory IDs in the namespace plus mode + merge_mode. Auto-invalidates
    on any namespace change.

    Modes:
      raw       — L1: every active memory as raw dicts
      aaak      — L2: lossless AAAK dialect encoding with compression metrics
      concept   — L3.1: LLM-synthesized concepts via CoreAIBackendClient
      cognition — L4: concept synthesis augmented with Cognition OS graph entities

    Story: KMV-COMPRESS-01 / S9N-3050 | KMV-S11.1
    """
    if mode not in {"raw", "aaak", "concept", "cognition"}:
        raise ValueError(f"mode must be raw|aaak|concept|cognition, got {mode!r}")
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
    from memory_vault.compression.aaak import compression_ratio, encode_aaak
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
            adapter,
            llm_client=client,
            org_id=str(user_id),
            namespace=namespace,
            merge_mode=merge_mode,
        )
        # L3.2 placeholder pass-through (KMV-COMPRESS-02 will hook this up)
        synthesis["concepts"] = await round_trip_concepts(
            None,
            synthesis["concepts"],
            namespace=namespace,
        )
        payload = {
            "mode": "concept",
            "merge_mode": merge_mode,
            "namespace": namespace,
            "source_count": synthesis.get("source_count", 0),
            "concepts": synthesis["concepts"],
            "source": synthesis.get("source", "local"),
        }

    if mode == "cognition":
        # L4: concept synthesis augmented with Cognition OS graph entities
        # First synthesize concepts (same as L3.1)
        class _DBAdapterCog:
            def __init__(self, mems: list[dict]) -> None:
                self._mems = mems

            async def list_episodes(self, *, org_id, limit=200, offset=0, include_invalid=False):
                return self._mems[offset : offset + limit]

            async def find_similar(self, *, content, org_id, limit=20):
                return []

            async def get_related(self, *, episode_id, relation_type, limit=10):
                return []

        adapter_cog = _DBAdapterCog(memory_dicts)
        client_cog = CoreAIBackendClient()
        synthesis_cog = await synthesize_namespace_local(
            adapter_cog,
            llm_client=client_cog,
            org_id=str(user_id),
            namespace=namespace,
            merge_mode=merge_mode,
        )
        synthesis_cog["concepts"] = await round_trip_concepts(
            None,
            synthesis_cog["concepts"],
            namespace=namespace,
        )
        # Now augment with Cognition OS graph entities (graceful degradation)
        graph_entities: list[dict] = []
        cognition_available = False
        try:
            from backend.services.cognition_bridge import get_cognition_bridge

            bridge = get_cognition_bridge()
            if bridge.enabled and not bridge.circuit_open:
                # Use the namespace as the query to find related graph entities
                query_terms = namespace
                if synthesis_cog["concepts"]:
                    # Extract key terms from the first concept for a richer query
                    first_concept = synthesis_cog["concepts"][0]
                    if isinstance(first_concept, dict):
                        query_terms = first_concept.get("summary", namespace) or namespace
                    elif isinstance(first_concept, str):
                        query_terms = first_concept[:200]
                graph_entities = await bridge.expand_recall(
                    query=query_terms,
                    org_id=str(user_id),
                    top_k=10,
                    min_score=0.3,
                )
                cognition_available = True
        except Exception:  # noqa: BLE001
            # Graceful degradation: Cognition OS unavailable — return concept-only payload
            pass
        payload = {
            "mode": "cognition",
            "merge_mode": merge_mode,
            "namespace": namespace,
            "source_count": synthesis_cog.get("source_count", 0),
            "concepts": synthesis_cog["concepts"],
            "graph_entities": graph_entities,
            "cognition_os_available": cognition_available,
            "source": "cognition_os" if cognition_available else "local",
        }

    cache.put(str(user_id), namespace, mode, merge_mode, memory_ids, payload)
    return payload
