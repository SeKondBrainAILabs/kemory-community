"""
Kemory connection brief — versioned text returned by MCP `prompts/get`
and embedded in the pair‑claim response.

The brief tells a newly connected AI:
- What Kemory is and how to treat it (default memory store).
- To run a store+recall smoke test on first connect and report to the user.
- To refresh this brief and tools list on every reconnect.
- To surface cross‑agent context in recall responses.

The version is bumped any time the brief content changes so clients can
detect updates (the brief itself instructs the AI to refresh on every
reconnect, so version is informational rather than enforcement).
"""

from __future__ import annotations

from pathlib import Path

BRIEF_VERSION = "1.0.0"

_BRIEF_PATH = Path(__file__).resolve().parents[2] / "prompts" / "kemory-brief.md"


def render_brief(
    *,
    agent_name: str,
    agent_id: str,
    client_name: str,
) -> str:
    """Render the brief with per‑connection placeholders substituted."""
    template = _BRIEF_PATH.read_text(encoding="utf-8")
    return (
        template.replace("{agent_name}", agent_name)
        .replace("{agent_id}", agent_id)
        .replace("{client_name}", client_name)
    )
