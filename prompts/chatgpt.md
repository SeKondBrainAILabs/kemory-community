# Kemory Connector Prompt — ChatGPT

## TL;DR

ChatGPT does not natively support MCP (as of 2026-04). Two integration
paths until it does:

- **(A) Custom GPT with Actions** — define Kemory's REST API as an
  OpenAPI Action; the GPT calls it like any other tool. Recommended.
- **(B) Custom Instructions + manual REST** — paste the System Prompt
  below into your Custom Instructions; you (the human) paste curl
  responses back to the chat. Awkward, but works on free ChatGPT.

When ChatGPT ships MCP, swap to the [`generic-mcp-agent.md`](generic-mcp-agent.md) prompt.

---

## Setup A — Custom GPT with Actions (recommended)

1. ChatGPT → **Explore GPTs** → **Create**.
2. **Configure** tab → **Actions** → **Create new action**.
3. Paste this minimal OpenAPI 3.1 schema (extend with more endpoints as needed):

```yaml
openapi: 3.1.0
info: { title: Kemory, version: "1.0" }
servers: [{ url: "{{KEMORY_URL}}" }]
paths:
  /api/v1/namespaces:
    get:
      operationId: listNamespaces
      summary: List namespaces with description, count, consolidated_summary
      responses: { "200": { description: ok } }
  /api/v1/namespaces/{namespace}/summary:
    get:
      operationId: getNamespaceSummary
      summary: Rolling L3.1 / L3.0 consolidated cross-session summary
      parameters:
        - { name: namespace, in: path, required: true, schema: { type: string } }
      responses: { "200": { description: ok } }
  /api/v1/memories/search:
    post:
      operationId: searchMemories
      summary: Hybrid search across memories
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                query: { type: string }
                namespace: { type: string }
                limit: { type: integer, default: 20 }
      responses: { "200": { description: ok } }
  /api/v1/memories:
    post:
      operationId: storeMemory
      summary: Create a memory; matcher may return HTTP 409
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [namespace, content]
              properties:
                namespace: { type: string }
                content: { type: string }
                content_type: { type: string, default: text }
                namespace_description: { type: string }
                allow_duplicate: { type: boolean, default: false }
      responses:
        "201": { description: created }
        "409": { description: related_namespace — matcher suggests existing namespace(s) }
components:
  securitySchemes:
    apiKey:
      type: apiKey
      in: header
      name: X-API-Key
security: [{ apiKey: [] }]
```

4. **Authentication** → API Key → **Custom Header Name** `X-API-Key` → paste `{{KEMORY_API_KEY}}`.
5. Paste the **System Prompt block** below into the GPT's **Instructions** field.
6. Save. Test: "list my Kemory namespaces" should trigger `listNamespaces` and return your buckets.

## Setup B — Custom Instructions + manual REST

In ChatGPT → **Settings** → **Personalization** → **Custom Instructions**, paste the System Prompt block.

For reads/writes, *you* run curl from your terminal and paste the response back to ChatGPT:

```bash
# List namespaces
curl -s -H "X-API-Key: {{KEMORY_API_KEY}}" {{KEMORY_URL}}/api/v1/namespaces

# Get a namespace summary
curl -s -H "X-API-Key: {{KEMORY_API_KEY}}" {{KEMORY_URL}}/api/v1/namespaces/{{NAMESPACE}}/summary

# Store a memory
curl -s -X POST -H "X-API-Key: {{KEMORY_API_KEY}}" -H "Content-Type: application/json" \
  {{KEMORY_URL}}/api/v1/memories \
  -d '{"namespace":"user:preferences","content":"<fact>","content_type":"preference"}'

# Search
curl -s -X POST -H "X-API-Key: {{KEMORY_API_KEY}}" -H "Content-Type: application/json" \
  {{KEMORY_URL}}/api/v1/memories/search \
  -d '{"query":"<topic>","limit":10}'
```

---

## System Prompt block — paste into Instructions / Custom Instructions

```markdown
You have access to Kemory, a persistent cross-session memory store.
Use it for ALL facts that should survive past this chat.

### Session bootstrap (do this on the first user turn)

1. Call `listNamespaces` (or look at the response if I paste one) to discover buckets.
2. Call `searchMemories` with the conversation topic to pull prior memories.
3. For namespaces you'll write to, call `getNamespaceSummary` to read the rolling L3.1 / L3.0 cross-session summary.

### When to write — call storeMemory immediately

- User shares preference / style rule → namespace `user:preferences`.
- User corrects you or pushes back → namespace `user:feedback` with WHAT was wrong + HOW to do it next time.
- Project fact (decision, architecture, URL, port) → namespace `project:{{PROJECT_SLUG}}`.
- General cross-project fact → namespace `shared`.

### Namespaces

| Namespace | Use for |
|---|---|
| `shared` | Cross-project facts |
| `user:preferences` | Style rules, tooling preferences |
| `user:feedback` | Corrections to apply going forward |
| `project:{{PROJECT_SLUG}}` | Project-specific facts |

### Related-namespace HTTP 409

If `storeMemory` returns 409 with `error: related_namespace`, the
matcher found a near-duplicate. Pick the suggested existing namespace
(preferred) or retry with `allow_duplicate: true` only if conceptually
distinct. Tell the user about the redirect.

### Never store

Passwords, API keys, OAuth tokens, credentials, PII the user didn't
explicitly ask you to remember.

### Be transparent

Tell the user "stored to Kemory namespace X because Y" in one line
whenever you write.
```

---

## Anti-patterns

- ❌ Saying "I'll remember" without calling `storeMemory`.
- ❌ Storing facts in ChatGPT's "Memory" feature instead of Kemory (it's per-account, not per-project, and doesn't persist across orgs/devices).
- ❌ Bypassing the matcher with `allow_duplicate: true` to avoid handling the 409.
