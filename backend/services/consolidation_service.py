"""
S9N Memory Vault — Memory Consolidation & Decay Service (KMV-E13)

Implements the local consolidation pipeline:
  1. apply_weight_decay()   — KMV-S13.3: Reduce consolidation_weight daily per namespace policy
  2. auto_archive_expired() — KMV-S13.3: Archive memories older than retention_days

Spec reviewer mitigations applied:
  - Batched DB updates to avoid table locks on large datasets
  - Expired memories are archived locally without an external graph service
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.memory import Memory
from backend.models.namespace_policy import EXEMPT_NAMESPACES, NamespacePolicy

logger = logging.getLogger(__name__)

# Batch size for DB updates to avoid table locks
_BATCH_SIZE = 500
# Minimum weight floor — memories never fully disappear from synthesis
_MIN_WEIGHT = 0.01


async def _get_policy(db: AsyncSession, namespace: str) -> NamespacePolicy:
    """
    Fetch the namespace policy, or return a default policy if none exists.
    Exempt namespaces (skills, system) get auto_consolidate=False by default.
    """
    result = await db.execute(select(NamespacePolicy).where(NamespacePolicy.namespace == namespace))
    policy = result.scalar_one_or_none()
    if policy is None:
        # Return a synthetic default policy without persisting it
        policy = NamespacePolicy(
            namespace=namespace,
            decay_rate=0.1,
            retention_days=10,
            auto_consolidate=(namespace not in EXEMPT_NAMESPACES),
        )
    return policy


async def apply_weight_decay(
    db: AsyncSession,
    namespace: str | None = None,
) -> dict:
    """
    KMV-S13.3: Apply daily soft weight decay to all pending memories.

    For each namespace (or a specific one), reduces consolidation_weight by
    decay_rate per day:
        weight_new = max(MIN_WEIGHT, weight * (1 - decay_rate))

    Runs in batches of _BATCH_SIZE to avoid table locks.

    Returns a summary dict with counts of memories updated per namespace.
    """
    summary = {}

    # Get all distinct namespaces to process
    if namespace:
        namespaces = [namespace]
    else:
        result = await db.execute(
            select(Memory.namespace).where(Memory.consolidation_status == "pending").distinct()
        )
        namespaces = [row[0] for row in result.fetchall()]

    for ns in namespaces:
        policy = await _get_policy(db, ns)
        decay_rate = policy.decay_rate
        updated = 0

        # Process in batches
        offset = 0
        while True:
            result = await db.execute(
                select(Memory.memory_id, Memory.consolidation_weight)
                .where(
                    and_(
                        Memory.namespace == ns,
                        Memory.consolidation_status == "pending",
                        Memory.invalid_at.is_(None),
                    )
                )
                .limit(_BATCH_SIZE)
                .offset(offset)
            )
            rows = result.fetchall()
            if not rows:
                break

            for memory_id, current_weight in rows:
                new_weight = max(_MIN_WEIGHT, (current_weight or 1.0) * (1 - decay_rate))
                await db.execute(
                    update(Memory)
                    .where(Memory.memory_id == memory_id)
                    .values(
                        consolidation_weight=new_weight,
                        updated_at=datetime.now(UTC),
                    )
                )
                updated += 1

            offset += _BATCH_SIZE

        await db.commit()
        summary[ns] = {"weight_decay_applied": updated, "decay_rate": decay_rate}
        logger.info(
            "weight_decay_applied namespace=%s count=%d decay_rate=%.3f",
            ns,
            updated,
            decay_rate,
        )

    return summary


async def auto_archive_expired(
    db: AsyncSession,
    namespace: str | None = None,
) -> dict:
    """
    KMV-S13.3: Auto-archive memories older than the namespace retention window.

    Memories older than retention_days are set to consolidation_status='archived'
    regardless of whether they have been pushed to Cognition OS.
    This enforces the rolling retention window.

    Exempt namespaces (skills, system) are skipped unless explicitly targeted.
    """
    summary = {}

    if namespace:
        namespaces = [namespace]
    else:
        result = await db.execute(
            select(Memory.namespace).where(Memory.consolidation_status == "pending").distinct()
        )
        namespaces = [row[0] for row in result.fetchall()]

    for ns in namespaces:
        if ns in EXEMPT_NAMESPACES and namespace is None:
            logger.info("auto_archive_expired skipping exempt namespace=%s", ns)
            continue

        policy = await _get_policy(db, ns)
        cutoff = datetime.now(UTC) - timedelta(days=policy.retention_days)

        result = await db.execute(
            update(Memory)
            .where(
                and_(
                    Memory.namespace == ns,
                    Memory.consolidation_status == "pending",
                    Memory.created_at < cutoff,
                    Memory.invalid_at.is_(None),
                )
            )
            .values(
                consolidation_status="archived",
                updated_at=datetime.now(UTC),
            )
            .returning(Memory.memory_id)
        )
        archived_ids = result.fetchall()
        await db.commit()

        count = len(archived_ids)
        summary[ns] = {"auto_archived": count, "retention_days": policy.retention_days}
        logger.info(
            "auto_archive_expired namespace=%s count=%d cutoff=%s",
            ns,
            count,
            cutoff.isoformat(),
        )

    return summary


async def run_daily_consolidation(
    db: AsyncSession,
    namespace: str | None = None,
) -> dict:
    """
    KMV-S13.2: Full daily consolidation pipeline for a namespace (or all namespaces).

    Applies weight decay and archives memories past their local retention window.

    Returns a detailed summary dict.
    """
    today = datetime.now(UTC).date().isoformat()
    summary = {
        "epoch_date": today,
        "namespace": namespace or "all",
        "weight_decay": {},
        "auto_archived": {},
        "consolidated": {},
        "errors": [],
    }

    # Phase 1: Weight decay
    try:
        summary["weight_decay"] = await apply_weight_decay(db, namespace)
    except Exception as exc:
        logger.error("weight_decay_failed error=%s", exc)
        summary["errors"].append(f"weight_decay: {exc}")

    # Phase 2: Auto-archive expired memories
    try:
        summary["auto_archived"] = await auto_archive_expired(db, namespace)
    except Exception as exc:
        logger.error("auto_archive_failed error=%s", exc)
        summary["errors"].append(f"auto_archive: {exc}")

    return summary


async def get_consolidation_stats(
    db: AsyncSession,
    namespace: str | None = None,
) -> dict:
    """
    Return consolidation statistics for a namespace or all namespaces.
    Used by the admin dashboard (KMV-S14.2).
    """
    where_clause = [Memory.invalid_at.is_(None)]
    if namespace:
        where_clause.append(Memory.namespace == namespace)

    result = await db.execute(
        select(
            Memory.namespace,
            Memory.consolidation_status,
            func.count(Memory.memory_id).label("count"),
            func.avg(Memory.consolidation_weight).label("avg_weight"),
        )
        .where(and_(*where_clause))
        .group_by(Memory.namespace, Memory.consolidation_status)
        .order_by(Memory.namespace, Memory.consolidation_status)
    )
    rows = result.fetchall()

    stats = {}
    for row in rows:
        ns = row.namespace
        if ns not in stats:
            stats[ns] = {"pending": 0, "consolidating": 0, "archived": 0, "avg_weight": {}}
        stats[ns][row.consolidation_status] = row.count
        stats[ns]["avg_weight"][row.consolidation_status] = round(row.avg_weight or 0.0, 4)

    return stats
