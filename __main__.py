"""
Kemory CLI entry point — `kemory <command>`.

Subcommands:
  login         OAuth 2.0 device flow, caches tokens at ~/.kemory/credentials
  login --local Skip OAuth, generate a machine-local API key (dev mode)
  logout        Delete the cached credentials
  whoami        Hit /v1/me and print user/org/teams
  doctor        Run end-to-end health checks (network, auth, MCP host config)
  keys          Manage API keys (list, create, rotate, revoke)
  mcp install   Write an MCP server entry into supported MCP hosts
                (Claude Code, Claude Desktop, Cursor, Continue.dev)
  mcp serve     Run the stdio MCP bridge (called by the MCP host, not humans)
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path

import click
import httpx

from kemory_cli import __version__
from kemory_cli.auth import (
    DeviceFlowError,
    get_valid_credentials,
)
from kemory_cli.auth import (
    login as run_login,
)
from kemory_cli.config import Credentials, credentials_path

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


def _api_post(creds: Credentials, path: str, json_body: dict | None = None) -> httpx.Response:
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
@click.option(
    "--kemory-url", default=DEFAULT_KEMORY_URL, show_default=True, help="Base URL of the kemory API."
)
@click.option(
    "--issuer", default=DEFAULT_KEYCLOAK_ISSUER, show_default=True, help="Keycloak realm issuer URL."
)
@click.option("--client-id", default=DEFAULT_CLIENT_ID, show_default=True)
@click.option("--no-browser", is_flag=True, help="Print the URL but don't open it.")
@click.option(
    "--local",
    "local_mode",
    is_flag=True,
    help="Skip OAuth and use a machine-local API key (dev mode). "
    "Reads KEMORY_API_KEY (or legacy S9NMV_API_KEY / "
    "KORA_API_KEY) from the env, or registers a new agent "
    "against KEMORY_URL with a generated key.",
)
def login_cmd(kemory_url: str, issuer: str, client_id: str, no_browser: bool, local_mode: bool) -> None:
    """Log in. Default is OAuth 2.0 device flow against Keycloak; --local
    skips OAuth and stores a kemory API key at ~/.kemory/credentials so
    self-hosted / dev-mode users can onboard without a Keycloak install.
    """
    if local_mode:
        # P1 #9: KEMORY_API_KEY is canonical; the older names still work
        # for one minor version while existing integrations migrate.
        api_key = (
            os.environ.get("KEMORY_API_KEY")
            or os.environ.get("S9NMV_API_KEY")
            or os.environ.get("KORA_API_KEY")
        )
        if not api_key:
            raise click.ClickException(
                "--local mode needs an API key. Set KEMORY_API_KEY=<key> in "
                "the environment, then re-run `kemory login --local`. "
                "Generate a key by registering an agent against your local "
                "kemory: see docs/getting-started.md."
            )
        # Store the key as a pseudo-credential so the bridge can pick it up.
        # We use a far-future expiry and a placeholder issuer so refresh()
        # is never attempted on this credential.
        creds = Credentials(
            access_token=api_key,
            refresh_token="",
            expires_at=time.time() + 365 * 24 * 3600,
            issuer="local",
            client_id="local",
            kemory_url=kemory_url,
        )
        creds.save()
        click.echo(
            click.style(
                f"✓ Local credential stored. The MCP bridge will forward X-API-Key to {kemory_url}.",
                fg="green",
            )
        )
        return

    try:
        creds = run_login(
            issuer=issuer,
            client_id=client_id,
            kemory_url=kemory_url,
            open_browser=not no_browser,
        )
    except DeviceFlowError as exc:
        raise click.ClickException(
            f"{exc}\n\nThings to check:\n"
            f"  • is {issuer} reachable from this network?\n"
            f"  • is the kemory-cli client enabled in your Keycloak realm?\n"
            f"    (see keycloak/kemory-multi-tenant-mappers.md §3)\n"
            f"  • for self-hosted setups without Keycloak, try `kemory login --local`."
        )

    # Optimistically populate email + org_id from /v1/me.
    try:
        resp = _api_get(creds, "/api/v1/me")
        if resp.status_code == 200:
            data = resp.json()
            creds.email = data.get("email", "")
            creds.org_id = data.get("org_id", "")
            creds.save()
            click.echo(
                click.style(
                    f"✓ Logged in as {creds.email or 'unknown'} · "
                    f"org={creds.org_id or '?'} · "
                    f"teams={[t['name'] for t in data.get('teams', [])]}",
                    fg="green",
                )
            )
            return
    except httpx.HTTPError:
        pass
    click.echo(click.style("✓ Logged in. Cached tokens at ~/.kemory/credentials", fg="green"))


@cli.command("telemetry")
@click.argument("state", type=click.Choice(["on", "off", "status"]))
def telemetry_cmd(state: str) -> None:
    """Manage anonymous, opt-in usage telemetry.

    OFF BY DEFAULT. See kemory_cli/telemetry.py for the full list of
    fields collected and a guarantee on what is NOT collected (no user
    identity, no memory contents, no file paths).
    """
    from kemory_cli.telemetry import _enabled, _telemetry_path, disable, enable

    if state == "on":
        install_id = enable()
        click.echo(click.style(f"✓ Telemetry enabled. install_id={install_id[:8]}…", fg="green"))
        click.echo("  Disable any time with `kemory telemetry off`.")
    elif state == "off":
        disable()
        click.echo("✓ Telemetry disabled. install_id removed.")
    else:
        on = _enabled()
        click.echo(f"telemetry: {'on' if on else 'off'}")
        if on:
            click.echo(f"install_id file: {_telemetry_path()}")


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
@click.option(
    "--for",
    "agent_label",
    default=None,
    help="Target agent platform (e.g. manus, cursor-cloud, chatgpt). "
    "Tags the key in audit logs and `keys list` so credentials are "
    "attributable per-agent. Recommended for any cloud-hosted agent. "
    "See ADR-005.",
)
@click.option("--description", default=None)
@click.option(
    "--write",
    "allow_write",
    is_flag=True,
    default=False,
    help="Grant write access. Default is read-only (least privilege).",
)
@click.option(
    "--reason",
    default="agent-default",
    help="Reason attached to each declared scope (audit trail).",
)
@click.pass_context
def keys_create(
    ctx: click.Context,
    name: str,
    agent_label: str | None,
    description: str | None,
    allow_write: bool,
    reason: str,
) -> None:
    """Create an org-scoped API key. Read-only by default — pass --write to allow mutations.

    --for tags the key with a target-agent label for audit attribution
    (ADR-005 Phase A). When the long-term `kemory connect <agent>` flow ships
    in Phase B, this label is what `connect list` keys off.
    """
    creds = _require_creds(ctx)
    # Compose the description: prepend [agent=<label>] if --for was passed,
    # so `keys list` can extract the label without a schema migration. v2 of
    # this lifecycle (Phase B) gives the label its own column.
    if description is None:
        description = "Issued via `kemory keys create`"
    if agent_label:
        description = f"[agent={agent_label}] {description}"
    # Backend requires `reason` on each declared scope (audit field). Without
    # it the API rejects the body with 422 (P0 fix in cli-v0.2.1).
    declared_scopes: list[dict[str, str]] = [{"scope": "memory:read", "reason": reason}]
    if allow_write:
        declared_scopes.append({"scope": "memory:write", "reason": reason})
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
    click.echo(f"  agent_id    : {out['agent_id']}")
    click.echo(f"  api_key     : {out['api_key']}")
    if agent_label:
        click.echo(f"  agent_label : {agent_label}")


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


_AGENT_LABEL_RE = __import__("re").compile(r"\[agent=([a-z0-9-]+)\]")


def _extract_agent_label(description: str | None) -> str:
    """Pull the agent_label out of a description tagged by `kemory keys create --for`.

    v1 of ADR-005 Phase A stores the label as a `[agent=<label>]` prefix in
    the description (no DB migration needed). Phase B replaces this with a
    dedicated column.
    """
    if not description:
        return "-"
    match = _AGENT_LABEL_RE.search(description)
    return match.group(1) if match else "-"


@keys_grp.command("list")
@click.pass_context
def keys_list(ctx: click.Context) -> None:
    """List all API keys for this user, with their target-agent label.

    The `for` column shows what agent each key was minted for (set via
    `kemory keys create --for <agent>`). Helpful for auditing which key
    belongs to which integration. ADR-005 Phase A.
    """
    creds = _require_creds(ctx)
    resp = _api_get(creds, "/api/v1/agents")
    if resp.status_code != 200:
        raise click.ClickException(f"list failed: {resp.status_code} {resp.text}")
    rows = resp.json()
    if not rows:
        click.echo("(no agents)")
        return
    click.echo(f"{'agent_id':<38}  {'name':<30}  {'for':<14}  status")
    click.echo(f"{'-' * 38}  {'-' * 30}  {'-' * 14}  ------")
    for r in rows:
        label = _extract_agent_label(r.get("agent_description"))
        click.echo(
            f"{r.get('agent_id')}  {(r.get('agent_name') or '-'):<30}  {label:<14}  {r.get('status', '-')}"
        )


# ─── mcp ──────────────────────────────────────────────────────────────────


@cli.group("mcp")
def mcp_grp() -> None:
    """MCP (Model Context Protocol) integration commands."""


# Map host name → list of candidate config paths (first existing wins,
# else first in list is created). Cross-platform; tested by the doctor
# command below before writing.
def _host_config_paths() -> dict[str, list[Path]]:
    home = Path.home()
    macos_app_support = home / "Library" / "Application Support"
    win_appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    return {
        "claude-code": [home / ".claude.json"],
        "claude-desktop": [
            macos_app_support / "Claude" / "claude_desktop_config.json",
            win_appdata / "Claude" / "claude_desktop_config.json",
            home / ".config" / "Claude" / "claude_desktop_config.json",
        ],
        "cursor": [home / ".cursor" / "mcp.json"],
        "continue": [home / ".continue" / "config.json"],
    }


def _resolve_host_config(host: str) -> Path | None:
    """Pick the first candidate path that exists, or fall back to the
    first candidate (which we'll create). Returns None for unknown hosts."""
    candidates = _host_config_paths().get(host)
    if not candidates:
        return None
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def _write_mcp_entry(config_path: Path, name: str) -> None:
    """Idempotently merge a kemory MCP server entry into config_path."""
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text() or "{}")
        except json.JSONDecodeError:
            raise click.ClickException(
                f"{config_path} is not valid JSON. Refusing to overwrite — fix it first."
            )
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config = {}
    servers = config.setdefault("mcpServers", {})
    servers[name] = {"command": "kemory", "args": ["mcp", "serve"], "env": {}}
    config_path.write_text(json.dumps(config, indent=2))


