# Kemory Connector Prompt — Cursor

## TL;DR

1. Add the s9nmem MCP server to Cursor's MCP config.
2. Restart Cursor.
3. Add the **Rules block** below to your project's `.cursorrules` (or
   user-level Rules for Cursor).
4. Open Composer / Chat — verify `mcp_s9nmem_*` appears in the available
   tools.

---

## Setup (one-time)

### Cursor MCP config

Cursor → **Settings** → **Cursor Settings** → **MCP** → **Add new MCP server**:

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

Restart Cursor. The MCP panel should show the s9nmem server as
**connected** with 14 tools.

---

## Rules block — paste into `.cursorrules`

```markdown
# Kemory — persistent memory across Cursor sessions

You have the `s9nmem` MCP tools available. Use them for ALL persistent
memory. Cursor's per-chat context resets between sessions; Kemory
doesn't.

## Session bootstrap (BEFORE editing or answering)

1. Call `list_namespaces` — discover what buckets exist.
2. Call `get_context(topic=<current task>)` — pull relevant prior memories.
3. For any namespace you'll touch, call `get_namespace_summary(namespace)`
   to read the rolling L3.1 / L3.0 cross-session summary.

## When to write — call store_memory immediately

| Trigger | Namespace |
|---|---|
| User shares a code style preference | `user:preferences` |
| User pushes back on something you did / said | `user:feedback` (capture WHAT + HOW) |
| Architectural decision in this repo | `project:{{PROJECT_SLUG}}` |
| Cross-repo fact about this user | `shared` |
| Learned procedure with steps | `store_skill` instead |

## When to read

- Topic search: `get_context(topic, namespace?)`.
- Filter search: `recall_memory(query, namespace?, content_type?, tags?)`.
- Near-duplicate check: `find_similar(content)` — call before `store_memory`
  if you're unsure whether you've seen this fact before.

## Related-namespace HTTP 409

If `store_memory` returns HTTP 409 with `error: related_namespace`,
Kemory's matcher detected a near-duplicate namespace. Pick the
suggested existing namespace, or retry with `allow_duplicate=true`
only if genuinely distinct. Tell the user about the redirect.

## Never store

Passwords, API keys, OAuth tokens, credentials, .env values, or PII
the user didn't ask you to remember.

## Be transparent

When you store, say "stored to Kemory `<namespace>` because <reason>"
in one line.

## Memory policy

Kemory is the canonical memory. NEVER write to Cursor's per-project
notes, `.cursor/`, or local files as a substitute. If Kemory returns
an error, STOP and ask the user "Kemory failed because <reason> — OK
to fall back to local notes?" before writing anywhere else.
```

---

## Anti-patterns

- ❌ Storing facts in `.cursor/notes.md` or similar instead of Kemory.
- ❌ Skipping `list_namespaces` on a fresh repo because "Kemory probably has nothing" — it might have project-level facts from a sibling repo.
- ❌ Using the `shared` namespace for project-specific facts. One project = one `project:*` namespace.
- ❌ Storing `.env` values or any credential.

## Worked example — joining a new repo

```
User: refactor the auth module

Cursor [Composer]:
[calls list_namespaces]
→ ['shared', 'user:preferences', 'project:core_kora', 'project:peoplefinder', ...]
[calls get_context(topic="auth module refactor")]
→ Returns 4 prior memories about Keycloak integration patterns.
[calls get_namespace_summary("project:core_kora")]
→ Reads the L3.1 rollup: "Auth uses Keycloak SSO; never use OpenAI; ..."

"Picking up — this repo uses Keycloak SSO and prior sessions established
that auth tokens flow through `core_backend.organizations.id` per
ADR-004. Refactoring with that constraint in mind."
```
