"""Filter optional MCP-backed tools based on config/mcp.json."""

from __future__ import annotations

from core.config import get_mcp_servers

MASSIVE_TOOL_NAMES = frozenset({
    "massive_stock_quote",
    "massive_options_chain",
    "massive_search_endpoints",
    "massive_call_api",
    "massive_query_data",
})

FIRECRAWL_TOOL_NAMES = frozenset({
    "firecrawl_scrape",
    "firecrawl_search",
    "firecrawl_map",
    "firecrawl_crawl",
})

OPTIONAL_MCP_TOOLS: dict[str, frozenset[str]] = {
    "massive": MASSIVE_TOOL_NAMES,
    "firecrawl": FIRECRAWL_TOOL_NAMES,
}

ALL_OPTIONAL_MCP_TOOL_NAMES = MASSIVE_TOOL_NAMES | FIRECRAWL_TOOL_NAMES


def is_mcp_server_configured(server_name: str) -> bool:
    cfg = get_mcp_servers().get(server_name)
    return isinstance(cfg, dict) and bool(str(cfg.get("command", "")).strip())


def get_enabled_optional_tool_names() -> frozenset[str]:
    enabled: set[str] = set()
    for server, tool_names in OPTIONAL_MCP_TOOLS.items():
        if is_mcp_server_configured(server):
            enabled |= set(tool_names)
    return frozenset(enabled)


def get_active_tool_declarations() -> list[dict]:
    from core.llm.tool_declarations import TOOL_DECLARATIONS

    enabled_optional = get_enabled_optional_tool_names()
    return [
        decl
        for decl in TOOL_DECLARATIONS
        if decl["name"] not in ALL_OPTIONAL_MCP_TOOL_NAMES
        or decl["name"] in enabled_optional
    ]
