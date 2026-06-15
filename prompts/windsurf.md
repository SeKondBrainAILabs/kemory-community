# Kemory Connector Prompt — Windsurf

## TL;DR

1. Add the s9nmem MCP server to Windsurf's MCP config.
2. Restart Windsurf.
3. Add the **Rules block** below to your project's Windsurf rules
   (or to Cascade's global Memory).
4. Open Cascade — verify `s9nmem` tools appear under the available MCP
   servers.

---

## Setup (one-time)

### Windsurf MCP config

Windsurf → **Settings** → **Cascade** → **MCP Servers** → **Add server**:

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

Restart Windsurf. The MCP panel in Cascade should show `s9nmem` as
connected with its 14 tools.

---

## Rules block — paste into Windsurf project rules / Cascade Memory

```markdown
# Kemory — persistent memory across Windsurf sessions

You have the `s9nmem` MCP tools. Use them for ALL persistent memory.
Cascade's built-in Memory is per-workspace and doesn't sync across
machines or repos; Kemory does.

## Session bootstrap (BEFORE answering substantive questions)

1. Call `list_namespaces`.
2. Call `get_context(topic=<current task>)`.
3. For any namespace you'll touch, call `get_namespace_summary(namespace)`
   to read the rolling L3.1 / L3.0 cross-session summary.

## When to write — call store_memory immediately

| Trigger | Namespace |
|---|---|
| Code style / tooling preference | `user:preferences` |
| User correction or feedback | `user:feedback` (capture WHAT + HOW) |
| Architectural / project fact | `project:{{PROJECT_SLUG}}` |
| Cross-project fact for this user | `shared` |
| Learned procedure | `store_skill` |

## When to read

- Topic-level: `get_context(topic, namespace?)`.
- Filtered: `recall_memory(query, namespace?, content_type?, tags?)`.
- Near-duplicate before write: `find_similar(content)`.

## Related-namespace HTTP 409

If `store_memory` returns 409 with `error: related_namespace`, the
matcher found a near-duplicate namespace. Pick the suggested existing
namespace or retry with `allow_duplicate=true` only if genuinely
distinct. Surface the redirect to the user.

## Memory policy

Kemory is the canonical memory store. Do NOT write project-level facts
into Cascade's per-workspace Memory — those don't sync. Do NOT create
local `MEMORY.md` files. If Kemory returns an error, STOP and ask the
user before any local-file fallback.

## Never store

Passwords, API keys, OAuth tokens, credentials, `.env` values, PII the
user didn't ask you to remember.

## Be transparent

One-line confirmation per write: "stored to Kemory `<namespace>` because <reason>".
```

---

## Anti-patterns

- ❌ Using Cascade's "Add to Memory" button for facts that should be in Kemory — Cascade Memory is per-workspace; Kemory is per-user across everything.
- ❌ Skipping bootstrap because "Cascade has context" — it has *this session's* context, not prior sessions'.
- ❌ Storing the same fact in both Cascade Memory and Kemory.

## Worked example — opening a project after a week away

```
User: pick up where we left off on the kemory namespace work

Cascade:
[s9nmem.list_namespaces]
[s9nmem.get_context(topic="kemory namespace work")]
[s9nmem.get_namespace_summary("project:kemory")]

"Reading the project:kemory L3.1 summary — last activity was
v3.17.0 deploy on 2026-04-20 (namespace matcher + consolidated_summary
landed). PR #16 with the CLAUDE.md docs update is still open and
PR #15 already merged. Continuing from there."
```
