from __future__ import annotations

import asyncio
import io
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np
try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

try:
    import PIL.Image
    _PIL = True
except ImportError:
    _PIL = False

from core.config import get_llm_provider_name, uses_native_voice
from core.llm.helpers import llm_multimodal
from core.voice.policy import speak_ui
from core.voice.tts import stop_speech

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


from core.config import get_camera_index, get_os

_IMG_MAX_W = 640
_IMG_MAX_H = 360
_JPEG_Q    = 60

_SYSTEM_PROMPT = (
    "You are Emily, an advanced AI assistant. "
    "Analyze the provided image with precision and intelligence. "
    "Provide a detailed, complete, and thoroughly informative description based on the user's specific request. "
    "Do not arbitrarily limit your explanation to two sentences; be comprehensive. "
    "Address the user respectfully. "
    "Always call the appropriate tool; never simulate results."
)


def _compress(img_bytes: bytes, source_format: str = "PNG") -> tuple[bytes, str]:
    if not _PIL:
        return img_bytes, f"image/{source_format.lower()}"

    try:
        img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q, optimize=False)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        print(f"[Vision] ⚠️  Image compress failed: {e}")
        return img_bytes, f"image/{source_format.lower()}"

def _capture_screen() -> tuple[bytes, str]:

    if not _MSS:
        raise RuntimeError("mss is not installed. Run: pip install mss")

    with mss.mss() as sct:
        monitors = sct.monitors          # [0] = all combined, [1..n] = real screens
        target   = monitors[1] if len(monitors) > 1 else monitors[0]
        shot     = sct.grab(target)
        png      = mss.tools.to_png(shot.rgb, shot.size)

    return _compress(png, "PNG")


def _cv2_backend() -> int:
    """Return the best OpenCV camera backend for the current OS."""
    if not _CV2:
        return 0
    os_name = get_os()
    if os_name == "windows":
        return cv2.CAP_DSHOW    
    if os_name == "mac":
        return cv2.CAP_AVFOUNDATION  
    return cv2.CAP_ANY


def _probe_camera(index: int, backend: int, warmup: int = 5) -> bool:

    if not _CV2:
        return False
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        return False
    for _ in range(warmup):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return False
    return bool(np.mean(frame) > 8)


def _get_camera_index() -> int:
    return get_camera_index()


def _capture_from_player_camera(player) -> tuple[bytes, str] | None:
    """Use the live HUD webcam frame when the UI camera feed is active."""
    try:
        cam = getattr(getattr(player, "_win", None), "camera", None)
        if cam is not None and hasattr(cam, "get_snapshot_jpeg"):
            snap = cam.get_snapshot_jpeg()
            if snap:
                return snap
    except Exception as e:
        print(f"[Vision] HUD camera snapshot unavailable: {e}")
    return None


def _capture_camera(player=None) -> tuple[bytes, str]:
    hud = _capture_from_player_camera(player) if player else None
    if hud:
        print("[Vision] 📷 Using live HUD camera frame")
        return hud

    if not _CV2:
        raise RuntimeError("OpenCV (cv2) is not installed. Run: pip install opencv-python")

    index   = _get_camera_index()
    backend = _cv2_backend()
    cap     = cv2.VideoCapture(index, backend)

    if not cap.isOpened():
        raise RuntimeError(f"Camera index {index} could not be opened.")

    for _ in range(10):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError("Camera returned no frame.")

    if _PIL:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q)
        return buf.getvalue(), "image/jpeg"

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_Q])
    return buf.tobytes(), "image/jpeg"