@mcp_grp.command("install")
@click.option(
    "--host",
    "hosts",
    multiple=True,
    type=click.Choice(["claude-code", "claude-desktop", "cursor", "continue", "all"]),
    default=("claude-code",),
    help="MCP host(s) to configure. Pass --host all to wire every supported host on this machine.",
)
@click.option(
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Override host detection — write directly to this path.",
)
@click.option("--name", default="kemory", show_default=True, help="Server name to register under mcpServers.")
def mcp_install(hosts: tuple[str, ...], config_path: Path | None, name: str) -> None:
    """Write an MCP server entry into one or more MCP hosts. No API key
    is stored in the config — the bridge reads ~/.kemory/credentials at
    runtime, so config files stay safe to commit / sync.
    """
    if config_path is not None:
        _write_mcp_entry(config_path, name)
        click.echo(click.style(f"✓ Wrote MCP server entry '{name}' into {config_path}", fg="green"))
        return

    targets = list(hosts)
    if "all" in targets:
        targets = ["claude-code", "claude-desktop", "cursor", "continue"]

    written: list[tuple[str, Path]] = []
    skipped: list[tuple[str, str]] = []
    for host in targets:
        path = _resolve_host_config(host)
        if path is None:
            skipped.append((host, "unknown host"))
            continue
        try:
            _write_mcp_entry(path, name)
            written.append((host, path))
        except click.ClickException as exc:
            skipped.append((host, str(exc)))

    for host, path in written:
        click.echo(click.style(f"✓ {host:<15} {path}", fg="green"))
    for host, reason in skipped:
        click.echo(click.style(f"✗ {host:<15} {reason}", fg="yellow"))
    if written:
        click.echo("\nRestart the affected MCP host(s) to pick up the change.")


