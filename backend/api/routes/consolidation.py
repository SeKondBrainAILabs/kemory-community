"""
Kemory — Consolidation & Namespace Policy API Routes (KMV-E14)

Exposes the consolidation service as HTTP endpoints so the dashboard's
Analytics and Memory Explorer pages can read stats, manage namespace policies,
and trigger ad-hoc consolidation runs.

Endpoints mirror the dashboard's `dashboard/src/api/memories.ts` consolidation
block:

    GET  /api/v1/namespaces/consolidation-stats              — stats across all namespaces
    GET  /api/v1/namespaces/{namespace}/consolidation-stats  — stats for one namespace
    POST /api/v1/namespaces/{namespace}/consolidate          — trigger consolidation now
    GET  /api/v1/namespaces/{namespace}/policy               — read policy
    PUT  /api/v1/namespaces/{namespace}/policy               — upsert policy

All endpoints require authentication (Bearer or X-API-Key).
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth import AuthContext, require_auth
from backend.core.database import get_db
from backend.models.namespace_policy import NamespacePolicy
from backend.services.consolidation_service import get_consolidation_stats

router = APIRouter(prefix="/api/v1", tags=["Consolidation"])


# ─── Schemas ─────────────────────────────────────────────────────────────────


class NamespacePolicyResponse(BaseModel):
    namespace: str
    decay_rate: float
    retention_days: int
    auto_consolidate: bool
    consolidation_hour_utc: int = 2
    description: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class NamespacePolicyUpdate(BaseModel):
    decay_rate: float | None = Field(None, ge=0.0, le=1.0)
    retention_days: int | None = Field(None, ge=1, le=3650)
    auto_consolidate: bool | None = None
    consolidation_hour_utc: int | None = Field(None, ge=0, le=23)
    description: str | None = Field(None, max_length=500)


class ConsolidationTriggerResponse(BaseModel):
    namespace: str
    status: str
    message: str


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _to_response(p: NamespacePolicy) -> NamespacePolicyResponse:
    return NamespacePolicyResponse(
        namespace=p.namespace,
        decay_rate=p.decay_rate,
        retention_days=p.retention_days,
        auto_consolidate=p.auto_consolidate,
        consolidation_hour_utc=p.consolidation_hour_utc,
        description=p.description,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


# ─── Routes ──────────────────────────────────────────────────────────────────


@router.get(
    "/namespaces/consolidation-stats",
    summary="Consolidation stats across all namespaces",
)
async def get_all_consolidation_stats(
    _: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns a mapping of namespace → consolidation status counts and weights.
    Empty object if no memories exist yet.
    """
    return await get_consolidation_stats(db, namespace=None)


