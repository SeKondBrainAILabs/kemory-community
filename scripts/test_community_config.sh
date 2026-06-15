#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kemory-community-config}"
COMPOSE=(docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.community.yml)
QA_LOG="$(mktemp -t kemory-community-qa.XXXXXX.log)"

cleanup() {
  local status=$?
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  if [[ $status -eq 0 ]]; then
    rm -f "$QA_LOG"
  else
    echo "QA log retained at $QA_LOG" >&2
  fi
  exit "$status"
}
trap cleanup EXIT

export COMPOSE_DOCKER_CLI_BUILD=1
export DOCKER_BUILDKIT=1

echo "Validating docker-compose.community.yml"
"${COMPOSE[@]}" config >/dev/null

if command -v shellcheck >/dev/null 2>&1; then
  echo "Running shellcheck"
  shellcheck scripts/test_community_config.sh
else
  echo "shellcheck not found; skipping shell lint"
fi

echo "Running enterprise leak grep guard"
if grep -R --line-number --fixed-strings "from backend.plugins.cognition.enterprise" backend/plugins/cognition/community; then
  echo "Community cognition plugin imports enterprise code" >&2
  exit 1
fi
if grep -R --line-number -E '\b(namespace_merge|suggest_merge)\b' backend/plugins/cognition/community; then
  echo "Community cognition plugin references enterprise merge stages" >&2
  exit 1
fi

echo "Running enterprise-symbol grep guard (outside their adapter)"
ENTERPRISE_SYMBOLS='minio|weaviate|keycloak|posthog'
LEAKS=$(grep -RnE "^(from|import)\s+(${ENTERPRISE_SYMBOLS})\b" backend/ \
  | grep -vE "^backend/adapters/(blob_store|vector_store|identity_provider|telemetry)/" \
  || true)
if [ -n "$LEAKS" ]; then
  echo "Enterprise symbol imported outside its adapter:" >&2
  echo "$LEAKS" >&2
  exit 1
fi

echo "Building community API image"
"${COMPOSE[@]}" build api

echo "Starting community data services"
"${COMPOSE[@]}" up -d postgres redis

echo "Waiting for community data services"
postgres_ready=0
redis_ready=0
for _ in $(seq 1 60); do
  if [[ "$postgres_ready" -ne 1 ]] && "${COMPOSE[@]}" exec -T postgres pg_isready -U kora -d kora_vault >/dev/null 2>&1; then
    postgres_ready=1
  fi
  if [[ "$redis_ready" -ne 1 ]] && "${COMPOSE[@]}" exec -T redis redis-cli ping >/dev/null 2>&1; then
    redis_ready=1
  fi
  if [[ "$postgres_ready" -eq 1 && "$redis_ready" -eq 1 ]]; then
    break
  fi
  sleep 2
done
if [[ "$postgres_ready" -ne 1 || "$redis_ready" -ne 1 ]]; then
  "${COMPOSE[@]}" ps >&2 || true
  echo "Community data services did not become ready" >&2
  exit 1
fi

echo "Bootstrapping fresh community database schema"
"${COMPOSE[@]}" run --rm -T --no-deps api sh -eu -c '
python - <<'"'"'PY'"'"'
import asyncio

from sqlalchemy import text

import backend.models  # noqa: F401 - registers all ORM tables
from backend.core.database import Base, _get_engine


async def main() -> None:
    engine = _get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()


asyncio.run(main())
PY
python -m alembic -c alembic.ini stamp head
'

echo "Starting community API"
"${COMPOSE[@]}" up -d api

echo "Waiting for API readiness"
ready=0
for _ in $(seq 1 90); do
  if "${COMPOSE[@]}" exec -T api curl -fsS http://127.0.0.1:8000/health/ready >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" -ne 1 ]]; then
  "${COMPOSE[@]}" logs --no-color api >&2 || true
  echo "API did not become ready" >&2
  exit 1
fi

echo "Verifying Alembic revision inside the API container"
"${COMPOSE[@]}" exec -T api python -m alembic -c alembic.ini current

echo "Running qa_full_test.py inside the API container"
set +e
"${COMPOSE[@]}" exec -T api python scripts/qa_full_test.py --api http://127.0.0.1:8000 2>&1 | tee "$QA_LOG"
qa_status=${PIPESTATUS[0]}
set -e

