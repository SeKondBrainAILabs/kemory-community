"""
Kemory — namespace second-tier tag profiles (S9N-6612).

A namespace accumulates content from more than one real-world context —
the canonical repro is ``project:ai-expansion-strategy`` holding Builder.ai's
Insight-deal chats, EY client work, Al Ansari upskilling AND SeKondBrain's
sovereign-AI strategy, collapsed by shared corporate-AI vocabulary. Rather
than moving memories out (destructive, review-heavy), the namespace gets an
automatic second tier: ``namespace:tag`` segments that are shown separately
in the UI while search/recall continue to span the whole parent namespace.

One row here = one tag's *profile* within (user, namespace): its running
embedding centroid, entity anchor terms, observed era window, and member
count. The resolver (``backend/services/namespace_tag_service.py``) scores
new items against these profiles — entity-first, embedding second, era as an
optional boost (bulk-imported history has no dates until the extension's
S9N-6613 repopulation sweep lands them).

Tagging is automatic and reversible (clear the column); only *promotion* of
a tag out to a full namespace is a reviewed operation
(``scripts/promote_namespace_tag.py``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from backend.core.database import Base
from backend.core.types import GUID, JSONType


class NamespaceTag(Base):
    """Profile of one automatic segment (tag) within a user's namespace."""

    __tablename__ = "kemory_namespace_tags"

    tag_id = Column(GUID(), primary_key=True, default=uuid.uuid4, nullable=False)
    user_id = Column(GUID(), nullable=False, index=True)
    org_id = Column(String(64), nullable=False)

    namespace = Column(
        String(100),
        nullable=False,
        comment="Parent namespace this tag segments. Never rewritten by tagging.",
    )
    tag = Column(
        String(120),
        nullable=False,
        comment="Slug shown as namespace:tag (LLM-proposed, slugified).",
    )
    label = Column(
        String(200),
        nullable=False,
        comment="Human-readable segment name (LLM-proposed, renameable).",
    )
    description = Column(Text(), nullable=True)

    entity_terms = Column(
        JSONType(),
        nullable=True,
        comment=(
            "Lowercased anchor entities (companies/orgs/products/people) that "
            "discriminate this segment — e.g. ['builder.ai','insight partners'] "
            "vs ['sekondbrain']. Primary matching signal (entity-first)."
        ),
    )
    centroid = Column(
        JSONType(),
        nullable=True,
        comment=(
            "384-float L2-normalised running mean of member embeddings "
            "(bge-small-en-v1.5). Secondary matching signal."
        ),
    )
    member_count = Column(Integer(), nullable=False, default=0)

    occurred_from = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Earliest member content date observed (S9N-6613 occurred_at).",
    )
    occurred_to = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="Latest member content date observed. Era window is a BOOST, never a gate.",
    )

    source = Column(
        String(20),
        nullable=False,
        default="auto",
        comment="auto (ingest resolver) | backfill (retro script) | user (manual rename/create)",
    )
    active = Column(Boolean(), nullable=False, default=True)

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

    __table_args__ = (
        UniqueConstraint("user_id", "namespace", "tag", name="uq_namespace_tags_user_ns_tag"),
        Index("idx_namespace_tags_user_ns", "user_id", "namespace"),
        Index("idx_namespace_tags_org_user", "org_id", "user_id"),
    )

    def __repr__(self) -> str:
        return f"<NamespaceTag({self.namespace}:{self.tag}, members={self.member_count})>"
