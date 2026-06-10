"""Dev-only widget gallery — renders every instrument with live controls.

Run via:  python -m ui.preview --gallery

Each demo is a dict:
    {
        "title": str,
        "make":  () -> QWidget,                  # the widget instance
        "controls": [ (label, lo, hi, init, setter) ],  # sliders -> setter(widget, value)
    }
New widgets register themselves by appending to build_demos().
"""

from __future__ import annotations

import time

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from ui.theme import C, hud_font
from ui.widgets.base import HudPanel, anim_clock


def build_demos() -> list[dict]:
    """Return the list of widget demos. Phases 2+ extend this."""
    demos: list[dict] = []

    # --- Phase 0: base panel sanity demo ---
    class _DemoPanel(HudPanel):
        def __init__(self):
            super().__init__("DEMO PANEL", animated=True, accent=C.PRI)
            self._v = 0.5

        def set_v(self, v):
            self._v = v

        def paint_content(self, p, rect):
            from PyQt6.QtGui import QBrush, QPen
            from ui.theme import qcol
            w = rect.width() * self._v
            p.setBrush(QBrush(qcol(C.PRI, 90)))
            p.setPen(QPen(qcol(C.GLOW), 1))
            p.drawRect(int(rect.x()), int(rect.y() + rect.height() - 10), int(w), 8)
            p.setFont(hud_font(8, True))
            p.setPen(QPen(qcol(C.TEXT), 1))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self._v*100:.0f}%")

    demos.append({
        "title": "HudPanel + AnimClock",
        "make": _DemoPanel,
        "controls": [("value", 0, 100, 50, lambda w, v: w.set_v(v / 100.0))],
    })

    # Phase 2 appends gauges/dials/audio/camera demos here:
    try:
        from ui.widgets import _gallery_extra
        demos.extend(_gallery_extra.demos())
    except Exception:
        pass

    return demos


class DemoCard(QWidget):
    def __init__(self, demo: dict):
        super().__init__()
        self.setFixedSize(240, 240)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(3)

        title = QLabel(demo["title"])
        title.setFont(hud_font(8, True))
        title.setStyleSheet(f"color: {C.GLOW}; background: transparent;")
        lay.addWidget(title)

        widget = demo["make"]()
        widget.setMinimumHeight(150)
        lay.addWidget(widget, stretch=1)

        for label, lo, hi, init, setter in demo.get("controls", []):
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFont(hud_font(6))
            lbl.setFixedWidth(46)
            lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            row.addWidget(lbl)
            sld = QSlider(Qt.Orientation.Horizontal)
            sld.setRange(lo, hi)
            sld.setValue(init)
            sld.valueChanged.connect(lambda v, w=widget, s=setter: s(w, v))
            row.addWidget(sld)
            lay.addLayout(row)
            setter(widget, init)

        self.setStyleSheet(f"background: {C.PANEL}; border: 1px solid {C.BORDER_A};")


class GalleryWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Emily HUD — Widget Gallery")
        self.resize(1100, 760)
        self.setStyleSheet(f"background: {C.BG};")

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)

        header = QHBoxLayout()
        h = QLabel("◈ INSTRUMENT GALLERY")
        h.setFont(hud_font(11, True))
        h.setStyleSheet(f"color: {C.GLOW}; background: transparent;")
        header.addWidget(h)
        header.addStretch()
        self._fps = QLabel("-- fps")
        self._fps.setFont(hud_font(9, True))
        self._fps.setStyleSheet(f"color: {C.ARC}; background: transparent;")
        header.addWidget(self._fps)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none;")
        inner = QWidget()
        grid = QGridLayout(inner)
        grid.setSpacing(8)
        demos = build_demos()
        for i, demo in enumerate(demos):
            grid.addWidget(DemoCard(demo), i // 4, i % 4)
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

        # FPS meter off the shared clock.
        self._last = time.time()
        self._frames = 0
        anim_clock().tick.connect(self._fps_tick)

    def _fps_tick(self) -> None:
        self._frames += 1
        now = time.time()
        if now - self._last >= 1.0:
            self._fps.setText(f"{self._frames / (now - self._last):.0f} fps")
            self._frames = 0
            self._last = now
