"""
S9N Memory Vault — Waitlist Models

Per-service beta waitlist with referral tracking.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    BigInteger,
    Integer,
    DateTime,
    Index,
    UniqueConstraint,
)

from backend.core.database import Base
from backend.core.types import GUID


class WaitlistEntry(Base):
    """A user's waitlist registration for a specific service."""

    __tablename__ = "s9nmv_waitlist"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(GUID(), nullable=False)
    email = Column(String(255), nullable=False)
    display_name = Column(String(200), nullable=True)
    service = Column(String(50), nullable=False, default="memory_vault")
    status = Column(String(20), nullable=False, default="pending")
    position = Column(BigInteger, nullable=False)
    referral_code = Column(String(20), nullable=False, unique=True)
    referred_by_code = Column(String(20), nullable=True)
    referral_count = Column(Integer, nullable=False, default=0)
    joined_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    approved_at = Column(DateTime(timezone=True), nullable=True)
    source = Column(String(50), nullable=True, default="organic")

    __table_args__ = (
        UniqueConstraint("user_id", "service", name="uq_waitlist_user_service"),
        Index("ix_waitlist_status", "status"),
        Index("ix_waitlist_service", "service"),
        Index("ix_waitlist_position", "position"),
    )


class ReferralEvent(Base):
    """Tracks successful referral sign-ups."""

    __tablename__ = "s9nmv_referral_events"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    referrer_user_id = Column(GUID(), nullable=False)
    referred_user_id = Column(GUID(), nullable=False)
    referral_code = Column(String(20), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "referrer_user_id", "referred_user_id",
            name="uq_referral_pair",
        ),
        Index("ix_referral_referrer", "referrer_user_id"),
    )