@mcp_grp.command("serve")
def mcp_serve() -> None:
    """Run the kemory stdio MCP bridge. Invoked by the MCP host, not humans."""
    from kemory_cli.mcp_bridge import serve as run_bridge

    run_bridge()


# ─── doctor ───────────────────────────────────────────────────────────────


@cli.command("doctor")
@click.pass_context
def doctor_cmd(ctx: click.Context) -> None:
    """End-to-end health check: network → auth → API → MCP host config.

    Run this first when something feels wrong. Each line ends in PASS / FAIL
    / SKIP with a hint on what to do next. No personal data is printed.
    """
    creds = Credentials.load()
    kemory_url = (creds.kemory_url if creds else None) or DEFAULT_KEMORY_URL

    def emit(label: str, ok: bool | None, detail: str = "") -> None:
        if ok is True:
            tag = click.style("  PASS", fg="green")
        elif ok is False:
            tag = click.style("  FAIL", fg="red")
        else:
            tag = click.style("  SKIP", fg="yellow")
        click.echo(f"{tag}  {label}{('  ' + detail) if detail else ''}")

    click.echo(click.style("kemory doctor", bold=True))
    click.echo(f"  python  : {sys.version.split()[0]} on {platform.system()} {platform.release()}")
    click.echo(f"  cli     : {__version__}")
    click.echo(f"  kemory  : {kemory_url}")
    click.echo("")

    # 1. Credentials present?
    if creds is None:
        emit("credentials cached", False, "run `kemory login` (or `kemory login --local`)")
    else:
        ok = creds.access_token != ""
        emit("credentials cached", ok, f"~/.kemory/credentials, expires_at={int(creds.expires_at)}")

    # 2. Network reachability of kemory.
    try:
        resp = httpx.get(f"{kemory_url.rstrip('/')}/health/live", timeout=5.0)
        emit("kemory reachable", resp.status_code == 200, f"GET /health/live → {resp.status_code}")
    except httpx.HTTPError as exc:
        emit("kemory reachable", False, f"{type(exc).__name__}: {exc}")

    # 3. Token refresh — exercise the same code path operational commands use.
    # Without this, an expired access_token (normal — they live ~15 min) made
    # `doctor` look broken even though `whoami`/`memorize`/etc. would refresh
    # transparently. force=True exercises the refresh path regardless of the
    # current expiry window.
    if creds is None:
        emit("token refresh", None, "no credentials")
        fresh_creds = None
    elif creds.issuer == "local" or creds.client_id == "local":
        emit("token refresh", None, "local-mode credential — refresh not applicable")
        fresh_creds = creds
    else:
        try:
            refreshed = get_valid_credentials(force=True)
            if refreshed is None:
                emit(
                    "token refresh",
                    False,
                    "refresh failed — offline session expired or revoked. Run `kemory login`.",
                )
                fresh_creds = None
            else:
                fresh_creds = refreshed
                emit(
                    "token refresh",
                    True,
                    f"new access_token expires_at={int(refreshed.expires_at)}",
                )
        except (DeviceFlowError, httpx.HTTPError) as exc:
            emit("token refresh", False, f"{type(exc).__name__}: {exc}")
            fresh_creds = None

    # 4. Auth round-trip (use the refreshed token so we don't false-fail
    # on a stale local access_token).
    if fresh_creds and fresh_creds.access_token:
        try:
            resp = httpx.get(
                f"{kemory_url.rstrip('/')}/api/v1/me",
                headers={"Authorization": f"Bearer {fresh_creds.access_token}"},
                timeout=5.0,
            )
            if resp.status_code == 200:
                me = resp.json()
                emit(
                    "auth round-trip", True, f"org={me.get('org_id', '?')}, teams={len(me.get('teams', []))}"
                )
            elif resp.status_code == 401:
                emit(
                    "auth round-trip",
                    False,
                    "401 — backend rejected a fresh token. Confirm kemory has the correct "
                    "KEYCLOAK_PUBLIC_URL and that your token's `aud` includes `kemory-api`.",
                )
            else:
                emit("auth round-trip", False, f"GET /api/v1/me → {resp.status_code}")
        except httpx.HTTPError as exc:
            emit("auth round-trip", False, str(exc))
    else:
        emit("auth round-trip", None, "no usable credentials")

    # 4. MCP host config consistency — does any known host have a kemory entry?
    found = []
    for host, paths in _host_config_paths().items():
        for p in paths:
            if not p.exists():
                continue
            try:
                cfg = json.loads(p.read_text() or "{}")
                names = list((cfg.get("mcpServers") or {}).keys())
                if any("kemory" in n for n in names):
                    found.append((host, p))
            except json.JSONDecodeError:
                pass
    if found:
        for host, p in found:
            emit(f"mcp host: {host}", True, str(p))
    else:
        emit("mcp host config", False, "no kemory entry found — run `kemory mcp install --host all`")

    # 5. CLI freshness — kemory wheels are GitHub Release assets, not PyPI, so
    # nothing else will tell the user they're running a stale CLI (and the MCP
    # bridge ships inside the CLI, so a stale CLI = a stale bridge with the old
    # 30s read timeout). Soft-fail on network errors; a doctor run should not
    # require GitHub to be up.
    from kemory_cli.releases import is_newer, latest_cli_release

    info = latest_cli_release(timeout=3.0)
    if info is None:
        emit("cli up-to-date", None, "github.com unreachable")
    else:
        verdict = is_newer(info.version, __version__)
        if verdict is True:
            emit(
                "cli up-to-date",
                False,
                f"new version {info.version} available — run `kemory upgrade`",
            )
        elif verdict is False:
            emit("cli up-to-date", True, f"latest is {info.version}")
        else:
            emit("cli up-to-date", None, f"could not compare {__version__!r} vs {info.version!r}")

    click.echo("")
    click.echo("Done. If a check failed, the hint after FAIL tells you what to do.")


