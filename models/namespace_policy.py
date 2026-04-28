"""
S9N Memory Vault — Namespace Consolidation Policy Model (KMV-S13.1)

Defines per-namespace configuration for the memory consolidation and decay system.
Each namespace can have its own decay rate, retention window, and auto-consolidation toggle.

Architecture note:
  Memory Vault is SHORT-TERM working memory. Cognition OS is LONG-TERM semantic memory.
  This model governs how memories transition from short-term to long-term storage.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, Text

from backend.core.database import Base
from backend.core.types import GUID

# Namespaces that are exempt from auto-archiving by default.
# These contain stable, long-lived knowledge that should not be decayed.
EXEMPT_NAMESPACES = {"skills", "system", "config"}


class NamespacePolicy(Base):
    """
    Per-namespace consolidation and decay policy.

    Controls how memories in a given namespace are:
    - Decayed over time (consolidation_weight reduction)
    - Automatically archived after a retention window
    - Pushed to Cognition OS for long-term storage

    Default values represent a sensible baseline for conversational namespaces.
    Stable namespaces (skills, system) should set auto_consolidate=False.
    """

    __tablename__ = "kemory_namespace_policies"

    # ── Identity ──────────────────────────────────────────────────
    policy_id = Column(
        GUID(),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
        comment="Unique policy identifier",
    )
    namespace = Column(
        String(100),
        nullable=False,
        unique=True,
        index=True,
        comment="Namespace this policy applies to (matches Memory.namespace)",
    )

    # ── Decay Configuration ────────────────────────────────────────
    decay_rate = Column(
        Float,
        nullable=False,
        default=0.1,
        comment=(
            "Daily decay rate applied to consolidation_weight (0.0-1.0). "
            "Default 0.1 = 10% reduction per day. "
            "weight_new = max(0.01, weight * (1 - decay_rate))"
        ),
    )
    retention_days = Column(
        Integer,
        nullable=False,
        default=10,
        comment=(
            "Number of days to retain memories before auto-archiving. "
            "Memories older than this are archived regardless of Cognition OS availability."
        ),
    )

    # ── Consolidation Configuration ────────────────────────────────
    auto_consolidate = Column(
        Boolean,
        nullable=False,
        default=True,
        comment=(
            "If True, memories are automatically pushed to Cognition OS during the daily job. "
            "Set to False for stable namespaces (skills, system) that should not be decayed."
        ),
    )
    consolidation_hour_utc = Column(
        Integer,
        nullable=False,
        default=2,
        comment="UTC hour at which the daily consolidation job runs for this namespace (0-23).",
    )

    # ── Metadata ──────────────────────────────────────────────────
    description = Column(
        String(500),
        nullable=True,
        comment="Human-readable description of why this policy exists.",
    )

    # ── Consolidated cross-session summary (Namespace tab + agent summary) ─
    consolidated_summary = Column(
        Text,
        nullable=True,
        comment=(
            "Rolling cross-session summary of this namespace, kept in sync by "
            "the L3.1 compression pipeline. When absent we fall back to the "
            "latest L3 concept memory (L3.0 fallback)."
        ),
    )
    consolidated_summary_tier = Column(
        String(8),
        nullable=True,
        comment="Tier label of the current consolidated_summary (e.g. L3, L3.1).",
    )
    consolidated_summary_updated_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Timestamp when consolidated_summary was last upserted.",
    )
    related_namespaces = Column(
        JSON,
        nullable=True,
        comment=(
            "Array of {namespace, similarity, detected_at} entries — populated "
            "when the namespace matcher detected a 60-90% similar namespace at "
            "create time. Surfaced in the Namespaces tab so the user can merge."
        ),
    )

    created_by = Column(
        GUID(),
        nullable=True,
        comment="User ID who created or last modified this policy.",
    )

    # ── Timestamps ────────────────────────────────────────────────
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    def __repr__(self):
        return (
            f"<NamespacePolicy(namespace={self.namespace}, "
            f"decay_rate={self.decay_rate}, retention_days={self.retention_days}, "
            f"auto_consolidate={self.auto_consolidate})>"
        )
