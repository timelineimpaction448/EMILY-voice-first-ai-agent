"""Discover Gemini models that support the Live API (bidiGenerateContent)."""

from __future__ import annotations

import threading

GEMINI_LIVE_MODELS_FALLBACK: tuple[str, ...] = (
    "gemini-3.1-flash-live-preview",
    "gemini-2.5-flash-native-audio-latest",
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-2.5-flash-native-audio-preview-09-2025",
)

_cache: tuple[str, ...] | None = None
_lock = threading.Lock()


def fetch_gemini_live_models(
    *,
    api_key: str | None = None,
    force_refresh: bool = False,
) -> tuple[str, ...]:
    """Return model IDs supporting bidiGenerateContent, newest first."""
    global _cache
    with _lock:
        if _cache is not None and not force_refresh:
            return _cache

    key = (api_key or "").strip()
    if not key:
        _cache = GEMINI_LIVE_MODELS_FALLBACK
        return _cache

    try:
        from google import genai

        client = genai.Client(api_key=key, http_options={"api_version": "v1beta"})
        live_models: list[str] = []
        for model in client.models.list():
            name = (model.name or "").removeprefix("models/")
            actions = getattr(model, "supported_actions", None) or []
            if "bidiGenerateContent" in actions and name:
                live_models.append(name)

        if live_models:
            live_models.sort(reverse=True)
            _cache = tuple(live_models)
            return _cache
    except Exception as e:
        print(f"[Config] Could not fetch Gemini Live models: {e}")

    _cache = GEMINI_LIVE_MODELS_FALLBACK
    return _cache


def invalidate_cache() -> None:
    global _cache
    with _lock:
        _cache = None
