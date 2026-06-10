"""PolledService — background polling with backoff, caching, and Qt signals."""

from __future__ import annotations

import random
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from ui.services.cache import read_cache, write_cache


class PolledService(QObject):
    """Base class: subclasses implement poll() -> dict (or raise on failure).

    Signals:
        updated(object): emitted with the latest snapshot dict on success
        failed(str):     emitted with an error message on failure
        status(str):     "ok" | "stale" | "offline"
    """

    updated = pyqtSignal(object)
    failed = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(
        self,
        interval: float,
        *,
        name: str = "",
        cache_key: str | None = None,
        cache_ttl: float | None = None,
        max_backoff: float = 300.0,
        jitter: float = 0.3,
    ):
        super().__init__()
        self.interval = interval
        self.name = name or self.__class__.__name__
        self.cache_key = cache_key
        self.cache_ttl = cache_ttl
        self.max_backoff = max_backoff
        self.jitter = jitter

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._active = True
        self._last_good: object | None = None
        self._last_ok_mono: float | None = None
        self._consecutive_failures = 0
        self.status_str = "offline"

    # ----- lifecycle -----
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # Seed from disk cache so widgets have something instantly.
        if self.cache_key:
            cached = read_cache(self.cache_key, max_age=self.cache_ttl)
            if cached is not None:
                self._last_good = cached
                self._set_status("stale")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name=f"svc-{self.name}")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def set_active(self, active: bool) -> None:
        """Pause/resume polling without tearing down the thread (e.g. ISS only when visible)."""
        was = self._active
        self._active = active
        if active and not was:
            self.request_now()

    def request_now(self) -> None:
        """Force an immediate poll on the next loop iteration."""
        self._wake.set()

    def _set_status(self, s: str) -> None:
        self.status_str = s
        self.status.emit(s)

    @property
    def last_good(self) -> object | None:
        return self._last_good

    @property
    def seconds_since_ok(self) -> float | None:
        if self._last_ok_mono is None:
            return None
        return time.monotonic() - self._last_ok_mono

    # ----- override -----
    def poll(self) -> dict:
        raise NotImplementedError

    # ----- internals -----
    def _loop(self) -> None:
        # Jittered initial delay so many services don't all fire at once.
        self._interruptible_sleep(random.uniform(0, self.interval * self.jitter))
        while not self._stop.is_set():
            if self._active:
                self._do_poll()
                wait = self._next_wait()
            else:
                wait = min(self.interval, 5.0)
            self._wake.clear()
            self._interruptible_sleep(wait)

    def _do_poll(self) -> None:
        try:
            snap = self.poll()
            self._last_good = snap
            self._last_ok_mono = time.monotonic()
            self._consecutive_failures = 0
            if self.cache_key:
                write_cache(self.cache_key, snap)
            self.updated.emit(snap)
            self._set_status("ok")
        except Exception as e:
            self._consecutive_failures += 1
            self.failed.emit(str(e))
            self._set_status("offline" if self._last_good is None else "stale")
            print(f"[svc:{self.name}] poll failed ({self._consecutive_failures}): {e}")

    def _next_wait(self) -> float:
        if self._consecutive_failures == 0:
            return self.interval
        backoff = min(self.max_backoff, self.interval * (2 ** self._consecutive_failures))
        return backoff * (1 + random.uniform(-self.jitter, self.jitter))

    def _interruptible_sleep(self, seconds: float) -> None:
        # Wake early if request_now()/stop() fires.
        self._wake.wait(timeout=max(0.0, seconds))