if [[ "$qa_status" -eq 0 ]]; then
  echo "qa_full_test.py passed in community Docker mode"
else
  echo "qa_full_test.py exited $qa_status; checking for local_single_user Bearer-token mismatch"
  bearer_probe="$("${COMPOSE[@]}" exec -T api curl -sS -H "Authorization: Bearer community-probe" http://127.0.0.1:8000/api/v1/agents || true)"
  if [[ "$bearer_probe" != *"jwt_requires_hosted_kemory"* ]]; then
    echo "qa_full_test.py failed for a reason other than the expected community Bearer-token rejection" >&2
    exit "$qa_status"
  fi
  echo "Confirmed local_single_user rejects Bearer JWTs; running community API-key probe"
  "${COMPOSE[@]}" exec -T api python - <<'PY'
import os
import sys

import httpx

base = "http://127.0.0.1:8000"
api_key = os.environ["KEMORY_LOCAL_API_KEY"]
headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
checks: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append((name, ok, detail))
    marker = "PASS" if ok else "FAIL"
    suffix = f" ({detail})" if detail else ""
    print(f"{marker}: {name}{suffix}")


with httpx.Client(base_url=base, timeout=30.0) as client:
    ready = client.get("/health/ready")
    check("readiness is healthy", ready.status_code == 200, str(ready.status_code))

    no_creds = client.get("/api/v1/agents")
    check("no credentials rejected", no_creds.status_code == 401, str(no_creds.status_code))

    bearer = client.get("/api/v1/agents", headers={"Authorization": "Bearer local-jwt-probe"})
    check(
        "Bearer JWT rejected with hosted-upgrade response",
        bearer.status_code == 401 and bearer.json().get("error") == "jwt_requires_hosted_kemory",
        bearer.text[:120],
    )

    agents = client.get("/api/v1/agents", headers=headers)
    check("local API key authenticates", agents.status_code == 200, str(agents.status_code))

    for scope in ("memory:read", "memory:write", "memory:delete"):
        response = client.post(
            "/api/v1/permissions",
            headers=headers,
            json={"scope": scope, "action": "allow", "priority": 10, "namespace_filter": "*"},
        )
        check(f"permission {scope} created", response.status_code in (200, 201), str(response.status_code))

    memory = client.post(
        "/api/v1/memories",
        headers=headers,
        json={
            "namespace": "community:smoke",
            "content": "Community config smoke test memory for pgvector and local identity.",
            "content_type": "text",
        },
    )
    check("memory write succeeds with local API key", memory.status_code in (200, 201), str(memory.status_code))

    search = client.post(
        "/api/v1/memories/search",
        headers=headers,
        json={"namespace": "community:smoke", "query": "pgvector local identity", "limit": 5},
    )
    total = search.json().get("total") if search.status_code == 200 else None
    check("memory search succeeds on pgvector config", search.status_code == 200 and total is not None, f"total={total}")

    artifact = client.post(
        "/api/v1/artifacts/upload",
        headers={"X-API-Key": api_key},
        data={"namespace": "community:smoke", "artifact_type": "text"},
        files={"file": ("community.txt", b"community local_fs artifact\n", "text/plain")},
    )
    body = artifact.json() if artifact.status_code in (200, 201) else {}
    metadata = body.get("artifact_metadata") if isinstance(body.get("artifact_metadata"), dict) else {}
    check(
        "artifact upload succeeds on local_fs",
        artifact.status_code in (200, 201)
        and body.get("namespace") == "community:smoke"
        and bool(body.get("content_url"))
        and bool(metadata.get("storage_key")),
        f"status={artifact.status_code} url={bool(body.get('content_url'))}",
    )

env_expectations = {
    "KMV_VECTOR_BACKEND": "pgvector",
    "KMV_BLOB_BACKEND": "local_fs",
    "KMV_IDENTITY": "local_single_user",
    "KMV_TELEMETRY": "noop",
    "KMV_COGNITION_ENTERPRISE": "false",
}
for key, expected in env_expectations.items():
    check(f"{key}={expected}", os.environ.get(key) == expected, os.environ.get(key, ""))

failures = [name for name, ok, _ in checks if not ok]
if failures:
    print("\nCommunity probe failures:")
    for name in failures:
        print(f" - {name}")
    sys.exit(1)
PY
fi

echo "Community config Docker verification passed"
