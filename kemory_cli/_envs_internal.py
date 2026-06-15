"""Internal-only environment definitions (SeKondBrain staging).

Present in source checkouts and `uv tool install` builds, so SeKondBrain
engineers get the internal `staging` environment. The public release workflow
DELETES this file before PyInstaller bundles the public binary, so production
end users get a binary that contains no staging URLs whatsoever — `config.py`
imports this module inside a try/except and falls back to the public envs when
it's absent.

Keep ALL internal-env strings (URLs, realm names, server names, even the word
"staging") in this file only, so the public artifact stays free of them. The
module is named neutrally so its mere reference in `config.py` bytecode
discloses nothing about internal environments.

NOTE: kemory is not yet deployed to staging (pre-revenue trim) — `--env staging`
is wired here but will not connect until a kemory staging Deployment exists.
"""

from __future__ import annotations

INTERNAL_ENVIRONMENTS: dict[str, dict[str, str]] = {
    "staging": {
        "issuer": "https://accounts.staging.apps.s9n.ai/realms/s9n-staging",
        "kemory_url": "https://kemory.staging.apps.s9n.ai",
        "server_name": "kemory-staging",
    },
}
