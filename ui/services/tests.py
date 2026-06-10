"""Offline tests for the service layer. Run: python -m ui.services.tests

No network, no pytest — plain asserts with a tiny harness.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_BASE = Path(__file__).resolve().parent.parent.parent
if str(_BASE) not in sys.path:
    sys.path.insert(0, str(_BASE))

_passed = 0
_failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


def test_cache():
    from ui.services import cache
    key = "test_unit_cache"
    cache.write_cache(key, {"a": 1})
    check("cache roundtrip", cache.read_cache(key) == {"a": 1})
    check("cache age small", (cache.cache_age(key) or 99) < 5)
    check("cache TTL expiry", cache.read_cache(key, max_age=-1) is None)
    check("cache missing", cache.read_cache("no_such_key_xyz") is None)


def test_moon():
    from ui.services.weather import moon_phase
    # 2024-01-25 was a full moon -> illumination near 1.
    m = moon_phase(datetime(2024, 1, 25, 17, 54, tzinfo=timezone.utc))
    check("moon full illum", m["illumination"] > 0.9, f"illum={m['illumination']:.2f}")
    # 2024-01-11 was a new moon -> illumination near 0.
    m2 = moon_phase(datetime(2024, 1, 11, 11, 57, tzinfo=timezone.utc))
    check("moon new illum", m2["illumination"] < 0.1, f"illum={m2['illumination']:.2f}")
    check("moon name present", m["name"] in {
        "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
        "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"})


def test_geo():
    from ui.services.trackers import haversine_km, bearing_deg
    # London -> Paris ~ 343 km
    d = haversine_km(51.5074, -0.1278, 48.8566, 2.3522)
    check("haversine london-paris", 330 < d < 360, f"d={d:.0f}km")
    b = bearing_deg(51.5074, -0.1278, 48.8566, 2.3522)
    check("bearing london-paris SE-ish", 120 < b < 160, f"b={b:.0f}")
    check("haversine zero", haversine_km(10, 10, 10, 10) < 0.001)


def test_weather_parse():
    from ui.services.weather import WeatherService, wmo_info, aqi_band
    svc = WeatherService()
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    times = [now.replace(hour=h).isoformat(timespec="minutes") for h in range(0, 24)]
    hourly = {
        "time": times,
        "temperature_2m": list(range(24)),
        "weather_code": [0] * 24,
        "precipitation_probability": [10] * 24,
    }
    fc = svc._next_hours(hourly, n=6)
    check("weather next6 len", len(fc) == 6, f"got {len(fc)}")
    check("weather hour fmt", all(len(x["hour"]) == 2 for x in fc))
    check("wmo clear", wmo_info(0)[0] == "Clear")
    check("wmo unknown", wmo_info(999)[0] == "—")
    check("aqi good", aqi_band(10)[1] == "AQI_GOOD")
    check("aqi extreme", aqi_band(150)[1] == "AQI_VBAD")
    check("aqi none", aqi_band(None)[0] == "—")


def test_backoff():
    from ui.services.base import PolledService

    class Dummy(PolledService):
        def poll(self):
            return {}

    d = Dummy(interval=10, jitter=0.0)
    d._consecutive_failures = 0
    check("backoff none==interval", abs(d._next_wait() - 10) < 0.01)
    d._consecutive_failures = 3
    w = d._next_wait()
    check("backoff grows", w >= 10, f"w={w}")
    d._consecutive_failures = 99
    check("backoff capped", d._next_wait() <= d.max_backoff + 1)


def test_audio():
    from ui.services.audio_level import audio_level
    a = audio_level()
    a.push_mic_rms(6000)
    check("audio mic positive", a.mic_level() > 0)
    a.set_speaking(True)
    check("audio tts speaking", a.tts_level() > 0)
    a.set_speaking(False)
    check("audio spectrum len", len(a.spectrum(24)) == 24)


def main() -> int:
    for fn in (test_cache, test_moon, test_geo, test_weather_parse, test_backoff, test_audio):
        print(f"\n[{fn.__name__}]")
        try:
            fn()
        except Exception as e:
            global _failed
            _failed += 1
            print(f"  ERROR {fn.__name__}: {e}")
    print(f"\n{'='*40}\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
