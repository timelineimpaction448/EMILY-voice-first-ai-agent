"""Voice pipeline mode detection and ancillary speak routing."""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

from core.config import get_pipeline_label, uses_deepgram_voice, uses_native_voice

if TYPE_CHECKING:
    pass

_live_session: Any = None
_lock = threading.Lock()


def set_live_session(session: Any | None) -> None:
    global _live_session
    with _lock:
        _live_session = session


def get_live_session() -> Any | None:
    with _lock:
        return _live_session


def speak_ui(
    text: str,
    *,
    player=None,
    live_session=None,
    loop: asyncio.AbstractEventLoop | None = None,
) -> None:
    """Route speech through the live session when idle, else Supertonic."""
    if not text:
        return
    session = live_session if live_session is not None else get_live_session()
    if session and getattr(session, "can_speak", False):
        if player and getattr(player, "muted", False):
            return
        if loop:
            asyncio.run_coroutine_threadsafe(session.speak_text(text), loop)
        else:
            try:
                running = asyncio.get_running_loop()
                asyncio.run_coroutine_threadsafe(session.speak_text(text), running)
            except RuntimeError:
                asyncio.run(session.speak_text(text))
        return
    from core.voice.tts import speak_sync
    if uses_native_voice():
        print("[Voice] Live session busy — using Supertonic for ancillary speech")
    elif uses_deepgram_voice():
        print("[Voice] Using Deepgram for ancillary speech")
    speak_sync(text)


def speak_error_ui(tool_name: str, error: str, *, player=None, loop=None) -> None:
    short = str(error)[:120]
    if player:
        player.write_log(f"ERR: {tool_name} — {short}")
    speak_ui(f"Sir, {tool_name} encountered an error. {short}", player=player, loop=loop)


__all__ = [
    "get_pipeline_label",
    "get_live_session",
    "set_live_session",
    "speak_error_ui",
    "speak_ui",
    "uses_deepgram_voice",
    "uses_native_voice",
]
