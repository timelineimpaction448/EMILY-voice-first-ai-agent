"""Situational trackers: ISS live position and recent earthquakes (USGS).

Both compute bearing + great-circle distance from the user's origin so the radar
scope can plot blips. ISS polls fast but only while active (radar visible & in
ISS mode); quakes poll slowly.
"""

from __future__ import annotations

import math
import time

from ui.services.base import PolledService
from ui.services.http import get_json

_ISS = "http://api.open-notify.org/iss-now.json"
_QUAKES = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
_EARTH_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


class _OriginMixin:
    _origin: tuple[float, float] | None = None

    def set_origin(self, lat: float, lon: float) -> None:
        self._origin = (lat, lon)

    def _relative(self, lat: float, lon: float) -> dict:
        if not self._origin:
            return {"bearing": 0.0, "distance_km": None}
        olat, olon = self._origin
        return {
            "bearing": bearing_deg(olat, olon, lat, lon),
            "distance_km": haversine_km(olat, olon, lat, lon),
        }


class ISSService(_OriginMixin, PolledService):
    def __init__(self, interval: float = 5.0):
        super().__init__(interval, name="iss")
        self._active = False  # hub turns on when radar is showing ISS

    def poll(self) -> dict:
        data = get_json(_ISS, timeout=4.0)
        pos = data.get("iss_position", {})
        lat = float(pos.get("latitude"))
        lon = float(pos.get("longitude"))
        rel = self._relative(lat, lon)
        return {
            "lat": lat,
            "lon": lon,
            "bearing": rel["bearing"],
            "distance_km": rel["distance_km"],
            "timestamp": data.get("timestamp", time.time()),
        }


class QuakeService(_OriginMixin, PolledService):
    def __init__(self, interval: float = 600.0):
        super().__init__(interval, name="quakes", cache_key="quakes", cache_ttl=3600)

    def poll(self) -> dict:
        data = get_json(_QUAKES, timeout=6.0)
        feats = data.get("features", []) or []
        events = []
        for f in feats[:40]:
            try:
                lon, lat = f["geometry"]["coordinates"][0], f["geometry"]["coordinates"][1]
                props = f.get("properties", {})
                rel = self._relative(lat, lon)
                events.append({
                    "lat": lat,
                    "lon": lon,
                    "mag": props.get("mag"),
                    "place": props.get("place", ""),
                    "time": props.get("time"),
                    "bearing": rel["bearing"],
                    "distance_km": rel["distance_km"],
                })
            except (KeyError, IndexError, TypeError):
                continue
        # Strongest first.
        events.sort(key=lambda e: (e["mag"] or 0), reverse=True)
        return {"count": len(events), "events": events}
