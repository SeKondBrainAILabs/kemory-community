"""Community-only Python CLI contract."""

import json
from types import SimpleNamespace

from click.testing import CliRunner

from kemory_cli.__main__ import cli
from kemory_cli.config import Credentials


def test_cli_exposes_only_local_commands():
    result = CliRunner().invoke(cli, ["--help"])

    assert result.exit_code == 0
    for command in ("configure", "clear", "doctor", "mcp"):
        assert command in result.output
    for hosted_command in ("login", "logout", "whoami", "orgs", "keys", "telemetry", "upgrade"):
        assert hosted_command not in result.output


def test_configure_persists_mode_600_api_key(tmp_path, monkeypatch):
    target = tmp_path / "credentials.json"
    monkeypatch.setenv("KEMORY_CREDENTIALS_FILE", str(target))

    result = CliRunner().invoke(
        cli,
        ["configure", "--url", "http://127.0.0.1:8111", "--api-key", "local-secret"],
    )

    assert result.exit_code == 0
    assert Credentials.load() == Credentials(api_key="local-secret")
    assert json.loads(target.read_text())["api_key"] == "local-secret"
    assert target.stat().st_mode & 0o777 == 0o600


def test_mcp_install_writes_no_secret_or_hosted_auth(tmp_path, monkeypatch):
    credentials = tmp_path / "credentials.json"
    config = tmp_path / "mcp.json"
    monkeypatch.setenv("KEMORY_CREDENTIALS_FILE", str(credentials))
    Credentials(api_key="local-secret").save()

    result = CliRunner().invoke(cli, ["mcp", "install", "--config", str(config)])

    assert result.exit_code == 0
    text = config.read_text()
    assert "local-secret" not in text
    assert "mcp serve" not in text
    assert json.loads(text)["mcpServers"]["kemory"]["args"] == ["mcp", "serve"]


def test_doctor_uses_x_api_key_for_community_settings(tmp_path, monkeypatch):
    target = tmp_path / "credentials.json"
    monkeypatch.setenv("KEMORY_CREDENTIALS_FILE", str(target))
    Credentials(api_key="local-secret").save()
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        if url.endswith("/health/ready"):
            return SimpleNamespace(status_code=200)
        return SimpleNamespace(
            status_code=200,
            json=lambda: {
                "identity": "local_single_user",
                "vector_backend": "pgvector",
                "blob_backend": "local_fs",
                "telemetry": "noop",
            },
        )

    monkeypatch.setattr("kemory_cli.__main__.httpx.get", get)

    result = CliRunner().invoke(cli, ["doctor"])

    assert result.exit_code == 0
    assert calls[1][1]["headers"] == {"X-API-Key": "local-secret"}
    assert "local_single_user, pgvector, local_fs, noop" in result.output
