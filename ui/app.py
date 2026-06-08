from __future__ import annotations

import os
import platform
import sys

# Suppress the SetProcessDpiAwarenessContext() warning on Windows
if platform.system() == "Windows":
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_SCALE_FACTOR_ROUNDING_POLICY"] = "PassThrough"

import json
import math
import random
import subprocess
import threading
import time
from pathlib import Path

_WAKE_GREETINGS = ("Hello.", "Hi.", "Hi there.")
_DEFAULT_SLEEP_FACE_TIMEOUT_SEC = 300

import psutil

from PyQt6.QtCore import (
    QEasingCurve, QEvent, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QDragEnterEvent, QDropEvent, QFont, QFontDatabase,
    QImage, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QTextEdit,
    QVBoxLayout, QWidget, QProgressBar,
)

from ui.floating_orb import FloatingOrbWindow
from ui.orb_widget import OrbAnimatorMixin

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

_DEFAULT_W, _DEFAULT_H = 1040, 720
_MIN_W,     _MIN_H     = 860, 600
_LEFT_W  = 158
_RIGHT_W = 352

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    """F.R.I.D.A.Y. / Stark holographic HUD palette."""
    BG        = "#000102"
    PANEL     = "#020810"
    PANEL2    = "#031018"
    BORDER    = "#0a3d52"
    BORDER_B  = "#1a6a8f"
    BORDER_A  = "#124e68"
    PRI       = "#00d4ff"
    PRI_DIM   = "#0088aa"
    PRI_GHO   = "#001828"
    GLOW      = "#4de8ff"
    ARC       = "#ff9a00"
    ARC_CORE  = "#ffcc44"
    ACC       = "#ff6a00"
    ACC2      = "#ffd060"
    GREEN     = "#00ffaa"
    GREEN_D   = "#00aa66"
    RED       = "#ff3355"
    MUTED_C   = "#ff4466"
    TEXT      = "#a8f4ff"
    TEXT_DIM  = "#3d7a8a"
    TEXT_MED  = "#6ec4dc"
    WHITE     = "#e8fcff"
    DARK      = "#000810"
    BAR_BG    = "#021420"
    SCAN      = "#0d3040"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c


def _hud_font(size: int, bold: bool = False) -> QFont:
    weight = QFont.Weight.Bold if bold else QFont.Weight.Normal
    return QFont("Courier New", size, weight)


def _draw_hud_corners(
    p: QPainter, rect: QRectF, color: QColor, length: float = 16, pen_w: float = 2.0
) -> None:
    p.setPen(QPen(color, pen_w))
    x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
    for bx, by, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        p.drawLine(QPointF(bx, by), QPointF(bx + dx * length, by))
        p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * length))


def _draw_scanlines(p: QPainter, rect: QRectF, alpha: int = 14, spacing: int = 3) -> None:
    p.setPen(QPen(qcol(C.SCAN, alpha), 1))
    y = int(rect.top())
    bottom = int(rect.bottom())
    while y < bottom:
        p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        y += spacing


def _draw_hex_grid(p: QPainter, w: int, h: int, cx: float, cy: float, radius: float = 26) -> None:
    p.setPen(QPen(qcol(C.PRI_GHO, 90), 1))
    for row in range(-8, 9):
        for col in range(-8, 9):
            ox = (col + (row & 1) * 0.5) * radius * 1.75
            oy = row * radius * 1.52
            hx, hy = cx + ox, cy + oy
            if hx < -radius or hx > w + radius or hy < -radius or hy > h + radius:
                continue
            path = QPainterPath()
            for i in range(6):
                ang = math.radians(60 * i - 30)
                px = hx + radius * 0.38 * math.cos(ang)
                py = hy + radius * 0.38 * math.sin(ang)
                if i == 0:
                    path.moveTo(px, py)
                else:
                    path.lineTo(px, py)
            path.closeSubpath()
            p.drawPath(path)


def _panel_stylesheet(extra: str = "") -> str:
    return f"""
        background: {C.PANEL2};
        border: 1px solid {C.BORDER_A};
        border-radius: 2px;
        {extra}
    """

class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
            }


_metrics = _SysMetrics()

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False


def _load_camera_index() -> int:
    from core.config import get_camera_index
    return get_camera_index()


def _camera_cv_enabled() -> bool:
    from core.config import get_camera_cv_enabled
    return get_camera_cv_enabled()


def _sleep_mode_enabled() -> bool:
    from core.config import get_sleep_mode_enabled
    return get_sleep_mode_enabled()


def _sleep_face_timeout_sec() -> int:
    from core.config import get_sleep_face_timeout_sec
    return get_sleep_face_timeout_sec(_DEFAULT_SLEEP_FACE_TIMEOUT_SEC)


