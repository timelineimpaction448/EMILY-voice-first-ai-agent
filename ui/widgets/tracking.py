"""Radar panel (W13): live ISS / earthquake tracking on the radar scope."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ui.theme import C, hud_font
from ui.widgets.dials import RadarScope


class RadarPanel(QWidget):
    """Toggles between ISS live position and recent USGS earthquakes."""

    blip_info = pyqtSignal(str)

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self._mode = getattr(hub, "radar_mode", "iss")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(2)

        self._hdr = QLabel()
        self._hdr.setFont(hud_font(7, True))
        self._hdr.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hdr.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
        self._hdr.mousePressEvent = lambda e: self.toggle_mode()
        lay.addWidget(self._hdr)

        self.scope = RadarScope()
        self.scope.blip_clicked.connect(self._on_blip)
        lay.addWidget(self.scope, stretch=1)

        hub.iss.updated.connect(self._on_iss)
        hub.quakes.updated.connect(self._on_quakes)
        self.set_mode(self._mode)

    def set_mode(self, mode: str):
        self._mode = mode
        self.scope.set_mode(mode)
        self._hdr.setText(f"◈ RADAR · {'ISS ORBIT' if mode == 'iss' else 'SEISMIC 24H'}")
        self.hub.set_radar_mode(mode, visible=self.isVisible())
        # repaint with whatever the active service already has
        src = self.hub.iss if mode == "iss" else self.hub.quakes
        if isinstance(src.last_good, dict):
            (self._on_iss if mode == "iss" else self._on_quakes)(src.last_good)
        else:
            self.scope.set_blips([])

    def toggle_mode(self):
        self.set_mode("quakes" if self._mode == "iss" else "iss")

    def set_reduced_motion(self, v: bool):
        self.scope.set_reduced_motion(v)

    def showEvent(self, e):
        self.hub.set_radar_visible(True)
        super().showEvent(e)

    def hideEvent(self, e):
        self.hub.set_radar_visible(False)
        super().hideEvent(e)

    def _on_iss(self, snap):
        if self._mode != "iss" or not isinstance(snap, dict):
            return
        self.scope.set_blips([{
            "bearing": snap.get("bearing", 0),
            "distance_km": snap.get("distance_km"),
            "label": "ISS",
            "lat": snap.get("lat"), "lon": snap.get("lon"),
        }])

    def _on_quakes(self, snap):
        if self._mode != "quakes" or not isinstance(snap, dict):
            return
        self.scope.set_blips(snap.get("events", []))

    def _on_blip(self, b: dict):
        if self._mode == "iss":
            lat, lon = b.get("lat"), b.get("lon")
            dist = b.get("distance_km")
            msg = f"ISS: {lat:.1f}, {lon:.1f}"
            if dist:
                msg += f"  ·  {dist:.0f} km away"
        else:
            mag = b.get("mag")
            place = b.get("place", "")
            when = ""
            if b.get("time"):
                try:
                    when = datetime.fromtimestamp(b["time"] / 1000).strftime("%d %b %H:%M")
                except Exception:
                    pass
            msg = f"M{mag} {place} ({when})" if mag else place
        self.blip_info.emit(msg)
