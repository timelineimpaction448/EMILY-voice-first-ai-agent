"""Shared HTTP client for OpenAI-compatible providers (connection reuse)."""

from __future__ import annotations

import httpx

_client: httpx.Client | None = None


def get_http_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=5.0),
            limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
        )
    return _client
