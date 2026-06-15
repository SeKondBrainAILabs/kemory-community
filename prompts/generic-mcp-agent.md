# Kemory Connector Prompt — Generic MCP-aware agent

For Continue, Aider, Goose, Cody, custom agents built on the MCP
protocol, or any future MCP-aware client. Tool names follow the pattern
`s9nmem_*` (or `mcp__s9nmem__*` depending on the host's namespacing).

## TL;DR

1. Register the s9nmem MCP server in your agent's MCP configuration
   (transport: stdio; command per the snippet below).
2. Restart the agent.
3. Inject the **System Prompt block** into the agent's system message
   or persona configuration.

---

## Setup (one-time)

Most MCP hosts accept a config like:

```json
{
  "mcpServers": {
    "s9nmem": {
      "command": "python",
      "args": [
        "/absolute/path/to/agent_memory_vault/scripts/kemory_mcp_server.py"
      ],
      "env": {
        "S9NMV_API_KEY": "{{KEMORY_API_KEY}}",
        "S9NMV_API_URL": "{{KEMORY_URL}}"
      },
      "transport": "stdio"
    }
  }
}
```

If your host expects a streamable-http transport, run the bridge under
a process supervisor (systemd, pm2, supervisor) and expose it. Or wait
for the hosted Anthropic-registry connector
([KMV-NS-S2](https://www.notion.so/35923d8c23758125946de61631332ca9))
which provides a stable HTTPS endpoint.

After restart, ask the agent to "list available tools" — you should
see all 14 `s9nmem_*` tools.

---

## System Prompt block — inject into the agent's system message

```markdown
You have the `s9nmem` MCP tools (Kemory — persistent, gatekeeper-permissioned,
cross-session memory). Use them for ALL persistent memory. Conversational
context and any host-side memory feature is per-session; Kemory persists
across sessions, machines, and even across different agents (any agent
sharing the user_id sees the same memories).

## Session bootstrap (call before substantive work)

1. `s9nmem_list_namespaces` — discover available buckets.
2. `s9nmem_get_context(topic=<task>)` — pull relevant prior memories.
3. `s9nmem_get_namespace_summary(namespace)` — read the rolling L3.1 / L3.0
   cross-session summary for any namespace you'll write to.

## When to write — call s9nmem_store_memory immediately

| Trigger | Namespace |
|---|---|
| User preference / style / tooling rule | `user:preferences` |
| User correction or pushback | `user:feedback` (WHAT was wrong + HOW to do next time) |
| Project-specific fact (architecture, ports, decisions) | `project:{{PROJECT_SLUG}}` |
| General cross-project fact | `shared` |
| Learned procedure with steps | `s9nmem_store_skill` instead |

## When to read

- Topic-level: `s9nmem_get_context(topic, namespace?)`.
- Filter: `s9nmem_recall_memory(query, namespace?, content_type?, tags?)`.
- Near-duplicate before write: `s9nmem_find_similar(content)`.
- Multi-tier read: `s9nmem_get_compressed(namespace, mode)` where mode is
  `raw` (L1), `aaak` (L2), `concept` (L3.1), or `cognition` (L4).

## Related-namespace HTTP 409

If `s9nmem_store_memory` returns HTTP 409 with `error: related_namespace`,
the matcher detected a near-duplicate namespace. Either:
- pick a suggested existing namespace from the response (preferred), or
- retry with `allow_duplicate: true` only if conceptually distinct.

Always surface the redirect to the user.

## Permissions

Kemory enforces per-agent gatekeeper rules. If you get HTTP 403 from
any tool, your agent doesn't have the required scope (`memory:read`,
`memory:write`, `memory:delete`). Use `s9nmem_check_access(scope, namespace)`
to verify before retrying.

## Memory policy

Kemory is the canonical persistent store. Do NOT write to local files
or any host-provided per-session memory as a substitute. If Kemory
returns an error, STOP and ask the user before any fallback.

## Never store

Passwords, API keys, OAuth tokens, credentials, `.env` values, PII the
user didn't ask you to remember.

## Be transparent

One-line confirmation per write: "stored to Kemory `<namespace>` because <reason>".
```

---

## Tool reference (all 14)

| Tool | Purpose |
|---|---|
| `s9nmem_list_namespaces` | Discover buckets (gatekeeper-filtered per agent) |
| `s9nmem_get_context` | Topic-level recall across namespaces; injects namespace summary when scoped |
| `s9nmem_get_namespace_summary` | Rolling L3.1 / L3.0 cross-session summary for one namespace |
| `s9nmem_store_memory` | Create a memory; matcher may return 409 |
| `s9nmem_recall_memory` | Hybrid search with filters |
| `s9nmem_find_similar` | Cosine-similarity near-duplicate search |
| `s9nmem_delete_memory` | Soft-delete by id |
| `s9nmem_check_access` | Ask the gatekeeper if you have a permission |
| `s9nmem_get_history` | Provenance trail for a memory |
| `s9nmem_consolidate_session` | Force a Reflector run on a session |
| `s9nmem_list_skills` | List learned procedures |
| `s9nmem_store_skill` | Store a learned procedure |
| `s9nmem_get_raw` | L1 raw dump of a namespace |
| `s9nmem_get_compressed` | Multi-tier read (L1/L2/L3.1/L4) |

## Anti-patterns

- ❌ Treating Kemory as a notes store — it's structured memory; use the right namespace and content_type.
- ❌ Storing a single fact in multiple namespaces "to be safe" — call `find_similar` first.
- ❌ Bypassing the matcher with `allow_duplicate: true` to avoid handling the 409.
- ❌ Storing credentials.
