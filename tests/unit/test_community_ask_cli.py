from __future__ import annotations

import json

from click.testing import CliRunner

from kemory_cli.__main__ import cli
from kemory_cli.config import Credentials


class Response:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def credentials() -> Credentials:
    return Credentials(api_key="local-key", kemory_url="http://127.0.0.1:8111")


def test_cli_ask_shapes_request_and_prints_answer(monkeypatch):
    calls = []
    monkeypatch.setattr("kemory_cli.__main__._configured", credentials)

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"answer": "We chose pgvector [1].", "synthesized": True, "items": []})

    monkeypatch.setattr("kemory_cli.__main__.httpx.post", post)
    result = CliRunner().invoke(
        cli,
        ["ask", "What", "did", "we", "choose?", "--type", "memory", "--limit", "5"],
    )

    assert result.exit_code == 0
    assert "We chose pgvector" in result.output
    assert calls[0][0].endswith("/api/v1/ask")
    assert calls[0][1]["json"] == {
        "query": "What did we choose?",
        "types": ["memory"],
        "limit": 5,
    }
    assert calls[0][1]["timeout"] >= 60


def test_cli_ask_prints_evidence_and_supports_json(monkeypatch):
    payload = {
        "query": "q",
        "answer": None,
        "synthesized": False,
        "not_synthesized_reason": "digest_unavailable",
        "items": [{"type": "chat", "title": "Decision", "snippet": "Use pgvector"}],
    }
    monkeypatch.setattr("kemory_cli.__main__._configured", credentials)
    monkeypatch.setattr("kemory_cli.__main__.httpx.post", lambda *args, **kwargs: Response(payload))

    text_result = CliRunner().invoke(cli, ["ask", "q"])
    json_result = CliRunner().invoke(cli, ["ask", "q", "--json-output"])

    assert "Decision: Use pgvector" in text_result.output
    assert json.loads(json_result.output) == payload
