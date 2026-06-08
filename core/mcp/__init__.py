"""Optional MCP server clients driven by config/mcp.json."""

from core.mcp.client import MCPClientManager, get_mcp_client
from core.mcp.registry import get_active_tool_declarations, is_mcp_server_configured

__all__ = [
    "MCPClientManager",
    "get_mcp_client",
    "get_active_tool_declarations",
    "is_mcp_server_configured",
]
