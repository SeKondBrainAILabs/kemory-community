"""
Kemory CLI — environments + credential cache.

Built-in environments (``prod`` is the default; ``local`` targets a self-hosted
stack on localhost). ``staging`` is an INTERNAL SeKondBrain environment defined
in ``_envs_internal.py``, which ships in source / ``uv tool install`` builds but
is PHYSICALLY DELETED from the public Homebrew/curl binary by the release
workflow — so the public artifact contains no staging URLs at all and
``--env staging`` is rejected there. (This is hygiene on top of the real
boundary: staging is gated server-side at Keycloak.)

Each env caches its own tokens at ``~/.kemory/credentials-<env>`` so a staging
login never clobbers a prod one — an engineer can be connected to both at once.

File layout:
    ~/.kemory/
        credentials-prod      — JSON: { access_token, refresh_token, expires_at, ... }
        credentials-staging   — (internal builds only)

Why a flat file and not the OS keychain?
- Cross-platform without a heavyweight dep (keyring brings in dbus on Linux).
- Mode 0600 is good enough for a developer laptop. The server-side TTL on the
  refresh token (Keycloak idle timeout) is the ultimate gate.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

CREDENTIALS_VERSION = 2

# The pre-registered public PKCE client is named the same in every realm.
CLIENT_ID = "kemory-cli"

# Public environments — shipped in every build.
ENVIRONMENTS: dict[str, dict[str, str]] = {
    "prod": {
        "issuer": "https://accounts.prod.apps.s9n.ai/realms/s9n",
        "kemory_url": "https://kemory.prod.apps.s9n.ai",
        "server_name": "kemory",
    },
    "local": {
        "issuer": "http://localhost:8888/realms/s9n-mvp",
        "kemory_url": "http://localhost:8100",
        "server_name": "kemory-local",
    },
}

# `staging` is INTERNAL-ONLY. Its config lives in a separate module that ships
# in source / `uv tool install` builds but is deleted from the public binary by
# the release workflow (see release-cli.yml "Strip internal environments").
# config.py imports it inside try/except and falls back to public-only when
# absent. Keep ALL internal-env strings in that file so the public artifact
# stays free of them — the neutral module name discloses nothing.
try:
    from kemory_cli._envs_internal import INTERNAL_ENVIRONMENTS

    ENVIRONMENTS.update(INTERNAL_ENVIRONMENTS)
except ImportError:
    pass

DEFAULT_ENV = "prod"


def resolve_env(env_opt: str | None) -> str:
    """Pick the environment: --env flag > KEMORY_ENV > default (prod)."""
    env = (env_opt or os.environ.get("KEMORY_ENV") or DEFAULT_ENV).lower()
    if env not in ENVIRONMENTS:
        raise ValueError(
            f"unknown env '{env}' (choose: {', '.join(sorted(ENVIRONMENTS))}). "
            "staging is internal-only and absent from public builds."
        )
    return env


def env_profile(env: str) -> dict[str, str]:
    """Env config, with per-key env-var overrides for advanced/self-hosted use."""
    p = dict(ENVIRONMENTS[env])
    p["issuer"] = os.environ.get("KEMORY_OIDC_ISSUER", p["issuer"])
    p["kemory_url"] = os.environ.get("KEMORY_URL", p["kemory_url"])
    p["client_id"] = os.environ.get("KEMORY_CLI_CLIENT_ID", CLIENT_ID)
    return p


def active_env() -> str:
    """The env when no explicit --env was given (KEMORY_ENV or prod)."""
    return resolve_env(None)


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


def credentials_path(env: str | None = None) -> Path:
    """Per-env credentials file. ``env`` defaults to the active env."""
    return kemory_dir() / f"credentials-{resolve_env(env)}"


@dataclass
class Credentials:
    """Cached OAuth tokens for the kemory CLI / MCP bridge, for one env."""

    access_token: str
    refresh_token: str
    expires_at: float  # epoch seconds
    issuer: str  # e.g. https://accounts.prod.apps.s9n.ai/realms/s9n
    client_id: str  # kemory-cli
    kemory_url: str  # e.g. https://kemory.prod.apps.s9n.ai
    env: str = DEFAULT_ENV
    email: str = ""
    org_id: str = ""
    version: int = CREDENTIALS_VERSION

    def expires_within(self, seconds: int) -> bool:
        return time.time() + seconds >= self.expires_at

    @classmethod
    def load(cls, env: str | None = None, path: Path | None = None) -> Credentials | None:
        p = path or credentials_path(env)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text())
            if data.get("version") != CREDENTIALS_VERSION:
                return None
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (json.JSONDecodeError, TypeError):
            return None

    def save(self, path: Path | None = None) -> None:
        p = path or credentials_path(self.env)
        p.parent.mkdir(mode=0o700, exist_ok=True)
        # Write to a temp file then rename — atomic on POSIX.
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))
        os.chmod(tmp, 0o600)
        tmp.replace(p)
