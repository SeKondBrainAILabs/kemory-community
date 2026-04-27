"""
Kemory CLI entry point — `kemory <command>`.

Subcommands:
  login         OAuth 2.0 device flow, caches tokens at ~/.kemory/credentials
  logout        Delete the cached credentials
  whoami        Hit /v1/me and print user/org/teams
  keys          Manage API keys (list, create, rotate, revoke)
  mcp install   Write an MCP server entry into ~/.claude.json
  mcp serve     Run the stdio MCP bridge (called by the MCP host)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
import httpx

from kemory_cli import __version__
from kemory_cli.auth import (
    DeviceFlowError,
    get_valid_credentials,
    login as run_login,
)
from kemory_cli.config import Credentials, credentials_path, kemory_dir


# ─── Defaults ──────────────────────────────────────────────────────────────

DEFAULT_KEMORY_URL = os.environ.get("KEMORY_URL", "http://localhost:8100")
DEFAULT_KEYCLOAK_ISSUER = os.environ.get(
    "KEMORY_OIDC_ISSUER",
    "http://localhost:8888/realms/s9n-mvp",
)
DEFAULT_CLIENT_ID = os.environ.get("KEMORY_CLI_CLIENT_ID", "kemory-cli")


# ─── Helpers ──────────────────────────────────────────────────────────────


def _require_creds(ctx: click.Context) -> Credentials:
    creds = get_valid_credentials()
    if creds is None:
        click.echo(click.style("✗ No valid credentials. Run `kemory login` first.", fg="red"), err=True)
        ctx.exit(1)
    return creds


def _api_get(creds: Credentials, path: str) -> httpx.Response:
    return httpx.get(
        f"{creds.kemory_url.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {creds.access_token}"},
        timeout=10.0,
    )


def _api_post(creds: Credentials, path: str, json_body: Optional[dict] = None) -> httpx.Response:
    return httpx.post(
        f"{creds.kemory_url.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {creds.access_token}"},
        json=json_body or {},
        timeout=10.0,
    )


# ─── Root command group ───────────────────────────────────────────────────


@click.group(invoke_without_command=False)
@click.version_option(__version__, prog_name="kemory")
def cli() -> None:
    """Kemory — multi-tenant memory for AI agents."""


# ─── login / logout / whoami ──────────────────────────────────────────────


@cli.command("login")
@click.option("--kemory-url", default=DEFAULT_KEMORY_URL, show_default=True,
              help="Base URL of the kemory API.")
@click.option("--issuer", default=DEFAULT_KEYCLOAK_ISSUER, show_default=True,
              help="Keycloak realm issuer URL.")
@click.option("--client-id", default=DEFAULT_CLIENT_ID, show_default=True)
@click.option("--no-browser", is_flag=True, help="Print the URL but don't open it.")
def login_cmd(kemory_url: str, issuer: str, client_id: str, no_browser: bool) -> None:
    """Log in via OAuth 2.0 device flow. Caches tokens at ~/.kemory/credentials."""
    try:
        creds = run_login(
            issuer=issuer,
            client_id=client_id,
            kemory_url=kemory_url,
            open_browser=not no_browser,
        )
    except DeviceFlowError as exc:
        raise click.ClickException(str(exc))

    # Optimistically populate email + org_id from /v1/me.
    try:
        resp = _api_get(creds, "/api/v1/me")
        if resp.status_code == 200:
            data = resp.json()
            creds.email = data.get("email", "")
            creds.org_id = data.get("org_id", "")
            creds.save()
            click.echo(click.style(
                f"✓ Logged in as {creds.email or 'unknown'} · "
                f"org={creds.org_id or '?'} · "
                f"teams={[t['name'] for t in data.get('teams', [])]}",
                fg="green",
            ))
            return
    except httpx.HTTPError:
        pass
    click.echo(click.style("✓ Logged in. Cached tokens at ~/.kemory/credentials", fg="green"))


@cli.command("logout")
def logout_cmd() -> None:
    """Delete the cached credentials."""
    p = credentials_path()
    if p.exists():
        p.unlink()
        click.echo("✓ Removed ~/.kemory/credentials")
    else:
        click.echo("(no credentials file present)")


@cli.command("whoami")
@click.pass_context
def whoami_cmd(ctx: click.Context) -> None:
    """Print identity, org, and team membership."""
    creds = _require_creds(ctx)
    resp = _api_get(creds, "/api/v1/me")
    if resp.status_code != 200:
        raise click.ClickException(f"GET /api/v1/me failed: {resp.status_code} {resp.text}")
    me = resp.json()
    click.echo(f"Email:   {me.get('email')}")
    click.echo(f"User ID: {me.get('user_id')}")
    click.echo(f"Org:     {me.get('org_name')} ({me.get('org_id')})")
    click.echo(f"Roles:   {', '.join(me.get('roles') or []) or '-'}")
    teams = me.get("teams") or []
    if teams:
        click.echo("Teams:")
        for t in teams:
            click.echo(f"  • {t['name']:<30}  role={t['role']:<8}  can_write={t['can_write']}")
    else:
        click.echo("Teams:   (none)")


# ─── keys ─────────────────────────────────────────────────────────────────


@cli.group("keys")
def keys_grp() -> None:
    """Manage org-scoped API keys (WS-5)."""


@keys_grp.command("create")
@click.option("--name", required=True, help="Agent name (unique per user).")
@click.option("--description", default="Issued via `kemory keys create`")
@click.option("--write", "allow_write", is_flag=True, default=False,
              help="Grant write access. Default is read-only (least privilege).")
@click.pass_context
def keys_create(ctx: click.Context, name: str, description: str, allow_write: bool) -> None:
    """Create an org-scoped API key. Read-only by default — pass --write to allow mutations."""
    creds = _require_creds(ctx)
    declared_scopes: list[dict[str, str]] = [{"scope": "memory:read"}]
    if allow_write:
        declared_scopes.append({"scope": "memory:write"})
    body = {
        "agent_name": name,
        "agent_description": description,
        "declared_scopes": declared_scopes,
    }
    resp = _api_post(creds, "/api/v1/agents", body)
    if resp.status_code not in (200, 201):
        raise click.ClickException(f"create failed: {resp.status_code} {resp.text}")
    out = resp.json()
    click.echo(click.style("✓ Key created. Store it now — it is not shown again.", fg="green"))
    click.echo(f"  agent_id : {out['agent_id']}")
    click.echo(f"  api_key  : {out['api_key']}")


@keys_grp.command("rotate")
@click.argument("agent_id")
@click.pass_context
def keys_rotate(ctx: click.Context, agent_id: str) -> None:
    creds = _require_creds(ctx)
    resp = _api_post(creds, f"/api/v1/agents/{agent_id}/rotate-key")
    if resp.status_code not in (200, 201):
        raise click.ClickException(f"rotate failed: {resp.status_code} {resp.text}")
    out = resp.json()
    click.echo(click.style("✓ Key rotated. Old key is now invalid.", fg="green"))
    click.echo(f"  agent_id : {out['agent_id']}")
    click.echo(f"  api_key  : {out['api_key']}")


@keys_grp.command("list")
@click.pass_context
def keys_list(ctx: click.Context) -> None:
    creds = _require_creds(ctx)
    resp = _api_get(creds, "/api/v1/agents")
    if resp.status_code != 200:
        raise click.ClickException(f"list failed: {resp.status_code} {resp.text}")
    rows = resp.json()
    if not rows:
        click.echo("(no agents)")
        return
    for r in rows:
        click.echo(f"{r.get('agent_id')}  {r.get('agent_name'):<30}  status={r.get('status')}")


# ─── mcp ──────────────────────────────────────────────────────────────────


@cli.group("mcp")
def mcp_grp() -> None:
    """MCP (Model Context Protocol) integration commands."""


@mcp_grp.command("install")
@click.option("--config", "config_path",
              type=click.Path(dir_okay=False, path_type=Path),
              default=Path.home() / ".claude.json",
              show_default=True,
              help="Path to the MCP host config (Claude Code default).")
@click.option("--name", default="kemory", show_default=True,
              help="Server name to register under mcpServers.")
def mcp_install(config_path: Path, name: str) -> None:
    """Write an MCP server entry into ~/.claude.json so Claude Code calls
    `kemory mcp serve` whenever it needs the tools. No API key is stored
    in the config — the bridge reads ~/.kemory/credentials at runtime.
    """
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text() or "{}")
        except json.JSONDecodeError:
            raise click.ClickException(
                f"{config_path} is not valid JSON. Refusing to overwrite — fix it first."
            )
    else:
        config = {}

    servers = config.setdefault("mcpServers", {})
    servers[name] = {
        "command": "kemory",
        "args": ["mcp", "serve"],
        "env": {},
    }
    config_path.write_text(json.dumps(config, indent=2))
    click.echo(click.style(f"✓ Wrote MCP server entry '{name}' into {config_path}", fg="green"))
    click.echo("Restart Claude Code (or your MCP host) to pick it up.")


@mcp_grp.command("serve")
def mcp_serve() -> None:
    """Run the kemory stdio MCP bridge. Invoked by the MCP host, not humans."""
    from kemory_cli.mcp_bridge import serve as run_bridge
    run_bridge()


# ─── Entry point ──────────────────────────────────────────────────────────


def main() -> None:
    cli(prog_name="kemory")


if __name__ == "__main__":  # pragma: no cover
    main()
