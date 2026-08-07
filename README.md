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

Two commands to a working memory service for your AI agents:

```bash
npx kemory-community@latest init --runtime docker
npx kemory-community@latest up
```

Local Docker API at `http://127.0.0.1:8111`, dashboard at
`http://127.0.0.1:5175`. Same REST + MCP wire protocol as hosted
Kemory, so memories are portable.

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
