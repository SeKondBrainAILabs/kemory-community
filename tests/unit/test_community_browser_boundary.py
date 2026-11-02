"""The loopback API must not be callable from arbitrary web pages.

A wildcard CORS policy let any site the user visited read and write memories
with the API key; a missing Host check let a DNS-rebinding page do the same.
"""

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app, base_url="http://127.0.0.1:8111")


def _preflight(origin: str):
    return client.options(
        "/api/v1/namespaces",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-api-key",
        },
    )


def test_dashboard_origins_pass_cors():
    for origin in ("http://127.0.0.1:5175", "http://localhost:5175"):
        response = _preflight(origin)
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin


def test_browser_extension_origin_passes_cors():
    origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
    assert _preflight(origin).headers["access-control-allow-origin"] == origin


def test_foreign_origin_gets_no_cors_grant():
    response = _preflight("https://evil.example")
    assert "access-control-allow-origin" not in response.headers

    simple = client.get("/health/live", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in simple.headers


def test_foreign_host_header_is_rejected():
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/live", headers={"Host": "localhost:8111"}).status_code == 200
    assert client.get("/health/live", headers={"Host": "rebind.evil.example"}).status_code == 400
