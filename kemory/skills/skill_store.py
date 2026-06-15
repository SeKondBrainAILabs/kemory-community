"""
kemory/skills/skill_store.py
====================================
Agent Skill Memory — stores learned procedures as versioned memories.

Skills are memories with content_type='skill' and a structured schema:
- name: skill identifier
- trigger: when to use this skill
- steps: ordered list of steps
- version: auto-incremented on update
- visibility: agent-private, user-private, team, org-public

Stories: MV3-S03.1 through S03.4
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Skill content type constant
SKILL_CONTENT_TYPE = "skill"

# Skill schema for validation
SKILL_SCHEMA_FIELDS = {"name", "trigger", "steps"}


def validate_skill(skill_data: dict[str, Any]) -> bool:
    """Validate a skill dict has required fields."""
    return all(f in skill_data for f in SKILL_SCHEMA_FIELDS)


def format_skill_content(
    name: str,
    trigger: str,
    steps: list[str],
    version: int = 1,
) -> str:
    """
    Format a skill as structured JSON content for storage.

    Story: MV3-S03.1
    """
    skill = {
        "name": name,
        "trigger": trigger,
        "steps": steps,
        "version": version,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    return json.dumps(skill)


def parse_skill_content(content: str) -> dict[str, Any] | None:
    """Parse a skill from stored memory content."""
    try:
        data = json.loads(content)
        if validate_skill(data):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return None


async def store_skill(
    backend: Any,
    name: str,
    trigger: str,
    steps: list[str],
    source_agent: str,
    org_id: str,
    *,
    session_id: str = "skill-store",
    visibility: str = "user-private",
    version: int = 1,
) -> str:
    """
    Store a learned skill as a memory episode.

    Story: MV3-S03.2

    Parameters
    ----------
    backend: StorageBackend instance
    name: Skill identifier (e.g. "deploy-to-staging")
    trigger: When to use this skill (e.g. "user asks to deploy")
    steps: Ordered list of procedure steps
    source_agent: Agent that learned this skill
    org_id: Organisation scope
    visibility: Visibility tier
    version: Skill version number

    Returns
    -------
    str: Episode ID of the stored skill
    """
    content = format_skill_content(name, trigger, steps, version)

    metadata: dict[str, Any] = {
        "source_agent": source_agent,
        "session_id": session_id,
        "org_id": org_id,
        "valid_at": datetime.now(UTC).isoformat(),
        "namespace": f"skills:{source_agent}",
        "content_type": SKILL_CONTENT_TYPE,
        "extra": {
            "memory_type": "procedural",
            "content_type": SKILL_CONTENT_TYPE,
            "skill_name": name,
            "skill_version": version,
            "visibility": visibility,
        },
    }

    episode_id = await backend.add_episode(content, metadata)
    logger.info("skill_store: stored skill '%s' v%d as %s", name, version, episode_id)
    return episode_id


async def list_skills(
    backend: Any,
    org_id: str,
    source_agent: str | None = None,
) -> list[dict[str, Any]]:
    """
    List all stored skills for an org (optionally filtered by agent).

    Story: MV3-S03.3
    """
    episodes = await backend.list_episodes(
        org_id=org_id,
        include_invalid=False,
    )

    skills = []
    for ep in episodes:
        extra = ep.get("extra_json", ep.get("extra", "{}"))
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except Exception:
                extra = {}

        if extra.get("content_type") != SKILL_CONTENT_TYPE:
            continue

        if source_agent and ep.get("source_agent") != source_agent:
            continue

        parsed = parse_skill_content(ep.get("content", ""))
        if parsed:
            skills.append(
                {
                    "episode_id": ep.get("id"),
                    "skill": parsed,
                    "source_agent": ep.get("source_agent"),
                    "created_at": ep.get("created_at"),
                    "visibility": extra.get("visibility", "user-private"),
                }
            )

    return skills
