"""Text-to-speech — Supertonic 3 (local) or Deepgram Aura (cloud)."""

from __future__ import annotations

import io
import re
import threading
import wave
from concurrent.futures import Future, ThreadPoolExecutor

import numpy as np
import sounddevice as sd

from core.config import get_tts_voice, uses_deepgram_voice
from core.engine.prompts import plain_text_for_speech
from core.voice.errors import format_voice_model_error

_cancel_play = threading.Event()
_play_lock = threading.Lock()
_tts_engine = None
_tts_lock = threading.Lock()
_STREAM_CHUNK_LEN = 280
_SILENCE_DURATION = 0.02
_SINGLE_PASS_LIMIT = 360
_DEEPGRAM_SINGLE_PASS_LIMIT = 2000
_DEEPGRAM_CHUNK_LEN = 1200
_PCM_SILENCE_THRESHOLD = 450
_PCM_TRIM_PAD_SAMPLES = 240


def _configure_supertonic_providers() -> None:
    from core.voice.gpu_detect import detect_gpu_accel_profile, resolve_ort_providers

    profile = detect_gpu_accel_profile()
    providers = resolve_ort_providers(profile)
    import supertonic.config as st_config

    st_config.DEFAULT_ONNX_PROVIDERS = providers
    adapter = f" — {profile.adapter_name}" if profile.adapter_name else ""
    print(f"[TTS] Supertonic ONNX providers: {providers} ({profile.reason}{adapter})")


def _get_engine():
    global _tts_engine
    with _tts_lock:
        if _tts_engine is None:
            from supertonic import TTS

            _configure_supertonic_providers()
            print("[TTS] Loading Supertonic 3 (first run may download models)...")
            try:
                _tts_engine = TTS(auto_download=True)
            except Exception as exc:
                raise RuntimeError(format_voice_model_error("Text-to-speech", exc)) from exc
            print("[TTS] Supertonic ready")
        return _tts_engine


def preload_tts() -> None:
    print("[TTS] Starting text-to-speech preload...")
    if uses_deepgram_voice():
        from core.voice.deepgram_client import preload_deepgram
        preload_deepgram()
        print("[TTS] Deepgram client ready")
        return
    _get_engine()


def stop_speech() -> None:
    _cancel_play.set()
    try:
        sd.stop()
    except Exception:
        pass


def _wav_to_int16(wav: np.ndarray) -> np.ndarray:
    audio = np.asarray(wav).squeeze()
    if audio.dtype in (np.float32, np.float64):
        audio = np.clip(audio, -1.0, 1.0)
        return (audio * 32767).astype(np.int16)
    return audio.astype(np.int16)


def _play_pcm(pcm: np.ndarray, rate: int) -> None:
    with _play_lock:
        if _cancel_play.is_set():
            return
        try:
            sd.play(pcm, rate, blocking=True)
        except Exception as e:
            print(f"[TTS] Playback failed: {e}")


def _wav_bytes_to_pcm(wav_bytes: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
        sample_width = wf.getsampwidth()
        channels = wf.getnchannels()
    if sample_width == 2:
        audio = np.frombuffer(frames, dtype=np.int16)
    elif sample_width == 4:
        audio = (np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483647.0 * 32767).astype(np.int16)
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1).astype(np.int16)
    return audio, rate


def _trim_pcm_silence(pcm: np.ndarray, *, threshold: int = _PCM_SILENCE_THRESHOLD) -> np.ndarray:
    """Remove leading/trailing silence so chunk boundaries don't add long gaps."""
    if pcm.size == 0:
        return pcm
    abs_pcm = np.abs(pcm.astype(np.int32))
    voiced = np.where(abs_pcm > threshold)[0]
    if voiced.size == 0:
        return pcm
    start = max(0, int(voiced[0]) - _PCM_TRIM_PAD_SAMPLES)
    end = min(pcm.size, int(voiced[-1]) + _PCM_TRIM_PAD_SAMPLES + 1)
    return pcm[start:end]


