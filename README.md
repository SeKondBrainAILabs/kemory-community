# Kemory Community Edition

> Local-first, OSS memory for AI agents. Same wire protocol as hosted
> Kemory. Apache-2.0.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Build](https://img.shields.io/github/actions/workflow/status/SeKondBrainAILabs/kemory-community/ci.yml?branch=main)](https://github.com/SeKondBrainAILabs/kemory-community/actions)
[![npm](https://img.shields.io/badge/npm-v0.1-not--yet--released-lightgrey)](https://www.npmjs.com/package/kemory-community)

## Status

v0.1.0 is available. The Docker runtime is the default setup path for local
use and QA; current development selectively ports compatible hosted features.

## Quick Start

### Run from source (Docker)

```bash
git clone https://github.com/SeKondBrainAILabs/kemory-community.git
cd kemory-community
docker compose -f docker-compose.community.yml up -d --build
```

The first build takes a few minutes (it compiles the API image and bundles
the dashboard). After that:

- API: `http://127.0.0.1:8111`
- Dashboard: `http://127.0.0.1:5175`

Same REST + MCP wire protocol as hosted Kemory, so memories are portable.

The stack starts with a default API key (`kemory-community-ci-key`) meant
for local trials. To use your own:

```bash
KEMORY_LOCAL_API_KEY="$(openssl rand -hex 24)" \
  docker compose -f docker-compose.community.yml up -d
```

### Verify your install

```bash
curl -fsS http://127.0.0.1:8111/health/ready
```

```bash
curl -fsS -H "X-API-Key: ${KEMORY_LOCAL_API_KEY:-kemory-community-ci-key}" \
  http://127.0.0.1:8111/api/v1/namespaces
```

The first returns the readiness document; the second returns your (initially
empty) namespace list. A `401` from the second means the key doesn't match
what the API container was started with.

Ask across local memories, captured chats, and searchable text artifacts:

```bash
curl -fsS http://127.0.0.1:8111/api/v1/ask \
  -H "X-API-Key: ${KEMORY_LOCAL_API_KEY:-kemory-community-ci-key}" \
  -H "Content-Type: application/json" \
  -d '{"query":"What did we decide?","synthesize":false}'
```

Set a Groq key in the dashboard Settings page to synthesize a cited answer.
Without one, Ask still returns the ranked local evidence and an explicit
`digest_unavailable` reason.

### npm installer

```bash
npx kemory-community@latest init --runtime docker
npx kemory-community@latest up
```

The installer generates a compose file with a randomly generated API key and
pulls prebuilt images, waits for the API and dashboard to become ready, and
writes a secret-free `mcp.json` that starts the MCP bridge through Docker.
Use `npx kemory-community@latest doctor` for a live install check and
`npx kemory-community@latest down` to stop the stack. **Not available yet:** the npm
package and the public images for v0.1 are pending publication (see the npm
badge above). Until then, use the run-from-source path.

### Namespace tags

Kemory can automatically segment a broad namespace into view-only
`namespace:tag` groups. Search and recall still span the parent namespace.
Existing content can be previewed and tagged from the running API container:

```bash
docker compose -f docker-compose.community.yml exec api \
  python scripts/backfill_namespace_tags.py
docker compose -f docker-compose.community.yml exec api \
  python scripts/backfill_namespace_tags.py --apply
```

Promoting a tag to its own namespace is also dry-run by default:

```bash
docker compose -f docker-compose.community.yml exec api \
  python scripts/promote_namespace_tag.py \
  --namespace project:example --tag client-work --to-namespace project:client-work
```

## Your data

Kemory Community runs entirely on your machine, and it's a memory product, so
this is the first thing worth knowing:

- **Memories, chats, artifacts and indexes stay local.** Docker stores them in
  named volumes (`community_pgdata` and `community_api_data` for a source
  checkout). They survive container replacement and are deleted only when you
  explicitly remove the volumes.
- **No telemetry.** The community build ships `KMV_TELEMETRY: noop`. There is no
  analytics backend, no usage reporting, and no phone-home.
- **No account, no signup, no network identity.** Auth is a single local API key
  you control. There is no Keycloak, OIDC or OAuth in this edition.
- **Embeddings run in-process by default** (`fastembed`, a local ONNX model), so
  indexing your memories does not call out to anyone.
- **Outbound calls happen only for features you configure yourself** — a
  summarisation or alternative embedding provider you supply a key for. The
  provider key variables ship empty; leave them unset and nothing leaves the
  machine.

Full detail in [docs/privacy.md](docs/privacy.md).

## Community vs hosted

Same REST + MCP wire protocol, so memories are portable between them.

| | Community | Hosted |
| --- | --- | --- |
| Identity | one local API key | Keycloak / OIDC, orgs, teams |
| Tenancy | single user | multi-org with per-tenant isolation |
| Permissions | owner has full access | Gatekeeper rule engine |
| Vector search | pgvector | pgvector + hosted vector store |
| Blob storage | local filesystem | object storage |
| Telemetry | none | hosted analytics |
| Licence | Apache-2.0 | commercial |

Which upstream changes are ported, adapted or excluded — and why — is recorded
per cohort in [docs/HOSTED_DELTA_LEDGER.md](docs/HOSTED_DELTA_LEDGER.md).

## What ships in v0.1

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the full table.
Read the complete public documentation at
[docs.sekondbrain.ai/kemory/community](https://docs.sekondbrain.ai/kemory/community/).
Repository-local copies of the [port registry](docs/PORT_REGISTRY.md) and
[hosted delta ledger](docs/HOSTED_DELTA_LEDGER.md) remain beside the code so
runtime and upstream-sync changes can be reviewed atomically.

## Questions / feedback

[Discussions](https://github.com/SeKondBrainAILabs/kemory-community/discussions).
Bugs: [Issues](https://github.com/SeKondBrainAILabs/kemory-community/issues).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