class CameraFeedWidget(QWidget):
    """Small live webcam preview with HUD-style chrome and local CV overlays."""

    detections_updated = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None, width: int | None = None, height: int | None = None):
        super().__init__(parent)
        self._feed_w = width if width is not None else (_LEFT_W - 16)
        self._feed_h = height if height is not None else int(self._feed_w * 0.75)
        self.setFixedSize(self._feed_w, self._feed_h)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)

        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._frame_rgb: object | None = None
        self._status = "starting"
        self._rec_on = True
        self._dash_offset = 0.0
        self._scan_y = 0.0
        self._frame_i = 0
        self._det_lock = threading.Lock()
        self._detections: list = []
        self._detector = None
        self._presence_lock = threading.Lock()
        self._started_mono = time.monotonic()
        self._last_face_mono: float | None = None
        self._face_visible_now = False

        if _CV2 and _camera_cv_enabled():
            try:
                from vision.local_detector import LocalVisionEngine
                self._detector = LocalVisionEngine(
                    detect_objects=False,
                    detect_people=False,
                    detect_faces=True,
                )
            except Exception as e:
                print(f"[Camera] Local vision init failed: {e}")

        self._paint_tmr = QTimer(self)
        self._paint_tmr.timeout.connect(self._on_paint_tick)
        self._paint_tmr.start(33)

        self._blink_tmr = QTimer(self)
        self._blink_tmr.timeout.connect(self._toggle_rec_blink)
        self._blink_tmr.start(520)

        self.start()

    def start(self) -> None:
        if self._running or not _CV2:
            if not _CV2:
                self._status = "no_cv2"
                self.update()
            return
        self._running = True
        self._status = "starting"
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="EmilyCamera")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None
        with self._lock:
            self._frame_rgb = None
        with self._det_lock:
            self._detections = []

    def get_detections(self) -> list[dict]:
        """Latest local CV results (no LLM), for other modules."""
        with self._det_lock:
            return [d.as_dict() for d in self._detections]

    def is_face_visible(self) -> bool:
        with self._presence_lock:
            return self._face_visible_now

    def get_seconds_without_face(self) -> float:
        with self._presence_lock:
            if self._face_visible_now:
                return 0.0
            if self._last_face_mono is None:
                return time.monotonic() - self._started_mono
            return time.monotonic() - self._last_face_mono

    def get_snapshot_jpeg(self) -> tuple[bytes, str] | None:
        """Return the latest HUD camera frame as JPEG bytes for Gemini vision."""
        with self._lock:
            frame = self._frame_rgb
        if frame is None or not _CV2:
            return None
        try:
            from PIL import Image
            import io as _io

            img = Image.fromarray(frame)
            img.thumbnail((640, 360), Image.BILINEAR)
            buf = _io.BytesIO()
            img.save(buf, format="JPEG", quality=60)
            return buf.getvalue(), "image/jpeg"
        except Exception:
            try:
                bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                ok, enc = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 60])
                if ok:
                    return enc.tobytes(), "image/jpeg"
            except Exception as e:
                print(f"[Camera] Snapshot encode failed: {e}")
        return None

    def _update_face_presence(self, detections: list) -> None:
        face_present = any(getattr(d, "kind", None) == "face" for d in detections)
        with self._presence_lock:
            if face_present:
                self._last_face_mono = time.monotonic()
            self._face_visible_now = face_present

    def _open_capture(self, preferred_index: int):
        from core.devices import open_camera, persist_camera_index

        cap, index, _backend = open_camera(preferred_index)
        if cap is None or index is None:
            return None, preferred_index
        if index != preferred_index:
            persist_camera_index(index)
        return cap, index

    def _capture_loop(self) -> None:
        from core.devices import _frame_is_usable

        preferred = _load_camera_index()
        cap, index = self._open_capture(preferred)
        if cap is None:
            print(f"[Camera] No working camera found (preferred index {preferred})")
            self._status = "offline"
            self._running = False
            return

        self._status = "live"
        detect_every = 4
        bad_frames = 0

        while self._running:
            try:
                ret, frame = cap.read()
                if ret and frame is not None and _frame_is_usable(frame):
                    bad_frames = 0
                    frame = cv2.flip(frame, 1)
                    self._frame_i += 1
                    if self._detector and self._frame_i % detect_every == 0:
                        try:
                            dets = self._detector.detect(frame)
                            with self._det_lock:
                                self._detections = dets
                            self._update_face_presence(dets)
                            from vision.local_detector import LocalVisionEngine
                            summary = LocalVisionEngine.summary_text(dets)
                            self.detections_updated.emit(f"CV: {summary}")
                        except Exception as e:
                            print(f"[Camera] CV detect: {e}")
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    with self._lock:
                        self._frame_rgb = rgb.copy()
                else:
                    bad_frames += 1
                    time.sleep(0.05)
                    if bad_frames >= 40:
                        print(f"[Camera] Lost signal on index {index}, reconnecting...")
                        try:
                            cap.release()
                        except Exception:
                            pass
                        cap, index = self._open_capture(preferred)
                        if cap is None:
                            self._status = "offline"
                            break
                        self._status = "live"
                        bad_frames = 0
            except Exception as e:
                print(f"[Camera] Capture error: {e}")
                time.sleep(0.1)

        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

    def _toggle_rec_blink(self) -> None:
        self._rec_on = not self._rec_on
        self.update()

    def _on_paint_tick(self) -> None:
        self._dash_offset = (self._dash_offset + 0.6) % 20.0
        self._scan_y = (self._scan_y + 1.8) % float(self._feed_h)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        pad = 3
        inner = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        p.fillRect(self.rect(), qcol(C.BG, 0))

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(inner, 5, 5)

        img_rect = QRectF(inner.x() + 4, inner.y() + 4, inner.width() - 8, inner.height() - 8)
        has_frame = False

        with self._lock:
            frame = self._frame_rgb
        with self._det_lock:
            dets = list(self._detections)

        if frame is not None and _CV2:
            try:
                h, w, ch = frame.shape
                qimg = QImage(frame.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                pix = QPixmap.fromImage(qimg)
                pix = pix.scaled(
                    int(img_rect.width()), int(img_rect.height()),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                p.setClipRect(img_rect)
                px = int(img_rect.x() + (img_rect.width() - pix.width()) / 2)
                py = int(img_rect.y() + (img_rect.height() - pix.height()) / 2)
                p.drawPixmap(px, py, pix)

                if dets and pix.width() > 0 and pix.height() > 0:
                    scale = max(img_rect.width() / w, img_rect.height() / h)
                    for det in dets:
                        x1 = px + det.x1 * scale
                        y1 = py + det.y1 * scale
                        x2 = px + det.x2 * scale
                        y2 = py + det.y2 * scale
                        if det.kind == "person":
                            col = qcol(C.GREEN, 220)
                        elif det.kind == "face":
                            col = qcol(C.ACC, 220)
                        else:
                            col = qcol(C.PRI, 200)
                        p.setPen(QPen(col, 1.5))
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        p.drawRect(QRectF(x1, y1, x2 - x1, y2 - y1))
                        lbl = det.label
                        if det.confidence > 0 and det.kind != "face":
                            lbl = f"{det.label} {int(det.confidence * 100)}%"
                        p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
                        p.fillRect(QRectF(x1, max(img_rect.top(), y1 - 11), 72, 11), qcol(C.BG, 200))
                        p.setPen(QPen(col, 1))
                        p.drawText(QRectF(x1 + 2, max(img_rect.top(), y1 - 11), 70, 11),
                                   Qt.AlignmentFlag.AlignLeft, lbl[:14])

                p.setClipping(False)
                has_frame = True
            except Exception:
                has_frame = False

        if not has_frame:
            p.fillRect(img_rect, qcol("#000a10"))
            p.setPen(QPen(qcol(C.BORDER), 1))
            cx, cy = img_rect.center().x(), img_rect.center().y()
            p.drawLine(QPointF(cx - 18, cy), QPointF(cx + 18, cy))
            p.drawLine(QPointF(cx, cy - 18), QPointF(cx, cy + 18))
            msg = {
                "starting": "LINKING CAM…",
                "offline":  "NO SIGNAL",
                "no_cv2":   "CV2 MISSING",
            }.get(self._status, "NO SIGNAL")
            p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            p.drawText(img_rect, Qt.AlignmentFlag.AlignCenter, msg)

        scan_a = max(0, int(55 * (1.0 - abs(self._scan_y - img_rect.height() / 2) / (img_rect.height() / 2))))
        p.setPen(QPen(qcol(C.PRI, scan_a), 1))
        p.drawLine(
            QPointF(img_rect.left(), img_rect.top() + self._scan_y),
            QPointF(img_rect.right(), img_rect.top() + self._scan_y),
        )

        border_pen = QPen(
            qcol(C.GREEN if self._status == "live" else C.PRI_DIM, 220),
            1.5,
            Qt.PenStyle.DashLine,
        )
        border_pen.setDashOffset(self._dash_offset)
        p.setPen(border_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(inner, 5, 5)

        bl = 10
        bc = qcol(C.PRI, 200)
        p.setPen(QPen(bc, 1.5))
        x0, y0 = inner.left(), inner.top()
        x1, y1 = inner.right(), inner.bottom()
        for bx, by, dx, dy in [(x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)]:
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(inner.x() + 8, inner.y() + 6, 90, 14),
                   Qt.AlignmentFlag.AlignLeft, "◈ OPTICS")

        if self._status == "live":
            rec_col = qcol(C.RED if self._rec_on else "#661122")
            p.setBrush(QBrush(rec_col))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(inner.right() - 22, inner.y() + 7, 6, 6))
            p.setPen(QPen(rec_col, 1))
            p.setFont(QFont("Courier New", 6, QFont.Weight.Bold))
            p.drawText(QRectF(inner.right() - 52, inner.y() + 5, 44, 12),
                       Qt.AlignmentFlag.AlignRight, "LIVE")


class HudCanvas(QWidget, OrbAnimatorMixin):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.state = "INITIALISING"
        self._blink = True
        self._blink_tick = 0
        self._init_orb(face_path)

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def _step(self):
        self._step_orb()
        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        _draw_hex_grid(p, W, H, cx, cy, radius=24)
        _draw_scanlines(p, QRectF(0, 0, W, H), alpha=12, spacing=4)

        r_face = fw * 0.31
        active_col = C.MUTED_C if self.muted else (C.ARC if self.speaking else C.PRI)

        self._paint_orb(p, cx, cy, fw, compact=False, include_face=False, include_particles=False)

        # tick marks
        t_out, t_in = fw * 0.497, fw * 0.474
        p.setPen(QPen(qcol(C.PRI, 140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            p.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn  * math.cos(rad), cy - inn  * math.sin(rad)),
            )

        # crosshair
        ch_r, gap_h = fw * 0.51, fw * 0.16
        p.setPen(QPen(qcol(C.GLOW, int(self._halo * 0.45)), 1))
        p.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        p.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        p.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        p.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

        # outer HUD frame
        frame_r = fw * 0.54
        _draw_hud_corners(p, QRectF(cx - frame_r, cy - frame_r, frame_r * 2, frame_r * 2),
                          qcol(C.GLOW, 180), length=28, pen_w=2)

        # side telemetry readouts
        p.setFont(_hud_font(6, True))
        side_lines = [
            ("HOLO.LINK", C.PRI_DIM),
            ("ARC.REACTOR", C.ARC if self.speaking else C.PRI_DIM),
            ("NEURAL.CORE", C.GREEN if self.state == "LISTENING" else C.TEXT_DIM),
        ]
        for i, (txt, col) in enumerate(side_lines):
            p.setPen(QPen(qcol(col, 200), 1))
            p.drawText(QRectF(8, cy - frame_r + 12 + i * 14, 72, 12),
                       Qt.AlignmentFlag.AlignLeft, txt)
            p.drawText(QRectF(W - 80, cy - frame_r + 12 + i * 14, 72, 12),
                       Qt.AlignmentFlag.AlignRight, txt.replace(".", "·"))

        self._paint_orb_face(p, cx, cy, fw, compact=False)
        self._paint_orb_particles(p)

        # status text
        sy = cy + fw * 0.40
        if self.state == "SLEEP":
            sym = "◌" if self._blink else "○"
            txt, col = f"{sym}  STANDBY", qcol(C.TEXT_DIM)
        elif self.muted:
            txt, col = "⊘  COMMS OFF",     qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "◉  TRANSMITTING",  qcol(C.ARC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  ANALYSING",   qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  EXECUTING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  RECEIVING",  qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(_hud_font(11, True))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform (segmented HUD bars)
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C, 160)
            elif self.speaking:
                hgt = random.randint(3, 22)
                cl  = qcol(C.ARC if hgt > 14 else C.PRI_DIM)
            else:
                hgt = int(3 + 2 * math.sin(self._tick * 0.09 + i * 0.6))
                cl  = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 22 - hgt, bw - 2, hgt), cl)
            if hgt > 4 and not self.muted:
                p.fillRect(QRectF(wx0 + i * bw, wy + 22 - hgt, bw - 2, 1), qcol(C.GLOW, 90))

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(38)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        rect = QRectF(1, 1, W - 2, H - 2)

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER_A), 1))
        p.drawRect(rect)
        _draw_hud_corners(p, rect, qcol(C.PRI_DIM, 140), length=8, pen_w=1)

        bar_h   = 5
        bar_y   = H - bar_h - 6
        bar_w   = W - 14
        bar_x   = 7
        segs    = 14
        seg_w   = bar_w / segs
        filled  = int(segs * self._value / 100)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ARC)
        else:
            bar_col = qcol(self._color)

        for i in range(segs):
            sx = bar_x + i * seg_w + 1
            sw = seg_w - 2
            if i < filled:
                p.setBrush(QBrush(bar_col))
                p.setPen(QPen(qcol(C.GLOW, 60), 1))
            else:
                p.setBrush(QBrush(qcol(C.BAR_BG)))
                p.setPen(QPen(qcol(C.BORDER, 80), 1))
            p.drawRect(QRectF(sx, bar_y, sw, bar_h))

        p.setFont(_hud_font(7, True))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 4, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"▸ {self._label}")

        p.setFont(_hud_font(9, True))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 3, W - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self._text)

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER_A};
                border-left: 2px solid {C.PRI_DIM};
                border-radius: 2px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        tl = text.lower()
        if   tl.startswith("you:"):    tag = "you"
        elif tl.startswith("emily:"):  tag = "ai"
        elif tl.startswith("file:"):   tag = "file"
        elif "err" in tl:              tag = "err"
        else:                          tag = "sys"

        cur = self.textCursor()
        fmt = cur.charFormat()
        col = {
            "you":  qcol(C.WHITE),
            "ai":   qcol(C.GLOW),
            "err":  qcol(C.RED),
            "file": qcol(C.GREEN),
            "sys":  qcol(C.ARC),
        }.get(tag, qcol(C.TEXT))
        fmt.setForeground(QBrush(col))
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(text + "\n", fmt)
        self.setTextCursor(cur)
        self.ensureCursorVisible()


