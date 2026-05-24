"""
S9N Memory Vault — ORM Models

All SQLAlchemy models for the S9N Memory Vault schema.
Models follow the schema defined in Appendix A of the spec.
"""

from backend.models.agent import AgentRegistry
from backend.models.ai_chat import (
    AIChat,
    AIChatArtifact,
    AIChatTurn,
    ChatNamespaceMapping,
)
from backend.models.audit import AuditLog
from backend.models.consent import ConsentRequest
from backend.models.memory import Memory
from backend.models.memory_event import MemoryEvent
from backend.models.namespace_policy import NamespacePolicy
from backend.models.permission import PermissionRule
from backend.models.session_summary import SessionSummary
from backend.models.team import Team, TeamMember  # WS-4 + WS-9

__all__ = [
    "AgentRegistry",
    "AIChat",
    "AIChatArtifact",
    "AIChatTurn",
    "ChatNamespaceMapping",
    "PermissionRule",
    "AuditLog",
    "ConsentRequest",
    "Memory",
    "MemoryEvent",
    "NamespacePolicy",
    "SessionSummary",
    "Team",
    "TeamMember",
]
