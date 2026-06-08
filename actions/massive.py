"""
Massive.com market data — optional MCP server plus direct REST fallback.

Enabled only when mcpServers.massive is present in config/mcp.json.
"""

from __future__ import annotations

import json
from typing import Any

import requests

from core.config import get_mcp_servers, load_secrets
from core.mcp.client import get_mcp_client
from core.mcp.registry import is_mcp_server_configured

_MASSIVE_API_BASE = "https://api.massive.com"


def _unavailable() -> str:
    return (
        "Massive market data is not configured. "
        "Add mcpServers.massive to config/mcp.json to enable stock and options tools."
    )


def _massive_api_key() -> str | None:
    if not is_mcp_server_configured("massive"):
        return None
    mcp_env = get_mcp_servers().get("massive", {}).get("env", {})
    secrets = load_secrets()
    return (
        mcp_env.get("MASSIVE_API_KEY")
        or secrets.get("MASSIVE_API_KEY")
        or secrets.get("POLYGON_API_KEY")
    )


def _mcp_text(res: dict[str, Any]) -> str:
    if "error" in res:
        return res["error"]
    content_list = res.get("content", [])
    text_parts = [item.get("text", "") for item in content_list if item.get("type") == "text"]
    return "\n".join(text_parts) if text_parts else "No results found."


def _rest_headers() -> dict[str, str]:
    key = _massive_api_key()
    if not key:
        raise RuntimeError(_unavailable())
    return {"Authorization": f"Bearer {key}"}


def massive_stock_quote(parameters=None, player=None) -> str:
    if not is_mcp_server_configured("massive"):
        return _unavailable()

    params = parameters or {}
    ticker = (params.get("ticker") or params.get("symbol") or "").strip().upper()
    if not ticker:
        return "Please provide a stock ticker symbol (e.g. NVDA, AAPL)."

    if player:
        player.write_log(f"[massive_stock_quote] {ticker}")

    try:
        url = f"{_MASSIVE_API_BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}"
        r = requests.get(url, headers=_rest_headers(), timeout=20)
        if r.status_code == 401:
            return "Massive API authentication failed. Check MASSIVE_API_KEY in config/mcp.json."
        if r.status_code == 403:
            return f"Massive API access denied for {ticker}. Your plan may not include stock snapshots."
        if r.status_code == 404:
            return f"No snapshot data found for ticker {ticker}."
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return f"Massive REST request failed: {e}"

    t = data.get("ticker") or {}
    if not t:
        return f"Unexpected response for {ticker}: {json.dumps(data)[:500]}"

    sym = t.get("ticker", ticker)
    change = t.get("todaysChange")
    change_pct = t.get("todaysChangePerc")
    day = t.get("day") or {}
    last_trade = t.get("lastTrade") or {}
    last_quote = t.get("lastQuote") or {}

    price = last_trade.get("p") or day.get("c")
    bid = last_quote.get("p")
    ask = last_quote.get("P")
    vol = day.get("v")

    lines = [f"{sym} snapshot from Massive:"]
    if price is not None:
        lines.append(f"Last price: {price}")
    if bid is not None and ask is not None:
        lines.append(f"Bid {bid}, Ask {ask}")
    if change is not None and change_pct is not None:
        lines.append(f"Today change: {change} ({change_pct}%)")
    if vol is not None:
        lines.append(f"Volume today: {vol}")
    if day.get("o") is not None:
        lines.append(
            f"Day range open {day.get('o')} high {day.get('h')} low {day.get('l')} close {day.get('c')}"
        )
    return ". ".join(lines) + "."


