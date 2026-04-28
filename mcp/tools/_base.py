"""
Shared base types for MCP tool modules.

Each family file (memory.py, namespaces.py, consolidation.py, skills.py,
meta.py) imports MCPToolDefinition for tool defs and MCPToolResult for
return values. Kept tiny and dependency-free so importing it from any
of the family modules does not pull in handler-specific code.
"""

from __future__ import annotations

from pydantic import BaseModel


class MCPToolDefinition(BaseModel):
    """Schema for an MCP tool definition (returned in tools/list)."""

    name: str
    description: str
    inputSchema: dict


class MCPToolResult(BaseModel):
    """Standard MCP tool result envelope."""

    content: list[dict]  # [{type: "text", text: "..."}, ...]
    isError: bool = False
