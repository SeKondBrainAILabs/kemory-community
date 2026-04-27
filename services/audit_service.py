"""
S9N Memory Vault — Audit & Governance Service

Implements:
1. Append-only audit logging: every memory operation is logged immutably
2. Rate limiting: per-agent, per-user rate limits with sliding window
3. Write validation: content size, frequency, and quality gates
4. Audit trail querying: search and export audit logs

The audit log is designed as an append-only table — no UPDATE or DELETE
operations are permitted on audit records. Each record includes a hash
chain for tamper detection.

Spec reference: Section 7.6 (Governance), Section 12 (Security Architecture)

Stories: F07-US-001 (audit logging), F07-US-002 (rate limiting),
         F07-US-003 (write validation), F07-US-004 (audit querying)
"""
import uuid
import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Optional
from collections import defaultdict

from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.audit import AuditLog


# ─── Audit Schemas ────────────────────────────────────────────────

class AuditEntry(BaseModel):
    """Schema for an audit log entry."""
    audit_id: str
    user_id: str
    agent_id: Optional[str]
    action: str  # e.g., "memory:write", "memory:read", "memory:delete", "permission:evaluate"
    resource_type: str  # e.g., "memory", "permission", "agent"
    resource_id: Optional[str]
    namespace: Optional[str]
    outcome: str  # "success", "denied", "error"
    details: Optional[dict]
    ip_address: Optional[str]
    hash_chain: str  # SHA-256 hash linking to previous entry
    created_at: str


class AuditQueryRequest(BaseModel):
    """Request for querying audit logs."""
    user_id: Optional[str] = None
    agent_id: Optional[str] = None
    action: Optional[str] = None
    resource_type: Optional[str] = None
    outcome: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class AuditQueryResponse(BaseModel):
    """Response for audit log queries."""
    items: list[AuditEntry]
    total: int
    limit: int
    offset: int


class RateLimitStatus(BaseModel):
    """Current rate limit status for an agent."""
    agent_id: str
    window_seconds: int
    max_requests: int
    current_count: int
    remaining: int
    reset_at: str
    is_limited: bool


# ─── Rate Limiting Configuration ──────────────────────────────────

# Default rate limits per action type (requests per window)
RATE_LIMITS = {
    "memory:write": {"max_requests": 100, "window_seconds": 3600},    # 100 writes/hour
    "memory:read": {"max_requests": 1000, "window_seconds": 3600},    # 1000 reads/hour
    "memory:delete": {"max_requests": 50, "window_seconds": 3600},     # 50 deletes/hour
    "memory:search": {"max_requests": 500, "window_seconds": 3600},    # 500 searches/hour
    "permission:evaluate": {"max_requests": 2000, "window_seconds": 3600},  # 2000 evals/hour
    "default": {"max_requests": 200, "window_seconds": 3600},          # 200 default/hour
}

# Write validation limits
MAX_CONTENT_SIZE = 100_000  # 100KB max content size
MAX_METADATA_SIZE = 10_000   # 10KB max metadata size
MIN_WRITE_INTERVAL_SECONDS = 1  # Minimum 1 second between writes from same agent


# ─── Hash Chain ───────────────────────────────────────────────────

def compute_hash_chain(
    previous_hash: str,
    action: str,
    resource_id: str,
    timestamp: str,
) -> str:
    """
    Compute the hash chain value for tamper detection.

    Each audit entry's hash includes the previous entry's hash,
    creating an immutable chain. Any modification to a historical
    entry would break the chain.
    """
    payload = f"{previous_hash}:{action}:{resource_id}:{timestamp}"
    return hashlib.sha256(payload.encode()).hexdigest()


# ─── Audit Logging ────────────────────────────────────────────────

