"""Community Python CLI: local API-key setup, doctor, and MCP bridge."""

from __future__ import annotations

import json
import os
import platform
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path

import click
import httpx

from kemory_cli.config import DEFAULT_KEMORY_URL, Credentials, credentials_path

try:
    __version__ = package_version("kemory-community")
except PackageNotFoundError:  # pragma: no cover - source checkout
    __version__ = "0.0.0+source"


def _configured() -> Credentials:
    credentials = Credentials.load()
    if credentials is None or not credentials.api_key:
        raise click.ClickException("Not configured. Run `kemory configure` first.")
    return credentials


@click.group()
@click.version_option(__version__, prog_name="kemory")
def cli() -> None:
    """Operate a local Kemory Community instance."""


@cli.command("configure")
@click.option("--url", default=DEFAULT_KEMORY_URL, show_default=True, help="Community API URL.")
@click.option("--api-key", default=None, help="Local API key; prompts securely when omitted.")
def configure_cmd(url: str, api_key: str | None) -> None:
    """Store the local endpoint and API key for CLI and MCP use."""
    api_key = api_key or os.environ.get("KEMORY_LOCAL_API_KEY") or os.environ.get("KEMORY_API_KEY")
    if not api_key:
        api_key = click.prompt("Community API key", hide_input=True)
    api_key = api_key.strip()
    if not api_key:
        raise click.ClickException("API key cannot be empty.")
    credentials = Credentials(api_key=api_key, kemory_url=url.rstrip("/"))
    credentials.save()
    click.echo(f"Configured {credentials.kemory_url} in {credentials_path()}")


@cli.command("clear")
def clear_cmd() -> None:
    """Delete the locally cached community credential."""
    target = credentials_path()
    if target.exists():
        target.unlink()
        click.echo(f"Removed {target}")
    else:
        click.echo("No cached community credential.")


def _host_config_paths() -> dict[str, list[Path]]:
    home = Path.home()
    app_support = home / "Library" / "Application Support"
    win_appdata = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    return {
        "claude-code": [home / ".claude.json"],
        "claude-desktop": [
            app_support / "Claude" / "claude_desktop_config.json",
            win_appdata / "Claude" / "claude_desktop_config.json",
            home / ".config" / "Claude" / "claude_desktop_config.json",
        ],
        "cursor": [home / ".cursor" / "mcp.json"],
        "continue": [home / ".continue" / "config.json"],
        "warp": [home / ".warp" / ".mcp.json"],
    }


def _resolve_host_config(host: str) -> Path | None:
    candidates = _host_config_paths().get(host)
    if not candidates:
        return None
    return next((path for path in candidates if path.exists()), candidates[0])


def _write_mcp_entry(config_path: Path, name: str) -> None:
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise click.ClickException(
                f"{config_path} is not valid JSON. Refusing to overwrite it."
            ) from exc
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config = {}
    config.setdefault("mcpServers", {})[name] = {
        "command": "kemory",
        "args": ["mcp", "serve"],
        "env": {},
    }
    config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


@cli.group("mcp")
def mcp_group() -> None:
    """Manage the local MCP stdio bridge."""


@mcp_group.command("install")
@click.option(
    "--host",
    "hosts",
    multiple=True,
    type=click.Choice(["claude-code", "claude-desktop", "cursor", "continue", "warp", "all"]),
    default=("claude-code",),
)
@click.option("--config", "config_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--name", default="kemory")
def mcp_install(hosts: tuple[str, ...], config_path: Path | None, name: str) -> None:
    """Install the bridge into one or more supported MCP hosts."""
    _configured()
    if config_path is not None:
        _write_mcp_entry(config_path, name)
        click.echo(f"Wrote MCP server '{name}' to {config_path}")
        return
    targets = ["claude-code", "claude-desktop", "cursor", "continue", "warp"] if "all" in hosts else list(hosts)
    for host in targets:
        target = _resolve_host_config(host)
        if target is None:
            raise click.ClickException(f"Unsupported MCP host: {host}")
        _write_mcp_entry(target, name)
        click.echo(f"Configured {host}: {target}")


@mcp_group.command("serve")
def mcp_serve() -> None:
    """Run the stdio MCP bridge for an MCP host."""
    from kemory_cli.mcp_bridge import serve

    serve()


@cli.command("doctor")
def doctor_cmd() -> None:
    """Check local API readiness, API-key auth, and adapter selection."""
    credentials = Credentials.load()
    url = credentials.kemory_url if credentials else DEFAULT_KEMORY_URL

    def emit(label: str, ok: bool, detail: str) -> None:
        click.echo(f"  {'PASS' if ok else 'FAIL'}  {label}  {detail}")

    click.echo("kemory community doctor")
    click.echo(f"  python  {sys.version.split()[0]} on {platform.system()}")
    click.echo(f"  cli     {__version__}")
    click.echo(f"  api     {url}")
    emit("credentials", credentials is not None and bool(credentials.api_key), str(credentials_path()))

    try:
        readiness = httpx.get(f"{url}/health/ready", timeout=5.0)
        emit("readiness", readiness.status_code == 200, f"HTTP {readiness.status_code}")
    except httpx.HTTPError as exc:
        emit("readiness", False, f"{type(exc).__name__}: {exc}")

    if credentials is None:
        emit("api-key auth", False, "run `kemory configure`")
        raise click.exceptions.Exit(1)
    try:
        response = httpx.get(
            f"{url}/api/v1/community/settings",
            headers={"X-API-Key": credentials.api_key},
            timeout=5.0,
        )
        if response.status_code == 200:
            settings = response.json()
            detail = ", ".join(
                str(settings.get(key, "?"))
                for key in ("identity", "vector_backend", "blob_backend", "telemetry")
            )
            emit("api-key auth", True, detail)
        else:
            emit("api-key auth", False, f"HTTP {response.status_code}")
            raise click.exceptions.Exit(1)
    except httpx.HTTPError as exc:
        emit("api-key auth", False, f"{type(exc).__name__}: {exc}")
        raise click.exceptions.Exit(1) from exc


def main() -> None:
    cli(prog_name="kemory")


if __name__ == "__main__":  # pragma: no cover
    main()
