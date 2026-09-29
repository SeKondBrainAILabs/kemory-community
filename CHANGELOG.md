# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Structured output schemas and results across all Community MCP tools while
  retaining existing text responses for older clients.
- MCP namespace-tag writes, caller-controlled relevance floors, and a read-only
  endpoint for retrieving a chat's stored rolling digest.
- Shared-infrastructure deployment mode for source and npm installs. Community
  API/dashboard containers join external `shared-infra`, reuse an isolated
  PostgreSQL database/user and Redis database `14`, and include idempotent
  provisioning, guarded standalone-data migration, and an application-owned
  infrastructure port registry.

- Local-first Ask over memories, captured chats, and inline text artifacts via
  `POST /api/v1/ask`, MCP `kemory_ask`, and the Python `kemory ask` command.
  Retrieval evidence remains available when Groq is not configured.
- Additive MCP `outputSchema` and `structuredContent` support for machine-readable
  Ask results without changing the legacy text envelope.
- Automatic second-tier namespace tags with entity/embedding/era matching,
  local-user profile reads, Docker backfill and promotion tools, and dashboard chips.
- Unified, keyset-paginated namespace timeline interleaving source-ordered chats and memories.
- Source chronology for memories, chat turns, and artifacts, including migration `019`,
  source-date filtering, MCP output, file modified dates, and Happened/Added/Updated views.
- Rolling, token-budgeted session context with the latest three exchanges kept raw.
- Read-only digest provenance expansion through `kemory_rehydrate_session_sources`.
- Hosted-to-community delta ledger for explicit port/adapt/exclude decisions.
- Initial repo scaffolding (Apache-2.0 license, README, docs, CI, npm package shell). Backend code lands in v0.1.0.
- npm setup CLI for Docker-first community runtime configuration.
- Community backend/dashboard import with Docker compose for API, dashboard, Redis, and pgvector.
- Canonical `kemory_*` MCP tool names with `s9nmem_*` and `kora_*` compatibility aliases.
- Indexed pgvector retrieval with legacy-row fallback, batch encoding, deterministic ranking, and optional score floors.
- Standard MCP JSON-RPC 2.0 transport over authenticated HTTP and stdio.
- Dashboard Settings page for API key, persisted Groq/embedding/model/artifact/log settings,
  JSON export, and JSON import.
- Dedicated Artifacts workspace and Doctor route for local files and dependency health.
- User-supplied Groq execution for L2.1/L3/L3.1, reranking, and aggregation without the
  hosted AI proxy.
- FastEmbed by default with opt-in OpenAI, Voyage, and Cohere embedding providers that
  preserve the community pgvector dimension contract.
- Local-only Python CLI and MCP bridge with API-key configuration and no OAuth,
  Bearer-token, organisation, team, or hosted release paths.
- Responsive memory explorer with relevance sorting, result highlighting, Markdown detail, history, namespace filtering, and URL-backed pagination.
- Community-only dashboard surface with X-API-Key requests and no hosted identity, graph, or admin workflows.
- Community-only API route allowlist with no Gatekeeper evaluation, CogOS compression, or hosted telemetry startup.
- Community port registry at `docs/PORT_REGISTRY.md`.

### Changed
- Refreshed the hosted delta audit through `cb90234d89` (post-`v3.11.1`) and
  replayed Community-compatible MCP, digest, compression-source, and timeline
  correctness updates without importing hosted identity or infrastructure.
- L3.1 synthesis now selects its capped source set newest-first with a stable
  tie-break, and timeline fallbacks use immutable creation timestamps.
- SeKondBrain deployments now use `docker-compose.shared.yml`; the existing
  self-contained compose remains the portable public and CI default.
- Python CI now uses Ruff 0.16.3, matching the current hosted lint floor.
- The API image is now a multi-stage build that runs as non-root UID 1001 and
  leaves compilers and development headers out of the runtime image.
- Dashboard builds and CI now use Node 24, with Vite constrained to the
  hosted security floor (`^6.4.3`) and the npm lock refreshed to remove
  high-severity transitive advisories.
- The Quick Start now leads with cloning the repository and running
  `docker compose -f docker-compose.community.yml up -d --build`, which needs
  only Docker. The `npx kemory-community` installer is documented as pending
  its first publish rather than presented as available.
- Tagging a release now fails immediately when `NPM_TOKEN` is absent, before
  any image or package is published, instead of skipping the npm publish and
  reporting success.
- Dependabot now watches `dashboard/package-lock.json` and the Python
  dependencies in `pyproject.toml`. Minor and patch updates arrive grouped;
  majors still arrive individually.

### Removed
- Hosted agent-JWT, device-pairing and browser-extension-key code, none of
  which was reachable from the running application: the `agents`, `pair` and
  `extension_keys` routes and the `auth_service`, `agent_service` and
  `extension_key_service` modules behind them, along with the now-unread
  `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `JWT_EXPIRY_MINUTES` and
  `API_KEY_PEPPER` settings.
- A hosted QA script that could not run here — it imported a package this
  edition forbids and does not ship — and the `rich` dependency it was the
  only consumer of.
- `dashboard/pnpm-lock.yaml`, a leftover from the initial import. The build
  uses npm and `package-lock.json`; the stale file was the sole source of
  every open dependency advisory against this repository.

### Fixed
- The backend installs `sqlalchemy[asyncio]` instead of `sqlalchemy`.
  SQLAlchemy 2.1.0 stopped installing `greenlet` by default, so a fresh
  install failed to import `sqlalchemy.ext.asyncio` and the API could not start.
- UTF-8 text uploads up to 1 MiB are retained inline as searchable artifact
  evidence while the complete body remains in local filesystem blob storage.
- Chat pushes that repeat a `source_turn_id` now keep the last occurrence
  instead of risking a unique-constraint failure for the entire conversation.
- A fresh clone now starts a working stack. `KEMORY_RUN_MIGRATIONS` was set to
  `false` in the committed compose file, so the API came up against an empty
  database and every authenticated request failed with
  `relation "kemory_memories" does not exist`.
- MCP client setup instructions were unusable in every guide. They pointed at
  a `scripts/kemory_mcp_server.py` that does not exist in this repository, in
  a repository under its former name, through a hardcoded interpreter path.
  All six guides now configure the real bridge, `kemory mcp serve`, and
  mention the `kemory mcp install --host <client>` shortcut.

### Security
- Published ports now bind to `127.0.0.1` instead of every network interface,
  in both the committed compose file and the one the installer generates.
  Previously the dashboard served the local API key at `/config.json` to any
  unauthenticated caller, and the API accepted it — so anyone on the same
  network could read, modify and delete the entire memory store. If you rely
  on reaching the stack from another machine, publish the port deliberately.
- Secret scanning runs in CI (gitleaks, pinned by version and checksum, with
  rules for this project's own API-key formats), and a guard now rejects
  imports of hosted-only packages that no declared dependency provides.

[Unreleased]: https://github.com/SeKondBrainAILabs/kemory-community/compare/HEAD...HEAD