@router.get(
    "/namespaces/{namespace}/consolidation-stats",
    summary="Consolidation stats for a single namespace",
)
async def get_namespace_consolidation_stats(
    namespace: str,
    _: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    return await get_consolidation_stats(db, namespace=namespace)


@router.get(
    "/namespaces/{namespace}/policy",
    response_model=NamespacePolicyResponse,
    summary="Read the consolidation policy for a namespace",
)
async def get_policy(
    namespace: str,
    _: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(NamespacePolicy).where(NamespacePolicy.namespace == namespace))
    policy = result.scalar_one_or_none()
    if policy is None:
        # Synthesize a default response so the dashboard never shows a 404
        # when it opens a brand-new namespace. The default matches the
        # `_get_policy` fallback in consolidation_service.
        return NamespacePolicyResponse(
            namespace=namespace,
            decay_rate=0.1,
            retention_days=10,
            auto_consolidate=True,
        )
    return _to_response(policy)


@router.put(
    "/namespaces/{namespace}/policy",
    response_model=NamespacePolicyResponse,
    summary="Create or update the consolidation policy for a namespace",
)
async def upsert_policy(
    namespace: str,
    patch: NamespacePolicyUpdate,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(NamespacePolicy).where(NamespacePolicy.namespace == namespace))
    policy = result.scalar_one_or_none()
    now = datetime.now(UTC)

    if policy is None:
        policy = NamespacePolicy(
            namespace=namespace,
            decay_rate=patch.decay_rate if patch.decay_rate is not None else 0.1,
            retention_days=patch.retention_days if patch.retention_days is not None else 10,
            auto_consolidate=patch.auto_consolidate if patch.auto_consolidate is not None else True,
            consolidation_hour_utc=patch.consolidation_hour_utc
            if patch.consolidation_hour_utc is not None
            else 2,
            description=patch.description,
            created_by=getattr(auth, "user_id", None),
            created_at=now,
            updated_at=now,
        )
        db.add(policy)
    else:
        if patch.decay_rate is not None:
            policy.decay_rate = patch.decay_rate
        if patch.retention_days is not None:
            policy.retention_days = patch.retention_days
        if patch.auto_consolidate is not None:
            policy.auto_consolidate = patch.auto_consolidate
        if patch.consolidation_hour_utc is not None:
            policy.consolidation_hour_utc = patch.consolidation_hour_utc
        if patch.description is not None:
            policy.description = patch.description
        policy.updated_at = now

    await db.flush()
    await db.refresh(policy)
    return _to_response(policy)


@router.post(
    "/namespaces/{namespace}/consolidate",
    response_model=ConsolidationTriggerResponse,
    summary="Trigger an ad-hoc consolidation run for a namespace",
)
async def trigger_consolidation(
    namespace: str,
    _: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Kicks off an on-demand consolidation pass. Honours the namespace's
    `auto_consolidate` flag — if the namespace is opted out, we return a
    409 instead of silently skipping.
    """
    try:
        from backend.services.consolidation_service import run_daily_consolidation
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Consolidation runner not available: {exc}",
        )

    result = await db.execute(select(NamespacePolicy).where(NamespacePolicy.namespace == namespace))
    policy = result.scalar_one_or_none()
    if policy is not None and not policy.auto_consolidate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Namespace '{namespace}' is opted out of consolidation.",
        )

    try:
        await run_daily_consolidation(db, namespace=namespace)  # type: ignore[arg-type]
        return ConsolidationTriggerResponse(
            namespace=namespace,
            status="ok",
            message=f"Consolidation triggered for namespace '{namespace}'.",
        )
    except TypeError:
        # Older signature without namespace kwarg: fall back to a best-effort
        # global pass and let the caller retry with narrower scope.
        await run_daily_consolidation(db)  # type: ignore[misc]
        return ConsolidationTriggerResponse(
            namespace=namespace,
            status="ok",
            message="Consolidation triggered (global run).",
        )


# F14: Operator-facing "consolidate every namespace" trigger. Used to
# bootstrap the consolidation_status field on existing rows immediately
# after deploying the kemory-worker container, instead of waiting for
# the worker's first scheduled pass (which can be up to
# KEMORY_CONSOLIDATION_INTERVAL_SEC away).
@router.post(
    "/admin/consolidate-all",
    response_model=ConsolidationTriggerResponse,
    summary="Run consolidation across every active namespace (admin)",
)
async def trigger_consolidation_all(
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Iterate every distinct namespace with active non-concept memories and
    run `run_daily_consolidation` against each. Per-namespace failures are
    logged via the service layer but do not abort the loop. Returns a
    summary containing totals.

    Intended for operator use right after a fresh deploy of `kemory-worker`,
    so existing memories transition out of `consolidation_status='pending'`
    immediately.
    """
    from sqlalchemy import distinct

    from backend.models.memory import Memory

    try:
        from backend.services.consolidation_service import run_daily_consolidation
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=f"Consolidation runner not available: {exc}",
        )

    namespaces = (
        (
            await db.execute(
                select(distinct(Memory.namespace)).where(
                    Memory.invalid_at == None,  # noqa: E711
                    Memory.content_type != "concept",
                )
            )
        )
        .scalars()
        .all()
    )

    ok = 0
    failed: list[str] = []
    for ns in namespaces:
        if not ns:
            continue
        try:
            await run_daily_consolidation(db, namespace=ns)
            ok += 1
        except Exception as exc:
            failed.append(f"{ns}:{type(exc).__name__}")

    await db.commit()
    return ConsolidationTriggerResponse(
        namespace="*",
        status="ok" if not failed else "partial",
        message=(
            f"Consolidation pass complete. namespaces={len(namespaces)} "
            f"succeeded={ok} failed={len(failed)}"
            + (f" ({', '.join(failed[:5])}" + ("…)" if len(failed) > 5 else ")") if failed else "")
        ),
    )
