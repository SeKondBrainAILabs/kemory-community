"""
Kemory CLI — OAuth 2.0 device-authorization flow against Keycloak.

Spec: RFC 8628 (https://datatracker.ietf.org/doc/html/rfc8628).

Why device flow and not authorization code?
- The CLI runs on a laptop, often over SSH, sometimes in a container.
- Device flow doesn't need the CLI to spin up a local HTTP listener or
  parse a redirect — the user authenticates in any browser, the CLI just
  polls a token endpoint.
- Cleanly revocable from Keycloak admin (one click ends the session).

Flow:
  1. CLI POSTs to /protocol/openid-connect/auth/device with client_id+scope.
     Receives a device_code, user_code, verification_uri, interval.
  2. CLI prints the verification URL + user_code, opens the browser.
  3. CLI polls /protocol/openid-connect/token with grant_type=urn:ietf:params:oauth:grant-type:device_code
     until it gets back access+refresh tokens (or times out).
  4. Tokens are cached in ~/.kemory/credentials.
"""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import sys
import time
import webbrowser
from dataclasses import dataclass

import httpx

from kemory_cli.config import Credentials

# ─── PKCE (RFC 7636) ──────────────────────────────────────────────────────
# Defense-in-depth on top of the device-flow spec. RFC 8628 doesn't
# require PKCE for public clients, but adding it raises the bar against
# auth-code-leakage between device approval and token poll.


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for an S256 PKCE flow."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii")
    )
    return verifier, challenge


def _is_headless() -> bool:
    """Detect environments where opening a browser would be useless."""
    if os.environ.get("KEMORY_HEADLESS") == "1":
        return True
    if sys.platform.startswith("linux"):
        return not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY")
    if os.environ.get("SSH_TTY") or os.environ.get("SSH_CONNECTION"):
        return True
    return False


# ─── Device flow primitives ───────────────────────────────────────────────


@dataclass
class DeviceCodeResponse:
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class DeviceFlowError(RuntimeError):
    """Raised when the OAuth device flow fails or is denied."""


def request_device_code(
    issuer: str,
    client_id: str,
    scope: str = "openid profile email offline_access",
    timeout: float = 10.0,
    code_challenge: str | None = None,
) -> DeviceCodeResponse:
    """Initiate the device-authorization flow.

    code_challenge: PKCE S256 challenge. When provided, the matching
    code_verifier must be supplied to poll_for_token().
    """
    url = f"{issuer.rstrip('/')}/protocol/openid-connect/auth/device"
    data: dict[str, str] = {"client_id": client_id, "scope": scope}
    if code_challenge:
        data["code_challenge"] = code_challenge
        data["code_challenge_method"] = "S256"
    resp = httpx.post(url, data=data, timeout=timeout)
    if resp.status_code != 200:
        raise DeviceFlowError(f"device_code request failed: {resp.status_code} {resp.text}")
    data = resp.json()
    return DeviceCodeResponse(
        device_code=data["device_code"],
        user_code=data["user_code"],
        verification_uri=data["verification_uri"],
        verification_uri_complete=data.get("verification_uri_complete", data["verification_uri"]),
        expires_in=int(data.get("expires_in", 600)),
        interval=int(data.get("interval", 5)),
    )


def poll_for_token(
    issuer: str,
    client_id: str,
    device_code: DeviceCodeResponse,
    code_verifier: str | None = None,
) -> dict:
    """Block until the user approves or the device_code expires.

    Returns the raw token response dict; caller wraps it in Credentials.
    code_verifier: PKCE verifier matching the challenge passed to
    request_device_code.
    """
    token_url = f"{issuer.rstrip('/')}/protocol/openid-connect/token"
    deadline = time.time() + device_code.expires_in
    interval = device_code.interval

    while time.time() < deadline:
        body: dict[str, str] = {
            "client_id": client_id,
            "device_code": device_code.device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }
        if code_verifier:
            body["code_verifier"] = code_verifier
        resp = httpx.post(token_url, data=body, timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
        body = resp.json() if resp.content else {}
        err = body.get("error")
        if err == "authorization_pending":
            time.sleep(interval)
            continue
        if err == "slow_down":
            interval += 5
            time.sleep(interval)
            continue
        if err in {"expired_token", "access_denied"}:
            raise DeviceFlowError(f"device flow {err}: {body.get('error_description', '')}")
        raise DeviceFlowError(f"device flow unexpected response: {resp.status_code} {resp.text}")

    raise DeviceFlowError("device code expired before approval")


# ─── High-level helpers used by `kemory login` and the MCP bridge ────────


def login(
    issuer: str,
    client_id: str,
    kemory_url: str,
    open_browser: bool = True,
    output=print,
) -> Credentials:
    """Run the full device flow and return saved Credentials.

    Always uses PKCE (S256) — defense-in-depth on top of the device flow
    spec. Skips the auto-open-browser step in headless / SSH environments
    where launching a local browser would be useless.
    """
    code_verifier, code_challenge = _pkce_pair()
    dev = request_device_code(issuer, client_id, code_challenge=code_challenge)
    output(
        "\nOpen this URL in any browser and enter the code:\n"
        f"  {dev.verification_uri}\n"
        f"  Code: {dev.user_code}\n"
    )
    if open_browser and not _is_headless():
        try:
            webbrowser.open(dev.verification_uri_complete, new=2, autoraise=True)
        except Exception:
            pass

    output("Waiting for approval... (Ctrl-C to cancel)\n")
    token = poll_for_token(issuer, client_id, dev, code_verifier=code_verifier)

    creds = Credentials(
        access_token=token["access_token"],
        refresh_token=token["refresh_token"],
        expires_at=time.time() + int(token.get("expires_in", 300)),
        issuer=issuer,
        client_id=client_id,
        kemory_url=kemory_url,
    )
    creds.save()
    return creds


def refresh(creds: Credentials) -> Credentials:
    """Exchange the refresh_token for a fresh access_token. Saves on success."""
    token_url = f"{creds.issuer.rstrip('/')}/protocol/openid-connect/token"
    resp = httpx.post(
        token_url,
        data={
            "client_id": creds.client_id,
            "grant_type": "refresh_token",
            "refresh_token": creds.refresh_token,
        },
        timeout=10.0,
    )
    if resp.status_code != 200:
        raise DeviceFlowError(f"refresh failed: {resp.status_code} {resp.text}. Run `kemory login`.")
    token = resp.json()
    creds.access_token = token["access_token"]
    creds.refresh_token = token.get("refresh_token", creds.refresh_token)
    creds.expires_at = time.time() + int(token.get("expires_in", 300))
    creds.save()
    return creds


def get_valid_credentials(refresh_within: int = 60) -> Credentials | None:
    """Load credentials, refreshing if they're about to expire. Returns None
    if no credentials exist (caller should prompt for `kemory login`)."""
    creds = Credentials.load()
    if creds is None:
        return None
    if creds.expires_within(refresh_within):
        try:
            creds = refresh(creds)
        except DeviceFlowError:
            return None
    return creds
