"""Shared Deepgram SDK client singleton."""

from __future__ import annotations

import threading

from core.config import get_deepgram_api_key

_client = None
_lock = threading.Lock()


def get_deepgram_client():
    global _client
    with _lock:
        if _client is None:
            from deepgram import DeepgramClient

            api_key = get_deepgram_api_key()
            if not api_key:
                raise RuntimeError("Deepgram API key is not configured")
            _client = DeepgramClient(api_key=api_key)
            print("[Deepgram] Client ready")
        return _client


def with_deepgram_lock(fn):
    """Run a Deepgram SDK call under the shared client lock (thread-safe)."""
    with _lock:
        return fn()


def preload_deepgram() -> None:
    """Validate API key and initialize client (no model download)."""
    get_deepgram_client()


def reset_deepgram_client() -> None:
    """Clear cached client (e.g. after key change in setup)."""
    global _client
    with _lock:
        _client = None
