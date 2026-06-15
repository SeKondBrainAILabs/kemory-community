"""
S9N Memory Vault — Agent Registry Model

Spec reference: Appendix A.1, Table kemory_agent_registry
Stores registered agents with their declared scopes, API key hashes, and usage stats.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, Column, DateTime, Index, String, UniqueConstraint

from backend.core.database import Base
from backend.core.types import GUID, JSONType


class AgentRegistry(Base):
    """
    Represents a registered AI agent in the S9N Memory Vault system.

    Each agent is registered by a user and has:
    - Declared scopes (what data types it wants to access)
    - An API key (bcrypt hashed) for authentication
    - A status lifecycle: pending_approval -> active -> suspended/revoked
    - Usage counters for reads, writes, and denied requests
    """

    __tablename__ = "kemory_agent_registry"

    # Primary key
    agent_id = Column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Unique identifier for the agent",
    )

    # Foreign key to users table (user who registered this agent)
    user_id = Column(
        GUID(),
        nullable=False,
        index=True,
        comment="ID of the user who registered this agent",
    )

    # ── Multi-tenancy (WS-1 / WS-5) ──────────────────────────────
    # Bound to caller's org at /v1/agents creation time (WS-5). A leaked
    # key in org A cannot read org B because authenticate_api_key() reads
    # this column and seeds AuthContext.org_id from it — never from request
    # headers. Nullable for migration safety; revision 011 enforces NOT NULL.
    org_id = Column(
        String(64),
        nullable=True,
        index=True,
        comment="Tenant the key is bound to (WS-5). Read by authenticate_api_key().",
    )

    # Agent metadata
    agent_name = Column(
        String(100),
        nullable=False,
        comment="Human-readable agent name, unique per user",
    )
    agent_description = Column(
        String(500),
        nullable=False,
        comment="Description of what the agent does",
    )

    # Declared scopes — JSON array of scope objects
    declared_scopes = Column(
        JSONType(),
        nullable=False,
        default=list,
        comment="Array of scope objects declaring what data types the agent wants",
    )

    # Authentication
    api_key_hash = Column(
        String(255),
        nullable=False,
        comment="Bcrypt hash of the agent's API key",
    )
    api_key_prefix = Column(
        String(16),
        nullable=True,
        index=True,
        comment="SHA-256 prefix of the plaintext API key for O(1) lookup (avoids bcrypt scan)",
    )

    # Callback URL for verification and JIT consent
    callback_url = Column(
        String(2048),
        nullable=True,
        comment="Agent's callback URL for verification. No internal IPs allowed.",
    )

    # Status lifecycle
    status = Column(
        String(20),
        nullable=False,
        default="pending_approval",
        comment="Agent status: pending_approval, active, suspended, revoked",
    )

    # ── Kind (chats-v1) ───────────────────────────────────────────
    # 'agent'     = regular MCP / SDK agent (default)
    # 'extension' = Kanvas Chrome Extension install. Auth path is identical
    #               (same X-API-Key flow, same Gatekeeper checks); the kind
    #               only changes which mint/list endpoints surface the row
    #               and lets the dashboard render extension installs in
    #               their own tab. See backend/api/routes/extension_keys.py.
    agent_kind = Column(
        String(20),
        nullable=False,
        default="agent",
        comment="agent | extension. See chats-v1 migration 015.",
    )

    # Timestamps
    registered_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="When the agent was registered",
    )
    last_active_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last time the agent made an API call",
    )

    # Usage counters
    total_reads = Column(BigInteger, nullable=False, default=0)
    total_writes = Column(BigInteger, nullable=False, default=0)
    denied_requests = Column(BigInteger, nullable=False, default=0)

    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint("user_id", "agent_name", name="unique_agent_name_per_user"),
        Index("idx_agent_registry_user_id", "user_id"),
        Index("idx_agent_registry_status", "user_id", "status"),
        Index("idx_agent_registry_key_prefix", "api_key_prefix"),
        Index("idx_agent_registry_org_user", "org_id", "user_id"),
        Index("idx_agent_registry_kind", "user_id", "agent_kind"),
    )

    def __repr__(self):
        return f"<AgentRegistry(agent_id={self.agent_id}, name={self.agent_name}, status={self.status})>"
