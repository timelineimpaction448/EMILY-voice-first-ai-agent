"""PCM audio playback for realtime voice engines (24 kHz mono int16)."""

from __future__ import annotations

import asyncio
import collections
import threading

import numpy as np
import sounddevice as sd

OUTPUT_SAMPLE_RATE = 24_000
CHANNELS = 1


class AudioOutputPlayer:
    def __init__(self, sample_rate: int = OUTPUT_SAMPLE_RATE):
        self.sample_rate = sample_rate
        self._buffer: collections.deque[int] = collections.deque()
        self._lock = threading.Lock()
        self._stream: sd.OutputStream | None = None

    def start(self) -> None:
        if self._stream is not None:
            return

        def callback(outdata, frames, time_info, status):
            with self._lock:
                for i in range(frames):
                    if self._buffer:
                        outdata[i, 0] = self._buffer.popleft() / 32768.0
                    else:
                        outdata[i, 0] = 0.0

        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype="float32",
            callback=callback,
            blocksize=1024,
        )
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self.clear()

    def feed(self, pcm: bytes) -> None:
        if not pcm:
            return
        samples = np.frombuffer(pcm, dtype=np.int16)
        with self._lock:
            self._buffer.extend(int(s) for s in samples)

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()

    def pending_samples(self) -> int:
        with self._lock:
            return len(self._buffer)

    async def drain(self, *, idle_sec: float = 0.4, timeout: float = 45.0) -> None:
        import time
        deadline = time.monotonic() + timeout
        idle_since: float | None = None
        while time.monotonic() < deadline:
            if self.pending_samples() == 0:
                if idle_since is None:
                    idle_since = time.monotonic()
                elif time.monotonic() - idle_since >= idle_sec:
                    return
            else:
                idle_since = None
            await asyncio.sleep(0.05)