async def log_audit_event(
    user_id: uuid.UUID,
    agent_id: Optional[uuid.UUID],
    action: str,
    resource_type: str,
    resource_id: Optional[str],
    outcome: str,
    db: AsyncSession,
    namespace: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
    org_id: Optional[str] = None,
    team_id: Optional[str] = None,
) -> AuditEntry:
    """
    Log an audit event to the append-only audit log.

    This is the primary entry point for all audit logging.
    Every memory operation, permission check, and agent action
    should be logged through this function.

    org_id / team_id are auto-resolved from the active TenantScope when
    not passed explicitly — so existing call-sites get tenant-aware
    audits "for free" without a code change. Compliance / GDPR exports
    can then filter by org_id with one indexed query (idx_audit_log_org_time).
    """
    now = datetime.now(timezone.utc)

    # Auto-thread tenant context. Falls back to an empty string for
    # cross-tenant background tasks (the global filter bypass path) so
    # we still record SOMETHING rather than crashing audit emission.
    if org_id is None or team_id is None:
        from backend.core.tenancy import current_org_id, current_team_ids
        if org_id is None:
            org_id = current_org_id() or None
        if team_id is None:
            tids = current_team_ids()
            team_id = tids[0] if len(tids) == 1 else None

    # Get the previous hash for chain continuity
    result = await db.execute(
        select(AuditLog.hash_chain)
        .where(AuditLog.user_id == user_id)
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    previous_hash = result.scalar_one_or_none() or "GENESIS"

    # Compute hash chain
    hash_chain = compute_hash_chain(
        previous_hash=previous_hash,
        action=action,
        resource_id=resource_id or "none",
        timestamp=now.isoformat(),
    )

    # Create audit record — set created_at explicitly to match the timestamp
    # used in hash computation (ensures chain verification works)
    audit = AuditLog(
        user_id=user_id,
        agent_id=agent_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        namespace=namespace,
        outcome=outcome,
        details=details or {},
        ip_address=ip_address,
        hash_chain=hash_chain,
        created_at=now,
        org_id=org_id,
        team_id=team_id,
    )
    db.add(audit)
    await db.flush()

    return AuditEntry(
        audit_id=str(audit.audit_id),
        user_id=str(audit.user_id),
        agent_id=str(audit.agent_id) if audit.agent_id else None,
        action=audit.action,
        resource_type=audit.resource_type,
        resource_id=audit.resource_id,
        namespace=audit.namespace,
        outcome=audit.outcome,
        details=audit.details,
        ip_address=audit.ip_address,
        hash_chain=audit.hash_chain,
        created_at=audit.created_at.isoformat() if audit.created_at else now.isoformat(),
    )


async def query_audit_logs(
    request: AuditQueryRequest,
    requesting_user_id: uuid.UUID,
    db: AsyncSession,
    admin_view: bool = False,
) -> AuditQueryResponse:
    """
    Query audit logs with filtering and pagination.

    When ``admin_view`` is True (Keycloak admin/super_admin/platform_admin
    role) the user_id filter is omitted so the admin can inspect all
    Memory Vault audit records across every user.  Regular users only see
    their own entries.

    Supports optional date-range filtering via ``request.start_time`` and
    ``request.end_time`` (ISO-8601 strings).
    """
    # Admin sees every record; regular users are scoped to their own vault.
    if admin_view:
        query = select(AuditLog)
    else:
        query = select(AuditLog).where(AuditLog.user_id == requesting_user_id)

    # Apply filters
    if request.agent_id:
        query = query.where(AuditLog.agent_id == uuid.UUID(request.agent_id))
    if request.action:
        query = query.where(AuditLog.action == request.action)
    if request.resource_type:
        query = query.where(AuditLog.resource_type == request.resource_type)
    if request.outcome:
        query = query.where(AuditLog.outcome == request.outcome)
    # Date-range filters (ISO-8601 strings, e.g. "2025-01-01T00:00:00Z")
    if request.start_time:
        from datetime import datetime as _dt
        start_dt = _dt.fromisoformat(request.start_time.replace("Z", "+00:00"))
        query = query.where(AuditLog.created_at >= start_dt)
    if request.end_time:
        from datetime import datetime as _dt
        end_dt = _dt.fromisoformat(request.end_time.replace("Z", "+00:00"))
        query = query.where(AuditLog.created_at <= end_dt)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(AuditLog.created_at.desc())
    query = query.offset(request.offset).limit(request.limit)

    result = await db.execute(query)
    logs = result.scalars().all()

    return AuditQueryResponse(
        items=[
            AuditEntry(
                audit_id=str(log.audit_id),
                user_id=str(log.user_id),
                agent_id=str(log.agent_id) if log.agent_id else None,
                action=log.action,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                namespace=log.namespace,
                outcome=log.outcome,
                details=log.details,
                ip_address=log.ip_address,
                hash_chain=log.hash_chain,
                created_at=log.created_at.isoformat() if log.created_at else "",
            )
            for log in logs
        ],
        total=total,
        limit=request.limit,
        offset=request.offset,
    )


# ─── Rate Limiting ────────────────────────────────────────────────

async def check_rate_limit(
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    action: str,
    db: AsyncSession,
) -> RateLimitStatus:
    """
    Check if an agent has exceeded its rate limit for a given action.

    Uses a sliding window approach based on audit log entries.
    """
    limits = RATE_LIMITS.get(action, RATE_LIMITS["default"])
    window_seconds = limits["window_seconds"]
    max_requests = limits["max_requests"]

    window_start = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

    # Count requests in the current window
    result = await db.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.user_id == user_id,
            AuditLog.agent_id == agent_id,
            AuditLog.action == action,
            AuditLog.created_at >= window_start,
        )
    )
    current_count = result.scalar() or 0

    remaining = max(0, max_requests - current_count)
    reset_at = datetime.now(timezone.utc) + timedelta(seconds=window_seconds)

    return RateLimitStatus(
        agent_id=str(agent_id),
        window_seconds=window_seconds,
        max_requests=max_requests,
        current_count=current_count,
        remaining=remaining,
        reset_at=reset_at.isoformat(),
        is_limited=current_count >= max_requests,
    )


