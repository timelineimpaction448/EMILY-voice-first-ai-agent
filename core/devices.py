"""Enumerate microphones and cameras for onboarding and runtime capture."""

from __future__ import annotations

import platform
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import cv2 as cv2_types

_MAX_CAMERA_PROBE = 6
_MIN_FRAME_MEAN = 8.0


def list_microphones() -> list[tuple[int, str]]:
    try:
        import sounddevice as sd
    except ImportError:
        print("[Devices] sounddevice not installed — no microphones listed.")
        return []

    devices: list[tuple[int, str]] = []
    try:
        hostapis = sd.query_hostapis()
        default_in = hostapis[sd.default.device[0]].get("name", "") if sd.default.device else ""
        for i, dev in enumerate(sd.query_devices()):
            if int(dev.get("max_input_channels", 0)) > 0:
                name = str(dev.get("name", f"Device {i}"))
                if default_in and name == default_in:
                    name = f"{name} (default)"
                devices.append((i, name))
    except Exception as e:
        print(f"[Devices] Microphone enumeration failed: {e}")
    return devices


def _cv2_backends() -> list[int]:
    try:
        import cv2
    except ImportError:
        return [0]

    os_name = platform.system()
    if os_name == "Windows":
        backends = [cv2.CAP_DSHOW]
        if hasattr(cv2, "CAP_MSMF"):
            backends.append(cv2.CAP_MSMF)
        backends.append(cv2.CAP_ANY)
        return backends
    if os_name == "Darwin":
        return [cv2.CAP_AVFOUNDATION, cv2.CAP_ANY]
    return [cv2.CAP_ANY]


def _cv2_backend() -> int:
    backends = _cv2_backends()
    return backends[0] if backends else 0


def _frame_is_usable(frame) -> bool:
    try:
        import numpy as np
    except ImportError:
        return frame is not None
    if frame is None:
        return False
    try:
        return bool(np.mean(frame) > _MIN_FRAME_MEAN)
    except Exception:
        return True


def _probe_opened_camera(cap, warmup: int = 4) -> bool:
    for _ in range(warmup):
        cap.read()
    ret, frame = cap.read()
    return ret and _frame_is_usable(frame)


def _probe_camera(index: int, backend: int, warmup: int = 4) -> bool:
    try:
        import cv2
    except ImportError:
        return False
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        return False
    ok = _probe_opened_camera(cap, warmup=warmup)
    cap.release()
    return ok


def _camera_try_order(preferred: int | None, max_probe: int = _MAX_CAMERA_PROBE) -> list[int]:
    if preferred is None:
        return list(range(max_probe))
    return [preferred] + [i for i in range(max_probe) if i != preferred]


def _try_open_index(idx: int, backend: int):
    try:
        import cv2
    except ImportError:
        return None
    cap = None
    try:
        cap = cv2.VideoCapture(idx, backend)
        if cap.isOpened() and _probe_opened_camera(cap):
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            print(f"[Camera] Opened index {idx} (backend {backend})")
            return cap
    except Exception:
        pass
    if cap is not None:
        cap.release()
    return None


def open_camera(
    preferred_index: int | None = None,
    *,
    max_probe: int = _MAX_CAMERA_PROBE,
) -> tuple["cv2_types.VideoCapture | None", int | None, int | None]:
    """Open the first working camera, trying preferred index then fallbacks/backends."""
    backends = _cv2_backends()
    indices = _camera_try_order(preferred_index, max_probe=max_probe)

    if preferred_index is not None:
        for backend in backends:
            cap = _try_open_index(preferred_index, backend)
            if cap is not None:
                return cap, preferred_index, backend

    for backend in backends:
        for idx in indices:
            if idx == preferred_index:
                continue
            cap = _try_open_index(idx, backend)
            if cap is not None:
                return cap, idx, backend
    return None, None, None


def persist_camera_index(index: int) -> None:
    from core.config import get_camera_index, save_user_config

    current = get_camera_index()
    if index == current:
        return
    print(f"[Camera] Saving working index {index} (was {current})")
    save_user_config({"camera_index": index})


def list_cameras(max_probe: int = _MAX_CAMERA_PROBE) -> list[tuple[int, str]]:
    try:
        import cv2  # noqa: F401
    except ImportError:
        print("[Devices] opencv-python not installed — no cameras listed.")
        return []

    cameras: list[tuple[int, str]] = []
    seen: set[int] = set()
    for backend in _cv2_backends():
        for idx in range(max_probe):
            if idx in seen:
                continue
            if _probe_camera(idx, backend):
                cameras.append((idx, f"Camera {idx}"))
                seen.add(idx)
    return cameras
