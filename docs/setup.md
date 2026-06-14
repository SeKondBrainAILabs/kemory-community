# Setup

Kemory Community Edition is installed through npm. v0.1 will support two
runtime modes:

- `docker` - default and recommended for local development and QA.
- `local` - uses the downloaded platform binary directly on the host.

For the current scaffold, Docker setup files can be generated before the
backend image is published.

## Docker Runtime

```bash
npx kemory-community@pre init --runtime docker
npx kemory-community@pre up
```

The Docker runtime uses the local port registry allocation:

| Service | Host | Container |
| --- | ---: | ---: |
| API | `8111` | `8100` |
| Dashboard | `5175` | `5173` |
| Postgres + pgvector | `5434` | `5432` |

The API will be available at `http://127.0.0.1:8111` and the dashboard at
`http://127.0.0.1:5175`.

## Local Runtime

```bash
npx kemory-community@pre init --runtime local
```

The local runtime writes configuration only in the scaffold release. v0.1 will
wire this mode to the downloaded platform binary.
