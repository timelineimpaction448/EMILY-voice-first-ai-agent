"""Dial primitives: compass, battery/uptime arc, sun-arc, radar scope."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ui.theme import (
    C, draw_glow_arc, draw_glow_ellipse, draw_glow_line, hud_font, digital_font, qcol,
)
from ui.widgets.base import anim_clock


def _square(rect: QRectF) -> QRectF:
    s = min(rect.width(), rect.height())
    return QRectF(rect.x() + (rect.width() - s) / 2, rect.y() + (rect.height() - s) / 2, s, s)


# ---------------- compass ----------------

def paint_compass(p: QPainter, rect: QRectF, heading: float, *,
                  speed_text: str = "", color: str = C.PRI) -> None:
    sq = _square(rect)
    cx, cy = sq.center().x(), sq.center().y()
    r = sq.width() / 2 - 4

    p.setPen(QPen(qcol(C.BORDER_B, 180), 1.5))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r, r)

    # cardinal ticks + letters
    p.setFont(hud_font(max(6, int(r * 0.20)), True))
    for deg, lab in ((0, "N"), (90, "E"), (180, "S"), (270, "W")):
        a = math.radians(deg - 90)
        x1 = cx + (r - 3) * math.cos(a)
        y1 = cy + (r - 3) * math.sin(a)
        x2 = cx + r * math.cos(a)
        y2 = cy + r * math.sin(a)
        p.setPen(QPen(qcol(C.TEXT_MED, 200), 1.5))
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        lx = cx + (r - r * 0.30) * math.cos(a)
        ly = cy + (r - r * 0.30) * math.sin(a)
        p.setPen(QPen(qcol(C.TEXT_DIM if lab != "N" else C.ARC, 220), 1))
        p.drawText(QRectF(lx - 8, ly - 7, 16, 14), Qt.AlignmentFlag.AlignCenter, lab)
    for deg in range(0, 360, 30):
        if deg % 90 == 0:
            continue
        a = math.radians(deg - 90)
        p.setPen(QPen(qcol(C.BORDER_B, 120), 1))
        p.drawLine(QPointF(cx + (r - 2) * math.cos(a), cy + (r - 2) * math.sin(a)),
                   QPointF(cx + r * math.cos(a), cy + r * math.sin(a)))

    # faint inner orbit ring
    p.setPen(QPen(qcol(color, 60), 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r * 0.62, r * 0.62)

    # needle (points toward heading)
    a = math.radians(heading - 90)
    nx, ny = math.cos(a), math.sin(a)
    tip = QPointF(cx + nx * r * 0.78, cy + ny * r * 0.78)
    tail = QPointF(cx - nx * r * 0.42, cy - ny * r * 0.42)
    perp = QPointF(-ny, nx)
    base1 = QPointF(cx + perp.x() * r * 0.10, cy + perp.y() * r * 0.10)
    base2 = QPointF(cx - perp.x() * r * 0.10, cy - perp.y() * r * 0.10)
    needle = QPolygonF([tip, base1, tail, base2])
    draw_glow_line(p, tail, tip, color, width=1.5, glow=2, alpha=150)
    p.setBrush(QBrush(qcol(color)))
    p.setPen(QPen(qcol(C.GLOW, 160), 1))
    p.drawPolygon(needle)
    # glowing hub
    p.setBrush(QBrush(qcol(C.ARC_CORE, 90)))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(cx, cy), 4.5, 4.5)
    p.setBrush(QBrush(qcol(C.ARC)))
    p.drawEllipse(QPointF(cx, cy), 2.5, 2.5)

    if speed_text:
        p.setFont(digital_font(max(7, int(r * 0.22))))
        p.setPen(QPen(qcol(C.WHITE), 1))
        p.drawText(QRectF(cx - r, cy + r * 0.30, r * 2, r * 0.4),
                   Qt.AlignmentFlag.AlignHCenter, speed_text)


# ---------------- battery / uptime ----------------

def paint_battery_arc(p: QPainter, rect: QRectF, percent: float, plugged: bool,
                      *, color: str = C.GREEN) -> None:
    sq = _square(rect)
    s = sq.width()
    pen_w = max(4.0, s * 0.12)
    inset = pen_w / 2 + 3
    arc = QRectF(sq.x() + inset, sq.y() + inset, s - 2 * inset, s - 2 * inset)
    c = C.RED if percent < 15 else (C.ARC if percent < 40 else color)
    p.setPen(QPen(qcol(C.BORDER, 150), pen_w))
    p.drawArc(arc, 0, 360 * 16)
    draw_glow_arc(p, arc, 90 * 16, -int(percent / 100 * 360) * 16, c, width=pen_w, glow=2, alpha=200)
    cx, cy = sq.center().x(), sq.center().y()
    p.setFont(digital_font(max(9, int(s * 0.20))))
    p.setPen(QPen(qcol(C.WHITE), 1))
    p.drawText(sq, Qt.AlignmentFlag.AlignCenter, f"{percent:.0f}%")
    p.setFont(hud_font(max(6, int(s * 0.10)), True))
    p.setPen(QPen(qcol(c, 220), 1))
    p.drawText(QRectF(sq.x(), cy + s * 0.18, s, s * 0.16),
               Qt.AlignmentFlag.AlignHCenter, ("⚡ CHARGING" if plugged else "BATTERY"))


def paint_uptime_dial(p: QPainter, rect: QRectF, seconds: float, *, color: str = C.PRI) -> None:
    sq = _square(rect)
    s = sq.width()
    pen_w = max(4.0, s * 0.12)
    inset = pen_w / 2 + 3
    arc = QRectF(sq.x() + inset, sq.y() + inset, s - 2 * inset, s - 2 * inset)
    # progress = fraction of the current hour, just for motion
    frac = (seconds % 3600) / 3600.0
    p.setPen(QPen(qcol(C.BORDER, 150), pen_w))
    p.drawArc(arc, 0, 360 * 16)
    draw_glow_arc(p, arc, 90 * 16, -int(frac * 360) * 16, color, width=pen_w, glow=2, alpha=200)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    cx, cy = sq.center().x(), sq.center().y()
    p.setFont(digital_font(max(9, int(s * 0.18))))
    p.setPen(QPen(qcol(C.WHITE), 1))
    p.drawText(sq, Qt.AlignmentFlag.AlignCenter, f"{h:02d}:{m:02d}")
    p.setFont(hud_font(max(6, int(s * 0.10)), True))
    p.setPen(QPen(qcol(color, 220), 1))
    p.drawText(QRectF(sq.x(), cy + s * 0.18, s, s * 0.16),
               Qt.AlignmentFlag.AlignHCenter, "UPTIME")


# ---------------- sun arc ----------------

def paint_sun_arc(p: QPainter, rect: QRectF, day_frac: float, is_day: bool,
                  *, moon_glyph: str = "🌙", sun_glyph: str = "☀") -> None:
    """day_frac: 0 at sunrise, 1 at sunset (position of sun along its arc)."""
    w, h = rect.width(), rect.height()
    cx = rect.x() + w / 2
    baseline = rect.y() + h * 0.82
    radius = min(w * 0.42, h * 0.66)
    # horizon line
    p.setPen(QPen(qcol(C.BORDER_B, 160), 1.4))
    p.drawLine(QPointF(rect.x() + w * 0.08, baseline), QPointF(rect.right() - w * 0.08, baseline))
    # arc (sunrise left → sunset right), angle 180°..0°
    arc_rect = QRectF(cx - radius, baseline - radius, radius * 2, radius * 2)
    p.setPen(QPen(qcol(C.ARC if is_day else C.PRI_DIM, 150), 1.5, Qt.PenStyle.DashLine))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(arc_rect, 0, 180 * 16)
    # body position
    frac = max(0.0, min(1.0, day_frac))
    ang = math.radians(180 - frac * 180)
    bx = cx + radius * math.cos(ang)
    by = baseline - radius * math.sin(ang)
    if is_day:
        grad = QRadialGradient(bx, by, radius * 0.22)
        grad.setColorAt(0.0, qcol(C.ARC_CORE))
        grad.setColorAt(1.0, qcol(C.ARC, 0))
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(bx, by), radius * 0.16, radius * 0.16)
        p.setBrush(QBrush(qcol(C.ARC_CORE)))
        p.drawEllipse(QPointF(bx, by), radius * 0.07, radius * 0.07)
    else:
        p.setFont(hud_font(max(10, int(radius * 0.30))))
        p.setPen(QPen(qcol(C.TEXT_MED), 1))
        p.drawText(QRectF(bx - 12, by - 12, 24, 24), Qt.AlignmentFlag.AlignCenter, moon_glyph)


# ---------------- radar scope ----------------

def _dist_to_frac(distance_km: float | None, max_range: float) -> float:
    if distance_km is None:
        return 0.85
    # sqrt scaling keeps near targets visible without crushing far ones
    return min(1.0, math.sqrt(distance_km / max_range)) if distance_km > 0 else 0.0


def paint_radar_grid(p: QPainter, rect: QRectF, max_range: float = 12000.0) -> None:
    """Static radar background (depth disc + rings + degree labels). Cacheable."""
    sq = _square(rect)
    cx, cy = sq.center().x(), sq.center().y()
    R = sq.width() / 2 - 4

    # depth disc: dark teal center fading to black
    grad = QRadialGradient(cx, cy, R)
    grad.setColorAt(0.0, qcol("#06303a", 200))
    grad.setColorAt(0.7, qcol("#03161c", 150))
    grad.setColorAt(1.0, qcol(C.BG, 0))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(cx, cy), R, R)

    # range rings + labels
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setFont(hud_font(5, True))
    for f in (0.33, 0.66, 1.0):
        p.setPen(QPen(qcol(C.GREEN_D, 120), 1))
        p.drawEllipse(QPointF(cx, cy), R * f, R * f)
        km = (f * f) * max_range  # sqrt distance scaling → square the fraction
        p.setPen(QPen(qcol(C.GREEN_D, 150), 1))
        p.drawText(QRectF(cx + 2, cy - R * f - 8, 46, 9),
                   Qt.AlignmentFlag.AlignLeft, f"{km/1000:.0f}K")
    p.setPen(QPen(qcol(C.GREEN_D, 90), 1))
    p.drawLine(QPointF(cx - R, cy), QPointF(cx + R, cy))
    p.drawLine(QPointF(cx, cy - R), QPointF(cx, cy + R))

    # degree labels every 30°
    p.setFont(hud_font(5, True))
    p.setPen(QPen(qcol(C.GREEN_D, 140), 1))
    for deg in range(0, 360, 30):
        a = math.radians(deg - 90)
        lx = cx + (R - 9) * math.cos(a)
        ly = cy + (R - 9) * math.sin(a)
        p.drawText(QRectF(lx - 9, ly - 5, 18, 10), Qt.AlignmentFlag.AlignCenter, f"{deg:03d}")


def paint_radar(p: QPainter, rect: QRectF, sweep_deg: float, blips: list, *,
                mode: str = "iss", max_range: float = 12000.0, reduced: bool = False,
                draw_grid: bool = True, trail: list | None = None) -> list:
    """Returns list of (screen_x, screen_y, radius, blip) for hit-testing."""
    sq = _square(rect)
    cx, cy = sq.center().x(), sq.center().y()
    R = sq.width() / 2 - 4

    if draw_grid:
        paint_radar_grid(p, rect, max_range)

    # rotating outer tick ring
    if not reduced:
        base = sweep_deg * 0.5
        p.setPen(QPen(qcol(C.GREEN_D, 130), 1))
        for k in range(36):
            a = math.radians(base + k * 10 - 90)
            p.drawLine(QPointF(cx + (R - 3) * math.cos(a), cy + (R - 3) * math.sin(a)),
                       QPointF(cx + R * math.cos(a), cy + R * math.sin(a)))

    # sweep
    if not reduced:
        sweep_rad = math.radians(sweep_deg - 90)
        grad = QRadialGradient(cx, cy, R)
        grad.setColorAt(0.0, qcol(C.GREEN, 110))
        grad.setColorAt(1.0, qcol(C.GREEN, 0))
        path = QPainterPath()
        path.moveTo(cx, cy)
        for d in range(0, 36):
            a = sweep_rad - math.radians(d * 1.2)
            path.lineTo(cx + R * math.cos(a), cy + R * math.sin(a))
        path.closeSubpath()
        p.setBrush(QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path)
        draw_glow_line(p, QPointF(cx, cy),
                       QPointF(cx + R * math.cos(sweep_rad), cy + R * math.sin(sweep_rad)),
                       C.GREEN, width=1.5, glow=2, alpha=220)

    # ISS trail (fading breadcrumbs)
    if trail:
        for i, (tb, tdkm) in enumerate(trail):
            frac = _dist_to_frac(tdkm, max_range)
            a = math.radians(tb - 90)
            tx, ty = cx + R * frac * math.cos(a), cy + R * frac * math.sin(a)
            alpha = int(30 + 90 * (i / max(1, len(trail))))
            p.setBrush(QBrush(qcol(C.GREEN, alpha)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(tx, ty), 1.6, 1.6)

    hit = []
    for b in blips:
        bearing = b.get("bearing", 0.0)
        frac = _dist_to_frac(b.get("distance_km"), max_range)
        a = math.radians(bearing - 90)
        bx = cx + R * frac * math.cos(a)
        by = cy + R * frac * math.sin(a)
        # brightness from how recently the sweep passed
        if reduced:
            bright = 220
        else:
            delta = (sweep_deg - bearing) % 360
            bright = max(70, int(255 * (1.0 - delta / 360.0)))
        if mode == "quakes" and b.get("mag") is not None:
            sz = 2.5 + min(6.0, float(b["mag"]))
            col = C.RED if b["mag"] >= 5 else (C.ARC if b["mag"] >= 4 else C.AMBER)
        else:
            sz = 3.5
            col = C.GREEN
        # glow halo + core
        p.setBrush(QBrush(qcol(col, max(40, bright // 2))))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(bx, by), sz + 3, sz + 3)
        p.setBrush(QBrush(qcol(col, bright)))
        p.setPen(QPen(qcol(C.WHITE, bright), 1))
        p.drawEllipse(QPointF(bx, by), sz, sz)
        hit.append((bx, by, sz + 4, b))
    return hit


class RadarScope(QWidget):
    blip_clicked = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._sweep = 0.0
        self._blips: list = []
        self._mode = "iss"
        self._hit: list = []
        self._reduced = False
        self._grid_cache = None
        self._grid_key = None
        self._trail: list = []  # ISS breadcrumbs (bearing, distance_km)
        anim_clock().tick.connect(self._tick)

    def _max_range(self) -> float:
        return 12000.0 if self._mode == "iss" else 8000.0

    def _ensure_grid(self) -> "QPixmap":
        from PyQt6.QtGui import QPixmap
        key = (self.width(), self.height(), self._mode)
        if self._grid_cache is None or self._grid_key != key:
            dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
            pm = QPixmap(int(self.width() * dpr), int(self.height() * dpr))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.GlobalColor.transparent)
            gp = QPainter(pm)
            gp.setRenderHint(QPainter.RenderHint.Antialiasing)
            paint_radar_grid(gp, QRectF(self.rect()), self._max_range())
            gp.end()
            self._grid_cache = pm
            self._grid_key = key
        return self._grid_cache

    def set_blips(self, blips: list):
        self._blips = blips or []
        # keep an ISS breadcrumb trail
        if self._mode == "iss" and self._blips:
            b = self._blips[0]
            self._trail.append((b.get("bearing", 0.0), b.get("distance_km")))
            self._trail = self._trail[-12:]
        self.update()

    def set_mode(self, mode: str):
        self._mode = mode
        self._trail = []
        self.update()

    def set_reduced_motion(self, v: bool):
        self._reduced = v

    def _tick(self):
        if not self._reduced:
            self._sweep = (self._sweep + 2.2) % 360
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(0, 0, self._ensure_grid())  # cached static rings/cross
        self._hit = paint_radar(p, QRectF(self.rect()), self._sweep, self._blips,
                                mode=self._mode, max_range=self._max_range(),
                                reduced=self._reduced, draw_grid=False,
                                trail=self._trail if self._mode == "iss" else None)

    def mousePressEvent(self, e):
        pos = e.position()
        for bx, by, r, blip in self._hit:
            if (pos.x() - bx) ** 2 + (pos.y() - by) ** 2 <= r * r:
                self.blip_clicked.emit(blip)
                return
