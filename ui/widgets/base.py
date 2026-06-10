"""Shared widget base classes and the single animation clock.

`AnimClock` is a process-wide ~30 fps heartbeat. Every animated widget connects
to its `tick` signal instead of owning its own QTimer, keeping the timer count
(and wakeups) constant no matter how many instruments are on screen.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ui.theme import (
    C, draw_glow_line, hud_font, notched_path, qcol, serial_for,
)

_DEFAULT_FPS = 30


class AnimClock(QObject):
    """One timer to drive them all."""

    tick = pyqtSignal()

    _instance: "AnimClock | None" = None

    def __init__(self, fps: int = _DEFAULT_FPS):
        super().__init__()
        self._fps = fps
        self._frame = 0
        self._reduced = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timeout)
        self._timer.start(int(1000 / fps))

    def _on_timeout(self) -> None:
        self._frame += 1
        self.tick.emit()

    @property
    def frame(self) -> int:
        return self._frame

    @property
    def fps(self) -> int:
        return self._fps

    @property
    def reduced_motion(self) -> bool:
        return self._reduced

    def set_reduced_motion(self, value: bool) -> None:
        """When True, widgets should freeze sweeps/rotation (still repaint on data)."""
        self._reduced = bool(value)
        # Slow the heartbeat in reduced-motion mode to cut idle wakeups.
        self._timer.setInterval(int(1000 / (8 if value else self._fps)))


def anim_clock() -> AnimClock:
    """Lazily create the shared clock (after QApplication exists)."""
    if AnimClock._instance is None:
        AnimClock._instance = AnimClock()
    return AnimClock._instance


class HudPanel(QWidget):
    """Base instrument panel: dark plate, corner brackets, optional title chip.

    Subclasses implement `paint_content(p, content_rect)`. Set `self.animated`
    True to subscribe to the shared clock and repaint every frame.
    """

    def __init__(
        self,
        title: str = "",
        parent: QWidget | None = None,
        *,
        animated: bool = False,
        accent: str = C.PRI,
        framed: bool = True,
        min_size: tuple[int, int] | None = None,
    ):
        super().__init__(parent)
        self.title = title
        self.accent = accent
        self.framed = framed
        self.animated = animated
        self._frame = 0
        self._reduced = False
        self._serial = serial_for(title) if title else ""
        self._shimmer_phase = int(self._serial or "0", 16) % 360
        self._chrome: QPixmap | None = None
        self._chrome_size = (0, 0)
        if min_size:
            self.setMinimumSize(QSize(*min_size))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        # Every panel rides the shared clock: animated panels repaint each frame,
        # the rest repaint at ~5 fps purely for the shimmer sheen.
        anim_clock().tick.connect(self._on_tick)

    def set_reduced_motion(self, v: bool) -> None:
        self._reduced = bool(v)

    # ----- animation -----
    def _on_tick(self) -> None:
        self._frame += 1
        if self.animated:
            self.on_tick(self._frame)
            self.update()
        elif self.framed and not self._reduced and self._frame % 6 == 0:
            self.update()

    def on_tick(self, frame: int) -> None:
        """Override to advance animation state (called before update)."""

    def _title_h(self) -> float:
        return 17.0 if self.title else 0.0

    # ----- cached chrome -----
    def _build_chrome(self, w: int, h: int) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, w - 2, h - 2)
        path = notched_path(rect, cut=9)

        # translucent fill so the backdrop ghosts through
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, qcol(C.STEEL_HI, 205))
        grad.setColorAt(1.0, qcol(C.STEEL_LO, 215))
        p.fillPath(path, QBrush(grad))
        p.setPen(QPen(qcol(C.BORDER_A, 220), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # inner top highlight
        p.setPen(QPen(qcol(C.BORDER_B, 90), 1))
        p.drawLine(QPointF(rect.x() + 10, rect.y() + 2), QPointF(rect.right() - 14, rect.y() + 2))

        # glowing accent segment on the top edge
        draw_glow_line(p, QPointF(rect.x() + 8, rect.y() + 1),
                       QPointF(rect.x() + 8 + rect.width() * 0.40, rect.y() + 1),
                       self.accent, width=2.0, glow=2, alpha=220)

        # left-edge micro tick stack
        p.setPen(QPen(qcol(self.accent, 120), 1))
        for k in range(6):
            ty = rect.y() + 24 + k * 7
            if ty < rect.bottom() - 6:
                p.drawLine(QPointF(rect.x() + 2, ty), QPointF(rect.x() + 5, ty))

        # corner ticks (bottom-right square corner accent)
        p.setPen(QPen(qcol(self.accent, 150), 1.4))
        p.drawLine(QPointF(rect.right() - 12, rect.bottom()), QPointF(rect.right(), rect.bottom()))
        p.drawLine(QPointF(rect.right(), rect.bottom() - 12), QPointF(rect.right(), rect.bottom()))

        # title row
        if self.title:
            p.setBrush(QBrush(qcol(self.accent)))
            p.setPen(Qt.PenStyle.NoPen)
            dcx, dcy = rect.x() + 12, rect.y() + 9
            p.drawConvexPolygon(QPointF(dcx, dcy - 3), QPointF(dcx + 3, dcy),
                                QPointF(dcx, dcy + 3), QPointF(dcx - 3, dcy))
            p.setFont(hud_font(7, True))
            p.setPen(QPen(qcol(self.accent, 230), 1))
            p.drawText(QRectF(rect.x() + 20, rect.y() + 3, rect.width() - 70, 13),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title)
            p.setPen(QPen(qcol(C.TEXT_DIM, 160), 1))
            p.setFont(hud_font(6, True))
            p.drawText(QRectF(rect.right() - 52, rect.y() + 3, 48, 13),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"·{self._serial}")
            # underline fading right
            ug = QLinearGradient(rect.x() + 20, 0, rect.right() - 8, 0)
            ug.setColorAt(0.0, qcol(self.accent, 150))
            ug.setColorAt(1.0, qcol(self.accent, 0))
            p.setPen(QPen(QBrush(ug), 1))
            p.drawLine(QPointF(rect.x() + 20, rect.y() + 16), QPointF(rect.right() - 8, rect.y() + 16))
        p.end()
        return pm

    # ----- painting -----
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        rect = QRectF(1, 1, W - 2, H - 2)

        if self.framed:
            if self._chrome is None or self._chrome_size != (W, H):
                self._chrome = self._build_chrome(W, H)
                self._chrome_size = (W, H)
            p.drawPixmap(0, 0, self._chrome)
            self._paint_shimmer(p, rect)
            self._paint_status_edge(p, rect)

        title_h = self._title_h()
        content = QRectF(rect.x() + 5, rect.y() + title_h + 2,
                         rect.width() - 10, rect.height() - title_h - 7)
        try:
            self.paint_content(p, content)
        except Exception as e:  # never let a paint bug kill the whole HUD
            p.setPen(QPen(qcol(C.RED), 1))
            p.setFont(hud_font(7))
            p.drawText(content, Qt.AlignmentFlag.AlignCenter, f"paint err\n{type(e).__name__}")

    def _paint_shimmer(self, p: QPainter, rect: QRectF) -> None:
        if self._reduced:
            return
        span = rect.width() + 240
        pos = ((self._frame * 1.4 + self._shimmer_phase) % span) - 120
        grad = QLinearGradient(pos - 55, rect.y(), pos + 55, rect.bottom())
        grad.setColorAt(0.0, qcol(C.GLOW, 0))
        grad.setColorAt(0.5, qcol(C.GLOW, 16))
        grad.setColorAt(1.0, qcol(C.GLOW, 0))
        p.save()
        p.setClipPath(notched_path(rect, cut=9))
        p.fillRect(rect, QBrush(grad))
        p.restore()

    def _paint_status_edge(self, p: QPainter, rect: QRectF) -> None:
        col = self._status_color()
        if not col:
            return
        p.setPen(QPen(qcol(col, 230), 2))
        p.drawLine(QPointF(rect.x() + 1, rect.y() + 18),
                   QPointF(rect.x() + 1, rect.bottom() - 4))

    def _status_color(self) -> str | None:
        """Override (DataPanel) to tint the left edge by service status."""
        return None

    def paint_content(self, p: QPainter, rect: QRectF) -> None:
        """Override to draw the instrument body within `rect`."""


class DataPanel(HudPanel):
    """HudPanel bound to a PolledService: stores latest snapshot + status."""

    def __init__(self, title="", parent=None, *, accent=C.PRI, animated=False,
                 framed=True, min_size=None):
        super().__init__(title, parent, accent=accent, animated=animated,
                         framed=framed, min_size=min_size)
        self.data: dict | None = None
        self.status_str = "offline"

    def bind(self, service) -> "DataPanel":
        service.updated.connect(self._on_data)
        service.status.connect(self._on_status)
        if isinstance(service.last_good, dict):
            self.data = service.last_good
            self.status_str = "stale"
        return self

    def _on_data(self, snap) -> None:
        if isinstance(snap, dict):
            self.data = snap
            self.update()

    def _on_status(self, status: str) -> None:
        self.status_str = status
        self.update()

    @property
    def online(self) -> bool:
        return self.status_str == "ok"

    def _status_color(self) -> str | None:
        return {"ok": C.GREEN, "stale": C.ARC, "offline": C.RED}.get(self.status_str)


def draw_no_link(p: QPainter, rect: QRectF, label: str = "NO LINK") -> None:
    """Standard offline placeholder for data widgets."""
    p.setPen(QPen(qcol(C.TEXT_DIM), 1))
    cx, cy = rect.center().x(), rect.center().y()
    p.drawLine(int(cx - 14), int(cy), int(cx + 14), int(cy))
    p.drawLine(int(cx), int(cy - 14), int(cx), int(cy + 14))
    p.setFont(hud_font(7, True))
    p.setPen(QPen(qcol(C.MUTED_C, 200), 1))
    p.drawText(
        QRectF(rect.x(), cy + 8, rect.width(), 14),
        Qt.AlignmentFlag.AlignHCenter,
        label,
    )
