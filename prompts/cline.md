# Kemory Connector Prompt — Cline (VS Code)

## TL;DR

1. Add the s9nmem MCP server to Cline's MCP settings.
2. Reload VS Code window.
3. Paste the **System Prompt block** below into Cline's **Custom Instructions**.
4. Open Cline — verify `s9nmem` tools appear in the MCP servers panel.

---

## Setup (one-time)

### Cline MCP config

Cline icon in VS Code → **MCP Servers** tab → **Edit MCP Settings**.
This opens `cline_mcp_settings.json`. Add under `mcpServers`:

```json
{
  "mcpServers": {
    "s9nmem": {
      "command": "/opt/anaconda3/bin/python",
      "args": [
        "/absolute/path/to/agent_memory_vault/scripts/kemory_mcp_server.py"
      ],
      "env": {
        "S9NMV_API_KEY": "{{KEMORY_API_KEY}}",
        "S9NMV_API_URL": "{{KEMORY_URL}}"
      }
    }
  }
}
```

Save → reload VS Code window (`Cmd+Shift+P` → "Reload Window"). The
Cline MCP panel should show `s9nmem` as connected with its 14 tools.

---

## System Prompt block — paste into Cline's Custom Instructions

```markdown
You have the `s9nmem` MCP tools (Kemory — persistent cross-session
memory). Use them for ALL persistent memory. VS Code workspace state
and Cline's per-task context don't survive a window reload; Kemory
does.

## Session bootstrap (BEFORE doing the user's task)

1. Call `list_namespaces`.
2. Call `get_context(topic=<current task>)`.
3. For each namespace you'll touch, call `get_namespace_summary(namespace)`
   to read the rolling L3.1 / L3.0 cross-session summary.

## When to write — call store_memory immediately

| Trigger | Namespace |
|---|---|
| Code style / tooling preference | `user:preferences` |
| User correction or feedback | `user:feedback` (WHAT + HOW) |
| Architectural / project fact | `project:{{PROJECT_SLUG}}` |
| Cross-project fact | `shared` |
| Learned procedure with steps | `store_skill` |

## When to read

- Topic-level: `get_context(topic, namespace?)`.
- Filtered: `recall_memory(query, namespace?, content_type?, tags?)`.
- Near-duplicate before write: `find_similar(content)`.

## Related-namespace HTTP 409

If `store_memory` returns HTTP 409 with `error: related_namespace`,
Kemory's matcher found a near-duplicate. Use the suggested existing
namespace, or retry with `allow_duplicate=true` only if genuinely
distinct. Surface the redirect to the user.

## Memory policy

Kemory is the canonical store. Don't write `.vscode/notes.md`,
`MEMORY.md`, or similar local files as a substitute. If Kemory returns
an error, STOP and ask the user "Kemory failed because <reason> — OK
to fall back to a local note?" before writing anywhere else.

## Never store

Passwords, API keys, OAuth tokens, credentials, `.env` values, PII
the user didn't ask you to remember.

## Be transparent

One-line confirmation per write: "stored to Kemory `<namespace>` because <reason>".
```

---

## Anti-patterns

- ❌ Storing project facts in VS Code's workspace settings (`.vscode/settings.json`) instead of Kemory.
- ❌ Skipping bootstrap because Cline shows recent task history — that's the last few tasks in this VS Code session, not prior sessions.
- ❌ Using `shared` for project-specific facts.

## Worked example — fresh `code .` on a known repo

```
User: continue the namespace migration

Cline:
[s9nmem.list_namespaces]
[s9nmem.get_context(topic="namespace migration")]
[s9nmem.get_namespace_summary("project:kemory")]

"Project rollup says v3.17.0 already shipped the matcher and
consolidated_summary; the pending follow-up is migrating the 4 legacy
~/.claude memory files into Kemory namespaces. Picking that up now."
```
