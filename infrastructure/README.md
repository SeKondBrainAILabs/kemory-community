# Shared Infrastructure Deployment

This directory contains the SeKondBrain deployment contract for Kemory
Community. The public installer remains self-contained; this deployment joins
the machine-wide `shared-infra` Docker network and reuses its PostgreSQL and
Redis containers with logical isolation.

```bash
./infrastructure/provision-shared-infra.sh
docker compose --env-file .env.shared -f docker-compose.shared.yml up -d --build
```

Provisioning is idempotent. It starts the shared stack, creates the dedicated
`kemory_community` PostgreSQL database and user, enables `vector` and `pg_trgm`,
reserves Redis database `14`, and writes a mode-`0600` `.env.shared` file.

For an existing standalone source deployment, stop writes and migrate before
the first shared-mode start:

```bash
docker compose -p kemory-community -f docker-compose.community.yml stop api dashboard
./infrastructure/migrate-standalone-data.sh
docker compose -p kemory-community -f docker-compose.community.yml down
docker compose -p kemory-community --env-file .env.shared -f docker-compose.shared.yml up -d --build
```

The migration refuses a non-empty target, verifies exact row counts for every
public table, and never deletes the source database or volume. Shared mode
deliberately reuses the existing `community_api_data` volume for settings and
local artifacts. Redis contains disposable runtime state and starts empty in
its reserved shared logical database.

Only the Community API and dashboard are application containers. PostgreSQL
and Redis remain owned by `~/infra`; do not add duplicate database or cache
services to `docker-compose.shared.yml`.
