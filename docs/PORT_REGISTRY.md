# Port Registry

Kemory Community reserves these local ports for its Docker runtimes.

| Mode | Service | Host Port | Container Port | Notes |
| --- | --- | ---: | ---: | --- |
| Both | API | `8111` | `8000` | FastAPI backend, loopback only |
| Both | Dashboard | `5175` | `5173` | Vite/nginx dashboard, loopback only |
| Standalone | Postgres + pgvector | `5434` | `5432` | Community-owned container |
| Shared | PostgreSQL | `5432` | `5432` | Infra-owned; database/user `kemory_community` |
| Shared | Redis | `6379` | `6379` | Infra-owned; logical database `14` |

The CLI defaults in `bin/kemory-community.js`, `docker-compose.community.yml`,
`docker-compose.shared.yml`, and setup docs must stay aligned with this
registry. The shared allocation is also recorded in
`infrastructure/PORT_REGISTRY.md` for mirroring to `~/infra/docs/PORT_REGISTRY.md`.
