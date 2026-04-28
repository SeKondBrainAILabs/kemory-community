"""
Kemory CLI (WS-10) — `kemory login`, `whoami`, `keys`, `mcp install/serve`.

Designed to make adding kemory to Claude (or any MCP client) feel like:

    $ kemory login         # device-flow OAuth, once per laptop
    $ kemory mcp install   # writes the MCP server entry into ~/.claude.json

No API key in any config file. The MCP bridge reads ~/.kemory/credentials,
refreshes the access token in the background, and forwards it as a Bearer.
"""

__version__ = "0.1.0"
