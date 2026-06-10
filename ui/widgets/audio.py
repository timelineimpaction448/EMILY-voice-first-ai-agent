"""Audio spectrum bars — reflects real mic/TTS level; flat-lines when muted."""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ui.theme import C, qcol
from ui.services.audio_level import audio_level
from ui.widgets.base import anim_clock


def paint_spectrum(p: QPainter, rect: QRectF, bands: list, *, muted: bool = False,
                   speaking: bool = False) -> None:
    n = len(bands)
    if n == 0:
        return
    bw = rect.width() / n
    # baseline sits above the bottom to leave room for the reflection
    base = rect.bottom() - rect.height() * 0.22
    usable = rect.height() * 0.74
    color = C.MUTED_C if muted else (C.ARC if speaking else C.PRI)
    for i, mag in enumerate(bands):
        h = 1.5 if muted else max(1.5, mag * usable)
        x = rect.x() + i * bw
        p.setBrush(QBrush(qcol(color, 230)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(x + 1, base - h, bw - 2, h))
        # mirrored faint reflection
        p.setBrush(QBrush(qcol(color, 55)))
        p.drawRect(QRectF(x + 1, base + 2, bw - 2, h * 0.4))
        # glow cap on tall bars
        if not muted and h > usable * 0.55:
            p.fillRect(QRectF(x + 1, base - h, bw - 2, 2), qcol(C.GLOW, 180))
            p.setBrush(QBrush(qcol(C.GLOW, 70)))
            p.drawEllipse(QPointF(x + bw / 2, base - h), bw * 0.4, bw * 0.4)
    # center baseline (glowing)
    p.setPen(QPen(qcol(color, 150), 1))
    p.drawLine(QPointF(rect.x(), base), QPointF(rect.right(), base))


class SpectrumBars(QWidget):
    def __init__(self, n_bands: int = 24, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._n = n_bands
        self._bars = [0.0] * n_bands
        self._muted = False
        self._speaking = False
        anim_clock().tick.connect(self._tick)

    def set_muted(self, muted: bool):
        self._muted = muted

    def set_speaking(self, speaking: bool):
        self._speaking = speaking

    def _tick(self):
        target = audio_level().spectrum(self._n, speaking=self._speaking)
        # decay falloff toward target
        for i in range(self._n):
            t = target[i]
            self._bars[i] = max(t, self._bars[i] * 0.78)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_spectrum(p, QRectF(self.rect()).adjusted(2, 2, -2, -2), self._bars,
                       muted=self._muted, speaking=self._speaking)
