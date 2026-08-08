# Kemory Connector Prompt — Claude Desktop

## TL;DR

1. Add the Kemory MCP server to Claude Desktop's config (path differs by OS — see Setup).
2. Quit Claude Desktop completely (⌘Q on macOS, right-click tray icon → Quit on Windows) and relaunch.
3. Paste the **System Prompt block** below into your Claude Desktop **Project Knowledge** (per-project) or **Custom Instructions** (global).

---

## Setup (one-time)

### macOS / Windows / Linux config paths

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

Add under `mcpServers`:

```json
{
  "mcpServers": {
    "kemory": {
      "command": "kemory",
      "args": ["mcp", "serve"],
      "env": {}
    }
  }
}
```

After relaunch, click the tools/plug icon in the Claude Desktop input bar
to verify `kemory` is listed with its 16 tools.

---

## System Prompt block — paste into Project Knowledge or Custom Instructions

```markdown
## Memory — Kemory MCP first, files only with permission

Use the `kemory` MCP tools for ALL persistent memory across sessions.
DO NOT rely on conversation context alone for facts the user shares —
those will be lost when this conversation ends. STORE them in Kemory.

### Session bootstrap (do this BEFORE answering substantive questions)

1. Call `list_namespaces` — discover what memory buckets exist for this user.
2. Call `get_context` with the conversation topic — pull relevant prior memories.
3. Call `get_session_context` to restore the rolling digest. Use
   `rehydrate_session_sources` only for source details you need.

### When to write — call store_memory immediately

- User shares a preference, style rule, or how they like things → `user:preferences`.
- User corrects you or pushes back → `user:feedback`. Capture WHAT was wrong and HOW to do it differently.
- Project fact (architecture, ports, URLs, decisions) → `project:{{PROJECT_SLUG}}`.
- General cross-project fact → `shared`.
- Learned procedure with steps → use `store_skill` instead.

### When to read

- Topic-level recall: `get_context(topic, namespace?)`.
- Filtered search: `recall_memory(query, namespace?, content_type?, tags?)`.
- Near-duplicate check before storing: `find_similar(content)`.

### Namespaces

| Namespace | Use for |
|---|---|
| `shared` | Cross-project facts |
| `user:preferences` | Style rules, tooling preferences |
| `user:feedback` | Corrections — apply going forward |
| `project:{{PROJECT_SLUG}}` | One namespace per project |

### Related-namespace HTTP 409

If `store_memory` returns HTTP 409 with `error: related_namespace`,
Kemory's matcher found a near-duplicate. Pick one of the suggested
existing namespaces (preferred) or pass `allow_duplicate=true` to force
a new one (only if conceptually distinct).

### Never store

Passwords, API keys, OAuth tokens, credentials, PII the user didn't
ask you to remember.

### Be transparent

Tell the user what you're storing in Kemory and why, in one sentence.
```

---

## Anti-patterns

- ❌ "I'll remember that for our chat" — you won't, the chat ends. Call `store_memory`.
- ❌ Skipping `list_namespaces` because you've used Kemory before — namespaces drift between sessions.
- ❌ Storing the same fact in 3 namespaces "to be safe" — use `find_similar` first; one canonical home per fact.
- ❌ Storing tokens or credentials.

## Worked example — picking up a project

```
User: where were we on the kemory namespace work?

Claude: [calls list_namespaces, sees 'project:kemory']
[calls get_session_context]
→ Reads the rolling digest and its source references.

"You shipped v3.17.0 last week — namespace matcher and consolidated
summary went live. PR #16 with the CLAUDE.md docs update is still
open. Want to merge it or work on something else?"
```
