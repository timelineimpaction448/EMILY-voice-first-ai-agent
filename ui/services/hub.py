"""ServiceHub — owns all data services, wires cross-service data, lifecycle.

Widgets get their service from the hub; the MainWindow creates one hub and
starts it. Cross-wiring done here:
  - metrics throughput  -> network history (single sampling source)
  - weather location    -> tracker origins (radar distance/bearing)
"""

from __future__ import annotations

import sys
from pathlib import Path

from ui.services.audio_level import audio_level
from ui.services.network import NetworkService
from ui.services.system_metrics import SystemMetricsService
from ui.services.trackers import ISSService, QuakeService
from ui.services.weather import WeatherService

_BASE = Path(__file__).resolve().parent.parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))


def _read_cfg() -> dict:
    try:
        from core.config import load_user_config
        return load_user_config()
    except Exception:
        return {}


class ServiceHub:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg if cfg is not None else _read_cfg()
        units = "imperial" if str(cfg.get("weather_units", "metric")).lower() == "imperial" else "metric"
        location = str(cfg.get("weather_location", "auto") or "auto")
        self.radar_mode = str(cfg.get("radar_mode", "iss")).lower()

        self.metrics = SystemMetricsService()
        self.network = NetworkService()
        self.weather = WeatherService(units=units, location=location)
        self.iss = ISSService()
        self.quakes = QuakeService()
        self.audio = audio_level()

        self._started = False
        self._wire()

    def _wire(self) -> None:
        self.metrics.updated.connect(self._on_metrics)
        self.weather.updated.connect(self._on_weather)

    def _on_metrics(self, snap: object) -> None:
        if isinstance(snap, dict):
            self.network.push_throughput(snap.get("net_down_mbs", 0.0), snap.get("net_up_mbs", 0.0))

    def _on_weather(self, snap: object) -> None:
        if isinstance(snap, dict):
            loc = snap.get("location") or {}
            if "lat" in loc and "lon" in loc:
                self.iss.set_origin(loc["lat"], loc["lon"])
                self.quakes.set_origin(loc["lat"], loc["lon"])

    # ----- lifecycle -----
    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self.metrics.start()
        self.network.start()
        self.weather.start()
        self.quakes.start()
        self.iss.start()
        self.set_radar_mode(self.radar_mode, visible=False)
        # slow-interval services: fetch first data immediately instead of waiting
        # out the initial polling jitter (weather interval is 10 min).
        self.weather.request_now()
        self.network.request_now()
        self.quakes.request_now()

    def stop(self) -> None:
        for svc in (self.metrics, self.network, self.weather, self.iss, self.quakes):
            try:
                svc.stop()
            except Exception:
                pass
        self._started = False

    # ----- radar control -----
    def set_radar_mode(self, mode: str, *, visible: bool = True) -> None:
        self.radar_mode = mode
        # ISS only polls (fast) while the scope is visible and in ISS mode.
        self.iss.set_active(visible and mode == "iss")

    def set_radar_visible(self, visible: bool) -> None:
        self.iss.set_active(visible and self.radar_mode == "iss")


def _selftest() -> int:
    import json
    import time

    from PyQt6.QtCore import QCoreApplication

    app = QCoreApplication(sys.argv)  # services use QObject signals
    hub = ServiceHub()
    hub.set_radar_mode("iss", visible=True)
    hub.start()
    print("[selftest] services started; collecting for ~12s...")

    deadline = time.time() + 12
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.2)

    def dump(name, svc):
        snap = svc.last_good
        status = "OK" if snap is not None else "NO DATA"
        print(f"\n=== {name} [{status}] ===")
        if isinstance(snap, dict):
            short = {k: (v if not isinstance(v, (list, dict)) else f"<{type(v).__name__}:{len(v)}>")
                     for k, v in snap.items()}
            print(json.dumps(short, indent=2, default=str)[:1500])

    dump("system", hub.metrics)
    dump("network", hub.network)
    dump("weather", hub.weather)
    dump("iss", hub.iss)
    dump("quakes", hub.quakes)
    print(f"\n[selftest] audio mic={hub.audio.mic_level():.2f} tts={hub.audio.tts_level():.2f}")
    hub.stop()
    print("[selftest] done.")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("Usage: python -m ui.services.hub --selftest")
