"""Lightweight authenticated identity shared by community API layers."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class AuthContext(BaseModel):
    """The immutable local identity shape retained for wire compatibility."""

    user_id: uuid.UUID
    auth_method: str
    agent_id: uuid.UUID | None = None
    agent_name: str = ""
    scopes: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    org_id: str | None = None
    acting_user_id: uuid.UUID | None = None
    team_ids: list[str] = Field(default_factory=list)
    org_role: str | None = None
    org_type: str | None = None
