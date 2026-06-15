# Kemory Community Edition

> Local-first, OSS memory for AI agents. Same wire protocol as hosted
> Kemory. Apache-2.0.

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Build](https://img.shields.io/github/actions/workflow/status/SeKondBrainAILabs/kemory-community/ci.yml?branch=main)](https://github.com/SeKondBrainAILabs/kemory-community/actions)
[![npm](https://img.shields.io/badge/npm-v0.1-not--yet--released-lightgrey)](https://www.npmjs.com/package/kemory-community)

## Status

v0.1.0 community build is in progress. The Docker runtime is the default
setup path for local use and QA.

## Quick Start

Two commands to a working memory service for your AI agents:

```bash
npx kemory-community@latest init --runtime docker
npx kemory-community@latest up
```

Local Docker API at `http://127.0.0.1:8111`, dashboard at
`http://127.0.0.1:5175`. Same REST + MCP wire protocol as hosted
Kemory, so memories are portable.

## What ships in v0.1

See [PROJECT_PLAN.md](PROJECT_PLAN.md) for the full table.
See [docs/PORT_REGISTRY.md](docs/PORT_REGISTRY.md) for the local Docker
ports.

## Questions / feedback

[Discussions](https://github.com/SeKondBrainAILabs/kemory-community/discussions).
Bugs: [Issues](https://github.com/SeKondBrainAILabs/kemory-community/issues).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
