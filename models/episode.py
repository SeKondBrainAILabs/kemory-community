"""
kemory/models/episode.py
===============================
Pydantic data models for Memory Vault episodes.

These models are shared across all storage backends and the MemoryService.
They define the canonical shape of an episode as it flows through the system.

Story: KMV-S1.2 — Refactor Production Backends
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


class EpisodeCreate(BaseModel):
    """
    Input model for creating a new memory episode.

    Attributes
    ----------
    content:
        The raw text content of the episode.
    source_agent:
        Identifier of the agent that created this episode.
    session_id:
        Session context identifier.
    org_id:
        Organisation scope identifier (used for multi-tenant isolation).
    valid_at:
        ISO-8601 UTC datetime when this fact became true.
        Defaults to the current UTC time.
    extra:
        Optional arbitrary metadata dictionary.
    """

    content: str = Field(..., description="Raw text content of the episode.")
    source_agent: str = Field(..., description="Identifier of the creating agent.")
    session_id: str = Field(..., description="Session context identifier.")
    org_id: str = Field(..., description="Organisation scope identifier.")
    valid_at: str = Field(
        default_factory=_utcnow_iso,
        description="ISO-8601 UTC datetime when this fact became true.",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional arbitrary metadata.",
    )

    @field_validator("content", mode="before")
    @classmethod
    def content_must_not_be_none(cls, v: object) -> object:
        """Content may be empty string but must not be None."""
        if v is None:
            raise ValueError("content must not be None")
        return v

    @field_validator("source_agent", "session_id", "org_id")
    @classmethod
    def string_fields_must_not_be_empty(cls, v: str, info: Any) -> str:
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return v


class EpisodeRecord(BaseModel):
    """
    Full episode record as stored and returned by the backend.

    Attributes
    ----------
    id:
        UUID v4 string. Auto-generated if not provided.
    content:
        Raw text content.
    source_agent:
        Identifier of the creating agent.
    session_id:
        Session context identifier.
    org_id:
        Organisation scope identifier.
    created_at:
        ISO-8601 UTC datetime when the record was persisted.
    valid_at:
        ISO-8601 UTC datetime when this fact became true.
    invalid_at:
        ISO-8601 UTC datetime when this fact was superseded.
        ``None`` means the episode is still valid.
    extra:
        Optional arbitrary metadata dictionary.
    score:
        Relevance score from a semantic search (0.0–1.0).
        Only populated when returned from ``search_episodes``.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str
    source_agent: str
    session_id: str
    org_id: str
    created_at: str = Field(default_factory=_utcnow_iso)
    valid_at: str = Field(default_factory=_utcnow_iso)
    invalid_at: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None

    @property
    def is_valid(self) -> bool:
        """Return True if the episode has not been invalidated."""
        return self.invalid_at is None

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dictionary (excludes None score)."""
        d = self.model_dump()
        if d["score"] is None:
            del d["score"]
        return d

    @classmethod
    def from_create(cls, create: EpisodeCreate) -> EpisodeRecord:
        """Construct a full EpisodeRecord from an EpisodeCreate input."""
        return cls(
            content=create.content,
            source_agent=create.source_agent,
            session_id=create.session_id,
            org_id=create.org_id,
            valid_at=create.valid_at,
            extra=create.extra,
        )
