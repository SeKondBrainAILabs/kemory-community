"""
S9N Memory Vault — Team Model (MV3-E02)

Team data model with roles and membership management.
Teams provide shared memory spaces with configurable visibility.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Boolean, Integer, Index, UniqueConstraint
from backend.core.database import Base
from backend.core.types import GUID, JSONType


class Team(Base):
    """A team that shares a memory space."""
    __tablename__ = "teams"

    team_id = Column(
        GUID(), primary_key=True, default=uuid.uuid4, nullable=False,
    )
    org_id = Column(GUID(), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    description = Column(String(1000), nullable=True)
    visibility = Column(
        String(20), nullable=False, default="team",
        comment="Default visibility for team memories: team or org-public",
    )
    settings = Column(JSONType(), nullable=True, default=dict)
    created_by = Column(GUID(), nullable=False)
    created_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    is_deleted = Column(Boolean, nullable=False, default=False)

    def __repr__(self):
        return f"<Team(team_id={self.team_id}, name={self.name})>"


class TeamMember(Base):
    """A user's membership in a team."""
    __tablename__ = "team_members"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(GUID(), nullable=False, index=True)
    user_id = Column(GUID(), nullable=False, index=True)
    role = Column(
        String(20), nullable=False, default="member",
        comment="owner, admin, member, viewer",
    )
    can_write = Column(
        Boolean, nullable=False, default=False,
        comment="Whether this member can write to team memory spaces",
    )
    joined_at = Column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="uq_team_member"),
        Index("idx_team_members_user", "user_id"),
    )

    def __repr__(self):
        return f"<TeamMember(team_id={self.team_id}, user_id={self.user_id}, role={self.role})>"
