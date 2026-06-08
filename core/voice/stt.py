"""Speech-to-text — faster-whisper (local) or Deepgram (cloud)."""

from __future__ import annotations

import io
import threading
import wave

import numpy as np

from core.config import get_stt_model, get_voice_mode
from core.voice.errors import format_voice_model_error

SAMPLE_RATE = 16_000

_engine = None
_lock = threading.Lock()


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()


class FasterWhisperSTT:
    def __init__(self, model_size: str | None = None):
        self.model_size = model_size or get_stt_model()
        self._model = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel

        print(f"[STT] Loading faster-whisper model: {self.model_size}")
        try:
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
                local_files_only=True,
            )
            print("[STT] Model ready (cached)")
            return
        except Exception:
            print(f"[STT] Model not cached — downloading from HuggingFace (requires internet)...")

        try:
            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
            )
            print("[STT] Model ready")
        except Exception as exc:
            raise RuntimeError(format_voice_model_error("Speech-to-text", exc)) from exc

    def transcribe_pcm(self, pcm_bytes: bytes, language: str | None = None) -> str:
        self._ensure_model()
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size == 0:
            return ""
        segments, _ = self._model.transcribe(
            audio,
            language=language,
            vad_filter=True,
            beam_size=1,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        return text


class DeepgramSTT:
    def __init__(self, model: str | None = None):
        self.model = model or get_stt_model()

    def transcribe_pcm(self, pcm_bytes: bytes, language: str | None = None) -> str:
        if not pcm_bytes:
            return ""
        from core.voice.deepgram_client import get_deepgram_client, with_deepgram_lock

        client = get_deepgram_client()
        wav_bytes = _pcm_to_wav(pcm_bytes)
        kwargs: dict = {
            "request": wav_bytes,
            "model": self.model,
            "smart_format": True,
            "punctuate": True,
        }
        if language:
            kwargs["language"] = language

        def _call():
            return client.listen.v1.media.transcribe_file(**kwargs)

        response = with_deepgram_lock(_call)
        results = getattr(response, "results", None)
        if not results:
            print("[STT] Deepgram returned no results")
            return ""
        channels = getattr(results, "channels", None) or []
        if not channels:
            print("[STT] Deepgram returned no channels")
            return ""
        alternatives = getattr(channels[0], "alternatives", None) or []
        if not alternatives:
            print("[STT] Deepgram returned no alternatives")
            return ""
        text = (alternatives[0].transcript or "").strip()
        if text:
            print(f"[STT] Deepgram: {text[:120]}")
        else:
            print("[STT] Deepgram returned empty transcript")
        return text


def get_stt_engine():
    global _engine
    with _lock:
        if _engine is None:
            if get_voice_mode() == "deepgram":
                _engine = DeepgramSTT()
            else:
                _engine = FasterWhisperSTT()
        return _engine


def preload_stt() -> None:
    print("[STT] Starting speech-to-text preload...")
    if get_voice_mode() == "deepgram":
        from core.voice.deepgram_client import preload_deepgram
        preload_deepgram()
        print("[STT] Deepgram client ready")
        return
    get_stt_engine()._ensure_model()
