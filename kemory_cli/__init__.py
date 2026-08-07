"""Local API-key CLI and MCP bridge for Kemory Community."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version

try:
    __version__ = package_version("kemory-community")
except PackageNotFoundError:  # pragma: no cover - source checkout
    __version__ = "0.0.0+source"
