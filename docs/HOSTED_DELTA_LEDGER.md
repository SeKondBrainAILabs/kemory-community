# Hosted Kemory Delta Ledger

This ledger tracks the downstream relationship between hosted Kemory and
Kemory Community. The community repository receives selected subtree changes;
it is not a mirror of the hosted product.

## Repository Relationship

`SeKondBrainAILabs/kemory-community` is an independent public repository, not
a GitHub fork. Hosted Kemory is the upstream product and design source; the
community repository preserves its own release history, Docker runtime, npm
installer, local-user security boundary, and Apache-2.0 distribution surface.

Updates are intentionally replayed by feature cohort rather than merged as a
whole upstream tree. For each hosted baseline:

1. List every hosted commit after the last inspected hash.
2. Classify it as port, adapt, or exclude against the community boundaries.
3. Replay compatible behavior in a `community/` pull request with Docker tests.
4. Record source commits, adaptations, exclusions, and the new baseline here.
5. Verify the community repository still carries upstream's **security gates**,
   not just its code — see below.

This avoids reintroducing hosted authentication, billing, telemetry, storage,
analytics, or organisation workflows while keeping compatible memory behavior
and wire contracts current.

Replay is deliberately manual. There is no automated subtree-pull job: a
scheduled mirror would defeat the per-cohort classification that keeps hosted
concerns out of this repository.

### Step 5 — why gates need their own step

Steps 1-4 decide which *code* crosses the boundary. They say nothing about the
CI and repository settings that catch a bad crossing, and those do not travel
with a subtree import. Every one of the following was true at the v0.1.0
baseline:

- upstream ran gitleaks with a tuned config; this repository had no secret
  scanning of any kind, on the one repository where a leak is public the moment
  it lands
- GitHub secret scanning and push protection were enabled upstream and disabled
  here — GitHub only turns them on by default for public repositories owned by
  *personal accounts*, never organisation-owned ones
- `ruff` and `compileall` covered `backend`, `kemory`, `kemory_cli` and `tests`
  but not `scripts/`, so a ported script that raised `ImportError` on its first
  line passed every check
- the forbidden-package guard read `pyproject.toml` only, so a ported module
  could import a package nobody declared
- Dependabot pointed at a lockfile the build does not use, while the lockfile it
  does use went unwatched

So each replay must confirm: scanners still run and still cover the new paths,
lint and compile roots include everything shipped, the community boundary
guards in `scripts/test_community_config.sh` still fail on what they should,
and repository security settings match upstream's. A gate that silently stopped
covering something is indistinguishable from a gate that passes.

## Baseline

- Community release baseline: `v0.1.0` at `d97ff32fe`.
- Hosted baseline inspected: `300696e8e9` (`v2.21.1`); previous recorded
  baseline was `60390acd5f` (`v1.8.2`).
- Backend subtree anchor: `5b70a8a884` (equivalent hosted tree at `305adba0e8:backend`).
- Python SDK anchor: `ea2c494530`.
- CLI anchor: `6fb85a6d4b`.
- Dashboard anchor: `c82bebf5cd`.

The `v2.21.1` audit classified 784 hosted commits after the previous recorded
baseline. Its final refresh window contained 46 merged PRs and 215 commits
after the local hosted `v2.10.0` checkout. Changes are ported by feature cohort,
with community adapters and Docker runtime constraints applied at each
boundary; the hosted worktree itself was not modified during the audit.

## Classification