def _deepgram_synthesize(text: str, voice: str) -> tuple[np.ndarray, int]:
    from core.voice.deepgram_client import get_deepgram_client, with_deepgram_lock

    client = get_deepgram_client()

    def _call():
        # linear16 + wav — container alone defaults to mp3 encoding and returns 400.
        audio_iter = client.speak.v1.audio.generate(
            text=text,
            model=voice,
            encoding="linear16",
            container="wav",
            sample_rate=24000,
        )
        return b"".join(audio_iter)

    wav_bytes = with_deepgram_lock(_call)
    pcm, rate = _wav_bytes_to_pcm(wav_bytes)
    return _trim_pcm_silence(pcm), rate


def _speak_supertonic(text: str, voice: str | None, lang: str) -> None:
    from supertonic.utils import chunk_text

    voice = voice or get_tts_voice()
    engine = _get_engine()
    style = engine.get_voice_style(voice_name=voice)
    rate = engine.sample_rate
    if len(text) <= _SINGLE_PASS_LIMIT:
        chunks = [text]
    else:
        chunks = chunk_text(text, max_len=_STREAM_CHUNK_LEN)
    if not chunks:
        return

    def _synth(chunk: str):
        return engine.synthesize(
            chunk,
            voice_style=style,
            lang=lang,
            silence_duration=_SILENCE_DURATION,
            max_chunk_length=_STREAM_CHUNK_LEN,
        )

    pending: Future | None = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        for chunk in chunks:
            if _cancel_play.is_set():
                break
            if pending is not None:
                wav, _ = pending.result()
                _play_pcm(_wav_to_int16(wav), rate)
                if _cancel_play.is_set():
                    break
            pending = pool.submit(_synth, chunk)

        if pending is not None and not _cancel_play.is_set():
            wav, _ = pending.result()
            _play_pcm(_wav_to_int16(wav), rate)


def _split_chunks_deepgram(text: str, max_len: int) -> list[str]:
    """Split on paragraph/length boundaries — avoid breaking on every sentence period."""
    text = text.strip()
    if len(text) <= max_len:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > max_len:
            if current:
                chunks.append(current)
                current = ""
            start = 0
            while start < len(para):
                end = min(start + max_len, len(para))
                if end < len(para):
                    split_at = para.rfind(" ", start, end)
                    if split_at > start:
                        end = split_at
                piece = para[start:end].strip()
                if piece:
                    chunks.append(piece)
                start = end if end > start else end + 1
            continue

        candidate = f"{current} {para}".strip() if current else para
        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = para

    if current:
        chunks.append(current)
    return chunks or [text]


def _speak_deepgram(text: str, voice: str | None) -> None:
    voice = voice or get_tts_voice()
    if len(text) <= _DEEPGRAM_SINGLE_PASS_LIMIT:
        chunks = [text]
    else:
        chunks = _split_chunks_deepgram(text, _DEEPGRAM_CHUNK_LEN)
    if not chunks:
        return

    pending: Future | None = None
    with ThreadPoolExecutor(max_workers=1) as pool:
        for chunk in chunks:
            if _cancel_play.is_set():
                break
            if pending is not None:
                pcm, rate = pending.result()
                _play_pcm(pcm, rate)
                if _cancel_play.is_set():
                    break
            pending = pool.submit(_deepgram_synthesize, chunk, voice)

        if pending is not None and not _cancel_play.is_set():
            pcm, rate = pending.result()
            _play_pcm(pcm, rate)


def _split_chunks(text: str, max_len: int) -> list[str]:
    """Simple sentence-boundary chunking for Deepgram TTS."""
    import re
    parts = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(current) + len(part) + 1 <= max_len:
            current = f"{current} {part}".strip() if current else part
        else:
            if current:
                chunks.append(current)
            if len(part) <= max_len:
                current = part
            else:
                for i in range(0, len(part), max_len):
                    chunks.append(part[i : i + max_len])
                current = ""
    if current:
        chunks.append(current)
    return chunks


def speak_sync(text: str, voice: str | None = None, lang: str = "en") -> None:
    """Synthesize and play text in chunks for low time-to-first-audio."""
    text = plain_text_for_speech(text or "")
    if not text:
        return
    _cancel_play.clear()

    if uses_deepgram_voice():
        _speak_deepgram(text, voice)
    else:
        _speak_supertonic(text, voice, lang)


def speak_async(text: str, voice: str | None = None, lang: str = "en") -> threading.Thread:
    t = threading.Thread(target=speak_sync, args=(text, voice, lang), daemon=True)
    t.start()
    return t