# ─── Write Validation ────────────────────────────────────────────

class WriteValidationResult(BaseModel):
    """Result of write validation."""
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


async def validate_write(
    content: str,
    metadata: Optional[dict],
    user_id: uuid.UUID,
    agent_id: uuid.UUID,
    db: AsyncSession,
) -> WriteValidationResult:
    """
    Validate a memory write operation.

    Checks:
    1. Content size limits
    2. Metadata size limits
    3. Write frequency (minimum interval between writes)
    4. Rate limits
    """
    errors = []
    warnings = []

    # Check content size
    content_size = len(content.encode("utf-8"))
    if content_size > MAX_CONTENT_SIZE:
        errors.append(
            f"Content size ({content_size} bytes) exceeds maximum ({MAX_CONTENT_SIZE} bytes)"
        )
    elif content_size > MAX_CONTENT_SIZE * 0.8:
        warnings.append(
            f"Content size ({content_size} bytes) is approaching the limit ({MAX_CONTENT_SIZE} bytes)"
        )

    # Check metadata size
    if metadata:
        metadata_size = len(json.dumps(metadata).encode("utf-8"))
        if metadata_size > MAX_METADATA_SIZE:
            errors.append(
                f"Metadata size ({metadata_size} bytes) exceeds maximum ({MAX_METADATA_SIZE} bytes)"
            )

    # Check write frequency
    min_interval = timedelta(seconds=MIN_WRITE_INTERVAL_SECONDS)
    result = await db.execute(
        select(AuditLog.created_at)
        .where(
            AuditLog.user_id == user_id,
            AuditLog.agent_id == agent_id,
            AuditLog.action == "memory:write",
        )
        .order_by(AuditLog.created_at.desc())
        .limit(1)
    )
    last_write = result.scalar_one_or_none()
    if last_write:
        if last_write.tzinfo is None:
            last_write = last_write.replace(tzinfo=timezone.utc)
        elapsed = datetime.now(timezone.utc) - last_write
        if elapsed < min_interval:
            warnings.append(
                f"High write frequency detected: {elapsed.total_seconds():.1f}s since last write"
            )

    # Check rate limit
    rate_status = await check_rate_limit(user_id, agent_id, "memory:write", db)
    if rate_status.is_limited:
        errors.append(
            f"Rate limit exceeded: {rate_status.current_count}/{rate_status.max_requests} "
            f"writes in the current window"
        )

    return WriteValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )


# ─── Audit Chain Verification ─────────────────────────────────────

async def verify_audit_chain(
    user_id: uuid.UUID,
    db: AsyncSession,
    limit: int = 100,
) -> dict:
    """
    Verify the integrity of the audit hash chain.

    Checks that each entry's hash correctly chains to the previous entry.
    Returns a verification report.
    """
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.user_id == user_id)
        .order_by(AuditLog.created_at.asc())
        .limit(limit)
    )
    logs = result.scalars().all()

    if not logs:
        return {"status": "empty", "verified": 0, "errors": []}

    errors = []
    previous_hash = "GENESIS"

    for i, log in enumerate(logs):
        # Normalize timezone: SQLite may strip tz info, so re-add UTC if missing
        ts = log.created_at
        if ts and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        expected_hash = compute_hash_chain(
            previous_hash=previous_hash,
            action=log.action,
            resource_id=log.resource_id or "none",
            timestamp=ts.isoformat() if ts else "",
        )
        if log.hash_chain != expected_hash:
            errors.append({
                "index": i,
                "audit_id": str(log.audit_id),
                "expected_hash": expected_hash[:16] + "...",
                "actual_hash": log.hash_chain[:16] + "...",
            })
        previous_hash = log.hash_chain

    return {
        "status": "valid" if not errors else "tampered",
        "verified": len(logs),
        "errors": errors,
    }
