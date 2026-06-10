"""Central reactor orb — the HUD's hero state visualizer (full intensity).

Layered, JARVIS-style: bloom core, rotating circular-text ring, counter-rotating
segmented gear ring, orbiting satellites, iris spokes, triangle markers, and a
lens flare whose intensity tracks the live audio level. Reuses OrbAnimatorMixin
(shared with the floating orb) and the single AnimClock.

State programs: LISTENING cyan · THINKING/PROCESSING amber · SPEAKING amber flare
· MUTED red · SLEEP dim breathing.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ui.orb_widget import OrbAnimatorMixin
from ui.theme import (
    C, draw_circular_text, draw_glow_ellipse, draw_glow_line, draw_hud_corners,
    hud_font, qcol,
)
from ui.services.audio_level import audio_level
from ui.widgets.base import anim_clock

_RING_TEXT = " E.M.I.L.Y · NEURAL CORE · ARC REACTOR · MARK II · "


class ReactorOrb(QWidget, OrbAnimatorMixin):
    def __init__(self, face_path: str, parent=None):
        super().__init__(parent)
        # translucent so the animated backdrop (bloom + particles) shows through
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(280, 280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.state = "INITIALISING"
        self._blink = True
        self._blink_tick = 0
        self._reduced = False
        self._field = []  # ambient drifting particles behind the orb
        self._init_orb(face_path)
        # orbiting satellites: (radius_frac, speed, phase)
        self._orbiters = [
            (0.40, 1.3, 0), (0.44, -0.9, 70), (0.50, 0.6, 140),
            (0.46, 1.7, 210), (0.52, -1.1, 300),
        ]
        anim_clock().tick.connect(self._on_tick)

    def set_reduced_motion(self, v: bool):
        self._reduced = bool(v)

    # ----- engine-facing API (mirrors HudCanvas) -----
    def set_state(self, state: str) -> None:
        self.state = state
        self.speaking = state == "SPEAKING"
        if state == "MUTED":
            self.muted = True
        elif state in ("LISTENING", "SPEAKING", "THINKING", "PROCESSING"):
            self.muted = False
        audio_level().set_speaking(self.speaking)

    def set_muted(self, muted: bool) -> None:
        self.muted = muted

    # ----- animation -----
    def _on_tick(self) -> None:
        self._step_orb()
        self._blink_tick += 1
        if self._blink_tick >= 22:
            self._blink = not self._blink
            self._blink_tick = 0
        if not self._reduced:
            self._advance_field()
        self.update()

    def _advance_field(self):
        import random as _r
        W, H = self.width(), self.height()
        for pt in self._field:
            pt[0] += pt[2]
            pt[1] += pt[3]
            pt[4] += pt[5]  # phase
            # gentle pull toward center so motes swirl around the orb
            if pt[0] < -20 or pt[0] > W + 20 or pt[1] < -20 or pt[1] > H + 20:
                pt[0], pt[1] = _r.uniform(0, W), _r.uniform(0, H)

    def _ang(self, speed: float) -> float:
        return 0.0 if self._reduced else self._tick * speed

    # ----- paint -----
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)
        lvl = audio_level().active_level()
        active = C.MUTED_C if self.muted else (C.ARC if self.speaking else C.PRI)

        # translucent dark core (keeps the orb legible) fading to fully transparent
        # at the edges so the backdrop bloom/particles read around the circle.
        bg = QRadialGradient(cx, cy, fw * 0.62)
        bg.setColorAt(0.0, qcol(C.BG, 225))
        bg.setColorAt(0.45, qcol(C.BG, 175))
        bg.setColorAt(0.80, qcol(C.BG, 60))
        bg.setColorAt(1.0, qcol(C.BG, 0))
        p.fillRect(self.rect(), QBrush(bg))

        self._paint_field(p, cx, cy, fw, active)
        self._paint_bloom(p, cx, cy, fw, active, lvl)
        self._paint_iris(p, cx, cy, fw, active)
        self._paint_rings_decor(p, cx, cy, fw, active)

        # core glow + halos + pulses + mixin rings (no face/particles yet)
        self._paint_orb(p, cx, cy, fw, compact=False, include_face=False, include_particles=False)

        self._paint_ticks(p, cx, cy, fw)
        self._paint_crosshair(p, cx, cy, fw)
        self._paint_amplitude(p, cx, cy, fw, active, lvl)
        self._paint_triangles(p, cx, cy, fw, active)
        self._paint_orbiters(p, cx, cy, fw, active)

        frame_r = fw * 0.54
        draw_hud_corners(p, QRectF(cx - frame_r, cy - frame_r, frame_r * 2, frame_r * 2),
                         qcol(C.GLOW, 180), length=28, pen_w=2)

        self._paint_orb_face(p, cx, cy, fw, compact=False)
        self._paint_orb_particles(p)
        self._paint_lens_flare(p, cx, cy, fw, active, lvl)
        self._paint_state_word(p, W, cy, fw)

    def _paint_field(self, p, cx, cy, fw, col):
        import random as _r
        if not self._field:
            W, H = self.width(), self.height()
            rng = _r.Random(1234)
            for _ in range(46):
                self._field.append([
                    rng.uniform(0, W), rng.uniform(0, H),
                    rng.uniform(-0.35, 0.35), rng.uniform(-0.30, 0.30),
                    rng.uniform(0, math.tau), rng.uniform(0.02, 0.06),
                    rng.uniform(1.0, 2.6),
                ])
        p.setPen(Qt.PenStyle.NoPen)
        for pt in self._field:
            tw = 0.5 + 0.5 * math.sin(pt[4])
            a = int(40 + 90 * tw)
            sz = pt[6]
            # soft halo + core for a bloom-y mote
            p.setBrush(QBrush(qcol(C.GLOW, a // 3)))
            p.drawEllipse(QPointF(pt[0], pt[1]), sz * 2.4, sz * 2.4)
            p.setBrush(QBrush(qcol(col, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), sz, sz)

    def _paint_bloom(self, p, cx, cy, fw, col, lvl):
        # wide ambient bloom
        rw = fw * (0.50 + 0.06 * lvl)
        aw = int(min(150, self._halo * 0.9 + 60 * lvl))
        gw = QRadialGradient(cx, cy, rw)
        gw.setColorAt(0.0, qcol(col, aw))
        gw.setColorAt(0.55, qcol(col, aw // 3))
        gw.setColorAt(1.0, qcol(col, 0))
        p.setBrush(QBrush(gw))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(cx, cy), rw, rw)
        # tight bright core bloom
        r = fw * (0.34 + 0.05 * lvl)
        a = int(min(235, self._halo * 1.7 + 90 * lvl))
        grad = QRadialGradient(cx, cy, r)
        grad.setColorAt(0.0, qcol(C.GLOW if not self.muted else col, a))
        grad.setColorAt(0.4, qcol(col, a // 2))
        grad.setColorAt(1.0, qcol(col, 0))
        p.setBrush(QBrush(grad))
        p.drawEllipse(QPointF(cx, cy), r, r)

    def _paint_iris(self, p, cx, cy, fw, col):
        r0, r1 = fw * 0.17, fw * 0.27
        a = 60 if not self.muted else 40
        p.setPen(QPen(qcol(col, a), 1))
        base = self._ang(0.4)
        for i in range(24):
            ang = math.radians(i * 15 + base)
            p.drawLine(QPointF(cx + r0 * math.cos(ang), cy + r0 * math.sin(ang)),
                       QPointF(cx + r1 * math.cos(ang), cy + r1 * math.sin(ang)))

    def _paint_rings_decor(self, p, cx, cy, fw, col):
        # rotating circular text ring
        draw_circular_text(p, cx, cy, fw * 0.43, _RING_TEXT, col, size=7,
                           angle_offset=self._ang(0.5), alpha=130)
        # counter-rotating segmented gear ring
        gr = fw * 0.46
        rect = QRectF(cx - gr, cy - gr, gr * 2, gr * 2)
        base = self._ang(-0.8)
        p.setPen(QPen(qcol(col, 150), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for k in range(16):
            a0 = base + k * 22.5
            p.drawArc(rect, int(a0 * 16), int(9 * 16))
        # faint full guide ring
        p.setPen(QPen(qcol(C.BORDER_B, 70), 1))
        p.drawEllipse(QPointF(cx, cy), gr * 1.05, gr * 1.05)

    def _paint_ticks(self, p, cx, cy, fw):
        t_out, t_in = fw * 0.497, fw * 0.474
        p.setPen(QPen(qcol(C.PRI, 140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            p.drawLine(QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                       QPointF(cx + inn * math.cos(rad), cy - inn * math.sin(rad)))

    def _paint_crosshair(self, p, cx, cy, fw):
        ch_r, gap_h = fw * 0.51, fw * 0.16
        p.setPen(QPen(qcol(C.GLOW, int(self._halo * 0.45)), 1))
        p.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        p.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        p.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        p.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

    def _paint_amplitude(self, p, cx, cy, fw, col, lvl):
        if lvl > 0.02 and not self.muted:
            amp_r = fw * (0.42 + 0.07 * lvl)
            draw_glow_ellipse(p, cx, cy, amp_r, amp_r, col,
                              width=1.5 + 2.0 * lvl, glow=2, alpha=int(90 + 150 * lvl))

    def _paint_triangles(self, p, cx, cy, fw, col):
        r = fw * 0.52
        base = self._scan if not self._reduced else 0
        p.setBrush(QBrush(qcol(col, 200)))
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(3):
            ang = math.radians(base + k * 120)
            tx, ty = cx + r * math.cos(ang), cy + r * math.sin(ang)
            perp = ang + math.pi / 2
            s = fw * 0.018
            p.drawConvexPolygon(
                QPointF(tx + s * math.cos(ang), ty + s * math.sin(ang)),
                QPointF(tx + s * 0.7 * math.cos(perp), ty + s * 0.7 * math.sin(perp)),
                QPointF(tx - s * 0.7 * math.cos(perp), ty - s * 0.7 * math.sin(perp)),
            )

    def _paint_orbiters(self, p, cx, cy, fw, col):
        for (rf, speed, phase) in self._orbiters:
            r = fw * rf
            # orbit path
            p.setPen(QPen(qcol(C.BORDER, 50), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)
            ang = math.radians(self._ang(speed) + phase)
            ox, oy = cx + r * math.cos(ang), cy + r * math.sin(ang)
            p.setBrush(QBrush(qcol(C.GLOW, 70)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(ox, oy), 4.0, 4.0)
            p.setBrush(QBrush(qcol(col, 235)))
            p.drawEllipse(QPointF(ox, oy), 2.0, 2.0)

    def _paint_lens_flare(self, p, cx, cy, fw, col, lvl):
        if self.muted:
            return
        intensity = max(0.12, lvl if self.speaking else lvl * 0.6)
        if intensity < 0.06:
            return
        # horizontal streak
        w = fw * 0.92 * (0.5 + intensity)
        grad = QLinearGradient(cx - w / 2, cy, cx + w / 2, cy)
        a = int(120 * intensity)
        grad.setColorAt(0.0, qcol(col, 0))
        grad.setColorAt(0.5, qcol(C.ARC_CORE if self.speaking else C.GLOW, a))
        grad.setColorAt(1.0, qcol(col, 0))
        p.fillRect(QRectF(cx - w / 2, cy - 1.5, w, 3), QBrush(grad))
        # 4-point star sparkle
        s = fw * 0.10 * (0.6 + intensity)
        draw_glow_line(p, QPointF(cx - s, cy), QPointF(cx + s, cy), C.WHITE,
                       width=1.0, glow=2, alpha=int(180 * intensity))
        draw_glow_line(p, QPointF(cx, cy - s), QPointF(cx, cy + s), C.WHITE,
                       width=1.0, glow=2, alpha=int(180 * intensity))

    def _paint_state_word(self, p, W, cy, fw):
        sy = cy + fw * 0.40
        txt, col = self._state_label()
        p.setPen(QPen(col, 1))
        p.setFont(hud_font(11, True))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

    def _state_label(self):
        if self.state == "SLEEP":
            sym = "◌" if self._blink else "○"
            return f"{sym}  STANDBY", qcol(C.TEXT_DIM)
        if self.muted:
            return "⊘  COMMS OFF", qcol(C.MUTED_C)
        if self.speaking:
            return "◉  TRANSMITTING", qcol(C.ARC)
        if self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            return f"{sym}  ANALYSING", qcol(C.ACC2)
        if self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            return f"{sym}  EXECUTING", qcol(C.ACC2)
        if self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            return f"{sym}  RECEIVING", qcol(C.GREEN)
        sym = "●" if self._blink else "○"
        return f"{sym}  {self.state}", qcol(C.PRI)