class ThinkingStreamWidget(QTextEdit):
    """Live model reasoning / thought summaries (streaming)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 7))
        self.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.setPlaceholderText("Neural trace idle…")
        self.setMinimumHeight(72)
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER_A};
                border-left: 2px solid {C.ARC};
                border-radius: 2px;
                padding: 5px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 6px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 3px;
                min-height: 16px;
            }}
        """)

    def append_chunk(self, text: str) -> None:
        if not text:
            return
        cur = self.textCursor()
        fmt = cur.charFormat()
        fmt.setForeground(QBrush(qcol(C.GLOW)))
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(text, fmt)
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def append_system_line(self, text: str) -> None:
        if not text:
            return
        cur = self.textCursor()
        fmt = cur.charFormat()
        fmt.setForeground(QBrush(qcol(C.TEXT_MED)))
        cur.movePosition(cur.MoveOperation.End)
        if self.toPlainText() and not self.toPlainText().endswith("\n"):
            cur.insertText("\n", fmt)
        cur.insertText(text.rstrip() + "\n", fmt)
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def end_turn(self) -> None:
        if not self.toPlainText().strip():
            return
        cur = self.textCursor()
        fmt = cur.charFormat()
        fmt.setForeground(QBrush(qcol(C.BORDER_B)))
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText("\n· · ·\n", fmt)
        self.setTextCursor(cur)
        self.ensureCursorVisible()

    def clear_stream(self) -> None:
        self.clear()


