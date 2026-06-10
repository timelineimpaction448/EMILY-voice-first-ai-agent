"""Shared audio-level store for the reactor ring and spectrum bars.

Two real inputs feed this (wired in Phase 3):
  - mic RMS, from a read-only tap in the voice engine's input callback
  - TTS level, from start_speaking/stop_speaking (synthetic envelope if no PCM)

Reads apply time-based decay so the visuals fall smoothly even if pushes stop.
Scalar levels are real; per-band spectrum magnitudes are synthesized from the
current level (the bars are decorative — amplitude is the truth).
"""

from __future__ import annotations

import math
import random
import time

_N_BANDS = 24


class AudioLevel:
    _instance: "AudioLevel | None" = None

    def __init__(self):
        self._mic = 0.0
        self._tts = 0.0
        self._mic_t = 0.0
        self._tts_t = 0.0
        self._speaking = False
        self._bands = [0.0] * _N_BANDS

    # ----- inputs -----
    def push_mic_rms(self, rms: float, *, ref: float = 3000.0) -> None:
        """rms: raw int16 RMS (~0..32767). Normalised to 0..1 with a soft knee."""
        norm = min(1.0, rms / ref)
        # perceptual-ish curve
        self._mic = max(self._mic * 0.5, norm ** 0.6)
        self._mic_t = time.monotonic()

    def push_tts_level(self, level: float) -> None:
        self._tts = max(0.0, min(1.0, level))
        self._tts_t = time.monotonic()

    def set_speaking(self, speaking: bool) -> None:
        self._speaking = speaking
        if not speaking:
            self._tts = 0.0

    # ----- outputs (with decay) -----
    def mic_level(self) -> float:
        return self._decayed(self._mic, self._mic_t, tau=0.18)

    def tts_level(self) -> float:
        if self._speaking and (time.monotonic() - self._tts_t) > 0.15:
            # No real PCM stream — synthesize a lively envelope.
            t = time.monotonic()
            env = 0.45 + 0.35 * abs(math.sin(t * 6.0)) + 0.18 * abs(math.sin(t * 13.0))
            return min(1.0, env)
        return self._decayed(self._tts, self._tts_t, tau=0.12)

    def active_level(self) -> float:
        """Whichever channel is live (speaking dominates)."""
        return max(self.tts_level() if self._speaking else 0.0, self.mic_level())

    def spectrum(self, n: int = _N_BANDS, *, speaking: bool | None = None) -> list[float]:
        speaking = self._speaking if speaking is None else speaking
        level = self.tts_level() if speaking else self.mic_level()
        t = time.monotonic()
        out = []
        for i in range(n):
            # Bell-ish spectral envelope weighted toward mid bands, modulated by level.
            pos = i / max(1, n - 1)
            shape = math.exp(-((pos - 0.4) ** 2) / 0.08)
            wobble = 0.5 + 0.5 * math.sin(t * (4 + i * 0.7) + i)
            mag = level * shape * (0.55 + 0.45 * wobble)
            if random.random() < 0.06:
                mag *= 1.25
            out.append(min(1.0, mag))
        return out

    @staticmethod
    def _decayed(value: float, last_t: float, *, tau: float) -> float:
        if last_t == 0.0:
            return 0.0
        dt = time.monotonic() - last_t
        return value * math.exp(-dt / tau)


def audio_level() -> AudioLevel:
    if AudioLevel._instance is None:
        AudioLevel._instance = AudioLevel()
    return AudioLevel._instance
