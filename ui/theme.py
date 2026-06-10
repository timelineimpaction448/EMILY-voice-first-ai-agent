"""Central HUD theme: palette, fonts, stylesheets, and shared paint primitives.

This module is the single source of truth for the cockpit look. It must not
import from `ui.app` (or any widget module) so it can be used everywhere
without circular imports.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen


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

    # --- Cockpit 2.0 extensions ---
    STEEL_HI  = "#0a1a26"   # bulkhead plate highlight
    STEEL_LO  = "#020a12"   # bulkhead plate shadow
    BEZEL     = "#0e2c3c"   # instrument bezel ring
    PURPLE    = "#9a6cff"   # tracking / secondary data
    AMBER      = "#ffb020"  # caution
    AQI_GOOD  = "#00ffaa"
    AQI_MOD   = "#ffd060"
    AQI_BAD   = "#ff6a00"
    AQI_VBAD  = "#ff3355"


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h)
    c.setAlpha(a)
    return c


def hud_font(size: int, bold: bool = False) -> QFont:
    weight = QFont.Weight.Bold if bold else QFont.Weight.Normal
    return QFont("Courier New", size, weight)


def digital_font(size: int, bold: bool = True) -> QFont:
    """Monospace numeric readout font with a slight letter-spacing feel."""
    f = QFont("Consolas", size, QFont.Weight.Bold if bold else QFont.Weight.Normal)
    f.setStyleHint(QFont.StyleHint.TypeWriter)
    return f


# Backwards-compatible private aliases (ui/app.py historically used these names).
_hud_font = hud_font


def draw_hud_corners(
    p: QPainter, rect: QRectF, color: QColor, length: float = 16, pen_w: float = 2.0
) -> None:
    p.setPen(QPen(color, pen_w))
    x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
    for bx, by, dx, dy in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
        p.drawLine(QPointF(bx, by), QPointF(bx + dx * length, by))
        p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * length))


def draw_scanlines(p: QPainter, rect: QRectF, alpha: int = 14, spacing: int = 3) -> None:
    p.setPen(QPen(qcol(C.SCAN, alpha), 1))
    y = int(rect.top())
    bottom = int(rect.bottom())
    while y < bottom:
        p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        y += spacing


def draw_hex_grid(p: QPainter, w: int, h: int, cx: float, cy: float, radius: float = 26) -> None:
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


def panel_stylesheet(extra: str = "") -> str:
    return f"""
        background: {C.PANEL2};
        border: 1px solid {C.BORDER_A};
        border-radius: 2px;
        {extra}
    """


# Backwards-compatible private aliases.
_draw_hud_corners = draw_hud_corners
_draw_scanlines = draw_scanlines
_draw_hex_grid = draw_hex_grid
_panel_stylesheet = panel_stylesheet


# ---------------------------------------------------------------------------
# FX helpers — glow strokes, notched panel silhouettes, circular text, glyphs
# ---------------------------------------------------------------------------

def draw_glow_ellipse(p: QPainter, cx: float, cy: float, rx: float, ry: float,
                      color: str, width: float = 1.5, glow: int = 3,
                      alpha: int = 255) -> None:
    """Fake-bloom ellipse: layered strokes at decreasing alpha / rising width."""
    for i in range(glow, 0, -1):
        a = int(alpha * 0.16 * (1.0 - (i - 1) / glow))
        p.setPen(QPen(qcol(color, a), width + i * 2.2))
        p.drawEllipse(QPointF(cx, cy), rx, ry)
    p.setPen(QPen(qcol(color, alpha), width))
    p.drawEllipse(QPointF(cx, cy), rx, ry)


def draw_glow_arc(p: QPainter, rect: QRectF, start16: int, span16: int,
                  color: str, width: float = 2.0, glow: int = 3,
                  alpha: int = 255, cap=Qt.PenCapStyle.RoundCap) -> None:
    for i in range(glow, 0, -1):
        a = int(alpha * 0.15 * (1.0 - (i - 1) / glow))
        p.setPen(QPen(qcol(color, a), width + i * 2.4, Qt.PenStyle.SolidLine, cap))
        p.drawArc(rect, start16, span16)
    p.setPen(QPen(qcol(color, alpha), width, Qt.PenStyle.SolidLine, cap))
    p.drawArc(rect, start16, span16)


def draw_glow_line(p: QPainter, a: QPointF, b: QPointF, color: str,
                   width: float = 1.2, glow: int = 2, alpha: int = 255) -> None:
    for i in range(glow, 0, -1):
        ga = int(alpha * 0.18 * (1.0 - (i - 1) / glow))
        p.setPen(QPen(qcol(color, ga), width + i * 2.0))
        p.drawLine(a, b)
    p.setPen(QPen(qcol(color, alpha), width))
    p.drawLine(a, b)


def notched_path(rect: QRectF, cut: float = 9.0) -> QPainterPath:
    """Panel silhouette with sci-fi cut corners (TL square, TR/BL cut, BR square)."""
    c = min(cut, rect.width() / 4, rect.height() / 4)
    x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
    path = QPainterPath()
    path.moveTo(x0, y0)
    path.lineTo(x1 - c, y0)
    path.lineTo(x1, y0 + c)
    path.lineTo(x1, y1)
    path.lineTo(x0 + c, y1)
    path.lineTo(x0, y1 - c)
    path.closeSubpath()
    return path


def draw_circular_text(p: QPainter, cx: float, cy: float, radius: float,
                       text: str, color: str, size: int = 7,
                       angle_offset: float = 0.0, alpha: int = 200,
                       spacing_deg: float | None = None) -> None:
    """Characters laid around a circle (rotating ring labels, à la arc-reactor)."""
    if not text:
        return
    n = len(text)
    step = spacing_deg if spacing_deg is not None else 360.0 / n
    p.setFont(hud_font(size, True))
    p.setPen(QPen(qcol(color, alpha), 1))
    for i, ch in enumerate(text):
        ang = angle_offset + i * step
        p.save()
        p.translate(cx, cy)
        p.rotate(ang)
        p.translate(0, -radius)
        p.drawText(QRectF(-6, -6, 12, 12), Qt.AlignmentFlag.AlignCenter, ch)
        p.restore()


def serial_for(name: str) -> str:
    """Deterministic decorative hex serial per widget title (stable, not random)."""
    h = 0
    for ch in name:
        h = (h * 131 + ord(ch)) & 0xFFFF
    return f"{h:04X}"


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def metric_color(pct: float) -> str:
    """Standard load coloring: cyan → amber > 80% → red > 95%."""
    if pct >= 95:
        return C.RED
    if pct >= 80:
        return C.ARC
    return C.PRI
