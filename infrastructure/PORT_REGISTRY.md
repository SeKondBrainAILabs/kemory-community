# Shared Infrastructure Port Registry

Kemory Community uses these allocations when deployed on the external
`shared-infra` Docker network. This file is the application-owned registry
entry and must be mirrored into `~/infra/docs/PORT_REGISTRY.md`.

| Owner | Service | Host Port | Container Port | Network / isolation |
| --- | --- | ---: | ---: | --- |
| Kemory Community | API | `8111` | `8000` | `shared-infra` |
| Kemory Community | Dashboard | `5175` | `5173` | `shared-infra` |
| Shared infrastructure | PostgreSQL | `5432` | `5432` | Database/user `kemory_community` |
| Shared infrastructure | Redis | `6379` | `6379` | Logical database `14` |

The shared deployment does not publish a second PostgreSQL or Redis port.
The standalone public installer retains PostgreSQL host port `5434` because it
runs its own isolated backing-service containers.
