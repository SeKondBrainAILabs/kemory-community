"""S9N-6773: a genuinely fresh `docker compose -f docker-compose.community.yml up`
must be able to create its own schema, with no manual step.

If `docker-compose.community.yml` sets `KEMORY_RUN_MIGRATIONS: "false"`,
`init_db()` (backend/core/database.py) returns immediately without running its
fresh-database bootstrap (build the schema from the ORM models, stamp
alembic_version at head). A real self-host operator following the README then
gets a container that reports `/health/ready` == healthy against a completely
empty database — every DB-backed route 500s, and a manual `alembic upgrade
head` fails on migration 002 (`InFailedSQLTransactionError`), because migration
002 assumes a pre-Alembic baseline schema that was never created.

This compose file is the one self-host operators actually run, so the guard
that keeps `KEMORY_RUN_MIGRATIONS` from regressing back to "false" lives here,
next to the file it protects. It is a fast, no-Docker check — it cannot
re-verify the runtime behavior (that needs real containers), but it makes the
exact line that caused this un-revertable by accident.

Dependency-free on purpose: it scans the compose text directly rather than
importing a YAML parser, so it can never take down the unit job over a missing
optional dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = REPO_ROOT / "docker-compose.community.yml"
SHARED_COMPOSE_PATH = REPO_ROOT / "docker-compose.shared.yml"
SHARED_MIGRATION_PATH = REPO_ROOT / "infrastructure" / "migrate-standalone-data.sh"

_MIGRATIONS_LINE = re.compile(
    r"""^\s*KEMORY_RUN_MIGRATIONS\s*:\s*["']?([^"'\s#]+)""",
    re.MULTILINE,
)


def test_migrations_are_not_disabled_for_community():
    text = COMPOSE_PATH.read_text()
    matches = _MIGRATIONS_LINE.findall(text)

    # Absence is fine — init_db()'s own default is "true". An explicit "false"
    # (in any casing alembic's boolean parser would accept) is the one value
    # that leaves a fresh install with zero schema.
    value = matches[0].strip().lower() if matches else "true"
    assert value not in {"false", "0", "no"}, (
        "KEMORY_RUN_MIGRATIONS is disabled in docker-compose.community.yml — "
        "this leaves a fresh self-host install with zero database tables while "
        "/health/ready still reports healthy (S9N-6773). See "
        "backend/core/database.py::init_db for the fresh-DB bootstrap it gates."
    )


def test_api_image_is_multi_stage_and_non_root():
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()

    assert "FROM python:3.11-slim AS builder" in dockerfile
    assert "FROM python:3.11-slim AS runtime" in dockerfile
    assert "USER kemory" in dockerfile


def test_shared_compose_reuses_infra_without_duplicate_backing_services():
    text = SHARED_COMPOSE_PATH.read_text()

    assert "external: true" in text
    assert "shared-infra:" in text
    assert not re.search(r"^  (postgres|redis):\s*$", text, re.MULTILINE)
    assert "@postgres:5432/" in text
    assert "redis://redis:6379/${KEMORY_COMMUNITY_REDIS_DB:-14}" in text
    assert '"127.0.0.1:${KEMORY_COMMUNITY_API_PORT:-8111}:8000"' in text
    assert '"127.0.0.1:${KEMORY_COMMUNITY_DASHBOARD_PORT:-5175}:5173"' in text


def test_shared_compose_keeps_migrations_enabled():
    matches = _MIGRATIONS_LINE.findall(SHARED_COMPOSE_PATH.read_text())
    value = matches[0].strip().lower() if matches else "true"
    assert value not in {"false", "0", "no"}


def test_shared_port_registry_matches_compose():
    registry = (REPO_ROOT / "infrastructure" / "PORT_REGISTRY.md").read_text()

    for allocation in ("`8111`", "`5175`", "`5432`", "`6379`", "`14`"):
        assert allocation in registry


def test_shared_migration_is_cross_version_and_checks_every_table():
    script = SHARED_MIGRATION_PATH.read_text()

    assert "--format=plain" in script
    assert "--exclude-extension=vector" in script
    assert "--exclude-extension=pg_trgm" in script
    assert "pg_restore" not in script
    assert 'psql \\\n  -U "$TARGET_USER"' in script
    assert "REASSIGN OWNED" not in script
    assert "SELECT tablename FROM pg_tables" in script
    assert 'cmp -s "$SOURCE_MANIFEST" "$TARGET_MANIFEST"' in script