def massive_options_chain(parameters=None, player=None) -> str:
    if not is_mcp_server_configured("massive"):
        return _unavailable()

    params = parameters or {}
    underlying = (params.get("underlying") or params.get("ticker") or "").strip().upper()
    if not underlying:
        return "Please provide underlying ticker (e.g. AAPL)."

    if player:
        player.write_log(f"[massive_options_chain] {underlying}")

    try:
        url = f"{_MASSIVE_API_BASE}/v3/snapshot/options/{underlying}"
        r = requests.get(url, headers=_rest_headers(), timeout=30)
        if r.status_code in (401, 403, 404):
            return f"Massive options snapshot failed ({r.status_code}): {r.text[:300]}"
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return f"Massive options REST failed: {e}"

    results = data.get("results") or data.get("options") or []
    if isinstance(results, dict):
        results = list(results.values()) if results else []

    if not results:
        return f"No options chain data returned for {underlying}."

    lines = [f"Options snapshot for {underlying} ({len(results)} contracts in response). Top contracts:"]
    for item in results[:8]:
        if isinstance(item, dict):
            details = item.get("details") or item
            sym = details.get("ticker") or item.get("ticker") or "?"
            strike = details.get("strike_price") or details.get("strike")
            ctype = details.get("contract_type") or details.get("type")
            ltp = (item.get("last_trade") or {}).get("price") or item.get("last_price")
            seg = sym
            if strike is not None:
                seg += f" strike {strike}"
            if ctype:
                seg += f" {ctype}"
            if ltp is not None:
                seg += f" last {ltp}"
            lines.append(seg)
    return ". ".join(lines) + "."


def massive_search_endpoints(parameters=None, player=None) -> str:
    if not is_mcp_server_configured("massive"):
        return _unavailable()

    params = parameters or {}
    query = params.get("query", "").strip()
    if not query:
        return "Please specify a search query."

    args = {
        "query": query,
        "detail": params.get("detail", "more"),
        "max_results": int(params.get("max_results", 5)),
        "scope": params.get("scope", "all"),
    }

    if player:
        player.write_log(f"[massive_search_endpoints] {query!r}")

    res = get_mcp_client("massive").call_tool("search_endpoints", args, timeout=30.0, player=player)
    text = _mcp_text(res)
    if "error" in res:
        return (
            f"{text} "
            "For a simple stock price, use massive_stock_quote with the ticker instead of web_search."
        )
    return text


def massive_call_api(parameters=None, player=None) -> str:
    if not is_mcp_server_configured("massive"):
        return _unavailable()

    params = parameters or {}
    path = params.get("path", "").strip()
    if not path:
        return "Please specify the API path pattern."

    api_params = dict(params.get("params") or {})
    if "?" in path:
        path, qs = path.split("?", 1)
        for part in qs.split("&"):
            if "=" in part:
                k, v = part.split("=", 1)
                api_params.setdefault(k, v)

    args: dict[str, Any] = {"path": path}
    if api_params:
        args["params"] = api_params
    if params.get("store_as"):
        args["store_as"] = params["store_as"]
    if params.get("apply"):
        args["apply"] = params["apply"]

    if player:
        player.write_log(f"[massive_call_api] {path}")

    res = get_mcp_client("massive").call_tool("call_api", args, timeout=45.0, player=player)
    if "error" in res:
        ticker = api_params.get("ticker") or api_params.get("stocksTicker")
        if ticker and "snapshot" in path.lower():
            return massive_stock_quote({"ticker": ticker}, player=player)
        return _mcp_text(res)

    return _mcp_text(res) if _mcp_text(res) != "No results found." else "No response body received."


def massive_query_data(parameters=None, player=None) -> str:
    if not is_mcp_server_configured("massive"):
        return _unavailable()

    params = parameters or {}
    sql = params.get("sql", "").strip()
    if not sql:
        return "Please specify an SQL query."

    args: dict[str, Any] = {"sql": sql}
    if params.get("apply"):
        args["apply"] = params["apply"]

    if player:
        player.write_log(f"[massive_query_data] {sql[:80]}")

    res = get_mcp_client("massive").call_tool("query_data", args, timeout=40.0, player=player)
    text = _mcp_text(res)
    return text if text != "No results found." else "No rows returned."
