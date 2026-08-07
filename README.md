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

### npm installer

```bash
npx kemory-community@latest init --runtime docker
npx kemory-community@latest up
```

The installer generates a compose file with a randomly generated API key and
pulls prebuilt images — no clone needed. **Not available yet:** the npm
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