| Cohort | Decision | Community treatment |
| --- | --- | --- |
| Rolling session digest and raw-source rehydration (hosted PR #152) | Port and adapt | New `018` migration, local user scope, latest three exchanges raw, whole-item source expansion, no AAAK prompt context. |
| MCP JSON-RPC transport and canonical names | Ported and adapted | Standard JSON-RPC 2.0 over HTTP and stdio; advertise `kemory_*` only; retain `s9nmem_*` and `kora_*` dispatch aliases; keep X-API-Key auth. |
| Pgvector search scale, batch encoding, retrieval floor | Ported and adapted | ANN search and transactional writes use `kemory_memory_vectors`; legacy rows remain searchable; omit Gatekeeper, org fairness, and hosted telemetry. |
| Source content dates for memories, chat turns, and artifacts | Ported and adapted | Migration `019`; source timestamps remain nullable, local uploads send `File.lastModified`, and reads fall back to ingest time without inventing source dates. Adapted from hosted `11f3322`, `cb7a33e`, `391b5c2`, `6480507`, and `3b73f70`. |
| Memory timeline | Ported and adapted | Unified chat/memory source chronology with local-user keyset pagination and provenance; no Gatekeeper, hosted telemetry, or organisation analytics. Adapted from hosted `f4aad73` and `8325d9f`, with `occurred_at` support from the later chronology cohort. |
| Namespace tags | Ported and adapted | Migration `020`; local-user profiles, direct user-key Groq naming, deterministic entity/embedding/era matching, dry-run Docker backfill and promotion tools, and dashboard chips. No hosted Gatekeeper, audit, provenance, or organisation workflows. Adapted from hosted `554a427`, `50052ce`, `0086767`, `8bf0fc4`, `eeed4c6`, and `01b6883`. |
| Memory and namespace dashboard UX | Ported selectively | Improved explorer, detail/history, URL pagination, responsive navigation, and container runtime; uses X-API-Key only and exposes community workflows; excluded private design-system packages. |
| Community release surfaces and model configuration | Ported and adapted | Dedicated artifacts and doctor pages; persisted Groq, embedding, artifact-limit, and log settings; direct user-key Groq calls replace the hosted AI proxy. |
| Python CLI and stdio bridge | Ported and adapted | Local endpoint plus API-key configuration only; OAuth device flow, Bearer forwarding, hosted environments, org/team commands, telemetry, and hosted release upgrades are removed. |
| Ask over retrieved evidence (`b7e3898`, `37aacc1`) | Ported and adapted | `POST /api/v1/ask`, `kemory_ask`, and `kemory ask` search local memories, captured chats, and inline text artifacts. The configured user-supplied Groq key replaces the hosted gateway; evidence still returns when synthesis is disabled or unavailable. |
| MCP output schemas (`36c3d68`) | Ported selectively | MCP definitions and results support additive `outputSchema` and `structuredContent`; Ask declares and returns the structured envelope while legacy text remains intact. Hosted project/account tools remain absent. |
| Container hardening (`1d54fda`, `424e8aa`, `ada5236`) | Ported and adapted | Multi-stage API image, non-root UID 1001 runtime, writable Community config directory, no compiler toolchain in the final image. Community administration scripts remain because the Docker-first docs invoke them. |
| Ruff toolchain refresh (`5df260b`) | Ported | CI pins Ruff 0.16.3 and preserves the existing explicit rule policy. |
| Chat duplicate-source ingestion (`f217450`) | Ported and adapted | Repeated `source_turn_id` values in one Community push collapse last-write-wins before persistence; id-less turns remain distinct. |
| Retrieval-v2 question vectors, blind indexes, lexical calibration, cross-encoder reranking, and chat/file ANN | Deferred for Community-native design | Hosted migrations `080`-`100`, encryption keys, tenant blind indexes, embedding gateway, and benchmark infrastructure do not exist in Community. Ask uses the existing pgvector/FTS engine plus local chat/file evidence; future retrieval work must be measured against Community's schema before replay. |
| Hosted onboarding and MCP connection board | Excluded from direct replay | The new board verifies OAuth grants, DCR client adoption, managed connectors, and hosted Known Issues. Community retains its API-key Quick Connect and Settings/Doctor surfaces; copying the board would present unavailable setup paths. |
| Hosted enrichment caches and AI routing (`560abc6`, `5f74eee`, `82f27b8`) | Not applicable | These fixes protect tenant-pinned hosted gateway calls and model-output caches. Community enrichment is deterministic or calls the user's Groq endpoint directly and has neither cache. |
| Post-`v1.7.6` build security (`63b8035`, `60390ac`) | Ported and adapted | Raise the Vite floor to `^6.4.3`, refresh safe transitive dependency pins, and build the dashboard plus Node-based CI/release jobs on Node 24. Community retains npm/package-lock instead of hosted pnpm/private design-system dependencies. |
| Post-`v1.7.6` exec analytics, pooled value mode, and agent-admin auth (`14ff2f2`, `fa0ad02`, `fb2da18`) | Excluded | These commits operate on hosted executive analytics, cross-org pooling, and agent/account-admin authorization. None of those routes or identity modes execute in local single-user Community. |
| Keycloak, OIDC, OAuth, DCR, teams, Gatekeeper, trusted org delegation | Excluded | Removed dashboard identity/Bearer paths and hosted admin navigation; community boot does not import or mount agent JWT, pairing, identity/team, permission, or Gatekeeper routers, and memory reads bypass rule evaluation under `local_single_user`. |
| Weaviate, FalkorDB, MinIO, PostHog, Kafka, KMS, Core Backend billing | Exclude | Community boot remains pgvector, local filesystem, noop telemetry, and user-supplied local services only. |
| Hosted L5/CogOS push and executive analytics | Exclude | Hosted-only cognition and operational product surfaces. |

## Ported In This Cohort

- Local-first Ask across memories, captured chats, and inline text artifacts,
  with REST, MCP, and Python CLI parity and honest no-synthesis reasons.
- Additive MCP `outputSchema` / `structuredContent` support for Ask.
- Searchable inline copies of UTF-8 text uploads up to 1 MiB; the local blob
  remains the authoritative download body.
- Last-write-wins collapse for repeated chat turn source ids in one push.
- Multi-stage, non-root Community API image with no build toolchain at runtime.
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
- Community backend route allowlist, explicit local Gatekeeper bypass, noop telemetry boot, and no CogOS compression path
- Community Artifacts workspace, Doctor health route, persisted runtime Settings UI,
  direct Groq client, and configurable 384-dimensional embedding providers. Voyage
  and Cohere opt-ins request their supported 512-dimensional Matryoshka output,
  then truncate and normalize it to the community schema's fixed 384 dimensions.
- Nullable `occurred_at` source chronology across memories, chat turns, and artifacts;
  source-aware date filters and MCP recall; file modified-date capture; and dashboard
  Happened, Added, and Updated views. The hosted turn wire contract is retained as
  `timestamp`, while authentication and tenancy remain community-local.
- Unified namespace timeline with server-side chat/memory merge ordering, opaque
  keyset cursors, source-platform attribution, provenance counts, and a filtered
  dashboard stream.
- Automatic namespace tag profiles and ingest assignment, local-user tag reads,
  dry-run backfill and promotion tools, timeline/search/MCP attribution, and
  responsive dashboard chips. Tags partition views while recall continues to
  search the parent namespace.
- Focused service and MCP-contract tests

Future cohorts must update this ledger with source commit or PR, classification,
adaptation notes, migrations, tests, and documentation before merge.
