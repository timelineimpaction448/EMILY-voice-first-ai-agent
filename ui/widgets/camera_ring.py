"""Circular camera viewport — webcam masked to a graduated bezel ring.

Capture/detection/sleep-presence logic is ported from the legacy CameraFeedWidget
(unchanged behavior): same local CV face detection, face-presence tracking, and
get_snapshot_jpeg() used by the vision tools. Rendering is the new circular HUD.
"""

from __future__ import annotations

import math
import threading
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QImage, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ui.theme import C, draw_glow_arc, draw_glow_ellipse, hud_font, qcol
from ui.widgets.base import anim_clock

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False


def _camera_index() -> int:
    from core.config import get_camera_index
    return get_camera_index()


def _cv_enabled() -> bool:
    try:
        from core.config import get_camera_cv_enabled
        return get_camera_cv_enabled()
    except Exception:
        return True


class CircularViewport(QWidget):
    detections_updated = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None, diameter: int = 240):
        super().__init__(parent)
        self._d = diameter
        self.setMinimumSize(160, 160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # translucent so the backdrop bloom/particles read around the circle
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._frame_rgb = None
        self._status = "starting"
        self._det_lock = threading.Lock()
        self._detections: list = []
        self._detector = None
        self._presence_lock = threading.Lock()
        self._started_mono = time.monotonic()
        self._last_face_mono: float | None = None
        self._face_visible_now = False
        self._countdown: float | None = None  # 0..1 remaining, None = hidden

        if _CV2 and _cv_enabled():
            try:
                from vision.local_detector import LocalVisionEngine
                self._detector = LocalVisionEngine(
                    detect_objects=False, detect_people=False, detect_faces=True,
                )
            except Exception as e:
                print(f"[Camera] Local vision init failed: {e}")

        anim_clock().tick.connect(self.update)
        self.start()

    # ----- public API (parity with legacy CameraFeedWidget) -----
    def start(self) -> None:
        if self._running or not _CV2:
            if not _CV2:
                self._status = "no_cv2"
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

    def set_countdown(self, remaining_frac: float | None) -> None:
        self._countdown = remaining_frac

    def get_snapshot_jpeg(self) -> tuple[bytes, str] | None:
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

    # ----- capture thread -----
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
        preferred = _camera_index()
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
                    if self._detector and (int(time.monotonic() * 30) % detect_every == 0):
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

    # ----- paint -----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        d = min(W, H) - 6
        cx, cy = W / 2, H / 2
        r = d / 2
        frame_i = anim_clock().frame

        with self._lock:
            frame = self._frame_rgb
        with self._det_lock:
            dets = list(self._detections)

        # soft bloom halo behind the bezel (depth around the circle)
        live = self._status == "live"
        halo_col = C.GREEN if live else C.PRI
        halo = QRadialGradient(cx, cy, r * 1.35)
        halo.setColorAt(0.0, qcol(halo_col, 0))
        halo.setColorAt(0.62, qcol(halo_col, 0))
        halo.setColorAt(0.80, qcol(halo_col, 70))
        halo.setColorAt(0.92, qcol(halo_col, 30))
        halo.setColorAt(1.0, qcol(halo_col, 0))
        p.setBrush(QBrush(halo))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), r * 1.35, r * 1.35)

        # inner image disc
        disc = QRectF(cx - r + 8, cy - r + 8, (r - 8) * 2, (r - 8) * 2)
        img_r = (r - 8)
        clip = QPainterPath()
        clip.addEllipse(disc)
        p.save()
        p.setClipPath(clip)
        p.fillRect(disc, qcol("#000a10", 235))
        has_frame = False
        if frame is not None and _CV2:
            try:
                h, w, ch = frame.shape
                qimg = QImage(frame.data, w, h, ch * w, QImage.Format.Format_RGB888).copy()
                pix = QPixmap.fromImage(qimg).scaled(
                    int(disc.width()), int(disc.height()),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                px = int(disc.x() + (disc.width() - pix.width()) / 2)
                py = int(disc.y() + (disc.height() - pix.height()) / 2)
                p.drawPixmap(px, py, pix)
                # detection boxes (clipped to disc)
                if dets and pix.width() > 0:
                    scale = max(disc.width() / w, disc.height() / h)
                    for det in dets:
                        x1 = px + det.x1 * scale
                        y1 = py + det.y1 * scale
                        x2 = px + det.x2 * scale
                        y2 = py + det.y2 * scale
                        col = qcol(C.ACC, 220) if det.kind == "face" else qcol(C.GREEN, 200)
                        p.setPen(QPen(col, 1.5))
                        p.setBrush(Qt.BrushStyle.NoBrush)
                        p.drawRect(QRectF(x1, y1, x2 - x1, y2 - y1))
                has_frame = True
            except Exception:
                has_frame = False
        # scan sweep line
        scan_y = disc.y() + (frame_i * 2.2 % disc.height())
        p.setPen(QPen(qcol(C.PRI, 50), 1))
        p.drawLine(QPointF(disc.x(), scan_y), QPointF(disc.right(), scan_y))
        p.restore()

        if not has_frame:
            p.setPen(QPen(qcol(C.TEXT_DIM), 1))
            msg = {"starting": "LINKING CAM…", "offline": "NO SIGNAL",
                   "no_cv2": "CV2 MISSING"}.get(self._status, "NO SIGNAL")
            p.setFont(hud_font(8, True))
            p.drawText(disc, Qt.AlignmentFlag.AlignCenter, msg)

        # double bezel: glowing outer ring + inner ring + rotating dash ring between
        live = self._status == "live"
        outer_col = C.GREEN if live else C.PRI_DIM
        draw_glow_ellipse(p, cx, cy, r, r, outer_col, width=2.0, glow=2, alpha=230)
        p.setPen(QPen(qcol(C.BORDER_B, 150), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r - 7, r - 7)
        # rotating dash ring (slow)
        dash_rect = QRectF(cx - (r - 3.5), cy - (r - 3.5), (r - 3.5) * 2, (r - 3.5) * 2)
        base = (frame_i * 0.5) % 360
        p.setPen(QPen(qcol(outer_col, 170), 2))
        for k in range(24):
            p.drawArc(dash_rect, int((base + k * 15) * 16), int(5 * 16))
        # degree ticks
        p.setPen(QPen(qcol(C.BORDER_B, 150), 1))
        for deg in range(0, 360, 10):
            a = math.radians(deg)
            inn = r - (9 if deg % 30 == 0 else 5)
            p.drawLine(QPointF(cx + inn * math.cos(a), cy + inn * math.sin(a)),
                       QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))
        # bracket arcs at compass points
        for deg in (0, 90, 180, 270):
            draw_glow_arc(p, QRectF(cx - r, cy - r, r * 2, r * 2),
                          int((deg - 10) * 16), int(20 * 16), outer_col,
                          width=2.5, glow=2, alpha=200)
        # NSEW numerals
        p.setFont(hud_font(6, True))
        p.setPen(QPen(qcol(C.TEXT_MED, 180), 1))
        for deg, lab in ((90, "N"), (0, "E"), (270, "S"), (180, "W")):
            a = math.radians(deg)
            lx = cx + (r - 16) * math.cos(a)
            ly = cy - (r - 16) * math.sin(a)
            p.drawText(QRectF(lx - 6, ly - 6, 12, 12), Qt.AlignmentFlag.AlignCenter, lab)

        # face arc-markers on the bezel (angular position of each face)
        if frame is not None:
            with self._lock:
                fr = self._frame_rgb
            fw = fr.shape[1] if fr is not None else 1
            for det in dets:
                if det.kind != "face":
                    continue
                fcx = (det.x1 + det.x2) / 2.0
                ang = math.radians(-90 + (fcx / max(1, fw)) * 180 - 90)
                mx = cx + r * math.cos(ang)
                my = cy + r * math.sin(ang)
                p.setBrush(QBrush(qcol(C.ACC)))
                p.setPen(QPen(qcol(C.ACC2), 1))
                p.drawEllipse(QPointF(mx, my), 3.5, 3.5)

        # sleep countdown arc (depleting)
        if self._countdown is not None:
            p.setPen(QPen(qcol(C.MUTED_C, 230), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(cx - r + 1, cy - r + 1, (r - 1) * 2, (r - 1) * 2),
                      90 * 16, -int(self._countdown * 360) * 16)

        # label + REC
        p.setFont(hud_font(7, True))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(cx - r, cy - r - 2, r * 2, 14), Qt.AlignmentFlag.AlignHCenter, "◈ OPTICS")
        if live:
            blink = (frame_i // 15) % 2 == 0
            p.setBrush(QBrush(qcol(C.RED if blink else "#661122")))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(cx + r * 0.55, cy - r * 0.78), 4, 4)
        # micro readout under the bezel (real values)
        n_tgt = len(dets)
        readout = f"{'REC ·' if live else 'STBY ·'} {n_tgt} TGT · {self._status.upper()}"
        p.setFont(hud_font(6, True))
        p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
        p.drawText(QRectF(cx - r, cy + r - 2, r * 2, 12), Qt.AlignmentFlag.AlignHCenter, readout)
