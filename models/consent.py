"""
S9N Memory Vault — JIT Consent Request Model

Spec reference: Appendix A.1, Table kemory_consent_requests
Stores Just-in-Time consent prompts sent to users when agents request elevated access.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, DateTime, Index
)
from backend.core.database import Base
from backend.core.types import GUID, JSONType


class ConsentRequest(Base):
    """
    A Just-in-Time (JIT) consent request.

    Created when the Gatekeeper evaluates a permission rule with action='jit'.
    The user must approve or deny the request within the timeout period (default: 60s).
    If the timeout expires, the default action is DENY.
    """
    __tablename__ = "kemory_consent_requests"

    consent_id = Column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Unique identifier for the consent request",
    )

    user_id = Column(
        GUID(),
        nullable=False,
        index=True,
        comment="ID of the user being prompted",
    )

    agent_id = Column(
        GUID(),
        nullable=False,
        comment="ID of the agent requesting access",
    )

    # What the agent is requesting
    requested_scope = Column(
        String(100),
        nullable=False,
        comment="The scope the agent is requesting access to",
    )

    requested_resource = Column(
        String(255),
        nullable=True,
        comment="Specific resource being requested (namespace, memory category, etc.)",
    )

    # Context for the user
    context = Column(
        JSONType(),
        nullable=True,
        comment="Additional context to help the user make a decision (agent name, reason, etc.)",
    )

    # Status lifecycle
    status = Column(
        String(20),
        nullable=False,
        default="pending",
        comment="Status: pending, approved, denied, timeout",
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this consent request expires (default: created_at + 60s)",
    )

    resolved_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the user responded (or when timeout occurred)",
    )

    __table_args__ = (
        Index("idx_consent_user_status", "user_id", "status"),
        Index("idx_consent_agent", "agent_id"),
    )

    def __repr__(self):
        return f"<ConsentRequest(consent_id={self.consent_id}, scope={self.requested_scope}, status={self.status})>"
