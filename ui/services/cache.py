"""TTL-stamped JSON disk cache at ~/.emily/cache/ for offline fallback."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from threading import Lock

_CACHE_DIR = Path.home() / ".emily" / "cache"
_lock = Lock()


def _path(key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    return _CACHE_DIR / f"{safe}.json"


def write_cache(key: str, value: object) -> None:
    """Atomically persist a value with a timestamp."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"ts": time.time(), "value": value}
        target = _path(key)
        with _lock:
            fd, tmp = tempfile.mkstemp(dir=str(_CACHE_DIR), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(payload, f)
                os.replace(tmp, target)
            finally:
                if os.path.exists(tmp):
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
    except Exception as e:
        print(f"[Cache] write {key} failed: {e}")


def read_cache(key: str, max_age: float | None = None) -> object | None:
    """Return cached value, or None if missing/expired/corrupt."""
    try:
        target = _path(key)
        if not target.exists():
            return None
        with _lock:
            payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "value" not in payload:
            return None
        if max_age is not None and (time.time() - payload.get("ts", 0)) > max_age:
            return None
        return payload["value"]
    except Exception:
        return None


def cache_age(key: str) -> float | None:
    """Seconds since this key was last written, or None."""
    try:
        target = _path(key)
        if not target.exists():
            return None
        payload = json.loads(target.read_text(encoding="utf-8"))
        return time.time() - payload.get("ts", 0)
    except Exception:
        return None
