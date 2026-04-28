"""
S9N Memory Vault — Waitlist API Routes

Public endpoints (require Keycloak auth):
  POST  /api/v1/waitlist/join         — Join waitlist for a service
  GET   /api/v1/waitlist/status       — My status + position
  GET   /api/v1/waitlist/referral     — My referral code + stats
  POST  /api/v1/waitlist/referral/track — Track a referral after signup

Admin endpoints (require admin role):
  GET   /api/v1/admin/waitlist           — List entries (paginated, filterable)
  POST  /api/v1/admin/waitlist/{user_id}/approve  — Approve user
  POST  /api/v1/admin/waitlist/{user_id}/reject   — Reject user
  POST  /api/v1/admin/waitlist/bulk-approve       — Batch approve
  GET   /api/v1/admin/waitlist/stats     — Signup stats
"""
import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.exc import ProgrammingError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.auth import require_auth, require_admin
from backend.services.auth_service import AuthContext
from backend.config.settings import settings
from backend.core.rate_limit import rate_limit
from backend.services.waitlist_service import WaitlistService
from backend.services.email_service import email_service


# ─── Request/Response models ─────────────────────────────────────

class JoinRequest(BaseModel):
    email: str
    display_name: str | None = None
    service: str = "memory_vault"
    referred_by_code: str | None = None
    source: str = "organic"


class TrackReferralRequest(BaseModel):
    referral_code: str
    service: str = "memory_vault"


class BulkApproveRequest(BaseModel):
    user_ids: list[str]
    service: str = "memory_vault"


# ─── Public routes ────────────────────────────────────────────────

public_router = APIRouter(prefix="/api/v1/waitlist", tags=["Waitlist"])


@public_router.post("/join", dependencies=[Depends(rate_limit(5, 60))])
async def join_waitlist(
    body: JoinRequest,
    bg: BackgroundTasks,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Join the waitlist for a service."""
    svc = WaitlistService(db)
    try:
        entry = await svc.join(
            user_id=auth.user_id,
            email=body.email,
            display_name=body.display_name,
            service=body.service,
            referred_by_code=body.referred_by_code,
            source=body.source,
        )
        await db.commit()
    except (ProgrammingError, OperationalError) as exc:
        # BUG-013 fix: waitlist table may not exist yet (migration pending)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Waitlist service temporarily unavailable. Please try again later.",
        ) from exc

    # Send welcome email (best-effort)
    bg.add_task(
        email_service.send_welcome,
        to_email=body.email,
        display_name=body.display_name,
        position=entry.position,
        referral_code=entry.referral_code,
    )

    return {
        "status": entry.status,
        "position": entry.position,
        "referral_code": entry.referral_code,
        "service": entry.service,
    }


@public_router.get("/status")
async def get_status(
    service: str = Query("memory_vault"),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get my waitlist status and position."""
    svc = WaitlistService(db)
    try:
        result = await svc.get_status(auth.user_id, service)
    except (ProgrammingError, OperationalError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Waitlist service temporarily unavailable. Please try again later.",
        ) from exc
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not on waitlist for this service",
        )
    return result


@public_router.get("/referral")
async def get_referral(
    service: str = Query("memory_vault"),
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get my referral code and stats."""
    svc = WaitlistService(db)
    result = await svc.get_referral_info(auth.user_id, service)
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not on waitlist for this service",
        )
    return result


@public_router.post("/referral/track", dependencies=[Depends(rate_limit(10, 60))])
async def track_referral(
    body: TrackReferralRequest,
    bg: BackgroundTasks,
    auth: AuthContext = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Track a referral after signup."""
    svc = WaitlistService(db)
    tracked = await svc.track_referral(
        referred_user_id=auth.user_id,
        referral_code=body.referral_code,
        service=body.service,
    )
    await db.commit()

    # Notify referrer by email (best-effort)
    if tracked:
        referrer = await svc.get_entry_by_code(body.referral_code, body.service)
        if referrer:
            bg.add_task(
                email_service.send_referral_notification,
                to_email=referrer.email,
                display_name=referrer.display_name,
                new_position=referrer.position,
                referral_count=referrer.referral_count,
            )

    return {"tracked": tracked}


# ─── Admin routes ─────────────────────────────────────────────────

admin_router = APIRouter(prefix="/api/v1/admin/waitlist", tags=["Waitlist Admin"])


_require_admin = require_admin  # alias for backward compat


@admin_router.get("")
async def list_waitlist(
    service: str | None = Query(None),
    entry_status: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List waitlist entries (paginated, filterable)."""
    svc = WaitlistService(db)
    try:
        return await svc.list_entries(
            service=service, status=entry_status, limit=limit, offset=offset
        )
    except (ProgrammingError, OperationalError) as exc:
        # BUG-013 fix: waitlist table may not exist yet (migration pending)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Waitlist service temporarily unavailable — migration may be pending.",
        ) from exc


@admin_router.post("/{user_id}/approve")
async def approve_user(
    user_id: uuid.UUID,
    bg: BackgroundTasks,
    service: str = Query("memory_vault"),
    auth: AuthContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve a user on the waitlist."""
    svc = WaitlistService(db)
    entry = await svc.get_entry(user_id, service)
    if not entry or entry.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found on waitlist or not in pending status",
        )

    await svc.approve(user_id, service)
    await db.commit()

    # Assign beta_approved role in Keycloak (best-effort)
    if settings.keycloak_enabled:
        from backend.core.keycloak_admin import keycloak_admin
        await keycloak_admin.assign_role(user_id, "beta_approved")

    # Send approval email (best-effort)
    bg.add_task(
        email_service.send_approved,
        to_email=entry.email,
        display_name=entry.display_name,
    )

    return {"approved": True, "user_id": str(user_id)}


@admin_router.post("/{user_id}/reject")
async def reject_user(
    user_id: uuid.UUID,
    service: str = Query("memory_vault"),
    auth: AuthContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Reject a user on the waitlist."""
    svc = WaitlistService(db)
    ok = await svc.reject(user_id, service)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found on waitlist or not in pending status",
        )
    await db.commit()
    return {"rejected": True, "user_id": str(user_id)}


@admin_router.post("/bulk-approve")
async def bulk_approve(
    body: BulkApproveRequest,
    auth: AuthContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Batch approve multiple users."""
    user_ids = [uuid.UUID(uid) for uid in body.user_ids]
    svc = WaitlistService(db)
    count = await svc.bulk_approve(user_ids, body.service)
    await db.commit()
    return {"approved_count": count}


@admin_router.get("/stats")
async def get_stats(
    service: str | None = Query(None),
    auth: AuthContext = Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get waitlist statistics."""
    svc = WaitlistService(db)
    try:
        return await svc.get_stats(service)
    except (ProgrammingError, OperationalError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Waitlist service temporarily unavailable — migration may be pending.",
        ) from exc
