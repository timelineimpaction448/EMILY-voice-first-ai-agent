"""Firecrawl web scraping via optional MCP server (config/mcp.json)."""

from __future__ import annotations

from typing import Any

from core.mcp.client import get_mcp_client
from core.mcp.registry import is_mcp_server_configured

SCRAPE_TIMEOUT_SEC = 120.0
SEARCH_TIMEOUT_SEC = 75.0
CRAWL_TIMEOUT_SEC = 120.0


def _unavailable() -> str:
    return (
        "Firecrawl is not configured. "
        "Add mcpServers.firecrawl to config/mcp.json to enable scraping tools."
    )


def _mcp_text(res: dict[str, Any]) -> str:
    if "error" in res:
        return res["error"]
    content_list = res.get("content", [])
    text_parts = [item.get("text", "") for item in content_list if item.get("type") == "text"]
    return "\n".join(text_parts) if text_parts else "No content returned."


def _call(tool_name: str, arguments: dict, *, player=None, timeout: float = 45.0) -> str:
    if not is_mcp_server_configured("firecrawl"):
        return _unavailable()
    if player:
        player.write_log(f"[{tool_name}] {arguments}")
    return _mcp_text(get_mcp_client("firecrawl").call_tool(tool_name, arguments, timeout=timeout, player=player))


def firecrawl_scrape(parameters=None, player=None) -> str:
    params = parameters or {}
    url = str(params.get("url", "")).strip()
    if not url:
        return "Please provide a URL to scrape."
    args: dict[str, Any] = {
        "url": url,
        "formats": params.get("formats") or ["markdown"],
        "onlyMainContent": params.get("onlyMainContent", True),
    }
    if params.get("waitFor") is not None:
        args["waitFor"] = int(params["waitFor"])
    elif "fool.com" in url.lower():
        # Heavy JS / ad layout — give the page time to render article body.
        args["waitFor"] = 3000
    return _call("firecrawl_scrape", args, player=player, timeout=SCRAPE_TIMEOUT_SEC)


def firecrawl_search(parameters=None, player=None) -> str:
    params = parameters or {}
    query = str(params.get("query", "")).strip()
    if not query:
        return "Please provide a search query."
    args: dict[str, Any] = {"query": query}
    if "limit" in params:
        args["limit"] = int(params["limit"])
    if "scrapeResults" in params:
        args["scrapeResults"] = bool(params["scrapeResults"])
    return _call("firecrawl_search", args, player=player, timeout=SEARCH_TIMEOUT_SEC)


def firecrawl_map(parameters=None, player=None) -> str:
    params = parameters or {}
    url = str(params.get("url", "")).strip()
    if not url:
        return "Please provide a site URL to map."
    args: dict[str, Any] = {"url": url}
    if "limit" in params:
        args["limit"] = int(params["limit"])
    if params.get("search"):
        args["search"] = str(params["search"])
    return _call("firecrawl_map", args, player=player)


def firecrawl_crawl(parameters=None, player=None) -> str:
    params = parameters or {}
    url = str(params.get("url", "")).strip()
    if not url:
        return "Please provide a starting URL to crawl."
    args: dict[str, Any] = {"url": url}
    if "limit" in params:
        args["limit"] = int(params["limit"])
    if "maxDepth" in params:
        args["maxDepth"] = int(params["maxDepth"])
    return _call("firecrawl_crawl", args, player=player, timeout=CRAWL_TIMEOUT_SEC)
