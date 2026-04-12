"""
Memory Vault — Audit & Governance API Routes

Endpoints:
- GET  /api/v1/audit/logs          — Query audit logs with filters
                                     (admin sees ALL records; users see own)
- GET  /api/v1/audit/verify        — Verify audit chain integrity
- GET  /api/v1/audit/rate-limit    — Check rate limit status
- POST /api/v1/audit/validate-write — Validate a write operation

Fix: KMV-QA-001 — Audit log empty for admin users.
     Admin Keycloak users now receive an unrestricted view of all audit
     records via the ``admin_view`` flag passed to ``query_audit_logs``.

Fix: KMV-QA-011 — Date range filter added (start_time / end_time params).
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.auth import require_auth, AuthContext, is_admin
from backend.services.audit_service import (
    query_audit_logs,
    verify_audit_chain,
    check_rate_limit,
    validate_write,
    AuditQueryRequest,
)

router = APIRouter(prefix="/api/v1/audit", tags=["Audit & Governance"])


@router.get("/logs", summary="Query audit logs")
async def get_audit_logs(
    agent_id: Optional[str] = Query(None, description="Filter by agent ID"),
    action: Optional[str] = Query(None, description="Filter by action (e.g. memory:write)"),
    resource_type: Optional[str] = Query(None, description="Filter by resource type"),
    outcome: Optional[str] = Query(None, description="Filter by outcome (success/denied/error)"),
    start_time: Optional[str] = Query(None, description="ISO-8601 start datetime (inclusive)"),
    end_time: Optional[str] = Query(None, description="ISO-8601 end datetime (inclusive)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Query audit logs.

    Admin users (Keycloak roles: admin / super_admin / platform_admin) receive
    a cross-user view of all audit records.  Regular users only see their own
    vault's audit trail.
    """
    request = AuditQueryRequest(
        agent_id=agent_id,
        action=action,
        resource_type=resource_type,
        outcome=outcome,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    # KMV-QA-001: pass admin_view=True so admin Keycloak users see all records
    result = await query_audit_logs(request, auth.user_id, db, admin_view=is_admin(auth))
    return result.model_dump()


@router.get("/verify", summary="Verify audit chain integrity")
async def verify_chain(
    limit: int = Query(100, ge=1, le=1000),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Verify the integrity of the audit hash chain."""
    return await verify_audit_chain(auth.user_id, db, limit)


@router.get("/rate-limit", summary="Check rate limit status")
async def get_rate_limit(
    action: str = Query("memory:write"),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Check the current rate limit status for the authenticated agent."""
    result = await check_rate_limit(auth.user_id, auth.agent_id, action, db)
    return result.model_dump()


@router.post("/validate-write", summary="Validate a write operation")
async def validate_write_endpoint(
    content: str = "",
    metadata: Optional[dict] = None,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Validate a write operation before executing it.
    Checks content size, metadata size, write frequency, and rate limits.
    """
    result = await validate_write(content, metadata, auth.user_id, auth.agent_id, db)
    return result.model_dump()
