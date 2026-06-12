# Kemory Community Edition - Project Plan

This is the build plan for v0.1 of `kemory-community`. The repo is
currently in scaffolding phase; backend code lands via a `git subtree
split` from `SeKondBrainAILabs/agent_memory_vault` once that repo's
adapter refactor completes.

## What ships in community

Included:

- L1 memory CRUD (full text/fact/preference/conversation/structured/embedding types)
- L2 AAAK lossless encoding
- L3 per-namespace narrative summaries (via user's Groq key)
- L3.1 concept synthesis + `supersedes` directional graph
- `quality_score` enrichment scoring
- Namespace matcher (0.85 / 0.90 thresholds, 409 conflict, silent redirect)
- Session prewarm
- Hybrid recall (vector cosine union BM25, reciprocal rank fusion)
- MCP server over HTTP at `/mcp` with all `kemory_*` tools
- Full chats-v1 capture (`POST /api/v1/chats`, ChatGPT/Claude export ingestion)
- Artifacts with local filesystem blob storage
- Export endpoint (JSONL bundle) + import endpoint
- Dashboard pages: memories, namespaces, chats, artifacts, settings, doctor
- Settings UI: Groq key, embedding provider, Groq model, artifact limits, log level

Not included (stays in hosted Kemory):

- L5 cross-namespace merge detection (the one piece of cognition that's hosted-only)
- Keycloak / OIDC / multi-tenant org isolation
- FalkorDB knowledge graph (community uses `kemory_supersedes_edges` SQL table)
- Weaviate (community uses PGlite + pgvector)
- MinIO (community uses local filesystem)
- Hosted telemetry
- Teams, `team_members`, `visibility=team|org` evaluation (columns exist for portability; community ignores them)
- Gatekeeper rule engine evaluation (rules schema exists; community has one user)
- Cross-device sync

## Architecture

- **Backend:** Python 3.11 + FastAPI, shipped as a PyInstaller binary.
- **Database default:** PGlite (embedded WASM Postgres + pgvector) at `~/.kemory-community/data/pgdata/`. Zero install.
- **Database opt-in:** real Postgres via `kemory-community init --db postgres://...`.
- **LLM:** Groq, user-supplied key. Default model `llama-3.3-70b-versatile`.
- **Embeddings:** local `fastembed` with `BAAI/bge-small-en-v1.5`. Configurable to OpenAI/Voyage/Cohere.
- **Auth:** single-user, X-API-Key only. No Keycloak, no JWT.
- **Dashboard:** Vite + React (stripped fork of hosted dashboard, no Keycloak).
- **MCP tool prefix:** `kemory_*` (canonical). `s9nmem_*` / `kora_*` accepted as deprecation aliases.

## Distribution

`npm i -g kemory-community` (or `npx kemory-community@latest`). The
npm package's `postinstall` downloads the right platform binary from
GitHub Releases.

**v0.1 platforms:** macOS arm64 only. Windows x64 + Linux x64 in v0.2.

## Timeline target

| Week | Focus |
|------|-------|
| 1 (in `agent_memory_vault`) | Adapter refactors land: `VectorStore`, `BlobStore`, `IdentityProvider`, `Telemetry`, cognition plugin layout, community-config CI tripwire. |
| 2 (in this repo) | Receive subtree split, PGlite integration, dashboard de-Keycloak, npm packaging, macOS arm64 binary, Settings UI, export/import. Tag `v0.1.0`. |

## After v0.1

v0.2 (next 2 weeks): Windows + Linux binaries, GH Pages docs site at
`community.kemory.s9n.ai`, artifact thumbnails, recall benchmarks vs
Mem0/Letta/Zep, HN + Product Hunt launch.

## Questions?

Open a Discussion. Watch this repo to be notified when v0.1 ships.
