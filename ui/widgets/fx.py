"""Top-layer FX: scanline/armature overlay, boot sequence, live data ticker."""

from __future__ import annotations

import math
import random
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import QWidget

from ui.theme import (
    C, draw_glow_arc, draw_glow_line, hud_font, digital_font, qcol, serial_for,
)
from ui.widgets.base import anim_clock


def _cover(widget: QWidget) -> None:
    """Resize an overlay to fully cover its parent and float on top."""
    par = widget.parentWidget()
    if par is not None:
        widget.setGeometry(0, 0, par.width(), par.height())
        widget.raise_()


# ============================================================ scanline overlay

class ScanlineOverlay(QWidget):
    """Scanlines + sweeping band + corner armatures + soft flicker. Click-through."""

    SCAN_PERIOD = 190  # frames

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._cache: QPixmap | None = None
        self._cache_size = (0, 0)
        self._frame = 0
        self._reduced = False
        self._flicker = 1.0
        self._flicker_until = 0
        self._next_flicker = 120
        anim_clock().tick.connect(self._tick)

    def set_reduced_motion(self, v: bool):
        self._reduced = bool(v)

    def cover(self):
        _cover(self)

    def _tick(self):
        self._frame += 1
        if self._reduced:
            return
        # schedule occasional brief flicker dips (sub-3 Hz, gentle)
        if self._frame >= self._next_flicker:
            self._flicker_until = self._frame + random.randint(2, 4)
            self._next_flicker = self._frame + random.randint(150, 260)
        self._flicker = 0.84 if self._frame <= self._flicker_until else 1.0
        self.update()

    def _build_cache(self, w: int, h: int) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # scanlines
        p.setPen(QPen(qcol(C.SCAN, 11), 1))
        y = 0
        while y < h:
            p.drawLine(0, y, w, y)
            y += 3

        # corner armatures (large L brackets framing the view)
        m = 16
        arm = 64
        cap = 26
        for (ax, ay, sx, sy) in ((m, m, 1, 1), (w - m, m, -1, 1),
                                 (m, h - m, 1, -1), (w - m, h - m, -1, -1)):
            p.setPen(QPen(qcol(C.PRI_DIM, 150), 2))
            p.drawLine(QPointF(ax, ay), QPointF(ax + sx * arm, ay))
            p.drawLine(QPointF(ax, ay), QPointF(ax, ay + sy * arm))
            p.setPen(QPen(qcol(C.PRI, 90), 1))
            p.drawLine(QPointF(ax + sx * 6, ay + sy * 6), QPointF(ax + sx * (cap + 6), ay + sy * 6))
            p.drawLine(QPointF(ax + sx * 6, ay + sy * 6), QPointF(ax + sx * 6, ay + sy * (cap + 6)))
            # tick stack
            for k in range(4):
                p.drawLine(QPointF(ax + sx * (arm + 4 + k * 4), ay),
                           QPointF(ax + sx * (arm + 4 + k * 4), ay + sy * 6))
            p.setFont(hud_font(6, True))
            p.setPen(QPen(qcol(C.TEXT_DIM, 160), 1))
            tx = ax + sx * 10 if sx > 0 else ax - 44
            p.drawText(QRectF(tx, ay + sy * (arm - 14) if sy > 0 else ay - arm, 40, 10),
                       Qt.AlignmentFlag.AlignLeft, f"·{serial_for(str(ax)+str(ay))}")
        p.end()
        return pm

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        if self._cache is None or self._cache_size != (w, h):
            self._cache = self._build_cache(w, h)
            self._cache_size = (w, h)
        p = QPainter(self)
        p.setOpacity(self._flicker)
        p.drawPixmap(0, 0, self._cache)
        p.setOpacity(1.0)
        if self._reduced:
            return
        # sweeping bright band
        phase = (self._frame % self.SCAN_PERIOD) / self.SCAN_PERIOD
        by = phase * (h + 80) - 40
        band = QLinearGradient(0, by - 14, 0, by + 14)
        band.setColorAt(0.0, qcol(C.GLOW, 0))
        band.setColorAt(0.5, qcol(C.GLOW, 22))
        band.setColorAt(1.0, qcol(C.GLOW, 0))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(QRectF(0, by - 14, w, 28), QBrush(band))


# ============================================================ boot sequence

