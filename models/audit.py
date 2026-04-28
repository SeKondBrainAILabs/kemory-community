"""
S9N Memory Vault — Audit Log Model

Spec reference: Appendix A.1, Table s9nmv_audit_log
Append-only audit trail for all agent access attempts and permission evaluations.
Includes hash chain for tamper detection.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, Index, String

from backend.core.database import Base
from backend.core.types import GUID, IPAddress, JSONType


class AuditLog(Base):
    """
    Immutable audit record for every agent access attempt.

    This table is append-only — no UPDATE or DELETE operations are permitted.
    Each record includes a hash_chain linking to the previous entry for
    tamper detection. Supports GDPR compliance by recording all data access.
    """

    __tablename__ = "s9nmv_audit_log"

    audit_id = Column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Unique identifier for the audit entry",
    )

    user_id = Column(
        GUID(),
        nullable=False,
        index=True,
        comment="ID of the user whose vault was accessed",
    )

    agent_id = Column(
        GUID(),
        nullable=True,
        index=True,
        comment="ID of the agent that made the request",
    )

    # ── Multi-tenancy (WS-1 / WS-8) ───────────────────────────────
    # Populated from AuthContext.org_id at audit emission time. Required
    # for per-tenant audit exports (GDPR/SOC2) and the per-org observability
    # dashboards (WS-8). Nullable for migration safety; revision 011 enforces.
    org_id = Column(
        String(64),
        nullable=True,
        comment="Tenant context of the audited action (WS-8).",
    )
    team_id = Column(
        String(64),
        nullable=True,
        comment="Team context, when the action was team-scoped (WS-8).",
    )

    # Action details
    action = Column(
        String(50),
        nullable=False,
        comment="Action performed: memory:write, memory:read, memory:delete, permission:evaluate",
    )

    resource_type = Column(
        String(50),
        nullable=False,
        default="memory",
        comment="Type of resource: memory, permission, agent",
    )

    resource_id = Column(
        String(255),
        nullable=True,
        comment="ID of the specific resource accessed",
    )

    namespace = Column(
        String(255),
        nullable=True,
        comment="Namespace context of the action",
    )

    # Outcome
    outcome = Column(
        String(20),
        nullable=False,
        comment="Result: success, denied, error",
    )

    # Detailed context
    details = Column(
        JSONType(),
        nullable=True,
        comment="Detailed context: rules matched, scopes checked, decision chain",
    )

    # Request metadata
    ip_address = Column(
        IPAddress(),
        nullable=True,
        comment="IP address of the requesting agent",
    )

    # Hash chain for tamper detection
    hash_chain = Column(
        String(64),
        nullable=False,
        default="GENESIS",
        comment="SHA-256 hash linking to previous audit entry for tamper detection",
    )

    # Timestamp — immutable, set at creation
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="When the action occurred (UTC)",
    )

    __table_args__ = (
        Index("idx_audit_log_user_time", "user_id", "created_at"),
        Index("idx_audit_log_agent_time", "agent_id", "created_at"),
        Index("idx_audit_log_action", "action", "outcome"),
        Index("idx_audit_log_org_time", "org_id", "created_at"),
    )

    def __repr__(self):
        return f"<AuditLog(audit_id={self.audit_id}, action={self.action}, outcome={self.outcome})>"
