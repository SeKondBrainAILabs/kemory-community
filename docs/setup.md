# Setup

Kemory Community Edition is installed through npm. v0.1 supports the Docker
runtime and reserves the local ports below.

- `docker` - default and recommended for local development and QA.
- `local` - writes host-local configuration only; binary packaging is deferred.

Docker is the default path for local development, QA, and the first community
release.

## Docker Runtime

```bash
npx kemory-community@latest init --runtime docker
npx kemory-community@latest up
```

The Docker runtime uses the local port registry allocation:

| Service | Host | Container |
| --- | ---: | ---: |
| API | `8111` | `8000` |
| Dashboard | `5175` | `5173` |
| Postgres + pgvector | `5434` | `5432` |

The API will be available at `http://127.0.0.1:8111` and the dashboard at
`http://127.0.0.1:5175`.

## Local Runtime

```bash
npx kemory-community@latest init --runtime local
```

The local runtime writes configuration only. It is useful for inspecting the
generated settings, but it does not start services in v0.1.
