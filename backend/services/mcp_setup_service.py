"""
Per‑client connection snippets returned in the pair‑claim response.

Two shapes:

1. **MCP‑capable clients** (Claude Desktop, Cursor, Cline, Windsurf, Codex CLI,
   Gemini CLI, etc.) get a `mcpServers` JSON or TOML snippet that registers
   Kemory as a permanent remote MCP server. `supports_mcp=True`,
   `format="json" | "toml"`.

2. **Clients without a custom‑MCP surface** (Gemini Web / Gemini app, plain
   ChatGPT free, voice‑only assistants, …) get a REST‑based system‑prompt
   block the user pastes into their Gem / Project / Custom Instructions /
   GPT. `supports_mcp=False`, `format="manual"`. The AI then calls Kemory
   via plain HTTP using the embedded API key.

The AI's job is to surface whichever block applies to the user's client
and tell them where to paste it. This is what makes Kemory persist across
future sessions instead of needing a fresh pair every time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class ClientSetup:
    client_id: str  # canonical id used in payload
    display: str  # human label
    supports_mcp: bool  # True → mcpServers config; False → REST instructions
    config_path: str  # where the user pastes/edits
    format: str  # "json" | "toml" | "manual"
    snippet: str  # ready‑to‑paste config or system‑prompt block
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


def _api_base(mcp_url: str) -> str:
    """Strip the `/mcp/v1` suffix to get the REST API base."""
    return re.sub(r"/mcp/v\d+/?$", "", mcp_url).rstrip("/")


def _rest_instructions(mcp_url: str, api_key: str) -> str:
    """System‑prompt block for clients that can't register MCP servers.

    Pasted into Gemini Gems, ChatGPT Custom Instructions, Claude Projects,
    etc. The AI calls Kemory via REST using the embedded API key — slower
    than MCP but works anywhere the AI can issue HTTP requests."""
    base = _api_base(mcp_url)
    return (
        "You have access to Kemory, a persistent cross-session memory store, "
        f"via REST API at {base} (header: `X-API-Key: {api_key}`).\n\n"
        "## Session bootstrap (do this on the first user turn)\n"
        f"1. GET {base}/api/v1/namespaces — list available buckets.\n"
        f"2. POST {base}/api/v1/memories/search with body "
        '{"query":"<topic>","limit":10} — pull prior memories.\n\n'
        "## Consent rule\n"
        "Always ask the user before storing a memory. Phrase it like: "
        "\"I'd like to save this to Kemory as a <namespace> memory so future "
        'sessions can recall it — okay?" Wait for a yes.\n\n'
        "## When to write (after the user agrees)\n"
        f"POST {base}/api/v1/memories with body "
        '{"namespace":"<ns>","content":"<text>","content_type":"text"}.\n'
        "- User preference → namespace `user:preferences`\n"
        "- User correction → namespace `user:feedback`\n"
        "- Project fact → namespace `project:<slug>`\n"
        "- Cross-project fact → namespace `shared`\n\n"
        "## Never store\n"
        "Passwords, API keys, OAuth tokens, credentials, or PII the user "
        "didn't explicitly ask you to remember.\n\n"
        "## Be transparent\n"
        'Tell the user "stored to Kemory namespace X because Y" in one line '
        "whenever you write."
    )


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build_setup(client_name: str, mcp_url: str, api_key: str) -> ClientSetup:
    """Return the right config snippet for the AI's client. Falls back to a
    generic JSON form when we don't recognise the client_name."""
    s = _slug(client_name)
    j = _json_snippet(mcp_url, api_key)

    if "codex" in s or "chatgpt-codex" in s or "openai-codex" in s:
        return ClientSetup(
            client_id="codex",
            display="ChatGPT / Codex CLI",
            supports_mcp=True,
            config_path="~/.codex/config.toml",
            format="toml",
            snippet=_codex_toml(mcp_url, api_key),
            restart_hint="Restart the Codex CLI (or run `codex restart`).",
        )
    # Plain ChatGPT (no Codex) — Custom GPTs accept tool/action URLs but the
    # free chat UI does not register remote MCP servers. Use the REST form.
    if "chatgpt" in s:
        return ClientSetup(
            client_id="chatgpt-web",
            display="ChatGPT (web/app)",
            supports_mcp=False,
            config_path=(
                "ChatGPT → Settings → Personalization → Custom Instructions "
                "(or create a Custom GPT and paste into 'Instructions')."
            ),
            format="manual",
            snippet=_rest_instructions(mcp_url, api_key),
            restart_hint="Start a new chat — instructions apply on the next turn.",
        )
    if "claude-desktop" in s or s == "claude":
        return ClientSetup(
            client_id="claude-desktop",
            display="Claude Desktop",
            supports_mcp=True,
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
            supports_mcp=True,
            config_path="~/.config/claude-code/mcp_servers.json (or run `claude code mcp add kemory --url <mcp_url> --header X-API-Key=<api_key>`)",
            format="json",
            snippet=j,
            restart_hint="Reload your shell or restart the Claude Code session.",
        )
    # Claude.ai web app — supports remote MCP via Settings → Connectors.
    if "claude-ai" in s or s == "claude-web":
        return ClientSetup(
            client_id="claude-web",
            display="Claude.ai (web)",
            supports_mcp=True,
            config_path="Settings → Connectors → Add custom connector",
            format="json",
            snippet=j,
            restart_hint="Start a new conversation; connector is available immediately.",
        )
    if "cursor" in s:
        return ClientSetup(
            client_id="cursor",
            display="Cursor",
            supports_mcp=True,
            config_path="Settings → Features → MCP → Add new MCP server",
            format="json",
            snippet=j,
            restart_hint="Cursor picks up MCP changes immediately — refresh the MCP panel if needed.",
        )
    if "windsurf" in s:
        return ClientSetup(
            client_id="windsurf",
            display="Windsurf",
            supports_mcp=True,
            config_path="~/.codeium/windsurf/mcp_config.json",
            format="json",
            snippet=j,
            restart_hint="Restart Windsurf or reload the Cascade panel.",
        )
    if "cline" in s:
        return ClientSetup(
            client_id="cline",
            display="Cline",
            supports_mcp=True,
            config_path="VS Code → Cline extension → MCP Servers → Edit cline_mcp_settings.json",
            format="json",
            snippet=j,
            restart_hint="Reload the Cline extension after saving.",
        )
    # Gemini CLI supports MCP via ~/.gemini/settings.json. Gemini Web /
    # gemini.google.com does NOT — custom MCP only works in the CLI or in
    # Gemini Enterprise (Cloud Console). For plain "Gemini" we assume web.
    if "gemini-cli" in s or ("gemini" in s and "cli" in s):
        return ClientSetup(
            client_id="gemini-cli",
            display="Gemini CLI",
            supports_mcp=True,
            config_path="~/.gemini/settings.json (under `mcpServers`)",
            format="json",
            snippet=j,
            restart_hint="Restart the Gemini CLI session.",
        )
    if "gemini" in s:
        return ClientSetup(
            client_id="gemini-web",
            display="Gemini (web/app)",
            supports_mcp=False,
            config_path=(
                "Gemini → Gems → Create a new Gem → paste this into 'Instructions'. "
                "(Gemini Web doesn't accept custom MCP servers — for native MCP "
                "install Gemini CLI: `npm install -g @google/gemini-cli`.)"
            ),
            format="manual",
            snippet=_rest_instructions(mcp_url, api_key),
            restart_hint="Start a new chat with the Gem you just created.",
        )
    if "ollama" in s:
        return ClientSetup(
            client_id="ollama",
            display="Ollama (MCP‑aware front end)",
            supports_mcp=True,
            config_path="Depends on your Ollama front‑end — most accept the standard `mcpServers` JSON.",
            format="json",
            snippet=j,
            restart_hint="Restart your Ollama front‑end after saving.",
        )

    return ClientSetup(
        client_id="generic",
        display=client_name,
        supports_mcp=True,
        config_path="Wherever your MCP client stores its server list (often `mcpServers` JSON).",
        format="json",
        snippet=j,
        restart_hint="Restart your MCP client after saving.",
    )
