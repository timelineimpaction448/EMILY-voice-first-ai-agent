"""Tiny HTTP helper — short timeouts, JSON, no external deps beyond requests."""

from __future__ import annotations

from typing import Any

_UA = "EmilyHUD/2.0 (+local desktop assistant)"
_DEFAULT_TIMEOUT = 5.0


def get_json(url: str, *, params: dict | None = None, timeout: float = _DEFAULT_TIMEOUT) -> Any:
    import requests

    resp = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers={"User-Agent": _UA, "Accept": "application/json"},
    )
    resp.raise_for_status()
    return resp.json()


def get_text(url: str, *, params: dict | None = None, timeout: float = _DEFAULT_TIMEOUT) -> str:
    import requests

    resp = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers={"User-Agent": _UA},
    )
    resp.raise_for_status()
    return resp.text
