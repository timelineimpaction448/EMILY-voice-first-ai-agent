"""Voice activity detection — Silero ONNX (via faster-whisper) with energy fallback."""

from __future__ import annotations

from typing import Callable

import numpy as np

SAMPLE_RATE = 16_000
SILENCE_MS = 800
MIN_SPEECH_MS = 300
PRE_SPEECH_MS = 200
SILERO_WINDOW = 512
SILERO_CONTEXT = 64


class _StreamingSilero:
    """Streaming Silero VAD using the ONNX model bundled with faster-whisper."""

    def __init__(self) -> None:
        from faster_whisper.vad import get_vad_model

        self._model = get_vad_model()
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(SILERO_CONTEXT, dtype=np.float32)
        self._pending = np.array([], dtype=np.float32)
        self._last_prob = 0.0

    def feed_int16(self, frame: np.ndarray) -> float:
        samples = frame.astype(np.float32) / 32768.0
        if samples.size == 0:
            return self._last_prob
        self._pending = np.concatenate([self._pending, samples])
        while len(self._pending) >= SILERO_WINDOW:
            chunk = self._pending[:SILERO_WINDOW]
            self._pending = self._pending[SILERO_WINDOW:]
            self._last_prob = self._infer(chunk)
        return self._last_prob

    def _infer(self, chunk: np.ndarray) -> float:
        inp = np.concatenate([self._context, chunk]).reshape(1, -1).astype(np.float32)
        output, self._h, self._c = self._model.session.run(
            None,
            {"input": inp, "h": self._h, "c": self._c},
        )
        self._context = chunk[-SILERO_CONTEXT:]
        return float(np.asarray(output).reshape(-1)[0])


class _PreSpeechRing:
    """Rolling buffer of recent frames capped by duration (ms), not frame count."""

    def __init__(self, max_samples: int) -> None:
        self._max_samples = max_samples
        self._chunks: list[np.ndarray] = []
        self._total_samples = 0

    def append(self, frame: np.ndarray) -> None:
        self._chunks.append(frame.copy())
        self._total_samples += frame.size
        while self._total_samples > self._max_samples and self._chunks:
            dropped = self._chunks.pop(0)
            self._total_samples -= dropped.size

    def clear(self) -> None:
        self._chunks.clear()
        self._total_samples = 0

    def snapshot(self) -> list[np.ndarray]:
        return list(self._chunks)


class VADSegmenter:
    """Accumulates mic frames and emits complete utterance PCM (int16 bytes)."""

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        silence_ms: int = SILENCE_MS,
        min_speech_ms: int = MIN_SPEECH_MS,
        on_utterance: Callable[[bytes], None] | None = None,
        *,
        use_silero: bool = True,
    ):
        self.sample_rate = sample_rate
        self.silence_ms = silence_ms
        self.min_speech_ms = min_speech_ms
        self.on_utterance = on_utterance
        pre_samples = int(sample_rate * PRE_SPEECH_MS / 1000)
        self._ring = _PreSpeechRing(pre_samples)
        self._buffer: list[np.ndarray] = []
        self._in_speech = False
        self._silence_frames = 0
        self._speech_frames = 0
        self._silero: _StreamingSilero | None = None
        self._use_silero = False
        self._init_vad(use_silero=use_silero)

    def _init_vad(self, *, use_silero: bool) -> None:
        if not use_silero:
            print("[VAD] Energy-based end-of-speech detection (Deepgram STT)")
            return
        try:
            self._silero = _StreamingSilero()
            self._use_silero = True
            print("[VAD] Silero VAD loaded (ONNX)")
        except Exception as e:
            print(f"[VAD] Silero unavailable ({e}); using energy VAD")

    def _is_speech_frame(self, frame: np.ndarray) -> bool:
        if self._use_silero and self._silero is not None:
            try:
                prob = self._silero.feed_int16(frame)
                return prob > 0.5
            except Exception:
                pass
        rms = np.sqrt(np.mean(frame.astype(np.float32) ** 2))
        return rms > 400.0

    def feed(self, pcm_bytes: bytes) -> None:
        frame = np.frombuffer(pcm_bytes, dtype=np.int16)
        if frame.size == 0:
            return

        self._ring.append(frame)
        speech = self._is_speech_frame(frame)
        frame_ms = int(1000 * frame.size / self.sample_rate)

        if speech:
            if not self._in_speech:
                self._buffer = self._ring.snapshot()
                self._in_speech = True
                self._speech_frames = 0
            self._buffer.append(frame)
            self._speech_frames += frame_ms
            self._silence_frames = 0
        elif self._in_speech:
            self._buffer.append(frame)
            self._silence_frames += frame_ms
            if self._silence_frames >= self.silence_ms:
                self._finalize()

    def _finalize(self) -> None:
        if self._speech_frames >= self.min_speech_ms and self._buffer:
            audio = np.concatenate(self._buffer)
            ms = int(1000 * audio.size / self.sample_rate)
            print(f"[VAD] Utterance ready ({ms} ms)")
            if self.on_utterance:
                self.on_utterance(audio.tobytes())
        self._buffer = []
        self._in_speech = False
        self._silence_frames = 0
        self._speech_frames = 0
        self._ring.clear()

    def flush(self) -> None:
        if self._in_speech:
            self._finalize()
