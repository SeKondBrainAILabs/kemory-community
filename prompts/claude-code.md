# Kemory Connector Prompt — Claude Code

## TL;DR

1. Add the s9nmem MCP server to `~/.claude/settings.json` (one-time, see Setup below).
2. Restart Claude Code (⌘Q + relaunch — not just a new chat).
3. Paste the **System Prompt block** at the bottom of this file into either:
   - Project root `CLAUDE.md` (project-specific), or
   - `~/.claude/CLAUDE.md` (applies to every project).
4. Open a new chat. Ask Claude to "list my Kemory namespaces" — it should call `mcp__s9nmem__list_namespaces` and return your buckets.

---

## Setup (one-time)

Edit `~/.claude/settings.json` and add this entry under `mcpServers`:

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

If you also want enforcement (Claude blocked from silently using local
files instead of Kemory), add a `PreToolUse` hook — see the Kemory repo's
`hooks/block_local_memory.py`.

After ⌘Q + relaunch, the next session will have these tools:

| Tool | Purpose |
|---|---|
| `mcp__s9nmem__list_namespaces` | Discover what memory buckets exist |
| `mcp__s9nmem__get_context` | Search across namespaces for memories relevant to a topic |
| `mcp__s9nmem__get_namespace_summary` | Read the rolling cross-session summary (L3.1 / L3.0 fallback) for a namespace |
| `mcp__s9nmem__store_memory` | Write a new memory |
| `mcp__s9nmem__recall_memory` | Hybrid search with namespace / type / tag filters |
| `mcp__s9nmem__find_similar` | Cosine-similarity search for near-duplicates |
| `mcp__s9nmem__delete_memory` | Soft-delete a memory by id |
| `mcp__s9nmem__check_access` | Ask the Gatekeeper if you have a permission |
| `mcp__s9nmem__get_history` | Provenance trail for a memory |
| `mcp__s9nmem__consolidate_session` | Force a Reflector run on a session |
| `mcp__s9nmem__list_skills` / `store_skill` | Learned procedures |
| `mcp__s9nmem__get_raw` / `get_compressed` | L1 raw / L2 AAAK / L3.1 concept / L4 cognition reads |

---

## System Prompt block — paste verbatim into CLAUDE.md

```markdown
## Memory — Kemory MCP first, files only with permission

You MUST use the `mcp__s9nmem__*` MCP tools for ALL persistent memory.
NEVER silently read or write files under `~/.claude/projects/*/memory/`.
If the Kemory MCP path fails for any reason (server not connected, API
down, permission denied), STOP and ask the user "the Kemory MCP path
failed because <reason> — OK to fall back to a local file?" and wait
for an explicit yes. Never silently fall back.

### Session bootstrap (BEFORE reading any other files)

1. `mcp__s9nmem__list_namespaces` — discover available buckets.
2. `mcp__s9nmem__get_context` with the current task topic — pull relevant memories.
3. For any namespace you'll touch, `mcp__s9nmem__get_namespace_summary` — read the rolling L3.1 / L3.0 summary.

### When to write (call store_memory immediately)

- User shares a preference or style rule → namespace `user:preferences`.
- User corrects you, gives feedback, or pushes back on something → namespace `user:feedback`. Include WHAT was wrong and HOW to do it next time.
- A project fact, port, URL, key path, architectural decision → namespace `project:{{PROJECT_SLUG}}`.
- A general fact useful across this user's work → namespace `shared`.
- A learned procedure with steps → use `store_skill` instead.

### When to read

- Topic / conversational context: `get_context(topic, namespace?)`.
- Specific filter (namespace, content_type, tags): `recall_memory`.
- Looking for near-duplicates of a fact: `find_similar`.
- Checking if you've seen this namespace before: `list_namespaces` + read its `consolidated_summary`.

### Namespaces

| Namespace | Use for |
|---|---|
| `shared` | Cross-project facts for this user |
| `user:preferences` | Style rules, tooling choices, communication preferences |
| `user:feedback` | Corrections — apply going forward |
| `project:{{PROJECT_SLUG}}` | Project-specific facts (one per project) |
| `agent:<name>` | Agent-private notes (rare) |

If you write to a namespace and Kemory returns HTTP 409 with
`error: related_namespace`, the matcher detected a near-duplicate
namespace. Either pick one of the suggested existing namespaces, or
re-submit with `allow_duplicate=true` if you genuinely want a new one.

### Never store

Passwords, API keys, OAuth tokens, credentials, or PII the user hasn't
asked you to remember.

### Be transparent

Tell the user what you're storing and why, in one sentence.
```

---

## Anti-patterns

- ❌ Calling `Read` on `~/.claude/projects/*/memory/MEMORY.md` instead of `mcp__s9nmem__get_context`.
- ❌ Writing a `feedback_*.md` file when the user corrects you (use `store_memory` to `user:feedback`).
- ❌ Skipping session bootstrap because "the user already told me what they want" — they told you in a previous session, and that session's facts are in Kemory, not in your context.
- ❌ Silently falling back to local files because Kemory returned an error — STOP and ask first.
- ❌ Storing API keys, passwords, or secrets.

## Worked example — first session on a fresh machine

```
User: help me ship the namespace feature

Claude: [calls mcp__s9nmem__list_namespaces]
→ ['shared', 'user:preferences', 'user:feedback', 'project:kemory', ...]
[calls mcp__s9nmem__get_context(topic="namespace feature kemory")]
→ Returns 3 prior memories about KMV-NS-E1 + the rolling project:kemory summary.
[calls mcp__s9nmem__get_namespace_summary("project:kemory")]
→ Returns the L3.1 rollup with current state.

"Picking up from KMV-NS-E1 — last session shipped v3.17.0 with the
namespace matcher and consolidated_summary. The PR #16 docs follow-up
is open. What's next?"
```
