"""Telemetry adapter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID


class Telemetry(ABC):
    @abstractmethod
    def track(
        self,
        event: str,
        properties: dict,
        *,
        user_id: UUID | None = None,
        org_id: UUID | None = None,
    ) -> None:
        """Emit one telemetry event."""

    @abstractmethod
    def flush(self) -> None:
        """Flush any buffered events before process shutdown."""
