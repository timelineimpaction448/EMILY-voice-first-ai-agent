"""System telemetry widgets bound to SystemMetricsService / NetworkService."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ui.theme import C, hud_font, digital_font, qcol, metric_color
from ui.widgets.base import DataPanel, anim_clock, draw_no_link
from ui.widgets.gauges import paint_ring_gauge, paint_sparkline


class GaugeTrio(DataPanel):
    """CPU / RAM / GPU ring gauges in a row. GPU auto-hides when absent."""

    def __init__(self, parent=None):
        super().__init__("CORE VITALS", parent, accent=C.PRI)

    def paint_content(self, p: QPainter, rect: QRectF):
        if not self.data:
            draw_no_link(p, rect, "BOOTING")
            return
        cpu = self.data.get("cpu", 0.0)
        mem = self.data.get("mem_pct", 0.0)
        gpu = self.data.get("gpu")
        items = [("CPU", cpu, metric_color(cpu), None)]
        items.append(("RAM", mem, metric_color(mem),
                      f"{self.data.get('mem_used_gb', 0):.1f}G"))
        if gpu:
            items.append(("GPU", gpu.get("util", 0), metric_color(gpu.get("util", 0)), None))
        n = len(items)
        gw = rect.width() / n
        for i, (label, val, color, text) in enumerate(items):
            cell = QRectF(rect.x() + i * gw, rect.y(), gw, rect.height())
            paint_ring_gauge(p, cell.adjusted(4, 2, -4, -2), val, label=label,
                             text=text, color=color)


class CoreGrid(DataPanel):
    """Per-logical-core mini ring gauges (aggregated beyond a cap)."""

    MAX_RINGS = 8

    def __init__(self, parent=None):
        super().__init__("CORES", parent, accent=C.PRI_DIM)

    def paint_content(self, p: QPainter, rect: QRectF):
        if not self.data:
            draw_no_link(p, rect, "—")
            return
        cores = list(self.data.get("per_core", []))
        if not cores:
            return
        if len(cores) > self.MAX_RINGS:
            # aggregate extras into the last cell as an average
            head = cores[:self.MAX_RINGS - 1]
            tail = cores[self.MAX_RINGS - 1:]
            cores = head + [sum(tail) / len(tail)]
        n = len(cores)
        cols = min(n, 4)
        rows = math.ceil(n / cols)
        cw = rect.width() / cols
        ch = rect.height() / rows
        for i, v in enumerate(cores):
            r = i // cols
            c = i % cols
            cell = QRectF(rect.x() + c * cw, rect.y() + r * ch, cw, ch)
            paint_ring_gauge(p, cell.adjusted(3, 3, -3, -3), v, text=f"{v:.0f}",
                             color=metric_color(v), thickness=0.16, ticks=False)


class DiskDonut(DataPanel):
    """Disk usage donut; click cycles partitions."""

    def __init__(self, parent=None):
        super().__init__("STORAGE", parent, accent=C.PURPLE)
        self._idx = 0
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, e):
        disks = (self.data or {}).get("disks", [])
        if disks:
            self._idx = (self._idx + 1) % len(disks)
            self.update()

    def paint_content(self, p: QPainter, rect: QRectF):
        disks = (self.data or {}).get("disks", [])
        if not disks:
            draw_no_link(p, rect, "—")
            return
        d = disks[self._idx % len(disks)]
        pct = d.get("pct", 0)
        s = min(rect.width(), rect.height())
        sq = QRectF(rect.center().x() - s / 2, rect.y() + 2, s - 4, s - 4)
        cx, cy = sq.center().x(), sq.center().y()
        pen_w = max(5.0, s * 0.13)
        inset = pen_w / 2 + 2
        arc = QRectF(sq.x() + inset, sq.y() + inset, sq.width() - 2 * inset, sq.height() - 2 * inset)
        p.setPen(QPen(qcol(C.BORDER, 150), pen_w))
        p.drawArc(arc, 0, 360 * 16)
        p.setPen(QPen(qcol(metric_color(pct)), pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(arc, 90 * 16, -int(pct / 100 * 360) * 16)
        p.setFont(digital_font(max(9, int(s * 0.16))))
        p.setPen(QPen(qcol(C.WHITE), 1))
        p.drawText(sq, Qt.AlignmentFlag.AlignCenter, f"{pct:.0f}%")
        p.setFont(hud_font(7, True))
        p.setPen(QPen(qcol(C.PURPLE, 220), 1))
        mount = d.get("mount", "")
        p.drawText(QRectF(sq.x(), cy + s * 0.16, sq.width(), s * 0.16),
                   Qt.AlignmentFlag.AlignHCenter, mount[:12])
        p.setFont(hud_font(6))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(rect.x(), rect.bottom() - 12, rect.width(), 12),
                   Qt.AlignmentFlag.AlignHCenter,
                   f"{d.get('used_gb',0):.0f}/{d.get('total_gb',0):.0f} GB  ·  {self._idx+1}/{len(disks)}")


class NetSparkline(DataPanel):
    """Down/up throughput sparklines from NetworkService history + live readout."""

    def __init__(self, parent=None):
        # Not frame-animated: the series only changes on each metrics sample (~2s),
        # so we repaint when the hub pushes new throughput (wired in layout.py).
        super().__init__("NET FLOW", parent, accent=C.GREEN, animated=False)
        self._net = None

    def bind_network(self, net_service) -> "NetSparkline":
        self._net = net_service
        return self

    def paint_content(self, p: QPainter, rect: QRectF):
        if self._net is None:
            draw_no_link(p, rect)
            return
        down = self._net.down_history
        up = self._net.up_history
        graph = QRectF(rect.x(), rect.y(), rect.width(), rect.height() - 16)
        peak = max([1.0] + down + up)
        paint_sparkline(p, graph, down, color=C.GREEN, max_val=peak, baseline_grid=True)
        paint_sparkline(p, graph, up, color=C.ARC, max_val=peak, fill=False, baseline_grid=False)
        dnow = down[-1] if down else 0.0
        unow = up[-1] if up else 0.0
        p.setFont(hud_font(7, True))
        p.setPen(QPen(qcol(C.GREEN), 1))
        p.drawText(QRectF(rect.x(), rect.bottom() - 14, rect.width() / 2, 13),
                   Qt.AlignmentFlag.AlignLeft, f"▼ {self._fmt(dnow)}")
        p.setPen(QPen(qcol(C.ARC), 1))
        p.drawText(QRectF(rect.center().x(), rect.bottom() - 14, rect.width() / 2, 13),
                   Qt.AlignmentFlag.AlignRight, f"▲ {self._fmt(unow)}")

    @staticmethod
    def _fmt(mbs: float) -> str:
        if mbs < 1.0:
            return f"{mbs*1024:.0f} KB/s"
        return f"{mbs:.1f} MB/s"


class PowerArc(DataPanel):
    """Battery arc, or uptime dial on battery-less machines."""

    def __init__(self, parent=None):
        # Battery/uptime change slowly — repaint on metrics update, not per frame.
        super().__init__("POWER", parent, accent=C.GREEN, animated=False)

    def paint_content(self, p: QPainter, rect: QRectF):
        from ui.widgets.dials import paint_battery_arc, paint_uptime_dial
        if not self.data:
            draw_no_link(p, rect, "—")
            return
        batt = self.data.get("battery")
        if batt:
            paint_battery_arc(p, rect, batt.get("percent", 0), batt.get("plugged", False))
        else:
            paint_uptime_dial(p, rect, self.data.get("uptime_sec", 0))
