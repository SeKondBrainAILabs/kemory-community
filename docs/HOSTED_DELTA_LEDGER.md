# Hosted Kemory Delta Ledger

This ledger tracks the downstream relationship between hosted Kemory and
Kemory Community. The community repository receives selected subtree changes;
it is not a mirror of the hosted product.

## Baseline

- Community release baseline: `v0.1.0` at `d97ff32fe`.
- Hosted baseline inspected: `dcaa931ae8` (`v1.7.6`).
- Backend subtree anchor: `5b70a8a884` (equivalent hosted tree at `305adba0e8:backend`).
- Python SDK anchor: `ea2c494530`.
- CLI anchor: `6fb85a6d4b`.
- Dashboard anchor: `c82bebf5cd`.

The backend delta contains 374 effective commits. Dashboard contains 186
effective commits. Changes are therefore ported by feature cohort, with
community adapters and Docker runtime constraints applied at each boundary.

## Classification

| Cohort | Decision | Community treatment |
| --- | --- | --- |
| Rolling session digest and raw-source rehydration (hosted PR #152) | Port and adapt | New `018` migration, local user scope, latest three exchanges raw, whole-item source expansion, no AAAK prompt context. |
| MCP JSON-RPC transport and canonical names | Ported and adapted | Standard JSON-RPC 2.0 over HTTP and stdio; advertise `kemory_*` only; retain `s9nmem_*` and `kora_*` dispatch aliases; keep X-API-Key auth. |
| Pgvector search scale, batch encoding, retrieval floor | Ported and adapted | ANN search and transactional writes use `kemory_memory_vectors`; legacy rows remain searchable; omit Gatekeeper, org fairness, and hosted telemetry. |
| Chat source chronology, timeline, content dates, namespace tags | Planned port | Keep local user scope and PostgreSQL; assign sequential community migrations. |
| Memory and namespace dashboard UX | Ported selectively | Improved explorer, detail/history, URL pagination, responsive navigation, and container runtime; uses X-API-Key only and exposes community workflows; excluded private design-system packages. |
| Keycloak, OIDC, OAuth, DCR, teams, Gatekeeper, trusted org delegation | Excluded | Removed dashboard identity/Bearer paths and hosted admin navigation; backend portability code cannot execute under `local_single_user`. |
| Weaviate, FalkorDB, MinIO, PostHog, Kafka, KMS, Core Backend billing | Exclude | Community boot remains pgvector, local filesystem, noop telemetry, and user-supplied local services only. |
| Hosted L5/CogOS push and executive analytics | Exclude | Hosted-only cognition and operational product surfaces. |

## Ported In This Cohort

- `kemory_get_session_context`
- `kemory_rehydrate_session_sources`
- `kemory_session_digests` schema and ORM model
- Prompt `session_digest_v1`
- Canonical-only MCP discovery with legacy dispatch aliases
- Pgvector ANN retrieval, transactional vector upsert, ordered batch encoding,
  deterministic RRF, concept boost, and configurable result-score floor
- Standard MCP JSON-RPC methods at `/mcp/v1`, with stdio bridge parity
- Selective memory explorer and namespace dashboard UX with responsive and accessible states
- Community-only dashboard runtime config, X-API-Key client, routes, health surface, and memory levels
- Focused service and MCP-contract tests

Future cohorts must update this ledger with source commit or PR, classification,
adaptation notes, migrations, tests, and documentation before merge.
