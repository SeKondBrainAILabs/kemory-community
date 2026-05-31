"""
Latest-CLI-release lookup against the kemory GitHub repo.

kemory ships CLI wheels as GitHub Release assets (not PyPI), so
`uv tool upgrade kemory` won't discover new versions. This helper hits
`https://api.github.com/repos/.../releases`, finds the newest tag matching
`cli-v*`, and returns its parsed version + wheel URL so the `kemory upgrade`
command and `kemory doctor`'s freshness check can use the same result.

Network failures are intentionally swallowed and returned as `None` —
neither caller should hard-fail just because GitHub is unreachable.
"""

from __future__ import annotations

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


def latest_cli_release(timeout: float = 5.0) -> CliRelease | None:
    """Return the newest `cli-v*` release on GitHub, or None on any failure.

    Iterates the releases list (GitHub returns them newest-first) and returns
    the first one with a `cli-v*` tag AND a `.whl` asset. Releases without a
    wheel attached are skipped — they're not installable.
    """
    try:
        resp = httpx.get(RELEASES_URL, params={"per_page": 30}, timeout=timeout)
        resp.raise_for_status()
        releases = resp.json()
    except (httpx.HTTPError, ValueError):
        return None

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