_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for Emily", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001018" if z._drag_over else ("#000810" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 2, 2)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 2, 2)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · Video · Audio · PDF · Docs · Code · Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class MainWindow(QMainWindow):
    _log_sig          = pyqtSignal(str)
    _state_sig        = pyqtSignal(str)
    _voice_ready_sig  = pyqtSignal(bool)
    _think_append_sig = pyqtSignal(str)
    _think_line_sig   = pyqtSignal(str)
    _think_end_sig    = pyqtSignal()
    _think_clear_sig  = pyqtSignal()

    def __init__(self, face_path: str):
        super().__init__()
        self.setWindowTitle("E.M.I.L.Y. — F.R.I.D.A.Y. HUD")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command  = None
        self.on_stop          = None
        self._wake_greeting_handler = None
        self._muted           = True
        self._voice_ready     = False
        self._mic_available   = False
        self._muted_for_sleep = False
        self._sleep_mode      = False
        self._current_file: str | None = None
        self._compact_mode    = False
        self._floating = FloatingOrbWindow(face_path, on_restore=self._exit_compact_mode)
        self._floating.hide()

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        self.hud = HudCanvas(face_path)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        body.addWidget(self.hud, stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._voice_ready_sig.connect(self.set_voice_ready)
        self._think_append_sig.connect(self._thinking.append_chunk)
        self._think_line_sig.connect(self._thinking.append_system_line)
        self._think_end_sig.connect(self._thinking.end_turn)
        self._think_clear_sig.connect(self._thinking.clear_stream)

        self._ready = True
        self.hud.muted = True
        self._style_mute_btn()
        self._apply_state("THINKING")
        self._log.append_log("SYS: Loading voice stack... (watch console for download progress)")

        sc_settings = QShortcut(QKeySequence("Ctrl+,"), self)
        sc_settings.activated.connect(self._open_settings)

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        sc_compact = QShortcut(QKeySequence("Ctrl+M"), self)
        sc_compact.activated.connect(self._enter_compact_mode)

    def _enter_compact_mode(self) -> None:
        if self._compact_mode:
            return
        self._compact_mode = True
        if self.isMinimized():
            self.showNormal()
        self.hide()
        self._floating.set_muted(self._muted)
        self._floating.set_speaking(self.hud.speaking)
        self._floating.show()
        self._floating.raise_()

    def _exit_compact_mode(self) -> None:
        if not self._compact_mode:
            return
        self._compact_mode = False
        self._floating.hide()
        self.show()
        self.raise_()
        self.activateWindow()

    def changeEvent(self, event) -> None:
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and not self._compact_mode
        ):
            QTimer.singleShot(0, self._enter_compact_mode)
        super().changeEvent(event)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event):
        if hasattr(self, "camera"):
            self.camera.stop()
        if hasattr(self, "_floating"):
            self._floating.close()
        super().closeEvent(event)

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net*1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        try:
            boot_t  = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(58)
        w.setStyleSheet(
            f"background: qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            f"stop:0 {C.DARK}, stop:1 {C.BG});"
            f"border-bottom: 1px solid {C.BORDER_B};"
        )
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 16, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(_hud_font(8))
            l.setStyleSheet(
                f"color: {color}; background: {C.PANEL2};"
                f"border: 1px solid {C.BORDER_A}; padding: 2px 6px;"
            )
            return l

        left_col = QVBoxLayout(); left_col.setSpacing(1)
        left_col.addWidget(_badge("HOLO-LINK // ACTIVE", C.GREEN))
        left_col.addWidget(_badge("E.M.I.L.Y. OS // v3.1", C.PRI_DIM))
        lay.addLayout(left_col)
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        title = QLabel("E.M.I.L.Y.")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(_hud_font(18, True))
        title.setStyleSheet(f"color: {C.GLOW}; background: transparent; letter-spacing: 2px;")
        mid.addWidget(title)
        sub = QLabel("Female Replacement Intelligent Digital Assistant Youth")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(_hud_font(6))
        sub.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(sub)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(_hud_font(15, True))
        self._clock_lbl.setStyleSheet(f"color: {C.ARC}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(_hud_font(7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        settings_btn = QPushButton("⚙")
        settings_btn.setFixedSize(28, 28)
        settings_btn.setToolTip("Neural core settings (Ctrl+,)")
        settings_btn.setStyleSheet(f"color: {C.PRI}; background: {C.PANEL2}; border: 1px solid {C.BORDER_A};")
        settings_btn.clicked.connect(self._open_settings)
        right_col.addWidget(settings_btn, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 10, 8, 10)
        lay.setSpacing(6)

        hdr = QLabel("◈ SUIT TELEMETRY")
        hdr.setFont(_hud_font(7, True))
        hdr.setStyleSheet(f"color: {C.GLOW}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER_A}; padding-bottom: 4px;")
        lay.addWidget(hdr)
        lay.addSpacing(2)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)

        for bar in [self._bar_cpu, self._bar_mem, self._bar_net]:
            lay.addWidget(bar)

        self._stop_btn = QPushButton("◼  STOP")
        self._stop_btn.setFixedHeight(44)
        self._stop_btn.setFont(_hud_font(9, True))
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setStyleSheet(f"""
            QPushButton {{
                background: #180008;
                color: {C.RED};
                border: 2px solid {C.RED};
                border-radius: 2px;
            }}
            QPushButton:hover {{
                background: {C.RED};
                color: {C.WHITE};
            }}
            QPushButton:pressed {{
                background: #660018;
                color: {C.MUTED_C};
            }}
        """)
        self._stop_btn.clicked.connect(self._on_stop)
        lay.addWidget(self._stop_btn)

        lay.addSpacing(4)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: {C.PANEL2}; border: 1px solid {C.BORDER_A}; border-radius: 2px;"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent; border: none;")
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Courier New", 8))
        self._proc_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(_OS, _OS.upper())
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Courier New", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addSpacing(6)

        self.camera = CameraFeedWidget()
        lay.addWidget(self.camera, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._sleep_tmr = QTimer(self)
        self._sleep_tmr.timeout.connect(self._check_sleep_mode)
        self._sleep_tmr.start(5000)

        self._cv_detect_lbl = QLabel("CV: scanning…")
        self._cv_detect_lbl.setFont(QFont("Courier New", 6))
        self._cv_detect_lbl.setWordWrap(True)
        self._cv_detect_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._cv_detect_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera.detections_updated.connect(self._cv_detect_lbl.setText)
        lay.addWidget(self._cv_detect_lbl)

        lay.addSpacing(6)

        think_hdr = QLabel("◈ NEURAL TRACE")
        think_hdr.setFont(_hud_font(7, True))
        think_hdr.setStyleSheet(
            f"color: {C.ARC}; background: transparent; "
            f"border-bottom: 1px solid {C.BORDER_A}; padding-bottom: 3px;"
        )
        lay.addWidget(think_hdr)

        self._thinking = ThinkingStreamWidget()
        lay.addWidget(self._thinking, stretch=1)

        for txt, col in [
            ("ARC REACTOR\nONLINE",   C.ARC),
            ("HOLO LINK\nSECURE",     C.GREEN),
            ("PROTOCOL\nMARK VII",    C.TEXT_DIM),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(_hud_font(7, True))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: {C.PANEL2};"
                f"border: 1px solid {C.BORDER_A}; border-radius: 2px; padding: 4px;"
            )
            lay.addWidget(lbl)

        return w
    def _on_stop(self):
        self._log.append_log("SYS: Stop requested.")
        if self.on_stop:
            try:
                self.on_stop()
            except Exception as e:
                self._log.append_log(f"SYS: Stop failed — {e}")

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"background: {C.DARK}; border-left: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        def _sec(txt):
            l = QLabel(f"◈ {txt}")
            l.setFont(_hud_font(7, True))
            l.setStyleSheet(f"color: {C.GLOW}; background: transparent;")
            return l

        lay.addWidget(_sec("MISSION LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_sec("PAYLOAD UPLOAD"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded — drop or click above to upload")
        self._file_hint.setFont(QFont("Courier New", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("VOICE CHANNEL"))
        lay.addLayout(self._build_input_row())

        self._mute_btn = QPushButton("◉  VOICE CHANNEL ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        fs_btn = QPushButton("⛶  FULLSCREEN  [F11]")
        fs_btn.setFixedHeight(26)
        fs_btn.setFont(QFont("Courier New", 7))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER_A}; border-radius: 2px;
            }}
            QPushButton:hover {{
                color: {C.GLOW}; border: 1px solid {C.BORDER_B};
            }}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Courier New", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.BAR_BG}; color: {C.WHITE};
                border: 1px solid {C.BORDER_A}; border-radius: 2px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.GLOW}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.ARC};
                border: 1px solid {C.ARC}; border-radius: 2px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; color: {C.GLOW}; border: 1px solid {C.GLOW}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w); lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            l = QLabel(txt); l.setFont(QFont("Courier New", 7))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_fl("[F4] Comms  ·  [F11] Fullscreen  ·  [Ctrl+M] Compact"))
        lay.addStretch()
        lay.addWidget(_fl("E.M.I.L.Y.  ·  MARK XXXVIII HUD | 3.1 F", C.PRI_DIM))
        lay.addStretch()
        lay.addWidget(_fl("◈ CLASSIFIED", C.ARC))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        cat  = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(f"{icon}  {p.name}  ·  {size}  ·  Tell Emily what to do with it")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def _toggle_mute(self):
        if not self._voice_ready:
            self._log.append_log("SYS: Voice stack still loading...")
            return
        if not self._mic_available:
            self._log.append_log(
                "SYS: Mic unavailable — connect to the internet and restart to download voice models."
            )
            return
        if self._sleep_mode:
            self._log.append_log("SYS: Sleep mode — show your face to the camera to wake.")
            return
        self._apply_mute(not self._muted, user_initiated=True)

    def _apply_mute(self, muted: bool, *, user_initiated: bool = False) -> None:
        if self._muted == muted:
            return
        self._muted = muted
        self.hud.muted = muted
        if hasattr(self, "_floating"):
            self._floating.set_muted(muted)
        self._style_mute_btn()
        if user_initiated and muted:
            self._muted_for_sleep = False
        if self._sleep_mode and not muted:
            return
        if muted and not self._sleep_mode:
            if self._voice_ready:
                self._apply_state("MUTED")
            else:
                self._apply_state("THINKING")
            if user_initiated:
                self._log.append_log("SYS: Microphone muted.")
        elif not self._sleep_mode and self._voice_ready:
            self._apply_state("LISTENING")
            if user_initiated:
                self._log.append_log("SYS: Microphone active.")

    def set_voice_ready(self, enable_mic: bool = True) -> None:
        self._voice_ready = True
        self._mic_available = enable_mic
        if self._sleep_mode:
            return
        if enable_mic:
            self._apply_mute(False)
            self._apply_state("LISTENING")
            self._log.append_log("SYS: E.M.I.L.Y. online.")
        else:
            self._apply_state("THINKING")
            self._log.append_log("SYS: E.M.I.L.Y. online (text-only — mic needs internet to download Whisper).")

    def _check_sleep_mode(self) -> None:
        if not _sleep_mode_enabled() or not self.camera._detector:
            return

        if self.camera.is_face_visible():
            if self._sleep_mode:
                self._wake_from_sleep()
            return

        timeout = _sleep_face_timeout_sec()
        if self.camera.get_seconds_without_face() >= timeout and not self._sleep_mode:
            self._enter_sleep_mode()

    def _enter_sleep_mode(self) -> None:
        if self._sleep_mode:
            return
        self._sleep_mode = True
        mins = _sleep_face_timeout_sec() // 60
        self._log.append_log(f"SYS: Sleep mode — no face for {mins} min. Mic muted.")
        if not self._muted:
            self._muted_for_sleep = True
            self._apply_mute(True)
        self._apply_state("SLEEP")
        self.hud.muted = True
        self._style_mute_btn()

    def set_wake_greeting_handler(self, handler) -> None:
        """Callable() — plays wake greeting (wired from main.py)."""
        self._wake_greeting_handler = handler

    def _wake_from_sleep(self) -> None:
        if not self._sleep_mode:
            return
        self._sleep_mode = False
        self._log.append_log("SYS: Face detected — waking up.")
        unmute_after = self._muted_for_sleep
        self._muted_for_sleep = False
        self._apply_state("LISTENING")
        threading.Thread(
            target=self._run_wake_greeting,
            args=(unmute_after,),
            daemon=True,
            name="WakeGreeting",
        ).start()

    def _run_wake_greeting(self, unmute_after: bool) -> None:
        try:
            if self._wake_greeting_handler:
                self._wake_greeting_handler()
            else:
                self._play_wake_greeting_edge()
            self._log_sig.emit("SYS: Wake greeting played.")
        except Exception as e:
            msg = f"SYS: Wake greeting failed — {e}"
            print(f"[Sleep] {msg}")
            self._log_sig.emit(msg)
        finally:
            if unmute_after:
                QTimer.singleShot(0, lambda: self._finish_wake_unmute())

    def _finish_wake_unmute(self) -> None:
        if not self._sleep_mode:
            self._apply_mute(False)

    @staticmethod
    def _play_wake_greeting_edge() -> None:
        from core.tts import speak_sync

        speak_sync(random.choice(_WAKE_GREETINGS))

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("⊘  VOICE CHANNEL OFF")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #140006; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 2px;
                }}
            """)
        else:
            self._mute_btn.setText("◉  VOICE CHANNEL ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #141008; color: {C.ARC};
                    border: 1px solid {C.ARC}; border-radius: 2px;
                }}
                QPushButton:hover {{ background: #1a1808; color: {C.GLOW}; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        if self._sleep_mode and state not in ("SLEEP", "SPEAKING"):
            state = "SLEEP"
        self.hud.state = state
        speaking = state == "SPEAKING"
        self.hud.speaking = speaking
        if hasattr(self, "_floating"):
            self._floating.set_speaking(speaking)
            self._floating.set_muted(self._muted)

    def _open_settings(self):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self,
            "Settings",
            "Re-run terminal setup:\n\n  python main.py --setup",
        )
        self._log.append_log("SYS: Re-run setup: python main.py --setup")

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class EmilyUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if self._win._sleep_mode and v is False:
            return
        if v != self._win._muted:
            if v:
                self._win._apply_mute(True, user_initiated=True)
            else:
                self._win._apply_mute(False, user_initiated=True)

    @property
    def current_file(self) -> str | None:
        return self._win._drop_zone.current_file()

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_stop(self):
        return self._win.on_stop

    @on_stop.setter
    def on_stop(self, cb):
        self._win.on_stop = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def set_voice_ready(self, enable_mic: bool = True) -> None:
        """Thread-safe: schedules voice-channel activation on the Qt main thread."""
        self._win._voice_ready_sig.emit(enable_mic)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def append_thinking(self, text: str) -> None:
        self._win._think_append_sig.emit(text)

    def append_thinking_line(self, text: str) -> None:
        self._win._think_line_sig.emit(text)

    def end_thinking_turn(self) -> None:
        self._win._think_end_sig.emit()

    def clear_thinking(self) -> None:
        self._win._think_clear_sig.emit()

    def get_camera_detections(self) -> list[dict]:
        """Objects / people / faces currently visible in the webcam (local CV only)."""
        if hasattr(self._win, "camera"):
            return self._win.camera.get_detections()
        return []

    @property
    def sleep_mode(self) -> bool:
        return self._win._sleep_mode

    def wait_for_api_key(self):
        pass

    def wait_for_config(self):
        pass

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
