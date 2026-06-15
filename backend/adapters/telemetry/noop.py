"""No-op telemetry implementation for community edition."""

from __future__ import annotations

from uuid import UUID

from backend.adapters.telemetry.base import Telemetry


class NoOpTelemetry(Telemetry):
    def track(
        self,
        event: str,
        properties: dict,
        *,
        user_id: UUID | None = None,
        org_id: UUID | None = None,
    ) -> None:
        return None

    def flush(self) -> None:
        return None
