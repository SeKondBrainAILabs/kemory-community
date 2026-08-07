# Setup

Two ways to run Kemory Community Edition. Both use the same Docker stack and
the same reserved local ports:

| Service | Host | Container |
| --- | ---: | ---: |
| API | `8111` | `8000` |
| Dashboard | `5175` | `5173` |
| Postgres + pgvector | `5434` | `5432` |

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

The installer writes a compose file with a randomly generated API key into
`.kemory-community/` and pulls prebuilt images from GHCR.

### Local runtime

```bash
npx kemory-community@latest init --runtime local
```

The local runtime writes configuration only. It is useful for inspecting the
generated settings, but it does not start services in v0.1.
