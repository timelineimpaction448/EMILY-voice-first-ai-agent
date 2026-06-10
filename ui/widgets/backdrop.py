"""Animated cockpit backdrop — the living machine wall behind the panels.

Static layer (cached to a pixmap, rebuilt on resize):
    radial vignette → faint hex clusters → circuit traces with node dots
Dynamic layer (per AnimClock tick, drawn over the cache):
    traveling pulses along the traces → drifting dust motes → vertical scan band

`BackdropContainer` is the window's central widget: it hosts the root layout, so
all instrument widgets render on top. Give those children transparent backgrounds
(layout.py) and the circuitry glows through the gutters.
"""

from __future__ import annotations

import math
import random

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import QWidget

from ui.theme import C, draw_glow_line, qcol
from ui.widgets.base import anim_clock


def _point_along(poly, cum, dist):
    """Point at arc-length `dist` along polyline `poly` (cum = cumulative lengths)."""
    total = cum[-1]
    if total <= 0:
        return poly[0]
    dist = dist % total
    # binary-ish linear scan (polylines are short)
    for i in range(1, len(cum)):
        if cum[i] >= dist:
            seg = cum[i] - cum[i - 1]
            t = 0.0 if seg <= 0 else (dist - cum[i - 1]) / seg
            a, b = poly[i - 1], poly[i]
            return QPointF(a.x() + (b.x() - a.x()) * t, a.y() + (b.y() - a.y()) * t)
    return poly[-1]


