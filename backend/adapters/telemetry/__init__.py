"""Telemetry adapter factory."""

from __future__ import annotations

import os

from backend.adapters.telemetry.base import Telemetry
from backend.adapters.telemetry.noop import NoOpTelemetry

VALID_TELEMETRY_BACKENDS = ("noop",)

_telemetry: Telemetry | None = None
_telemetry_backend: str | None = None


def resolve_telemetry_backend(value: str | None = None) -> str:
    if value is None:
        value = os.environ.get("KMV_TELEMETRY", "noop")
    resolved = value.strip().lower() or "noop"
    if resolved not in VALID_TELEMETRY_BACKENDS:
        raise ValueError(f"Invalid KMV_TELEMETRY: {value!r}. Must be one of: {VALID_TELEMETRY_BACKENDS}")
    return resolved


def create_telemetry(
    backend: str | None = None,
    *,
    endpoint_url: str | None = None,
) -> Telemetry:
    resolved = resolve_telemetry_backend(backend)
    if resolved == "noop":
        return NoOpTelemetry()
    raise ValueError("Hosted telemetry is not available in Kemory Community.")


def configure_telemetry(backend: str | None = None) -> Telemetry:
    global _telemetry, _telemetry_backend
    selected = resolve_telemetry_backend(backend)
    _telemetry = create_telemetry(selected)
    _telemetry_backend = selected
    return _telemetry


def get_telemetry() -> Telemetry:
    selected = resolve_telemetry_backend()
    if _telemetry is None or _telemetry_backend != selected:
        return configure_telemetry(selected)
    return _telemetry


def reset_telemetry_for_tests() -> None:
    global _telemetry, _telemetry_backend
    _telemetry = None
    _telemetry_backend = None


__all__ = [
    "NoOpTelemetry",
    "Telemetry",
    "configure_telemetry",
    "create_telemetry",
    "get_telemetry",
    "reset_telemetry_for_tests",
    "resolve_telemetry_backend",
]
