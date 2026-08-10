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
