"""Cockpit layout — composes the HUD 2.0 instrument cluster.

build_cockpit(win, hub) creates every widget, binds it to its service, stores
references as attributes on `win`, and returns the central QWidget. Responsive
breakpoints hide secondary instruments on smaller windows.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from ui.theme import C, hud_font
from ui.widgets.backdrop import BackdropContainer
from ui.widgets.fx import ScanlineOverlay, TickerStrip
from ui.widgets.chrome import HeaderStrip, LinkStatus
from ui.widgets.comms import (
    ChevronBar, CommandInput, CommsControls, FileDropPod, LogConsole, NeuralTrace,
)
from ui.widgets.reactor import ReactorOrb
from ui.widgets.audio import SpectrumBars
from ui.widgets.camera_ring import CircularViewport
from ui.widgets.system import CoreGrid, DiskDonut, GaugeTrio, NetSparkline, PowerArc
from ui.widgets.tracking import RadarPanel
from ui.widgets.weather import WeatherMini, WindCompass

_LEFT_W = 220
_RIGHT_W = 336


def _column(width: int | None = None) -> tuple[QFrame, QVBoxLayout]:
    col = QFrame()
    if width:
        col.setFixedWidth(width)
    # transparent so the animated backdrop circuitry glows through the gutters
    col.setStyleSheet("background: transparent; border: none;")
    lay = QVBoxLayout(col)
    lay.setContentsMargins(8, 6, 8, 6)
    lay.setSpacing(8)
    return col, lay


def _titled(title: str, widget: QWidget, accent: str = C.GLOW) -> QFrame:
    """Wrap a bare widget (e.g. a console) with a cockpit-style header label."""
    box = QFrame()
    box.setStyleSheet("background: transparent; border: none;")
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(2)
    lbl = QLabel(f"◈ {title}")
    lbl.setFont(hud_font(7, True))
    lbl.setStyleSheet(f"color: {accent}; background: transparent;")
    v.addWidget(lbl)
    v.addWidget(widget, stretch=1)
    return box


def build_cockpit(win, hub) -> QWidget:
    central = BackdropContainer()
    win._central = central
    root = QVBoxLayout(central)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    # ---- header ----
    win.header = HeaderStrip().bind_hub(hub)
    win.header.setFixedHeight(54)
    root.addWidget(win.header)

    body = QHBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(0)

    # ---- LEFT: system telemetry ----
    left, ll = _column(_LEFT_W)
    win.gauge_trio = GaugeTrio().bind(hub.metrics)
    win.gauge_trio.setFixedHeight(118)
    win.core_grid = CoreGrid().bind(hub.metrics)
    win.core_grid.setFixedHeight(104)
    win.net_spark = NetSparkline().bind_network(hub.network)
    win.net_spark.setFixedHeight(94)
    # throughput history grows on each metrics sample → repaint then (no 30fps churn)
    hub.metrics.updated.connect(lambda *_: win.net_spark.update())
    win.disk = DiskDonut().bind(hub.metrics)
    win.disk.setFixedHeight(120)
    win.power = PowerArc().bind(hub.metrics)
    win.power.setFixedHeight(108)
    for w in (win.gauge_trio, win.core_grid, win.net_spark, win.disk, win.power):
        ll.addWidget(w)
    ll.addStretch()
    body.addWidget(left)

    # ---- CENTER: camera + reactor (top), radar + environment (bottom) ----
    center, cl = _column()
    center.setStyleSheet("background: transparent; border: none;")

    top = QHBoxLayout()
    top.setSpacing(6)
    win.camera = CircularViewport()
    win.camera.setMinimumSize(180, 180)
    win.camera.setMaximumWidth(230)
    win.camera.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
    top.addWidget(win.camera, stretch=2)
    win.reactor = ReactorOrb(win._face_path)
    top.addWidget(win.reactor, stretch=5)
    cl.addLayout(top, stretch=5)

    # audio spectrum strip (W8) — comms-open indicator
    win.spectrum = SpectrumBars(28)
    win.spectrum.setFixedHeight(40)
    cl.addWidget(win.spectrum)

    bottom = QHBoxLayout()
    bottom.setSpacing(6)
    win.radar = RadarPanel(hub)
    win.radar.setMinimumWidth(200)
    win.radar.setMaximumWidth(260)
    bottom.addWidget(win.radar, stretch=2)

    env, el = _column()
    env.setStyleSheet("background: transparent; border: none;")
    # NEURAL TRACE (LLM thinking output) takes the prominent slot
    win.trace = NeuralTrace()
    el.addWidget(_titled("NEURAL TRACE", win.trace, accent=C.ARC), stretch=3)
    dials_row = QHBoxLayout()
    dials_row.setSpacing(6)
    win.wind = WindCompass().bind(hub.weather)
    win.weather = WeatherMini().bind_service(hub.weather)  # weather replaces sun/moon
    win.link = LinkStatus().bind(hub.network)
    win.link.setFixedHeight(60)
    dials_row.addWidget(win.wind)
    dials_row.addWidget(win.weather)
    el.addLayout(dials_row, stretch=2)
    el.addWidget(win.link)
    bottom.addWidget(env, stretch=4)
    cl.addLayout(bottom, stretch=4)

    body.addWidget(center, stretch=1)

    # ---- RIGHT: chat console (non-thinking output) ----
    right, rl = _column(_RIGHT_W)
    win.log = LogConsole()
    rl.addWidget(_titled("MISSION LOG", win.log), stretch=1)

    pod_row = QHBoxLayout()
    pod_row.setSpacing(6)
    win.drop = FileDropPod()
    win.drop.setFixedSize(108, 108)
    pod_row.addWidget(win.drop)
    win.controls = CommsControls()
    pod_row.addWidget(win.controls, stretch=1)
    rl.addLayout(pod_row)

    win.cmd = CommandInput()
    rl.addWidget(win.cmd)
    body.addWidget(right)

    root.addLayout(body, stretch=1)

    # ---- footer: live data ticker framed by chevrons ----
    root.addWidget(_footer(win, hub))

    # ---- top overlay: scanlines + armatures + scan band (click-through) ----
    win.scanlines = ScanlineOverlay(central)
    win.scanlines.show()

    # widgets hidden at narrower widths
    win._bp_medium = [win.core_grid]               # hidden < 1280
    win._bp_small = [left]                          # left column hidden < 1024
    return central


def _footer(win, hub) -> QWidget:
    w = QWidget()
    w.setFixedHeight(22)
    w.setStyleSheet(f"background: rgba(0,4,8,0.85); border-top: 1px solid {C.BORDER};")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(10, 0, 10, 0)
    lay.setSpacing(8)
    lhs = QLabel("‹‹")
    lhs.setFont(hud_font(9, True))
    lhs.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
    lay.addWidget(lhs)
    win.ticker = TickerStrip(hub)
    lay.addWidget(win.ticker, stretch=1)
    rhs = QLabel("››")
    rhs.setFont(hud_font(9, True))
    rhs.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
    lay.addWidget(rhs)
    return w


def _legacy_footer() -> QWidget:
    w = QWidget()
    w.setFixedHeight(22)
    w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
    lay = QHBoxLayout(w)
    lay.setContentsMargins(14, 0, 14, 0)

    def _fl(txt, color=C.TEXT_MED):
        lbl = QLabel(txt)
        lbl.setFont(hud_font(7))
        lbl.setStyleSheet(f"color: {color}; background: transparent;")
        return lbl

    lay.addWidget(_fl("[F4] Comms  ·  [F11] Fullscreen  ·  [Ctrl+M] Compact  ·  [Ctrl+,] Settings"))
    lay.addStretch()
    lay.addWidget(_fl("E.M.I.L.Y.  ·  COCKPIT HUD v2", C.PRI_DIM))
    lay.addStretch()
    lay.addWidget(_fl("◈ CLASSIFIED", C.ARC))
    return w


def apply_breakpoints(win, width: int) -> None:
    medium = width >= 1280
    small = width >= 1024
    for w in getattr(win, "_bp_medium", []):
        w.setVisible(medium)
    for w in getattr(win, "_bp_small", []):
        w.setVisible(small)
