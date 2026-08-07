# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Rolling, token-budgeted session context with the latest three exchanges kept raw.
- Read-only digest provenance expansion through `kemory_rehydrate_session_sources`.
- Hosted-to-community delta ledger for explicit port/adapt/exclude decisions.
- Initial repo scaffolding (Apache-2.0 license, README, docs, CI, npm package shell). Backend code lands in v0.1.0.
- npm setup CLI for Docker-first community runtime configuration.
- Community backend/dashboard import with Docker compose for API, dashboard, Redis, and pgvector.
- Canonical `kemory_*` MCP tool names with `s9nmem_*` and `kora_*` compatibility aliases.
- Indexed pgvector retrieval with legacy-row fallback, batch encoding, deterministic ranking, and optional score floors.
- Standard MCP JSON-RPC 2.0 transport over authenticated HTTP and stdio.
- Dashboard Settings page for API key, runtime settings, JSON export, and JSON import.
- Responsive memory explorer with relevance sorting, result highlighting, Markdown detail, history, namespace filtering, and URL-backed pagination.
- Community-only dashboard surface with X-API-Key requests and no hosted identity, graph, or admin workflows.
- Community-only API route allowlist with no Gatekeeper evaluation, CogOS compression, or hosted telemetry startup.
- Community port registry at `docs/PORT_REGISTRY.md`.

[Unreleased]: https://github.com/SeKondBrainAILabs/kemory-community/compare/HEAD...HEAD
