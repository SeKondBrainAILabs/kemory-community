"""
Kemory CLI — anonymous, opt-in usage telemetry.

OFF BY DEFAULT. Enabled only when the user explicitly passes
``--telemetry`` to `kemory login` (or sets KEMORY_TELEMETRY=on later).
A persistent install id is generated locally and stored at
``~/.kemory/install_id`` — never tied to email, org_id, or user_id.

What we collect (only when enabled):
  - cli_version
  - command name (e.g. "login", "mcp install", "keys rotate")
  - exit_status (success / failure / abort)
  - install_id (random uuid v4 generated on first opt-in)
  - os_family + cli_python_version

What we never collect:
  - The user's identity, email, org_id, or any user-supplied data.
  - The contents of any memory.
  - File paths, hostnames, or arguments beyond the subcommand name.

Where it goes:
  - The kemory backend's /api/v1/telemetry endpoint, batched on a 5s flush
    or process exit. Failures are silent — telemetry never blocks the CLI.

Disabling
  - `kemory telemetry off`
  - `KEMORY_TELEMETRY=off`
  - delete ~/.kemory/install_id

This file is INTENTIONALLY small. If telemetry expands beyond these
fields, that requires its own ADR and an opt-in screen on first run.
"""

from __future__ import annotations

import os
import platform
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx

from kemory_cli import __version__
from kemory_cli.config import kemory_dir


def _telemetry_path() -> Path:
    return kemory_dir() / "install_id"


def _enabled() -> bool:
    """Telemetry is opt-in. Check env first, then ~/.kemory/install_id existence."""
    flag = os.environ.get("KEMORY_TELEMETRY", "").lower()
    if flag in {"off", "false", "0", "no"}:
        return False
    if flag in {"on", "true", "1", "yes"}:
        return True
    return _telemetry_path().exists()


def enable() -> str:
    """Enable telemetry by generating an install_id. Returns the id."""
    p = _telemetry_path()
    if p.exists():
        return p.read_text().strip()
    install_id = str(uuid.uuid4())
    p.write_text(install_id)
    os.chmod(p, 0o600)
    return install_id


def disable() -> None:
    p = _telemetry_path()
    if p.exists():
        p.unlink()


@dataclass
class Event:
    command: str
    exit_status: str
    duration_ms: int


def report(event: Event, kemory_url: str = "") -> None:
    """Best-effort telemetry emit. Never raises. Never blocks for >2s."""
    if not _enabled():
        return
    payload = {
        "install_id": _telemetry_path().read_text().strip(),
        "cli_version": __version__,
        "os_family": platform.system().lower(),
        "python_version": ".".join(map(str, sys.version_info[:3])),
        "command": event.command,
        "exit_status": event.exit_status,
        "duration_ms": event.duration_ms,
        "ts": int(time.time()),
    }
    url = (kemory_url or os.environ.get("KEMORY_URL", "")).rstrip("/")
    if not url:
        return
    try:
        httpx.post(f"{url}/api/v1/telemetry", json=payload, timeout=2.0)
    except Exception:
        pass  # never block on telemetry — it's never the user's problem
