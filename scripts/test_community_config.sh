#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kemory-community-config}"
COMPOSE=(docker compose -p "$COMPOSE_PROJECT_NAME" -f docker-compose.community.yml)

cleanup() {
  local status=$?
  "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

export COMPOSE_DOCKER_CLI_BUILD=1
export DOCKER_BUILDKIT=1

echo "Validating docker-compose.community.yml"
"${COMPOSE[@]}" config >/dev/null

echo "Checking reserved community ports"
compose_json="$("${COMPOSE[@]}" config --format json)"
COMPOSE_JSON="$compose_json" python3 - <<'PY'
import json
import os

services = json.loads(os.environ["COMPOSE_JSON"])["services"]
expected = {"api": 8111, "dashboard": 5175, "postgres": 5434}
allowed_services = {*expected, "redis"}
if set(services) != allowed_services:
    raise SystemExit(
        f"community compose services must be {sorted(allowed_services)}; got {sorted(services)}"
    )
for service, published in expected.items():
    actual = {int(port["published"]) for port in services[service].get("ports", [])}
    if published not in actual:
        raise SystemExit(f"{service} must publish reserved port {published}; got {sorted(actual)}")
PY

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
ENTERPRISE_SYMBOLS='minio|weaviate|keycloak|posthog|falkordb|neo4j|kafka'
LEAKS=$(grep -RnE "^(from|import)\s+(${ENTERPRISE_SYMBOLS})\b" backend/ \
  | grep -vE "^backend/adapters/(blob_store|vector_store|identity_provider|telemetry)/" \
  || true)
if [ -n "$LEAKS" ]; then
  echo "Enterprise symbol imported outside its adapter:" >&2
  echo "$LEAKS" >&2
  exit 1
fi

echo "Running forbidden-package dependency guard"
python3 - <<'PY'
import tomllib
from pathlib import Path

project = tomllib.loads(Path("pyproject.toml").read_text())
dependency_groups = [project["project"].get("dependencies", [])]
dependency_groups.extend(project["project"].get("optional-dependencies", {}).values())
forbidden = (
    "minio",
    "weaviate",
    "python-keycloak",
    "posthog",
    "python-jose",
    "falkordb",
    "neo4j",
    "kafka-python",
    "confluent-kafka",
)
dependencies = [item.lower() for group in dependency_groups for item in group]
leaks = [item for item in dependencies if item.startswith(forbidden)]
if leaks:
    raise SystemExit(f"hosted-only dependencies found in community package: {leaks}")
PY

echo "Building community API and dashboard images"
"${COMPOSE[@]}" build api dashboard

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

echo "Starting and probing community dashboard"
"${COMPOSE[@]}" up -d dashboard
dashboard_ready=0
for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:5175/ >/dev/null 2>&1; then
    dashboard_ready=1
    break
  fi
  sleep 2
done
if [[ "$dashboard_ready" -ne 1 ]]; then
  "${COMPOSE[@]}" logs --no-color dashboard >&2 || true
  echo "Dashboard did not become ready on reserved port 5175" >&2
  exit 1
fi

echo "Verifying Alembic revision inside the API container"
alembic_revision="$("${COMPOSE[@]}" exec -T api python -m alembic -c alembic.ini current)"
echo "$alembic_revision"
if [[ "$alembic_revision" != *"019 (head)"* ]]; then
  echo "Expected Alembic revision 019 (head)" >&2
  exit 1
fi

echo "Verifying canonical MCP discovery surface"
"${COMPOSE[@]}" exec -T api python - <<'PY'
from backend.mcp.tools import TOOL_DEFINITIONS

names = [tool.name for tool in TOOL_DEFINITIONS]
required = {"kemory_get_session_context", "kemory_rehydrate_session_sources"}
if len(names) != 16 or len(names) != len(set(names)):
    raise SystemExit(f"expected 16 unique MCP tools, got {names}")
if any(not name.startswith("kemory_") for name in names):
    raise SystemExit(f"non-canonical MCP tool advertised: {names}")
if not required.issubset(names):
    raise SystemExit(f"session context tools missing: {sorted(required - set(names))}")
PY

echo "Running community API-key probe"
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

    no_creds = client.get("/api/v1/namespaces")
    check("no credentials rejected", no_creds.status_code == 401, str(no_creds.status_code))

    bearer = client.get("/api/v1/namespaces", headers={"Authorization": "Bearer local-jwt-probe"})
    check(
        "Bearer JWT is not accepted",
        bearer.status_code == 401 and "X-API-Key" in bearer.json().get("detail", ""),
        bearer.text[:120],
    )

    namespaces = client.get("/api/v1/namespaces", headers=headers)
    check("local API key authenticates", namespaces.status_code == 200, str(namespaces.status_code))

    for hosted_path in (
        "/api/v1/agents",
        "/api/v1/audit/logs",
        "/api/v1/gatekeeper/evaluate",
        "/api/v1/graph/edges",
        "/api/v1/me",
        "/api/v1/pair/start",
        "/api/v1/permissions",
        "/api/v1/teams",
    ):
        response = client.get(hosted_path, headers=headers)
        check(f"hosted route absent: {hosted_path}", response.status_code == 404, str(response.status_code))

    tool_list = client.post("/mcp/v1/tools/list", headers=headers, json={})
    tool_names = [tool["name"] for tool in tool_list.json().get("tools", [])]
    check(
        "MCP HTTP discovery advertises 16 canonical tools",
        tool_list.status_code == 200
        and len(tool_names) == 16
        and len(tool_names) == len(set(tool_names))
        and all(name.startswith("kemory_") for name in tool_names),
        str(tool_names),
    )

    memory = client.post(
        "/api/v1/memories",
        headers=headers,
        json={
            "namespace": "community:smoke",
            "content": "Community config smoke test memory for pgvector and local identity.",
            "content_type": "text",
            "occurred_at": "2025-02-03T04:05:00Z",
        },
    )
    memory_body = memory.json() if memory.status_code in (200, 201) else {}
    check(
        "memory source date round-trips",
        memory.status_code in (200, 201)
        and memory_body.get("occurred_at") == "2025-02-03T04:05:00+00:00",
        f"status={memory.status_code} occurred_at={memory_body.get('occurred_at')}",
    )

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
        data={
            "namespace": "community:smoke",
            "artifact_type": "text",
            "occurred_at": "2025-02-03T04:05:00Z",
        },
        files={"file": ("community.txt", b"community local_fs artifact\n", "text/plain")},
    )
    body = artifact.json() if artifact.status_code in (200, 201) else {}
    metadata = body.get("artifact_metadata") if isinstance(body.get("artifact_metadata"), dict) else {}
    check(
        "artifact upload succeeds on local_fs",
        artifact.status_code in (200, 201)
        and body.get("namespace") == "community:smoke"
        and body.get("occurred_at") == "2025-02-03T04:05:00+00:00"
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

echo "Community config Docker verification passed"