# ─── upgrade ──────────────────────────────────────────────────────────────


@cli.command("upgrade")
@click.option("--yes", "-y", is_flag=True, help="Skip the confirmation prompt.")
@click.option(
    "--check",
    is_flag=True,
    help="Print whether a newer version is available; don't install.",
)
def upgrade_cmd(yes: bool, check: bool) -> None:
    """Upgrade the kemory CLI to the latest GitHub Release.

    kemory wheels are published as GitHub Release assets (the project isn't on
    PyPI), so a plain `uv tool upgrade kemory` doesn't see new versions. This
    command queries the kemory repo's releases, finds the newest `cli-v*` tag,
    and reinstalls via `uv tool install --force <wheel-url>`.
    """
    import shutil
    import subprocess

    from kemory_cli.releases import is_newer, latest_cli_release

    info = latest_cli_release()
    if info is None:
        click.echo(
            click.style("error", fg="red")
            + ": could not fetch the latest release from GitHub. Check your network."
        )
        sys.exit(1)

    click.echo(f"Current : {__version__}")
    click.echo(f"Latest  : {info.version}  ({info.html_url})")

    verdict = is_newer(info.version, __version__)
    if verdict is False:
        click.echo("")
        click.echo(click.style(f"Already on the latest CLI version ({__version__}).", fg="green"))
        return
    if verdict is None:
        click.echo("")
        click.echo(
            click.style("note", fg="yellow")
            + f": couldn't compare versions ({__version__!r} vs {info.version!r}); proceeding."
        )

    if check:
        click.echo("")
        click.echo("A newer version is available. Run `kemory upgrade` to install it.")
        return

    click.echo("")
    if not yes and not click.confirm(f"Upgrade kemory to {info.version}?", default=True):
        click.echo("Aborted.")
        return

    spec = f"kemory @ {info.wheel_url}"
    uv = shutil.which("uv")
    if uv is None:
        # We don't fall back silently to pipx — the install location would
        # differ from the user's existing install, leaving two `kemory`
        # binaries on PATH. Print the exact command and exit.
        click.echo(
            click.style("error", fg="red") + ": `uv` not found on PATH. Either install uv "
            "(https://docs.astral.sh/uv/) or run manually with your package manager, e.g.:"
        )
        click.echo(f"  pipx install --force '{spec}'")
        sys.exit(1)

    click.echo(f"Running: uv tool install --force '{spec}'")
    rc = subprocess.run([uv, "tool", "install", "--force", spec], check=False).returncode
    if rc != 0:
        click.echo(click.style("error", fg="red") + f": uv exited with status {rc}")
        sys.exit(rc)

    click.echo("")
    click.echo(click.style(f"Upgraded to {info.version}.", fg="green"))
    click.echo(
        "Restart your MCP host (Claude Code / Claude Desktop / Cursor) so the new bridge "
        "is loaded — the running `kemory mcp serve` process is the OLD code until then."
    )


# ─── Entry point ──────────────────────────────────────────────────────────


def main() -> None:
    cli(prog_name="kemory")


if __name__ == "__main__":  # pragma: no cover
    main()