class BootOverlay(QWidget):
    """One-shot ~3s boot animation. Click to skip. Self-removes when done."""

    finished = pyqtSignal()

    def __init__(self, parent=None, readiness=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._readiness = readiness or (lambda: {})
        self._start = time.monotonic()
        self._done = False
        self._subsystems = [
            ("SERVICE BUS", "bus"),
            ("TELEMETRY", "metrics"),
            ("WEATHER LINK", "weather"),
            ("OPTICS", "camera"),
            ("NEURAL CORE", "voice"),
        ]
        anim_clock().tick.connect(self._tick)

    def cover(self):
        _cover(self)

    def _tick(self):
        if self._done:
            return
        if time.monotonic() - self._start >= 3.1:
            self._finish()
        else:
            self.update()

    def _finish(self):
        if self._done:
            return
        self._done = True
        self.finished.emit()
        self.hide()
        self.deleteLater()

    def mousePressEvent(self, _):
        self._finish()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        t = time.monotonic() - self._start
        cx, cy = w / 2, h * 0.42
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # fade out near the end
        fade = max(0.0, min(1.0, (3.1 - t) / 0.6))
        p.setOpacity(fade)
        p.fillRect(self.rect(), qcol(C.BG, 235))

        # expanding rings (0..0.9s)
        if t < 1.1:
            for k in range(3):
                rr = (t * 520) - k * 70
                if 0 < rr < max(w, h):
                    a = int(180 * (1 - rr / max(w, h)))
                    draw_glow_arc(p, QRectF(cx - rr, cy - rr, rr * 2, rr * 2),
                                  0, 360 * 16, C.PRI, width=1.5, glow=2, alpha=a)
            # crosshair sweep
            ang = t * 900
            p.setPen(QPen(qcol(C.GLOW, 160), 1))
            for d in (ang, ang + 90, ang + 180, ang + 270):
                a = math.radians(d)
                p.drawLine(QPointF(cx, cy),
                           QPointF(cx + 200 * math.cos(a), cy + 200 * math.sin(a)))

        # title type-on (0.4..1.8s)
        title = "E.M.I.L.Y  //  COCKPIT  OS  v2.1"
        if t > 0.4:
            shown = int(min(len(title), (t - 0.4) / 1.4 * len(title)))
            p.setFont(digital_font(20))
            p.setPen(QPen(qcol(C.GLOW), 1))
            txt = title[:shown] + ("▌" if int(t * 3) % 2 == 0 and shown < len(title) else "")
            p.drawText(QRectF(0, cy + 60, w, 30), Qt.AlignmentFlag.AlignHCenter, txt)

        # subsystem readiness lines (staggered from 0.8s)
        ready = {}
        try:
            ready = self._readiness() or {}
        except Exception:
            ready = {}
        p.setFont(hud_font(9, True))
        ly = cy + 110
        for i, (label, key) in enumerate(self._subsystems):
            appear = 0.8 + i * 0.32
            if t < appear:
                continue
            ok = bool(ready.get(key)) or (t > appear + 0.6)  # fall back to timed
            real = bool(ready.get(key))
            mark, col = ("▮▮▮ OK", C.GREEN) if ok else ("░░░ …", C.TEXT_DIM)
            if ok and not real:
                mark, col = "▮▮▮ OK", C.GREEN
            p.setPen(QPen(qcol(C.TEXT_MED), 1))
            p.drawText(QRectF(cx - 150, ly + i * 22, 180, 18),
                       Qt.AlignmentFlag.AlignLeft, f"› {label}")
            p.setPen(QPen(qcol(col), 1))
            p.drawText(QRectF(cx + 36, ly + i * 22, 120, 18),
                       Qt.AlignmentFlag.AlignLeft, mark)

        p.setFont(hud_font(6))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, h - 26, w, 14), Qt.AlignmentFlag.AlignHCenter, "click to skip")


# ============================================================ data ticker

class TickerStrip(QWidget):
    """Scrolling marquee of live hub data along the footer."""

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self._hub = hub
        self.setFixedHeight(22)
        self._offset = 0.0
        self._text = "INITIALISING TELEMETRY…"
        self._text_px = 0
        self._last_compose = 0.0
        self._reduced = False
        anim_clock().tick.connect(self._tick)

    def set_reduced_motion(self, v: bool):
        self._reduced = bool(v)

    def _tick(self):
        now = time.monotonic()
        if now - self._last_compose > 5.0:
            self._text = self._compose()
            self._last_compose = now
        if not self._reduced:
            self._offset -= 1.4
            self.update()

    def _compose(self) -> str:
        seg = []
        m = self._hub.metrics.last_good if self._hub else None
        if isinstance(m, dict):
            seg.append(f"CPU {m.get('cpu',0):.0f}%")
            seg.append(f"MEM {m.get('mem_used_gb',0):.1f}G")
            if m.get("gpu"):
                seg.append(f"GPU {m['gpu'].get('util',0):.0f}%")
            seg.append(f"PROC {m.get('proc_count',0)}")
            up = m.get("uptime_sec", 0)
            seg.append(f"UP {int(up//3600):02d}:{int((up%3600)//60):02d}")
        n = self._hub.network.last_good if self._hub else None
        if isinstance(n, dict) and n.get("latency_ms") is not None:
            seg.append(f"PING {n['latency_ms']:.0f}ms")
        wdata = self._hub.weather.last_good if self._hub else None
        if isinstance(wdata, dict) and wdata.get("temp") is not None:
            from ui.services.weather import wmo_info
            seg.append(f"{wdata['temp']:.0f}{wdata.get('temp_unit','°C')} {wmo_info(wdata.get('code'))[0].upper()}")
        iss = self._hub.iss.last_good if self._hub else None
        if isinstance(iss, dict) and iss.get("distance_km"):
            seg.append(f"ISS {iss['distance_km']:.0f}km")
        if not seg:
            return "AWAITING TELEMETRY…"
        return "      ◈      ".join(seg) + "      ◈      "

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(digital_font(9, bold=False))
        fm = p.fontMetrics()
        self._text_px = fm.horizontalAdvance(self._text)
        if self._text_px <= 0:
            return
        if self._offset < -self._text_px:
            self._offset += self._text_px
        x = self._offset
        p.setPen(QPen(qcol(C.TEXT_MED), 1))
        while x < w:
            p.drawText(QRectF(x, 0, self._text_px + 40, h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
            x += self._text_px
