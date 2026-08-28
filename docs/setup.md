# Setup

Kemory Community supports a portable standalone Docker stack and a
SeKondBrain shared-infrastructure deployment. Both publish the same API and
dashboard ports:

| Service | Host | Container |
| --- | ---: | ---: |
| API | `8111` | `8000` |
| Dashboard | `5175` | `5173` |
| Postgres + pgvector | `5434` | `5432` |

The `5434` allocation is standalone-only. Shared mode uses the existing infra
PostgreSQL port `5432` with a dedicated `kemory_community` database and user.

## Run from source (available today)

Builds the API and dashboard images locally — no registry access or npm
package needed, just Docker.

```bash
git clone https://github.com/SeKondBrainAILabs/kemory-community.git
cd kemory-community
docker compose -f docker-compose.community.yml up -d --build
```

The API will be available at `http://127.0.0.1:8111` and the dashboard at
`http://127.0.0.1:5175`.

The stack starts with a default API key (`kemory-community-ci-key`) intended
for local trials. Set your own before starting:

```bash
KEMORY_LOCAL_API_KEY="$(openssl rand -hex 24)" \
  docker compose -f docker-compose.community.yml up -d
```

## Run on SeKondBrain shared infrastructure

This mode starts only the Community API and dashboard containers. PostgreSQL
and Redis remain owned by `~/infra` and are reached over the external
`shared-infra` Docker network.

```bash
./infrastructure/provision-shared-infra.sh
docker compose --env-file .env.shared -f docker-compose.shared.yml up -d --build
```

The idempotent provisioner starts shared infrastructure, creates the isolated
`kemory_community` database/user, enables `vector` and `pg_trgm`, reserves
Redis database `14`, and writes generated secrets to mode-`0600`
`.env.shared`. Ports are registered in
[`infrastructure/PORT_REGISTRY.md`](../infrastructure/PORT_REGISTRY.md).

When converting an existing standalone source deployment, use the guarded
[`migrate-standalone-data.sh`](../infrastructure/migrate-standalone-data.sh)
procedure in `infrastructure/README.md` before the first shared start. It
preserves the source database and reuses the existing artifact/config volume.

### Verify

```bash
curl -fsS http://127.0.0.1:8111/health/ready
curl -fsS -H "X-API-Key: ${KEMORY_LOCAL_API_KEY:-kemory-community-ci-key}" \
  http://127.0.0.1:8111/api/v1/namespaces
```

The first call returns the readiness document; the second returns your
(initially empty) namespace list. A `401` on the second means the key doesn't
match what the API container was started with.

## npm installer (pending first publish)

> **Status:** the `kemory-community` npm package and the public container
> images for v0.1 have not been published yet. These commands will work once
> they are; until then use the run-from-source path above.

```bash
npx kemory-community@latest init --runtime docker
npx kemory-community@latest up
```

For a machine with the SeKondBrain shared stack:

```bash
npx kemory-community@latest init --runtime docker --infra shared
npx kemory-community@latest provision-shared
npx kemory-community@latest up
```

The installer writes a compose file with a randomly generated API key into
`.kemory-community/`, pulls prebuilt images from GHCR, waits for readiness,
and generates `.kemory-community/mcp.json`. The MCP configuration contains no
API key; its Node bridge starts `kemory mcp serve` inside the API container.

```bash
npx kemory-community@latest doctor
npx kemory-community@latest mcp-config
npx kemory-community@latest down
```

Standalone mode uses Docker named volumes for PostgreSQL and
artifact/configuration data. Shared mode keeps PostgreSQL in the infra-owned
database and uses one Community-owned volume for artifacts/configuration.
`docker compose down` preserves application data; destructive volume or
database deletion remains an explicit operator action.

### Local runtime

```bash
npx kemory-community@latest init --runtime local
```

The local runtime writes configuration only. It is useful for inspecting the
generated settings, but it does not start services in v0.1.