class _VisionSession:
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._out_queue: Optional[asyncio.Queue] = None
        self._ready_evt: threading.Event = threading.Event()
        self._player = None
        self._lock: threading.Lock = threading.Lock()

    def start(self, player=None, timeout: float = 25.0) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                if player is not None:
                    self._player = player
                return
            self._player = player
            self._thread = threading.Thread(
                target=self._run_event_loop,
                daemon=True,
                name="VisionSessionThread",
            )
            self._thread.start()

        if not self._ready_evt.wait(timeout=timeout):
            raise RuntimeError(f"Vision session did not start within {timeout}s.")
        print("[Vision] Session ready")

    def analyze(self, image_bytes: bytes, mime_type: str, user_text: str) -> None:
        if not self._loop or not self._out_queue:
            print("[Vision] Session not started — dropping request")
            return
        asyncio.run_coroutine_threadsafe(
            self._out_queue.put((image_bytes, mime_type, user_text)),
            self._loop,
        )

    def is_ready(self) -> bool:
        return self._loop is not None

    def _run_event_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._worker_loop())

    async def _worker_loop(self) -> None:
        self._out_queue = asyncio.Queue(maxsize=30)
        self._ready_evt.set()
        print("[Vision] Worker online")
        while True:
            image_bytes, mime_type, user_text = await self._out_queue.get()
            try:
                print(
                    f"[Vision] Analyzing {len(image_bytes):,} bytes ({mime_type}) — "
                    f"'{user_text[:60]}'"
                )
                if get_llm_provider_name() == "gemini" and uses_native_voice():
                    from core.vision.gemini_live import analyze_image
                    from core.config import get_live_model
                    print(f"[Vision] Gemini Live ({get_live_model()})")
                    answer = await analyze_image(
                        image_bytes,
                        mime_type,
                        user_text,
                        system_prompt=_SYSTEM_PROMPT,
                    )
                else:
                    prompt = f"{_SYSTEM_PROMPT}\n\nUser question: {user_text}"
                    answer = await asyncio.to_thread(
                        llm_multimodal, prompt, image_bytes, mime_type
                    )
                    answer = re.sub(r"\s+", " ", answer).strip()
                    if answer:
                        await asyncio.to_thread(
                            speak_ui, answer, player=self._player,
                        )
                if answer and self._player:
                    self._player.write_log(f"Emily: {answer}")
                    print(f"[Vision] {answer[:120]}")
            except Exception as e:
                print(f"[Vision] Analysis error: {e}")
                err = f"Sir, I could not analyze the image. {str(e)[:100]}"
                if self._player:
                    self._player.write_log(f"ERR: {err}")
                await asyncio.to_thread(
                    speak_ui, err, player=self._player,
                )

_session      = _VisionSession()
_session_lock = threading.Lock()
_session_up   = False


def _ensure_session(player=None) -> None:
    global _session_up
    with _session_lock:
        if not _session_up:
            _session.start(player=player)
            _session_up = True
        elif player is not None:
            _session._player = player


def screen_process(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> bool:

    params    = parameters or {}
    user_text = (params.get("text") or params.get("user_text") or "").strip()
    angle     = params.get("angle", "screen").lower().strip()

    if not user_text:
        print("[Vision] ⚠️  No question provided — aborting")
        return False

    print(f"[Vision] ▶ angle={angle!r}  question='{user_text[:80]}'")

    try:
        _ensure_session(player=player)
    except Exception as e:
        print(f"[Vision] ❌ Could not start session: {e}")
        return False

    try:
        if angle == "camera":
            image_bytes, mime_type = _capture_camera(player=player)
            print(f"[Vision] 📷 Camera: {len(image_bytes):,} bytes")
        else:
            image_bytes, mime_type = _capture_screen()
            print(f"[Vision] 🖥️  Screen: {len(image_bytes):,} bytes")
    except Exception as e:
        print(f"[Vision] ❌ Capture error: {e}")
        return False

    _session.analyze(image_bytes, mime_type, user_text)
    return True


def stop_vision_audio() -> None:
    """Stop vision audio playback immediately."""
    try:
        from core.vision.gemini_live import stop_audio
        stop_audio()
    except Exception:
        pass
    stop_speech()


def warmup_session(player=None) -> None:
    try:
        _ensure_session(player=player)
    except Exception as e:
        print(f"[Vision] ⚠️  Warmup failed: {e}")

if __name__ == "__main__":
    print("[TEST] screen_processor.py")
    print("=" * 52)
    mode = input("angle — screen / camera (default: screen): ").strip().lower() or "screen"
    q    = input("Question (Enter = default): ").strip() or "What do you see? Be brief."

    t0 = time.perf_counter()
    warmup_session()
    print(f"Session ready in {time.perf_counter()-t0:.2f}s\n")

    t1 = time.perf_counter()
    ok = screen_process({"angle": mode, "text": q})
    print(f"Queued in {time.perf_counter()-t1:.3f}s — waiting for audio...")
    time.sleep(10)
    print("Done." if ok else "Failed.")