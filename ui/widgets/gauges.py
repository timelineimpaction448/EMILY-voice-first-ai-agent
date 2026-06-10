"""Gauge primitives: ring gauge, arc gauge, segmented bar, sparkline.

Each has a free `paint_*` function (so clusters can compose several into one
panel) and a thin QWidget wrapper for standalone / gallery use.
"""

from __future__ import annotations

import math
from collections import deque

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ui.theme import C, draw_glow_arc, hud_font, digital_font, qcol
from ui.widgets.base import anim_clock


def _square(rect: QRectF) -> QRectF:
    s = min(rect.width(), rect.height())
    return QRectF(
        rect.x() + (rect.width() - s) / 2,
        rect.y() + (rect.height() - s) / 2,
        s, s,
    )


def paint_ring_gauge(
    p, rect: QRectF, value: float, *,
    label: str = "", text: str | None = None, color: str = C.PRI,
    thickness: float = 0.13, ticks: bool = True,
) -> None:
    """value in 0..100. Sweeps clockwise from 12 o'clock."""
    sq = _square(rect)
    s = sq.width()
    pen_w = max(3.0, s * thickness)
    inset = pen_w / 2 + 2
    arc_rect = QRectF(sq.x() + inset, sq.y() + inset, s - 2 * inset, s - 2 * inset)
    cx, cy = sq.center().x(), sq.center().y()

    # background ring
    p.setPen(QPen(qcol(C.BORDER, 160), pen_w))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(arc_rect, 0, 360 * 16)

    # tick marks
    if ticks:
        r_out = arc_rect.width() / 2 + pen_w / 2
        r_in = r_out - pen_w * 0.7
        p.setPen(QPen(qcol(C.BORDER_B, 120), 1))
        for deg in range(0, 360, 30):
            a = math.radians(deg - 90)
            p.drawLine(
                QPointF(cx + r_in * math.cos(a), cy + r_in * math.sin(a)),
                QPointF(cx + r_out * math.cos(a), cy + r_out * math.sin(a)),
            )

    # value arc (clockwise from top) — glow under-stroke + segmented dashes
    v = max(0.0, min(100.0, value))
    total_span = v / 100.0 * 360.0
    draw_glow_arc(p, arc_rect, 90 * 16, -int(total_span * 16), color,
                  width=pen_w, glow=2, alpha=70)
    # segmented dashes
    p.setPen(QPen(qcol(color), pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    seg, gap = 9.0, 3.0
    a = 0.0
    while a < total_span:
        dash = min(seg, total_span - a)
        p.drawArc(arc_rect, int((90 - a) * 16), -int(dash * 16))
        a += seg + gap
    # inner decorative hairline ring
    ir = arc_rect.width() / 2 - pen_w
    if ir > 4:
        p.setPen(QPen(qcol(color, 70), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(cx, cy), ir, ir)
    # head dot on the value arc
    if v > 0.5:
        head = math.radians(90 - total_span)
        hr = arc_rect.width() / 2
        hx, hy = cx + hr * math.cos(head), cy - hr * math.sin(head)
        p.setBrush(QBrush(qcol(C.GLOW, 90)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(hx, hy), pen_w * 0.7, pen_w * 0.7)
        p.setBrush(QBrush(qcol(C.WHITE)))
        p.drawEllipse(QPointF(hx, hy), pen_w * 0.35, pen_w * 0.35)

    # center readout
    p.setPen(QPen(qcol(C.WHITE), 1))
    p.setFont(digital_font(max(9, int(s * 0.20))))
    txt = text if text is not None else f"{v:.0f}"
    p.drawText(sq, Qt.AlignmentFlag.AlignCenter, txt)
    if label:
        p.setFont(hud_font(max(6, int(s * 0.09)), True))
        p.setPen(QPen(qcol(color, 200), 1))
        p.drawText(
            QRectF(sq.x(), cy + s * 0.18, s, s * 0.18),
            Qt.AlignmentFlag.AlignHCenter, label,
        )


def paint_arc_gauge(
    p, rect: QRectF, value: float, *,
    lo: float = 0, hi: float = 100, label: str = "", text: str | None = None,
    color: str = C.PRI, start_deg: int = 210, span_deg: int = 240,
) -> None:
    """270-ish degree open arc gauge (speedometer style)."""
    sq = _square(rect)
    s = sq.width()
    pen_w = max(3.0, s * 0.10)
    inset = pen_w / 2 + 4
    arc_rect = QRectF(sq.x() + inset, sq.y() + inset, s - 2 * inset, s - 2 * inset)

    p.setPen(QPen(qcol(C.BORDER, 150), pen_w))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(arc_rect, start_deg * 16, -span_deg * 16)

    frac = 0.0 if hi == lo else max(0.0, min(1.0, (value - lo) / (hi - lo)))
    p.setPen(QPen(qcol(color), pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(arc_rect, start_deg * 16, -int(span_deg * frac) * 16)

    cx, cy = sq.center().x(), sq.center().y()
    p.setPen(QPen(qcol(C.WHITE), 1))
    p.setFont(digital_font(max(9, int(s * 0.18))))
    p.drawText(QRectF(sq.x(), cy - s * 0.12, s, s * 0.24),
               Qt.AlignmentFlag.AlignCenter, text if text is not None else f"{value:.0f}")
    if label:
        p.setFont(hud_font(max(6, int(s * 0.085)), True))
        p.setPen(QPen(qcol(color, 200), 1))
        p.drawText(QRectF(sq.x(), cy + s * 0.16, s, s * 0.14),
                   Qt.AlignmentFlag.AlignHCenter, label)


def paint_segmented_bar(
    p, rect: QRectF, value: float, *, segments: int = 16, color: str = C.PRI,
    vertical: bool = False,
) -> None:
    v = max(0.0, min(100.0, value))
    filled = int(round(segments * v / 100.0))
    if vertical:
        seg_h = rect.height() / segments
        for i in range(segments):
            y = rect.bottom() - (i + 1) * seg_h + 1
            on = i < filled
            p.setBrush(QBrush(qcol(color if on else C.BAR_BG, 255 if on else 120)))
            p.setPen(QPen(qcol(C.BORDER, 80), 1))
            p.drawRect(QRectF(rect.x() + 1, y, rect.width() - 2, seg_h - 2))
    else:
        seg_w = rect.width() / segments
        for i in range(segments):
            x = rect.x() + i * seg_w + 1
            on = i < filled
            p.setBrush(QBrush(qcol(color if on else C.BAR_BG, 255 if on else 120)))
            p.setPen(QPen(qcol(C.BORDER, 80), 1))
            p.drawRect(QRectF(x, rect.y() + 1, seg_w - 2, rect.height() - 2))


def paint_sparkline(
    p, rect: QRectF, series, *, color: str = C.GREEN, fill: bool = True,
    max_val: float | None = None, baseline_grid: bool = True,
) -> None:
    data = list(series)
    if baseline_grid:
        p.setPen(QPen(qcol(C.BORDER, 70), 1))
        for f in (0.25, 0.5, 0.75):
            y = rect.y() + rect.height() * f
            p.drawLine(QPointF(rect.x(), y), QPointF(rect.right(), y))
    if len(data) < 2:
        return
    peak = max_val if max_val is not None else max(data)
    peak = max(peak, 1e-6)
    n = len(data)
    dx = rect.width() / (n - 1)

    def pt(i):
        x = rect.x() + i * dx
        y = rect.bottom() - min(1.0, data[i] / peak) * rect.height()
        return QPointF(x, y)

    path = QPainterPath()
    path.moveTo(pt(0))
    for i in range(1, n):
        path.lineTo(pt(i))

    if fill:
        area = QPainterPath(path)
        area.lineTo(rect.right(), rect.bottom())
        area.lineTo(rect.x(), rect.bottom())
        area.closeSubpath()
        grad = QLinearGradient(0, rect.y(), 0, rect.bottom())
        grad.setColorAt(0.0, qcol(color, 90))
        grad.setColorAt(1.0, qcol(color, 0))
        p.fillPath(area, QBrush(grad))

    p.setBrush(Qt.BrushStyle.NoBrush)
    # glow passes then crisp line
    for gw, ga in ((4.5, 30), (2.8, 60)):
        p.setPen(QPen(qcol(color, ga), gw))
        p.drawPath(path)
    p.setPen(QPen(qcol(color), 1.6))
    p.drawPath(path)
    # head dot with halo
    head = pt(n - 1)
    p.setBrush(QBrush(qcol(C.GLOW, 80)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(head, 4.2, 4.2)
    p.setBrush(QBrush(qcol(C.WHITE)))
    p.drawEllipse(head, 2.0, 2.0)


# ---------------- widget wrappers ----------------

class _ValueWidget(QWidget):
    def __init__(self, *, animated: bool = False, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if animated:
            anim_clock().tick.connect(self.update)


class RingGauge(_ValueWidget):
    def __init__(self, label: str = "", color: str = C.PRI, parent=None):
        super().__init__(parent=parent)
        self._value = 0.0
        self._label = label
        self._color = color
        self._text = None

    def set_value(self, value: float, text: str | None = None, color: str | None = None):
        self._value = value
        self._text = text
        if color:
            self._color = color
        self.update()

    def paintEvent(self, _):
        from PyQt6.QtGui import QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_ring_gauge(p, QRectF(self.rect()), self._value,
                         label=self._label, text=self._text, color=self._color)


class Sparkline(_ValueWidget):
    def __init__(self, color: str = C.GREEN, maxlen: int = 120, parent=None):
        super().__init__(parent=parent)
        self._series = deque(maxlen=maxlen)
        self._color = color

    def push(self, v: float):
        self._series.append(v)
        self.update()

    def set_series(self, series):
        self._series = deque(series, maxlen=self._series.maxlen)
        self.update()

    def paintEvent(self, _):
        from PyQt6.QtGui import QPainter
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        paint_sparkline(p, QRectF(self.rect()).adjusted(2, 2, -2, -2), self._series, color=self._color)
