"""Gallery demo registrations for the Phase 2 instrument primitives."""

from __future__ import annotations

import random

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ui.theme import C
from ui.widgets.base import anim_clock
from ui.widgets import gauges, dials, audio, camera_ring


class _Paint(QWidget):
    """Minimal animated host that calls a paint fn(p, rect)."""

    def __init__(self, fn):
        super().__init__()
        self._fn = fn
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        anim_clock().tick.connect(self.update)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._fn(self, p, QRectF(self.rect()).adjusted(4, 4, -4, -4))


def demos() -> list[dict]:
    out: list[dict] = []

    # Ring gauge
    rg = gauges.RingGauge("CPU", C.PRI)
    out.append({"title": "RingGauge", "make": lambda: rg,
                "controls": [("load", 0, 100, 35, lambda w, v: w.set_value(v))]})

    # Arc gauge
    arc = _Paint(lambda w, p, r: gauges.paint_arc_gauge(p, r, w._v, label="TEMP", color=C.ARC))
    arc._v = 50
    out.append({"title": "ArcGauge", "make": lambda: arc,
                "controls": [("val", 0, 100, 50, lambda w, v: setattr(w, "_v", v))]})

    # Sparkline (auto, biased by slider)
    spark = gauges.Sparkline(C.GREEN)
    spark._bias = 20

    def _spark_tick():
        spark.push(max(0, spark._bias + random.uniform(-10, 10)))
    anim_clock().tick.connect(lambda: _spark_tick() if random.random() < 0.3 else None)
    out.append({"title": "Sparkline (net)", "make": lambda: spark,
                "controls": [("bias", 0, 100, 20, lambda w, v: setattr(w, "_bias", v))]})

    # Compass
    comp = _Paint(lambda w, p, r: dials.paint_compass(p, r, w._h, speed_text=f"{w._h:.0f}° 12km/h"))
    comp._h = 90
    out.append({"title": "CompassDial", "make": lambda: comp,
                "controls": [("dir", 0, 359, 90, lambda w, v: setattr(w, "_h", v))]})

    # Battery
    batt = _Paint(lambda w, p, r: dials.paint_battery_arc(p, r, w._p, w._p > 50))
    batt._p = 72
    out.append({"title": "BatteryArc", "make": lambda: batt,
                "controls": [("pct", 0, 100, 72, lambda w, v: setattr(w, "_p", v))]})

    # Sun arc
    sun = _Paint(lambda w, p, r: dials.paint_sun_arc(p, r, w._f / 100.0, w._f < 90))
    sun._f = 40
    out.append({"title": "SunArc", "make": lambda: sun,
                "controls": [("day%", 0, 100, 40, lambda w, v: setattr(w, "_f", v))]})

    # Radar
    radar = dials.RadarScope()
    radar.set_blips([
        {"bearing": 45, "distance_km": 1200, "mag": None},
        {"bearing": 200, "distance_km": 6000, "mag": None},
        {"bearing": 310, "distance_km": 9000, "mag": None},
    ])
    out.append({"title": "RadarScope (ISS)", "make": lambda: radar, "controls": []})

    # Radar quakes
    radar2 = dials.RadarScope()
    radar2.set_mode("quakes")
    radar2.set_blips([
        {"bearing": 30, "distance_km": 800, "mag": 5.4, "place": "demo"},
        {"bearing": 150, "distance_km": 3000, "mag": 3.1, "place": "demo"},
        {"bearing": 270, "distance_km": 5000, "mag": 4.2, "place": "demo"},
    ])
    out.append({"title": "RadarScope (quakes)", "make": lambda: radar2, "controls": []})

    # Spectrum
    spec = audio.SpectrumBars(24)
    spec.set_speaking(True)
    out.append({"title": "SpectrumBars", "make": lambda: spec,
                "controls": [("speak", 0, 1, 1, lambda w, v: w.set_speaking(bool(v)))]})

    # Camera (live)
    out.append({"title": "CircularViewport (live)", "make": lambda: camera_ring.CircularViewport(), "controls": []})

    # Reactor orb (state-driven)
    from pathlib import Path
    from ui.widgets.reactor import ReactorOrb
    from ui.services.audio_level import audio_level
    face = str(Path(__file__).resolve().parent.parent.parent / "face.png")
    orb = ReactorOrb(face)
    _states = ["LISTENING", "THINKING", "PROCESSING", "SPEAKING", "MUTED", "SLEEP"]

    def _set_state(w, v):
        w.set_state(_states[min(v, len(_states) - 1)])
    out.append({"title": "ReactorOrb", "make": lambda: orb,
                "controls": [("state", 0, len(_states) - 1, 0, _set_state)]})

    return out
