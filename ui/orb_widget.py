"""Shared Emily orb animation — HUD center and compact floating widget."""

from __future__ import annotations

import io
import math
import random
import time

from PyQt6.QtCore import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QPainter, QPen, QPixmap, QRadialGradient,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

# HUD palette (subset — avoids importing ui.app circularly)
class _C:
    BG = "#000102"
    PRI = "#00d4ff"
    PRI_DIM = "#0088aa"
    PRI_GHO = "#001828"
    GLOW = "#4de8ff"
    ARC = "#ff9a00"
    ARC_CORE = "#ffcc44"
    MUTED_C = "#ff4466"


def _qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h)
    c.setAlpha(a)
    return c


def _hud_font(size: int, bold: bool = False) -> QFont:
    weight = QFont.Weight.Bold if bold else QFont.Weight.Normal
    return QFont("Courier New", size, weight)


class OrbAnimatorMixin:
    """Animation state + orb painting shared by HudCanvas and EmilyOrbWidget."""

    def _init_orb(self, face_path: str) -> None:
        self.muted = False
        self.speaking = False
        self._tick = 0
        self._scale = 1.0
        self._tgt_scale = 1.0
        self._halo = 55.0
        self._tgt_halo = 55.0
        self._last_t = time.time()
        self._scan = 0.0
        self._scan2 = 180.0
        self._rings = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._load_face(face_path)

    def _load_face(self, path: str) -> None:
        try:
            from PIL import Image, ImageDraw

            img = Image.open(path).convert("RGBA")
            sz = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step_orb(self) -> None:
        self._tick += 1
        now = time.time()
        if now - self._last_t > (0.12 if self.speaking else 0.5):
            if self.speaking:
                self._tgt_scale = random.uniform(1.06, 1.14)
                self._tgt_halo = random.uniform(145, 190)
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo = random.uniform(15, 28)
            else:
                self._tgt_scale = random.uniform(1.001, 1.008)
                self._tgt_halo = random.uniform(48, 68)
            self._last_t = now

        sp = 0.38 if self.speaking else 0.15
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo += (self._tgt_halo - self._halo) * sp

        speeds = [1.3, -0.9, 2.0] if self.speaking else [0.55, -0.35, 0.9]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        self._scan = (self._scan + (3.0 if self.speaking else 1.3)) % 360
        self._scan2 = (self._scan2 + (-2.0 if self.speaking else -0.75)) % 360

        fw = min(self.width(), self.height()) if self.width() and self.height() else 72
        lim = fw * 0.74
        spd = 4.2 if self.speaking else 2.0
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.07 if self.speaking else 0.025):
            self._pulses.append(0.0)

        if self.speaking and random.random() < 0.28:
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.28
            self._particles.append([
                cx + math.cos(ang) * r_s,
                cy + math.sin(ang) * r_s,
                math.cos(ang) * random.uniform(0.9, 2.4),
                math.sin(ang) * random.uniform(0.9, 2.4) - 0.4,
                1.0,
            ])
        self._particles = [
            [p[0] + p[2], p[1] + p[3], p[2] * 0.97, p[3] * 0.97, p[4] - 0.028]
            for p in self._particles
            if p[4] > 0
        ]

    def _paint_orb(
        self,
        p: QPainter,
        cx: float,
        cy: float,
        fw: float,
        *,
        compact: bool = False,
        include_face: bool = True,
        include_particles: bool = True,
    ) -> None:
        r_face = fw * 0.31
        active_col = _C.MUTED_C if self.muted else (_C.ARC if self.speaking else _C.PRI)
        ghost_col = _C.MUTED_C if self.muted else _C.PRI

        if not self.muted:
            core_r = r_face * (0.22 if self.speaking else 0.16)
            grad = QRadialGradient(cx, cy, core_r * 2.2)
            core_a = min(255, int(self._halo * (2.2 if self.speaking else 1.4)))
            grad.setColorAt(0.0, _qcol(_C.ARC_CORE, core_a))
            grad.setColorAt(0.35, _qcol(_C.ARC, max(0, core_a - 60)))
            grad.setColorAt(0.75, _qcol(_C.PRI, max(0, core_a // 3)))
            grad.setColorAt(1.0, _qcol(_C.PRI_GHO, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(cx - core_r * 2, cy - core_r * 2, core_r * 4, core_r * 4))
            for ring_i, frac in enumerate((0.55, 0.72, 0.88)):
                rr = core_r * frac * 2
                a = max(0, min(255, int(self._halo * 0.35 * (1 - ring_i * 0.25))))
                p.setPen(QPen(_qcol(_C.ARC if self.speaking else _C.PRI_DIM, a), 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QRectF(cx - rr, cy - rr, rr * 2, rr * 2))

        halo_range = 6 if compact else 10
        for i in range(halo_range):
            r = r_face * (1.8 - i * 0.08)
            frc = 1.0 - i / halo_range
            a = max(0, min(255, int(self._halo * 0.085 * frc)))
            col = _qcol(active_col if self.speaking else ghost_col, a)
            p.setPen(QPen(col, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        for pr in self._pulses:
            a = max(0, int(230 * (1.0 - pr / (fw * 0.74))))
            col = _qcol(active_col if self.speaking else ghost_col, a)
            p.setPen(QPen(col, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        ring_specs = (
            [(0.48, 3, 115, 78), (0.40, 2, 78, 55), (0.32, 1, 56, 40)]
            if not compact
            else [(0.46, 2, 100, 85), (0.38, 1.5, 70, 60)]
        )
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(ring_specs):
            ring_r = fw * r_frac
            base = self._rings[idx % len(self._rings)]
            a_val = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            col = _qcol(active_col if (self.speaking and idx == 0) else ghost_col, a_val)
            p.setPen(QPen(col, w_r))
            p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        if not compact:
            sr = fw * 0.50
            sa = min(255, int(self._halo * 1.5))
            ex = 75 if self.speaking else 44
            p.setPen(QPen(_qcol(active_col, sa), 2.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
            p.drawArc(srect, int(self._scan * 16), int(ex * 16))
            p.setPen(QPen(_qcol(_C.ARC, sa // 2), 1.5))
            p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        if include_face:
            self._paint_orb_face(p, cx, cy, fw, compact=compact)

        if include_particles:
            self._paint_orb_particles(p)

    def _paint_orb_face(
        self,
        p: QPainter,
        cx: float,
        cy: float,
        fw: float,
        *,
        compact: bool = False,
    ) -> None:
        if self._face_px:
            fsz = int(fw * (0.68 if compact else 0.62) * self._scale)
            scaled = self._face_px.scaled(
                fsz,
                fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
        else:
            orb_r = int(fw * 0.27 * self._scale)
            oc = (200, 0, 50) if self.muted else (255, 120, 0)
            for i in range(8, 0, -1):
                r2 = int(orb_r * i / 8)
                frc = i / 8
                a = max(0, min(255, int(self._halo * 1.1 * frc)))
                p.setBrush(QBrush(QColor(int(oc[0] * frc), int(oc[1] * frc), int(oc[2] * frc), a)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))
            p.setPen(QPen(_qcol(_C.GLOW, min(255, int(self._halo * 2))), 1))
            p.setFont(_hud_font(8 if compact else 13, True))
            label = "E" if compact else "E.M.I.L.Y."
            box = QRectF(cx - 40, cy - 10, 80, 20) if compact else QRectF(cx - 80, cy - 14, 160, 28)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_orb_particles(self, p: QPainter) -> None:
        pt_col = _C.ARC if self.speaking else _C.PRI
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(_qcol(pt_col, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)


class EmilyOrbWidget(QWidget, OrbAnimatorMixin):
    """Compact circular orb for the floating always-on-top widget."""

    ORB_SIZE = 72

    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.ORB_SIZE, self.ORB_SIZE)
        self._init_orb(face_path)
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._on_tick)
        self._tmr.start(16)

    def _on_tick(self) -> None:
        self._step_orb()
        self.update()

    def set_speaking(self, speaking: bool) -> None:
        if self.speaking != speaking:
            self.speaking = speaking
            self.update()

    def set_muted(self, muted: bool) -> None:
        if self.muted != muted:
            self.muted = muted
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        fw = min(self.width(), self.height())
        cx, cy = self.width() / 2, self.height() / 2
        self._paint_orb(p, cx, cy, fw, compact=True)
