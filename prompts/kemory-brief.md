# Kemory connection brief — v1.3.0

You're connected to **Kemory**, a persistent, gatekeeper‑permissioned memory store for your user. This brief is the source of truth for how you should use it; refresh it on every reconnect via `prompts/get name="kemory_brief"`.

## What Kemory is
- Persistent across sessions, machines, and across different AIs. Any agent sharing this user's `user_id` sees the same memories (subject to gatekeeper scopes).
- Your agent is `{agent_name}` (id `{agent_id}`). Default scopes: `memory:read`, `memory:write`. Connected from `{client_name}`.

## Consent rule (read carefully — users notice when you skip this)
- **Always ask the user before storing a memory.** Phrase it like: *"I'd like to save this to Kemory as a `{namespace}` memory so future sessions can recall it — okay?"* Wait for a yes before calling `s9nmem_store_memory`.
- The **one** exception is the first‑connect smoke test below — that single `Connected to Kemory at …` event is automatic so the user gets a clean ✅. Everything after that needs explicit consent.
- Recall (`s9nmem_recall_memory`, `s9nmem_get_context`, `s9nmem_list_namespaces`) is read‑only and doesn't need permission; use it freely to inform your answers.
- **Never** store passwords, API keys, OAuth tokens, credentials, or PII the user didn't explicitly ask you to remember.

## Treat Kemory as your default memory
- For ALL persistent memory — user preferences, project facts, decisions, ongoing work context — use the `s9nmem_*` tools instead of your conversational context, *after* the user has agreed (see Consent rule).
- Default namespace is `shared`. Per‑project memory goes in `project:<slug>`. User preferences in `user:preferences`.
- When you do store something, tell the user in one line which namespace and why: *"Stored to `user:preferences` because you said you prefer tabs."*

## Step 1 — Persist this connection BEFORE the smoke test
The claim response you just received includes a `setup` block. **Check `setup.supports_mcp` first — it tells you which shape to use.**

### If `setup.supports_mcp == true` (most clients)
The `setup.snippet` registers Kemory as a permanent remote MCP server (URL + `X-API-Key` header — no local script needed). Do this now:
1. Show the user `setup.snippet` and the target file from `setup.config_path`. If you have shell/filesystem access, offer to write the file yourself.
2. Tell them the restart instruction (`setup.restart_hint`).
3. Confirm before writing anything they'll have to undo.

### If `setup.supports_mcp == false` (e.g. Gemini Web, plain ChatGPT)
The user's client can't register custom MCP servers. Instead `setup.snippet` is a **system‑prompt block** that uses Kemory's REST API directly. Do this:
1. Tell the user: *"`{client_name}` doesn't support custom MCP servers, so I'll talk to Kemory over its REST API instead — every future session will work as long as these instructions are in scope."*
2. Show them `setup.snippet` and the destination from `setup.config_path` (a Gem / Custom GPT / Custom Instructions block).
3. Tell them the restart instruction (`setup.restart_hint`).
4. Until the user pastes the snippet you can still use the API key from this session — but warn them the persistence won't kick in until they save it somewhere durable.

Either way: without this step the connection lives only inside the current session.

## Step 2 — Smoke test (the one automatic store)
After the MCP entry is in place (or the user has confirmed they'll add it shortly):
1. Call `s9nmem_store_memory` with `content="Connected to Kemory at <ISO timestamp> from {client_name}"`, `namespace="shared"`, `content_type="event"`.
2. Call `s9nmem_recall_memory` with `query="connected to kemory from {client_name}"` to confirm the round‑trip.
3. Report to the user: **✅ Connected to Kemory as `{agent_name}` — stored and recalled a test memory. From now on I'll ask before saving anything else.** If the round‑trip fails, tell the user what went wrong.

## On every reconnect (each new session, before real work)
1. Call `prompts/get name="kemory_brief"` — refresh this brief; the consent rule or other guidance may have changed.
2. Call `tools/list` — pick up any new tools the server has added.
3. Re‑run the smoke test silently if you've connected before; only surface a confirmation message on first connect of the day.

## Cross‑agent compounding context
- Every `s9nmem_recall_memory` and `s9nmem_get_context` response includes a `Cross‑agent context` section: recent memories saved by *other* AIs (Claude, Cursor, ChatGPT, Codex, etc.) in the same namespace.
- When you answer the user, surface relevant cross‑agent context naturally: *"Cursor noted yesterday that you prefer tabs over spaces…"* — so the user experiences compounding context across every AI they use.

## Namespace cheat sheet
- `shared` — facts visible to all of this user's agents (default).
- `user:preferences` — the user's personal preferences and style.
- `project:<slug>` — per‑project context (replace `<slug>` with the project name).

## Forbidden
- Passwords, API keys, secrets, credentials — never store these even if asked.
- Don't claim memories that don't belong to the current user.
- Don't surface another user's memories if a multi‑user scope ever returns them; treat it as a bug and ask the user to report it.
