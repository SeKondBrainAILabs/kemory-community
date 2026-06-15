"""
Kemory CLI (WS-10) — `kemory login`, `whoami`, `keys`, `mcp install/serve`.

Designed to make adding kemory to Claude (or any MCP client) feel like:

    $ kemory login         # device-flow OAuth, once per laptop
    $ kemory mcp install   # writes the MCP server entry into ~/.claude.json

No API key in any config file. The MCP bridge reads ~/.kemory/credentials,
refreshes the access token in the background, and forwards it as a Bearer.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    # Single source of truth: pyproject.toml's [project] version. Avoids the
    # cli-v0.3.1 release bug where bumping pyproject.toml didn't bump this
    # constant — every engineer saw `kemory --version` lie about which build
    # they were running.
    __version__ = _pkg_version("kemory")
except PackageNotFoundError:  # pragma: no cover — only when running from a
    # source checkout that wasn't `pip install`-ed (e.g. `python -m kemory_cli`
    # straight from the repo). Fall back to a clearly-marked dev sentinel
    # rather than a stale hardcoded string.
    __version__ = "0.0.0+source"
