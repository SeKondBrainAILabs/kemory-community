"""
Latest-CLI-release lookup against the kemory GitHub repo.

kemory ships CLI wheels as GitHub Release assets (not PyPI), so
`uv tool upgrade kemory` won't discover new versions. This helper finds the
newest tag matching `cli-v*` and returns its parsed version + wheel URL so
the `kemory upgrade` command and `kemory doctor`'s freshness check share
one source of truth.

The kemory repo is **private**, so anonymous `GET /repos/.../releases`
returns 404 and unauthenticated wheel downloads fail. We have two auth
paths: prefer `gh api` (uses the user's local GitHub CLI session — works
out of the box for any s9n engineer), and fall back to httpx + a
GH_TOKEN/GITHUB_TOKEN env var for CI/non-gh environments. All network
failures are swallowed and returned as `None` — neither caller should
hard-fail just because GitHub is unreachable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

import httpx

GITHUB_REPO = "SeKondBrainAILabs/kemory"
RELEASES_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
CLI_TAG_PREFIX = "cli-v"


@dataclass(frozen=True)
class CliRelease:
    """One CLI release on GitHub.

    `version` is the `cli-vX.Y.Z` tag with the `cli-v` prefix stripped — e.g.
    tag `cli-v0.3.2` → version `"0.3.2"`. `wheel_url` is the direct download
    URL for the `.whl` asset (used as the spec for `uv tool install --force`).
    """

    tag: str
    version: str
    wheel_url: str
    html_url: str


def _parse_semver(v: str) -> tuple[int, ...] | None:
    """Best-effort semver tuple. Returns None if `v` isn't `N(.N)*`.

    Done by hand to avoid pulling `packaging` into kemory's runtime deps.
    Tuple-of-ints comparison handles double-digit patches correctly (e.g.
    `(0, 3, 10) > (0, 3, 2)`), which a naïve string compare gets wrong.
    """
    parts = v.split("+", 1)[0].split("-", 1)[0].split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def _pick_release(releases: list[dict]) -> CliRelease | None:
    """Pick the newest `cli-v*` release with a `.whl` asset.

    GitHub returns releases newest-first; we still skip releases without a
    wheel attached (they're not installable). Shared between the gh-CLI
    and httpx auth paths.
    """
    for rel in releases:
        tag = rel.get("tag_name", "")
        if not tag.startswith(CLI_TAG_PREFIX):
            continue
        wheel = next(
            (
                a.get("browser_download_url")
                for a in rel.get("assets", [])
                if isinstance(a, dict) and str(a.get("name", "")).endswith(".whl")
            ),
            None,
        )
        if not wheel:
            continue
        return CliRelease(
            tag=tag,
            version=tag[len(CLI_TAG_PREFIX) :],
            wheel_url=wheel,
            html_url=rel.get("html_url", ""),
        )
    return None


def _releases_via_gh(timeout: float) -> list[dict] | None:
    """Fetch /releases via `gh api` (uses the user's existing GitHub auth).

    This is the preferred path because the kemory repo is private and any
    s9n engineer is already `gh auth login`-ed. Returns None if `gh` is
    missing, unauthenticated, or errors for any reason — callers fall back.
    """
    gh = shutil.which("gh")
    if gh is None:
        return None
    try:
        proc = subprocess.run(
            [gh, "api", f"repos/{GITHUB_REPO}/releases?per_page=30"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, list) else None


def _releases_via_httpx(timeout: float) -> list[dict] | None:
    """Fallback: hit the REST API with an explicit GH_TOKEN/GITHUB_TOKEN.

    Useful in CI or any environment without `gh` installed. Without a token
    this 404s (private repo); we surface that as None so callers SKIP.
    """
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = httpx.get(
            RELEASES_URL,
            params={"per_page": 30},
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    return data if isinstance(data, list) else None


def latest_cli_release(timeout: float = 5.0) -> CliRelease | None:
    """Return the newest `cli-v*` release with a wheel, or None on any failure.

    Tries `gh api` first (works out of the box for s9n engineers with
    `gh auth login`), then httpx + GH_TOKEN (for CI/automation).
    """
    releases = _releases_via_gh(timeout)
    if releases is None:
        releases = _releases_via_httpx(timeout)
    if releases is None:
        return None
    return _pick_release(releases)


def is_newer(latest: str, current: str) -> bool | None:
    """Strict version comparison; returns None when either side won't parse.

    Returning a tristate lets callers distinguish "definitely behind" from
    "couldn't tell" (e.g. when running from a source checkout where the
    installed version reads as `0.0.0+source`).
    """
    a = _parse_semver(latest)
    b = _parse_semver(current)
    if a is None or b is None:
        return None
    return a > b
