"""
Per‑client MCP setup snippets returned in the pair‑claim response.

When an AI claims a pair code we send back a `setup` block telling the AI:
  - which config file to write/edit on the user's machine
  - exactly what JSON/TOML to put there
  - what the user has to restart afterwards

The AI's job is then to surface the snippet to the user (or write it
itself if it has filesystem access). This is the piece that makes Kemory
persist across future sessions instead of needing a fresh pair every time.

We default to **remote/URL‑based MCP transport** (`url` + `headers`) so the
user doesn't need a local Python script. Some older clients only speak
stdio — we still emit the URL form because every actively‑maintained MCP
client now supports it; if a user's client refuses the URL form, the AI
can fall back and surface the stdio path it knows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class ClientSetup:
    client_id: str  # canonical id used in payload
    display: str  # human label
    config_path: str  # where the user pastes/edits
    format: str  # "json" | "toml"
    snippet: str  # ready‑to‑paste config
    restart_hint: str  # what to restart


def _json_snippet(mcp_url: str, api_key: str) -> str:
    """Standard `mcpServers` JSON shape used by Claude Desktop, Cursor,
    Cline, Windsurf, and most newer MCP clients."""
    return json.dumps(
        {
            "mcpServers": {
                "kemory": {
                    "url": mcp_url,
                    "headers": {"X-API-Key": api_key},
                }
            }
        },
        indent=2,
    )


def _codex_toml(mcp_url: str, api_key: str) -> str:
    """Codex CLI's TOML form. `[mcp_servers.kemory]` table."""
    return "[mcp_servers.kemory]\n" f'url = "{mcp_url}"\n' f'headers = {{ "X-API-Key" = "{api_key}" }}\n'


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build_setup(client_name: str, mcp_url: str, api_key: str) -> ClientSetup:
    """Return the right config snippet for the AI's client. Falls back to a
    generic JSON form when we don't recognise the client_name."""
    s = _slug(client_name)
    j = _json_snippet(mcp_url, api_key)

    if "codex" in s or "chatgpt" in s:
        return ClientSetup(
            client_id="codex",
            display="ChatGPT / Codex CLI",
            config_path="~/.codex/config.toml",
            format="toml",
            snippet=_codex_toml(mcp_url, api_key),
            restart_hint="Restart the Codex CLI (or run `codex restart`).",
        )
    if "claude-desktop" in s or s == "claude":
        return ClientSetup(
            client_id="claude-desktop",
            display="Claude Desktop",
            config_path=(
                "macOS: ~/Library/Application Support/Claude/claude_desktop_config.json | "
                "Windows: %APPDATA%\\Claude\\claude_desktop_config.json"
            ),
            format="json",
            snippet=j,
            restart_hint="Quit Claude Desktop fully (⌘Q) and reopen it.",
        )
    if "claude-code" in s:
        return ClientSetup(
            client_id="claude-code",
            display="Claude Code",
            config_path="~/.config/claude-code/mcp_servers.json (or run `claude code mcp add kemory --url <mcp_url> --header X-API-Key=<api_key>`)",
            format="json",
            snippet=j,
            restart_hint="Reload your shell or restart the Claude Code session.",
        )
    if "cursor" in s:
        return ClientSetup(
            client_id="cursor",
            display="Cursor",
            config_path="Settings → Features → MCP → Add new MCP server",
            format="json",
            snippet=j,
            restart_hint="Cursor picks up MCP changes immediately — refresh the MCP panel if needed.",
        )
    if "windsurf" in s:
        return ClientSetup(
            client_id="windsurf",
            display="Windsurf",
            config_path="~/.codeium/windsurf/mcp_config.json",
            format="json",
            snippet=j,
            restart_hint="Restart Windsurf or reload the Cascade panel.",
        )
    if "cline" in s:
        return ClientSetup(
            client_id="cline",
            display="Cline",
            config_path="VS Code → Cline extension → MCP Servers → Edit cline_mcp_settings.json",
            format="json",
            snippet=j,
            restart_hint="Reload the Cline extension after saving.",
        )
    if "gemini" in s:
        return ClientSetup(
            client_id="gemini-cli",
            display="Gemini CLI",
            config_path="~/.config/gemini-cli/mcp_servers.json",
            format="json",
            snippet=j,
            restart_hint="Restart the Gemini CLI session.",
        )
    if "ollama" in s:
        return ClientSetup(
            client_id="ollama",
            display="Ollama (MCP‑aware front end)",
            config_path="Depends on your Ollama front‑end — most accept the standard `mcpServers` JSON.",
            format="json",
            snippet=j,
            restart_hint="Restart your Ollama front‑end after saving.",
        )

    return ClientSetup(
        client_id="generic",
        display=client_name,
        config_path="Wherever your MCP client stores its server list (often `mcpServers` JSON).",
        format="json",
        snippet=j,
        restart_hint="Restart your MCP client after saving.",
    )
