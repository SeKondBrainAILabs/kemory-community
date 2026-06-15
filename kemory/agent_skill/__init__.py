"""
kemory/agent_skill
========================
Agent Skill — hybrid memory model guidance for LLM agents.

Provides the system prompt text (§8.11 V2-F10a) that teaches agents
how to use vault_context + memory_search effectively.

Story: KMV-V2-E10
"""

from kemory.agent_skill.skill import AGENT_SKILL_PROMPT, get_skill_prompt

__all__ = ["AGENT_SKILL_PROMPT", "get_skill_prompt"]
