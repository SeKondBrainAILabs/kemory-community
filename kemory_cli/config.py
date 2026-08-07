"""Local configuration for the community Python CLI and MCP bridge."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_VERSION = 1
DEFAULT_KEMORY_URL = "http://127.0.0.1:8111"


def kemory_dir() -> Path:
    configured = os.environ.get("KEMORY_COMMUNITY_HOME", "").strip()
    directory = Path(configured).expanduser() if configured else Path.home() / ".kemory-community"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    return directory


def credentials_path() -> Path:
    configured = os.environ.get("KEMORY_CREDENTIALS_FILE", "").strip()
    return Path(configured).expanduser() if configured else kemory_dir() / "credentials.json"


@dataclass
class Credentials:
    """Single-user community API endpoint and key."""

    api_key: str
    kemory_url: str = DEFAULT_KEMORY_URL
    version: int = CONFIG_VERSION

    @classmethod
    def load(cls, path: Path | None = None) -> Credentials | None:
        target = path or credentials_path()
        if not target.exists():
            return None
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if data.get("version") != CONFIG_VERSION:
                return None
            return cls(
                api_key=str(data["api_key"]),
                kemory_url=str(data.get("kemory_url") or DEFAULT_KEMORY_URL).rstrip("/"),
            )
        except (KeyError, OSError, TypeError, json.JSONDecodeError):
            return None

    def save(self, path: Path | None = None) -> None:
        target = path or credentials_path()
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(target.parent, 0o700)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(target)
