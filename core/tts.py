"""Backward-compatible TTS shim — delegates to Supertonic 3."""

from core.voice.tts import speak_sync, stop_speech

DEFAULT_TTS_VOICE = "M1"


def load_tts_voice() -> str:
    from core.config import get_tts_voice
    return get_tts_voice()


async def list_voices(locale_prefix: str = "en"):
    from core.config import TTS_VOICES
    return [{"ShortName": v, "Name": v} for v in TTS_VOICES]
