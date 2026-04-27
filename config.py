"""
Kemory CLI — configuration & credential cache.

Stores the OAuth refresh token and a cached access token under
``~/.kemory/credentials`` (mode 0600). The CLI and the MCP bridge both
read from this file; nothing else does.

File layout:
    ~/.kemory/
        config.toml        — host preferences (kemory_url, keycloak_url, ...)
        credentials        — JSON: { access_token, refresh_token, expires_at, issuer, client_id }

Why a flat file and not the OS keychain?
- Cross-platform without a heavyweight dep (keyring brings in dbus on Linux).
- Mode 0600 is good enough for a developer laptop. The server-side TTL
  on the refresh token (Keycloak idle timeout, 7d default) is the
  ultimate gate — a stolen file expires in days.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

CREDENTIALS_VERSION = 1


def kemory_dir() -> Path:
    """Return ~/.kemory, creating it with mode 0700 if missing."""
    d = Path.home() / ".kemory"
    d.mkdir(mode=0o700, exist_ok=True)
    # Tighten permissions if the dir already existed with the wrong mode.
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def credentials_path() -> Path:
    return kemory_dir() / "credentials"


@dataclass
class Credentials:
    """Cached OAuth tokens for the kemory CLI / MCP bridge."""

    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds
    issuer: str        # e.g. https://accounts.prod.apps.s9n.ai/realms/s9n
    client_id: str     # kemory-cli
    kemory_url: str    # e.g. https://kemory.prod.apps.s9n.ai
    email: str = ""
    org_id: str = ""
    version: int = CREDENTIALS_VERSION

    def expires_within(self, seconds: int) -> bool:
        return time.time() + seconds >= self.expires_at

    @classmethod
    def load(cls, path: Optional[Path] = None) -> Optional["Credentials"]:
        p = path or credentials_path()
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            if data.get("version") != CREDENTIALS_VERSION:
                return None
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return None

    def save(self, path: Optional[Path] = None) -> None:
        p = path or credentials_path()
        p.parent.mkdir(mode=0o700, exist_ok=True)
        # Write to a temp file then rename — atomic on POSIX.
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))
        os.chmod(tmp, 0o600)
        tmp.replace(p)
