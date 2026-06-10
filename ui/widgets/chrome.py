"""HUD chrome: link-status array (W14) and header strip (W20)."""

from __future__ import annotations

import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ui.theme import C, hud_font, digital_font, qcol
from ui.widgets.base import DataPanel, anim_clock


def _latency_color(ms: float | None) -> str:
    if ms is None:
        return C.MUTED_C
    if ms < 40:
        return C.GREEN
    if ms < 120:
        return C.ARC
    return C.RED


class LinkStatus(DataPanel):
    """Uplink telemetry: latency lamp, public IP, online/offline banner."""

    def __init__(self, parent=None):
        super().__init__("UPLINK", parent, accent=C.GREEN, animated=True)

    def paint_content(self, p: QPainter, rect: QRectF):
        online = self.online and self.data and self.data.get("online")
        ms = (self.data or {}).get("latency_ms") if online else None
        ip = (self.data or {}).get("public_ip") if self.data else None
        lamp = _latency_color(ms)

        # status lamp (pulsing when online)
        pulse = 0.5 + 0.5 * abs((anim_clock().frame % 40) / 40.0 - 0.5) * 2
        a = int(120 + 135 * pulse) if online else 180
        p.setBrush(QBrush(qcol(lamp, a)))
        p.setPen(QPen(qcol(C.GLOW, 80), 1))
        p.drawEllipse(QRectF(rect.x() + 2, rect.y() + 2, 12, 12))

        p.setFont(hud_font(8, True))
        p.setPen(QPen(qcol(lamp), 1))
        p.drawText(QRectF(rect.x() + 20, rect.y(), rect.width() - 20, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "LINK ONLINE" if online else "OFFLINE")

        p.setFont(digital_font(9))
        p.setPen(QPen(qcol(C.WHITE), 1))
        lat = "-- ms" if ms is None else f"{ms:.0f} ms"
        p.drawText(QRectF(rect.x(), rect.y() + 18, rect.width(), 16),
                   Qt.AlignmentFlag.AlignLeft, f"PING  {lat}")

        p.setFont(hud_font(7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(rect.x(), rect.y() + 34, rect.width(), 14),
                   Qt.AlignmentFlag.AlignLeft, f"IP  {ip or '—'}")


class HeaderStrip(DataPanel):
    """Title, live clock/date, session uptime, voice pipeline, state word."""

    def __init__(self, parent=None):
        super().__init__("", parent, accent=C.PRI, animated=True, framed=False)
        self._state = "INITIALISING"
        self._pipeline = ""
        self._start = time.time()
        self._hub = None
        self.setMinimumHeight(52)

    def bind_hub(self, hub):
        self._hub = hub
        return self

    def set_state(self, state: str):
        self._state = state

    def set_pipeline(self, label: str):
        self._pipeline = label

    def _status_dots(self, p: QPainter, rect: QRectF):
        if not self._hub:
            return
        services = [
            ("SYS", self._hub.metrics), ("NET", self._hub.network),
            ("WX", self._hub.weather), ("TRK", self._hub.iss),
        ]
        col_map = {"ok": C.GREEN, "stale": C.ARC, "offline": C.RED}
        x = rect.center().x() - 90
        y = rect.y() + rect.height() - 12
        p.setFont(hud_font(6, True))
        for label, svc in services:
            s = getattr(svc, "status_str", "offline")
            c = col_map.get(s, C.TEXT_DIM)
            p.setBrush(QBrush(qcol(c, 230)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(x, y - 3, 6, 6))
            p.setPen(QPen(qcol(C.TEXT_DIM, 200), 1))
            p.drawText(QRectF(x + 9, y - 7, 30, 12), Qt.AlignmentFlag.AlignLeft, label)
            x += 46

    def paint_content(self, p: QPainter, rect: QRectF):
        # title with glow + underline
        title_rect = QRectF(rect.x() + 8, rect.y(), 260, rect.height())
        p.setFont(hud_font(18, True))
        for gw, ga in ((3, 40), (1, 255)):
            p.setPen(QPen(qcol(C.GLOW, ga), gw))
            p.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "E.M.I.L.Y.")
        ug = QLinearGradient(rect.x() + 10, 0, rect.x() + 150, 0)
        ug.setColorAt(0.0, qcol(C.PRI, 180))
        ug.setColorAt(1.0, qcol(C.PRI, 0))
        p.setPen(QPen(QBrush(ug), 1.4))
        p.drawLine(QPointF(rect.x() + 10, rect.y() + rect.height() - 18),
                   QPointF(rect.x() + 150, rect.y() + rect.height() - 18))
        # pipeline + state
        p.setFont(hud_font(8, True))
        p.setPen(QPen(qcol(C.PRI_DIM), 1))
        p.drawText(QRectF(rect.x() + 8, rect.y() + rect.height() - 16, 220, 14),
                   Qt.AlignmentFlag.AlignLeft,
                   f"PIPELINE {self._pipeline or '…'}   ·   {self._state}")
        # live service status dots
        self._status_dots(p, rect)
        # clock
        p.setFont(digital_font(17))
        p.setPen(QPen(qcol(C.ARC), 1))
        p.drawText(QRectF(rect.right() - 240, rect.y(), 232, 22),
                   Qt.AlignmentFlag.AlignRight, time.strftime("%H:%M:%S"))
        p.setFont(hud_font(7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        up = time.time() - self._start
        h = int(up // 3600); m = int((up % 3600) // 60); s = int(up % 60)
        p.drawText(QRectF(rect.right() - 240, rect.y() + 22, 232, 14),
                   Qt.AlignmentFlag.AlignRight,
                   f"{time.strftime('%a %d %b %Y')}   ·   SESSION {h:02d}:{m:02d}:{s:02d}")
