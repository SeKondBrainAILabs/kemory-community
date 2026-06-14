"""Hosted telemetry sink.

The hosted deployment currently exposes telemetry through an HTTP ingest
endpoint. This adapter keeps that behavior behind the Telemetry ABC without
adding a hard dependency on the PostHog SDK.
"""

from __future__ import annotations

from uuid import UUID

import httpx

from backend.adapters.telemetry.base import Telemetry


class PostHogTelemetry(Telemetry):
    def __init__(self, endpoint_url: str | None = None, timeout_seconds: float = 2.0) -> None:
        self._endpoint_url = (endpoint_url or "").rstrip("/")
        self._timeout_seconds = timeout_seconds

    def track(
        self,
        event: str,
        properties: dict,
        *,
        user_id: UUID | None = None,
        org_id: UUID | None = None,
    ) -> None:
        if not self._endpoint_url:
            return
        payload = {
            "event": event,
            "properties": dict(properties),
        }
        if user_id is not None:
            payload["user_id"] = str(user_id)
        if org_id is not None:
            payload["org_id"] = str(org_id)
        try:
            httpx.post(self._endpoint_url, json=payload, timeout=self._timeout_seconds)
        except Exception:
            return

    def flush(self) -> None:
        return None
