# Port Registry

Kemory Community reserves these local ports for the Docker runtime.

| Service | Host Port | Container Port | Notes |
| --- | ---: | ---: | --- |
| API | `8111` | `8000` | FastAPI backend |
| Dashboard | `5175` | `5173` | Vite/nginx dashboard image |
| Postgres + pgvector | `5434` | `5432` | Optional host exposure for inspection |

The CLI defaults in `bin/kemory-community.js`, `docker-compose.community.yml`,
and setup docs must stay aligned with this registry.
