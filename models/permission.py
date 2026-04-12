"""
S9N Memory Vault — Permission Rule Model

Spec reference: Appendix A.1, Table s9nmv_permission_rules
Stores user-defined permission rules evaluated by the Gatekeeper.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, DateTime, Integer, Boolean, Index
)
from backend.core.database import Base
from backend.core.types import GUID, JSONType


class PermissionRule(Base):
    """
    A user-defined permission rule for the Gatekeeper.

    Rules are evaluated in priority order (lower number = higher priority).
    The Gatekeeper evaluates rules top-down and returns the first match.
    If no rule matches, the default action is DENY (default-deny posture).
    """
    __tablename__ = "s9nmv_permission_rules"

    rule_id = Column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Unique identifier for the permission rule",
    )

    user_id = Column(
        GUID(),
        nullable=False,
        index=True,
        comment="ID of the user who owns this rule",
    )

    agent_id = Column(
        GUID(),
        nullable=True,
        comment="ID of the agent this rule applies to. NULL = applies to all agents.",
    )

    # Scope and action
    scope = Column(
        String(100),
        nullable=False,
        comment="The scope this rule governs: memory:read, memory:write, memory:delete, namespace:*, etc.",
    )

    action = Column(
        String(20),
        nullable=False,
        comment="What happens when this rule matches: allow, deny, jit (just-in-time consent)",
    )

    # Priority (lower = evaluated first)
    priority = Column(
        Integer,
        nullable=False,
        default=100,
        comment="Evaluation priority. Lower numbers are evaluated first.",
    )

    # Optional constraints
    conditions = Column(
        JSONType(),
        nullable=True,
        comment="Optional JSON conditions: time_window, namespace_filter, rate_limit, etc.",
    )

    # Namespace filter
    namespace_filter = Column(
        String(255),
        nullable=True,
        comment="Glob pattern for namespace matching (e.g., 'agent_name:*' or 'shared')",
    )

    # Active flag
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether this rule is currently active",
    )

    # Timestamps
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index("idx_permission_rules_user_agent", "user_id", "agent_id"),
        Index("idx_permission_rules_scope", "user_id", "scope"),
        Index("idx_permission_rules_priority", "user_id", "priority"),
    )

    def __repr__(self):
        return f"<PermissionRule(rule_id={self.rule_id}, scope={self.scope}, action={self.action})>"
