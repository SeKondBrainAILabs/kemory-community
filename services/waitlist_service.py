"""
S9N Memory Vault — Waitlist Service

Handles waitlist join, status, referral mechanics, and admin operations.
Each user gets a unique 8-char referral code on join.
Each successful referral bumps the referrer up 5 positions.
"""
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.waitlist import WaitlistEntry, ReferralEvent

logger = structlog.get_logger(__name__)

REFERRAL_POSITION_BUMP = 5


def _generate_referral_code(length: int = 8) -> str:
    """Generate an alphanumeric referral code."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class WaitlistService:
    """Service layer for waitlist operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ─── Public endpoints ─────────────────────────────────────────

    async def join(
        self,
        user_id: uuid.UUID,
        email: str,
        display_name: str | None = None,
        service: str = "memory_vault",
        referred_by_code: str | None = None,
        source: str = "organic",
    ) -> WaitlistEntry:
        """Join the waitlist for a service. Idempotent — returns existing entry if already joined."""
        # Check if already on waitlist for this service
        existing = await self._get_entry(user_id, service)
        if existing:
            return existing

        # Get next position
        position = await self._next_position(service)

        # Generate unique referral code
        referral_code = await self._unique_referral_code()

        entry = WaitlistEntry(
            user_id=user_id,
            email=email,
            display_name=display_name,
            service=service,
            status="pending",
            position=position,
            referral_code=referral_code,
            referred_by_code=referred_by_code,
            source=source,
        )
        self.db.add(entry)
        await self.db.flush()

        logger.info(
            "waitlist.joined",
            user_id=str(user_id),
            service=service,
            position=position,
            referral_code=referral_code,
        )
        return entry

    async def get_status(
        self, user_id: uuid.UUID, service: str = "memory_vault"
    ) -> dict | None:
        """Get waitlist status for a user on a service."""
        entry = await self._get_entry(user_id, service)
        if not entry:
            return None

        total = await self._total_pending(service)
        ahead = await self._count_ahead(entry.position, service)

        return {
            "status": entry.status,
            "position": ahead + 1,
            "total_pending": total,
            "referral_code": entry.referral_code,
            "referral_count": entry.referral_count,
            "joined_at": entry.joined_at.isoformat() if entry.joined_at else None,
            "approved_at": entry.approved_at.isoformat() if entry.approved_at else None,
            "service": entry.service,
        }

    async def get_referral_info(
        self, user_id: uuid.UUID, service: str = "memory_vault"
    ) -> dict | None:
        """Get referral code and stats for a user."""
        entry = await self._get_entry(user_id, service)
        if not entry:
            return None

        return {
            "referral_code": entry.referral_code,
            "referral_count": entry.referral_count,
            "share_url": f"https://kora.sekondbrain.ai/vault/ref/{entry.referral_code}",
        }

    async def track_referral(
        self,
        referred_user_id: uuid.UUID,
        referral_code: str,
        service: str = "memory_vault",
    ) -> bool:
        """Track a referral after signup. Bumps referrer up in queue."""
        # Find referrer by code
        result = await self.db.execute(
            select(WaitlistEntry).where(
                WaitlistEntry.referral_code == referral_code,
                WaitlistEntry.service == service,
            )
        )
        referrer = result.scalar_one_or_none()
        if not referrer:
            return False

        # Don't self-refer
        if referrer.user_id == referred_user_id:
            return False

        # Check if already tracked
        existing = await self.db.execute(
            select(ReferralEvent).where(
                ReferralEvent.referrer_user_id == referrer.user_id,
                ReferralEvent.referred_user_id == referred_user_id,
            )
        )
        if existing.scalar_one_or_none():
            return False

        # Record referral event
        event = ReferralEvent(
            referrer_user_id=referrer.user_id,
            referred_user_id=referred_user_id,
            referral_code=referral_code,
        )
        self.db.add(event)

        # Bump referrer's count and position
        referrer.referral_count += 1
        referrer.position = max(1, referrer.position - REFERRAL_POSITION_BUMP)
        await self.db.flush()

        logger.info(
            "waitlist.referral_tracked",
            referrer=str(referrer.user_id),
            referred=str(referred_user_id),
            new_position=referrer.position,
        )
        return True

    # ─── Admin endpoints ──────────────────────────────────────────

    async def list_entries(
        self,
        service: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """List waitlist entries with pagination and filters."""
        query = select(WaitlistEntry).order_by(WaitlistEntry.position)
        count_query = select(func.count(WaitlistEntry.id))

        if service:
            query = query.where(WaitlistEntry.service == service)
            count_query = count_query.where(WaitlistEntry.service == service)
        if status:
            query = query.where(WaitlistEntry.status == status)
            count_query = count_query.where(WaitlistEntry.status == status)

        total = (await self.db.execute(count_query)).scalar() or 0
        result = await self.db.execute(query.limit(limit).offset(offset))
        entries = result.scalars().all()

        return {
            "entries": [self._serialize(e) for e in entries],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    async def approve(self, user_id: uuid.UUID, service: str = "memory_vault") -> bool:
        """Approve a user on the waitlist."""
        entry = await self._get_entry(user_id, service)
        if not entry or entry.status != "pending":
            return False

        entry.status = "approved"
        entry.approved_at = datetime.now(timezone.utc)
        await self.db.flush()

        logger.info("waitlist.approved", user_id=str(user_id), service=service)
        return True

    async def reject(self, user_id: uuid.UUID, service: str = "memory_vault") -> bool:
        """Reject a user on the waitlist."""
        entry = await self._get_entry(user_id, service)
        if not entry or entry.status != "pending":
            return False

        entry.status = "rejected"
        await self.db.flush()

        logger.info("waitlist.rejected", user_id=str(user_id), service=service)
        return True

    async def bulk_approve(
        self, user_ids: list[uuid.UUID], service: str = "memory_vault"
    ) -> int:
        """Approve multiple users. Returns count of approved."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(WaitlistEntry)
            .where(
                WaitlistEntry.user_id.in_(user_ids),
                WaitlistEntry.service == service,
                WaitlistEntry.status == "pending",
            )
            .values(status="approved", approved_at=now)
        )
        await self.db.flush()
        count = result.rowcount
        logger.info("waitlist.bulk_approved", count=count, service=service)
        return count

    async def get_stats(self, service: str | None = None) -> dict:
        """Get waitlist statistics."""
        base = select(WaitlistEntry)
        if service:
            base = base.where(WaitlistEntry.service == service)

        total = (await self.db.execute(
            select(func.count(WaitlistEntry.id)).select_from(base.subquery())
        )).scalar() or 0

        pending = (await self.db.execute(
            select(func.count(WaitlistEntry.id)).where(
                WaitlistEntry.status == "pending",
                *([WaitlistEntry.service == service] if service else []),
            )
        )).scalar() or 0

        approved = (await self.db.execute(
            select(func.count(WaitlistEntry.id)).where(
                WaitlistEntry.status == "approved",
                *([WaitlistEntry.service == service] if service else []),
            )
        )).scalar() or 0

        total_referrals = (await self.db.execute(
            select(func.count(ReferralEvent.id))
        )).scalar() or 0

        # Top referrers
        top_referrers_q = (
            select(
                WaitlistEntry.display_name,
                WaitlistEntry.email,
                WaitlistEntry.referral_count,
            )
            .where(WaitlistEntry.referral_count > 0)
            .order_by(WaitlistEntry.referral_count.desc())
            .limit(10)
        )
        if service:
            top_referrers_q = top_referrers_q.where(WaitlistEntry.service == service)

        top_rows = (await self.db.execute(top_referrers_q)).all()
        top_referrers = [
            {"name": r.display_name or r.email, "count": r.referral_count}
            for r in top_rows
        ]

        return {
            "total": total,
            "pending": pending,
            "approved": approved,
            "rejected": total - pending - approved,
            "conversion_rate": round(approved / total * 100, 1) if total > 0 else 0,
            "total_referrals": total_referrals,
            "top_referrers": top_referrers,
        }

    # ─── Public helpers (used by routes for email hooks) ─────────

    async def get_entry(
        self, user_id: uuid.UUID, service: str = "memory_vault"
    ) -> WaitlistEntry | None:
        """Get a waitlist entry (public accessor for route layer)."""
        return await self._get_entry(user_id, service)

    async def get_entry_by_code(
        self, referral_code: str, service: str = "memory_vault"
    ) -> WaitlistEntry | None:
        """Look up entry by referral code."""
        result = await self.db.execute(
            select(WaitlistEntry).where(
                WaitlistEntry.referral_code == referral_code,
                WaitlistEntry.service == service,
            )
        )
        return result.scalar_one_or_none()

    # ─── Helpers ──────────────────────────────────────────────────

    async def _get_entry(
        self, user_id: uuid.UUID, service: str
    ) -> WaitlistEntry | None:
        result = await self.db.execute(
            select(WaitlistEntry).where(
                WaitlistEntry.user_id == user_id,
                WaitlistEntry.service == service,
            )
        )
        return result.scalar_one_or_none()

    async def _next_position(self, service: str) -> int:
        result = await self.db.execute(
            select(func.coalesce(func.max(WaitlistEntry.position), 0)).where(
                WaitlistEntry.service == service
            )
        )
        return (result.scalar() or 0) + 1

    async def _total_pending(self, service: str) -> int:
        result = await self.db.execute(
            select(func.count(WaitlistEntry.id)).where(
                WaitlistEntry.service == service,
                WaitlistEntry.status == "pending",
            )
        )
        return result.scalar() or 0

    async def _count_ahead(self, position: int, service: str) -> int:
        result = await self.db.execute(
            select(func.count(WaitlistEntry.id)).where(
                WaitlistEntry.service == service,
                WaitlistEntry.status == "pending",
                WaitlistEntry.position < position,
            )
        )
        return result.scalar() or 0

    async def _unique_referral_code(self) -> str:
        for _ in range(10):
            code = _generate_referral_code()
            existing = await self.db.execute(
                select(WaitlistEntry.id).where(WaitlistEntry.referral_code == code)
            )
            if not existing.scalar_one_or_none():
                return code
        raise RuntimeError("Failed to generate unique referral code")

    @staticmethod
    def _serialize(entry: WaitlistEntry) -> dict:
        return {
            "id": str(entry.id),
            "user_id": str(entry.user_id),
            "email": entry.email,
            "display_name": entry.display_name,
            "service": entry.service,
            "status": entry.status,
            "position": entry.position,
            "referral_code": entry.referral_code,
            "referred_by_code": entry.referred_by_code,
            "referral_count": entry.referral_count,
            "joined_at": entry.joined_at.isoformat() if entry.joined_at else None,
            "approved_at": entry.approved_at.isoformat() if entry.approved_at else None,
            "source": entry.source,
        }
