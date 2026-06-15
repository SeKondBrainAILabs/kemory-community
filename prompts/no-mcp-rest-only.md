# Kemory Connector Prompt — Pure REST (no MCP)

For agents that don't speak MCP — open-source LLMs hitting an API
directly, prompt-engineered Llama / Mistral / Qwen agents, custom
internal tools, scripts, anything that can `curl` but can't speak the
MCP protocol.

## TL;DR

1. The agent calls Kemory's REST API directly with `X-API-Key` auth.
2. Either: (a) the agent's runtime has a generic HTTP-tool capability
   (function calling on a `kemory_*` schema) or (b) the human user
   acts as the bridge — agent emits `kemory: ...` directives, the
   user runs curl and pastes responses back.
3. Paste the **System Prompt block** into the agent's system message.

---

## Connection

| Field | Value |
|---|---|
| Base URL | `{{KEMORY_URL}}` |
| Auth header | `X-API-Key: {{KEMORY_API_KEY}}` |
| Content-Type | `application/json` |

## REST endpoints reference

```bash
# Discover namespaces (with description, count, consolidated_summary)
curl -s -H "X-API-Key: {{KEMORY_API_KEY}}" {{KEMORY_URL}}/api/v1/namespaces

# Get rolling L3.1 / L3.0 summary for a namespace
curl -s -H "X-API-Key: {{KEMORY_API_KEY}}" \
  {{KEMORY_URL}}/api/v1/namespaces/<namespace>/summary

# Hybrid topic search across memories
curl -s -X POST -H "X-API-Key: {{KEMORY_API_KEY}}" -H "Content-Type: application/json" \
  {{KEMORY_URL}}/api/v1/memories/search \
  -d '{"query":"<topic>","namespace":"<optional>","limit":20,"search_mode":"hybrid"}'

# Store a memory (matcher may return HTTP 409)
curl -s -X POST -H "X-API-Key: {{KEMORY_API_KEY}}" -H "Content-Type: application/json" \
  {{KEMORY_URL}}/api/v1/memories \
  -d '{
    "namespace": "user:preferences",
    "content": "<fact>",
    "content_type": "preference",
    "namespace_description": "<optional, helps the matcher>",
    "allow_duplicate": false
  }'

# Get a single memory
curl -s -H "X-API-Key: {{KEMORY_API_KEY}}" {{KEMORY_URL}}/api/v1/memories/<memory_id>

# Soft-delete
curl -s -X DELETE -H "X-API-Key: {{KEMORY_API_KEY}}" {{KEMORY_URL}}/api/v1/memories/<memory_id>

# Multi-tier compressed read
curl -s -H "X-API-Key: {{KEMORY_API_KEY}}" \
  "{{KEMORY_URL}}/api/v1/namespaces/<namespace>/compressed?mode=concept&merge_mode=current"
```

### Handling the 409 from the matcher

```json
HTTP/1.1 409
{
  "detail": {
    "error": "related_namespace",
    "message": "Namespace 'user_prefs' looks similar to existing namespace(s).",
    "requested": "user_prefs",
    "suggested": [
      { "namespace": "user:preferences", "similarity": 0.83 }
    ],
    "force_create_param": "allow_duplicate=true"
  }
}
```

Re-issue the POST with either:
- `"namespace": "<one of the suggested>"` (preferred), or
- `"allow_duplicate": true` (only if genuinely distinct).

---

## System Prompt block — paste into the agent's system message

```markdown
You have access to Kemory, a persistent cross-session memory store, via
REST. Use it for ALL persistent facts. Your conversational context
disappears at end-of-session; Kemory doesn't.

You can call Kemory in two modes depending on your runtime:

(A) If your runtime supports HTTP function-calling, treat each REST
endpoint above as a tool. Use the namespace + content fields exactly
as shown.

(B) If your runtime is text-only, emit instructions to the user in
this format and wait for them to paste the response:

  ```
  KEMORY_CALL: GET /api/v1/namespaces/<namespace>/summary
  ```

  The user will run curl and paste the JSON response back. Then continue.

## Session bootstrap (FIRST thing you do)

1. GET /api/v1/namespaces — discover buckets.
2. POST /api/v1/memories/search with the conversation topic — pull prior memories.
3. For namespaces you'll touch, GET /api/v1/namespaces/<ns>/summary — read the rolling L3.1 / L3.0 cross-session summary.

## When to write — POST /api/v1/memories immediately

| Trigger | Namespace |
|---|---|
| User preference | `user:preferences` |
| User correction / feedback | `user:feedback` (WHAT + HOW) |
| Project fact | `project:{{PROJECT_SLUG}}` |
| Cross-project fact | `shared` |

## Related-namespace 409

If POST returns 409 with `error: related_namespace`, the matcher found
a near-duplicate. Re-POST with one of the suggested namespaces, or with
`allow_duplicate: true` only if genuinely distinct. Surface the redirect
to the user.

## Never store

Passwords, API keys, OAuth tokens, credentials, `.env` values, PII the
user didn't ask you to remember.

## Be transparent

After every write, tell the user: "stored to Kemory `<namespace>` because <reason>".
```

---

## Anti-patterns

- ❌ Inventing a namespace per session (`session_2026_04_22`) — namespaces are durable buckets, not conversation IDs.
- ❌ Bypassing the matcher with `allow_duplicate: true` reflexively to avoid handling the 409.
- ❌ Re-storing the same fact every session "for safety" — call `/memories/search` first.
- ❌ Storing the API key inside a memory.

## Worked example (mode B — user as bridge)

```
Agent: I'm starting work on your auth refactor. Pulling Kemory context first.
       KEMORY_CALL: GET /api/v1/namespaces

User: [pastes JSON]
       [{"namespace":"shared","count":47,...},{"namespace":"project:core_kora","count":18,...}]

Agent: KEMORY_CALL: GET /api/v1/namespaces/project:core_kora/summary

User: [pastes JSON]
       {"consolidated_summary":"Auth uses Keycloak SSO. Never use OpenAI...","consolidated_summary_tier":"L3.1",...}

Agent: Got it — Keycloak SSO, no OpenAI. Proceeding with the refactor.
```