class BackdropContainer(QWidget):
    N_TRACES = 13
    N_PULSES = 8
    N_DUST = 55
    N_MOTES = 6        # large soft drifting bloom motes
    BAND_PERIOD = 270  # frames (~9s @30fps)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {C.BG};")
        self._cache: QPixmap | None = None
        self._cache_size = (0, 0)
        self._traces: list[tuple[list, list]] = []   # (polyline, cumulative-lengths)
        self._pulses: list[dict] = []
        self._dust: list[list] = []
        self._motes: list[list] = []
        self._frame = 0
        self._reduced = False
        self._disabled = False
        anim_clock().tick.connect(self._tick)

    def set_reduced_motion(self, v: bool):
        self._reduced = bool(v)

    def set_disabled(self, v: bool):
        """'off' FX mode — flat background, no circuitry/motion."""
        self._disabled = bool(v)
        self.update()

    # ---------------- seeding ----------------
    def _seed(self, w: int, h: int):
        rng = random.Random(w * 1313 + h)
        cx, cy = w * 0.47, h * 0.46
        self._traces = []
        for _ in range(self.N_TRACES):
            edge = rng.randint(0, 3)
            if edge == 0:      # left
                x, y = 0.0, rng.uniform(0.1, 0.9) * h
            elif edge == 1:    # right
                x, y = float(w), rng.uniform(0.1, 0.9) * h
            elif edge == 2:    # top
                x, y = rng.uniform(0.1, 0.9) * w, 0.0
            else:              # bottom
                x, y = rng.uniform(0.1, 0.9) * w, float(h)
            poly = [QPointF(x, y)]
            segs = rng.randint(2, 4)
            for s in range(segs):
                last = poly[-1]
                tx = last.x() + (cx - last.x()) * rng.uniform(0.35, 0.7)
                ty = last.y() + (cy - last.y()) * rng.uniform(0.35, 0.7)
                # snap to an axis-or-45° bend for the circuit look
                if rng.random() < 0.5:
                    poly.append(QPointF(tx, last.y()))
                    poly.append(QPointF(tx, ty))
                else:
                    poly.append(QPointF(last.x(), ty))
                    poly.append(QPointF(tx, ty))
            cum = [0.0]
            for i in range(1, len(poly)):
                d = math.hypot(poly[i].x() - poly[i - 1].x(), poly[i].y() - poly[i - 1].y())
                cum.append(cum[-1] + d)
            if cum[-1] > 40:
                self._traces.append((poly, cum))

        self._pulses = []
        for _ in range(self.N_PULSES):
            if not self._traces:
                break
            ti = rng.randrange(len(self._traces))
            self._pulses.append({
                "trace": ti,
                "d": rng.uniform(0, self._traces[ti][1][-1]),
                "speed": rng.uniform(1.6, 3.4),
                "col": rng.choice([C.PRI, C.GLOW, C.ARC]),
            })

        self._dust = []
        for _ in range(self.N_DUST):
            self._dust.append([
                rng.uniform(0, w), rng.uniform(0, h),
                rng.uniform(-0.22, 0.22), rng.uniform(-0.16, 0.16),
                rng.uniform(0, math.tau),
                rng.uniform(0.9, 2.0),  # size
            ])

        # large soft bloom motes that slowly drift (depth + life)
        self._motes = []
        for _ in range(self.N_MOTES):
            self._motes.append([
                rng.uniform(0, w), rng.uniform(0, h),
                rng.uniform(-0.10, 0.10), rng.uniform(-0.08, 0.08),
                rng.uniform(0, math.tau),
                rng.uniform(34, 70),  # radius
                rng.choice([C.PRI, C.GLOW, "#1a6a8f"]),
            ])

    # ---------------- static cache ----------------
    def _build_cache(self, w: int, h: int) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(QColor(C.BG))
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # vignette glows — strong blooms behind the reactor (centre) and camera
        for (gx, gy, gr, gc, ga) in (
            (w * 0.52, h * 0.40, max(w, h) * 0.50, "#0a3a4a", 210),   # reactor bloom
            (w * 0.52, h * 0.40, max(w, h) * 0.26, "#0e4a5e", 150),   # reactor core
            (w * 0.31, h * 0.37, max(w, h) * 0.30, "#073240", 175),   # camera bloom
            (w * 0.42, h * 0.82, max(w, h) * 0.30, "#04202c", 150),   # radar
            (w * 0.86, h * 0.30, max(w, h) * 0.26, "#06222c", 120),
            (w * 0.10, h * 0.70, max(w, h) * 0.24, "#06202a", 110),
        ):
            grad = QRadialGradient(gx, gy, gr)
            grad.setColorAt(0.0, qcol(gc, ga))
            grad.setColorAt(0.6, qcol(gc, ga // 3))
            grad.setColorAt(1.0, qcol(gc, 0))
            p.fillRect(QRectF(0, 0, w, h), QBrush(grad))

        # hex clusters (edge/gutter biased)
        rng = random.Random(w * 31 + h * 17)
        for _ in range(7):
            side = rng.random()
            hx = (rng.uniform(0, w * 0.22) if side < 0.5 else rng.uniform(w * 0.78, w))
            hy = rng.uniform(0.05, 0.95) * h
            self._draw_hex_cluster(p, hx, hy, rng)

        # circuit traces (faint base + node dots)
        for poly, _cum in self._traces:
            path = QPainterPath()
            path.moveTo(poly[0])
            for pt in poly[1:]:
                path.lineTo(pt)
            p.setPen(QPen(qcol(C.PRI_DIM, 42), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
            p.setBrush(QBrush(qcol(C.PRI_DIM, 70)))
            p.setPen(Qt.PenStyle.NoPen)
            for pt in poly[::2]:
                p.drawEllipse(pt, 1.6, 1.6)
        p.end()
        return pm

    def _draw_hex_cluster(self, p: QPainter, cx: float, cy: float, rng):
        p.setPen(QPen(qcol(C.PRI_GHO, 60), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        r = rng.uniform(9, 15)
        for _ in range(rng.randint(3, 8)):
            ox = rng.uniform(-3, 3) * r
            oy = rng.uniform(-3, 3) * r
            hx, hy = cx + ox, cy + oy
            path = QPainterPath()
            for i in range(6):
                ang = math.radians(60 * i - 30)
                px = hx + r * 0.5 * math.cos(ang)
                py = hy + r * 0.5 * math.sin(ang)
                path.moveTo(px, py) if i == 0 else path.lineTo(px, py)
            path.closeSubpath()
            p.drawPath(path)

    # ---------------- dynamic ----------------
    def resizeEvent(self, event):
        # keep any overlay children (scanlines, boot) covering the full area + on top
        for child in self.children():
            cover = getattr(child, "cover", None)
            if callable(cover):
                cover()
        super().resizeEvent(event)

    def _tick(self):
        self._frame += 1
        if self._reduced or self._disabled:
            return
        for pulse in self._pulses:
            pulse["d"] += pulse["speed"]
        w, h = max(1, self.width()), max(1, self.height())
        for dot in self._dust:
            dot[0] = (dot[0] + dot[2]) % w
            dot[1] = (dot[1] + dot[3]) % h
            dot[4] += 0.04
        for m in self._motes:
            m[0] = (m[0] + m[2]) % w
            m[1] = (m[1] + m[3]) % h
            m[4] += 0.012
        self.update()

    def paintEvent(self, _):
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        if self._disabled:
            QPainter(self).fillRect(self.rect(), qcol(C.BG))
            return
        if self._cache is None or self._cache_size != (w, h):
            self._seed(w, h)
            self._cache = self._build_cache(w, h)
            self._cache_size = (w, h)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self._cache)
        if self._reduced:
            return

        # large soft bloom motes (drawn first, behind everything)
        p.setPen(Qt.PenStyle.NoPen)
        for m in self._motes:
            tw = 0.5 + 0.5 * math.sin(m[4])
            rad = m[5]
            col = m[6]
            grad = QRadialGradient(m[0], m[1], rad)
            grad.setColorAt(0.0, qcol(col, int(26 + 26 * tw)))
            grad.setColorAt(1.0, qcol(col, 0))
            p.setBrush(QBrush(grad))
            p.drawEllipse(QPointF(m[0], m[1]), rad, rad)

        # traveling pulses
        for pulse in self._pulses:
            poly, cum = self._traces[pulse["trace"]]
            pos = _point_along(poly, cum, pulse["d"])
            tail = _point_along(poly, cum, pulse["d"] - 14)
            draw_glow_line(p, tail, pos, pulse["col"], width=1.4, glow=2, alpha=160)
            p.setBrush(QBrush(qcol(pulse["col"], 230)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(pos, 2.4, 2.4)
            p.setBrush(QBrush(qcol(C.GLOW, 70)))
            p.drawEllipse(pos, 4.2, 4.2)

        # dust (with soft glow halo)
        p.setPen(Qt.PenStyle.NoPen)
        for dot in self._dust:
            tw = 0.5 + 0.5 * math.sin(dot[4])
            a = int(45 + 70 * tw)
            sz = dot[5] if len(dot) > 5 else 1.3
            p.setBrush(QBrush(qcol(C.GLOW, a // 4)))
            p.drawEllipse(QPointF(dot[0], dot[1]), sz * 2.2, sz * 2.2)
            p.setBrush(QBrush(qcol(C.PRI, a)))
            p.drawEllipse(QPointF(dot[0], dot[1]), sz, sz)

        # vertical scan band
        phase = (self._frame % self.BAND_PERIOD) / self.BAND_PERIOD
        by = phase * (h + 120) - 60
        band = QLinearGradient(0, by - 30, 0, by + 30)
        band.setColorAt(0.0, qcol(C.PRI, 0))
        band.setColorAt(0.5, qcol(C.PRI, 16))
        band.setColorAt(1.0, qcol(C.PRI, 0))
        p.fillRect(QRectF(0, by - 30, w, 60), QBrush(band))
