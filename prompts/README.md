# Kemory Connector Onboarding Prompts

Copy-paste prompts that teach AI clients how to actually use Kemory once
the MCP connection (or REST API) is in place. **Connecting Kemory gives
the AI tools — these prompts give it the *behaviour*.**

> Story: [KMV-NS-S1](https://www.notion.so/35923d8c2375819fb7e8f987811eb362)
> · Epic: [KMV-NS-E1](https://www.notion.so/34823d8c23758193947cefe62e2e27ad)
> · Connector submission: [KMV-NS-S2](https://www.notion.so/35923d8c23758125946de61631332ca9)

## Pick your client

| Client | File | Where to paste |
|---|---|---|
| Claude Code (CLI) | [`claude-code.md`](claude-code.md) | Project `CLAUDE.md` or user `~/.claude/CLAUDE.md` |
| Claude Desktop | [`claude-desktop.md`](claude-desktop.md) | Project Knowledge or system prompt |
| ChatGPT (Custom GPT or Custom Instructions) | [`chatgpt.md`](chatgpt.md) | Custom Instructions / GPT system message |
| Cursor | [`cursor.md`](cursor.md) | `.cursorrules` |
| Windsurf | [`windsurf.md`](windsurf.md) | Project rules / Cascade memory |
| Cline (VS Code) | [`cline.md`](cline.md) | Custom instructions |
| Generic MCP-aware agent (Continue, Aider, custom) | [`generic-mcp-agent.md`](generic-mcp-agent.md) | System prompt / system message |
| Pure REST (no MCP) | [`no-mcp-rest-only.md`](no-mcp-rest-only.md) | System prompt + manual API calls |

## What every prompt teaches the AI

1. **Identity & connection** — where Kemory lives, how to authenticate.
2. **Tool reference** — all 14 `mcp__s9nmem__*` tools and when to call each.
3. **Namespace convention** — `shared`, `user:preferences`, `user:feedback`, `project:*`, `agent:*`.
4. **Memory policy** — Kemory-first; STOP and ask the user before any local-file fallback; never store secrets.
5. **Session bootstrap** — call `list_namespaces` + `get_context` BEFORE anything else.
6. **Write triggers** — store on preferences, project facts, decisions, corrections.
7. **Read triggers** — `recall_memory` vs `get_context` vs `find_similar`.
8. **Summary handling** — how to use `consolidated_summary` (L3.1 / L3.0 fallback).
9. **Related-namespace 409 / `allow_duplicate=true`** — what to do when the matcher pushes back.
10. **Worked examples + anti-patterns**.

## Placeholders to fill in

Every prompt uses these placeholders — replace before pasting:

| Placeholder | What to put |
|---|---|
| `{{KEMORY_URL}}` | Your Kemory API base, e.g. `https://api.memory.dxb-gw.basanti.ai` |
| `{{KEMORY_API_KEY}}` | Agent API key (`kora_...`). Get from the Kemory dashboard → Agents tab |
| `{{PROJECT_SLUG}}` | Lowercase project identifier, e.g. `kemory`, `core_kora`, `peoplefinder` |

## When new tools / namespaces ship

When KMV-NS-E1's matcher, `consolidated_summary`, or new MCP tools change,
update every prompt in lock-step. The `claude-code.md` file is the
canonical version; treat the others as platform-specific re-skins.
