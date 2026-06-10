"""Weather service — Open-Meteo (keyless) forecast + air quality + astronomy.

Pipeline: resolve location (config override → ip-api.com → cache) once, then poll
Open-Meteo forecast (current/hourly/daily) and the Open-Meteo Air Quality API.
Moon phase is computed locally (no API).
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from ui.services.base import PolledService
from ui.services.cache import read_cache, write_cache
from ui.services.http import get_json

_FORECAST = "https://api.open-meteo.com/v1/forecast"
_AIRQ = "https://air-quality-api.open-meteo.com/v1/air-quality"
_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
_IPAPI = "http://ip-api.com/json/"

# WMO weather code -> (label, glyph)
_WMO = {
    0: ("Clear", "☀"),
    1: ("Mainly clear", "🌤"), 2: ("Partly cloudy", "⛅"), 3: ("Overcast", "☁"),
    45: ("Fog", "🌫"), 48: ("Rime fog", "🌫"),
    51: ("Light drizzle", "🌦"), 53: ("Drizzle", "🌦"), 55: ("Dense drizzle", "🌧"),
    56: ("Freezing drizzle", "🌧"), 57: ("Freezing drizzle", "🌧"),
    61: ("Light rain", "🌦"), 63: ("Rain", "🌧"), 65: ("Heavy rain", "🌧"),
    66: ("Freezing rain", "🌧"), 67: ("Freezing rain", "🌧"),
    71: ("Light snow", "🌨"), 73: ("Snow", "🌨"), 75: ("Heavy snow", "❄"),
    77: ("Snow grains", "🌨"),
    80: ("Rain showers", "🌦"), 81: ("Rain showers", "🌧"), 82: ("Violent showers", "⛈"),
    85: ("Snow showers", "🌨"), 86: ("Snow showers", "🌨"),
    95: ("Thunderstorm", "⛈"), 96: ("Thunderstorm + hail", "⛈"), 99: ("Thunderstorm + hail", "⛈"),
}

_MOON_NAMES = [
    "New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
    "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent",
]
_MOON_GLYPHS = ["🌑", "🌒", "🌓", "🌔", "🌕", "🌖", "🌗", "🌘"]
_SYNODIC = 29.53058867


def wmo_info(code: int | None) -> tuple[str, str]:
    if code is None:
        return ("Unknown", "•")
    return _WMO.get(int(code), ("—", "•"))


def moon_phase(dt: datetime | None = None) -> dict:
    """Return moon phase fraction (0..1), illuminated fraction, name, glyph."""
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Reference new moon: 2000-01-06 18:14 UTC
    ref = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    days = (dt - ref).total_seconds() / 86400.0
    phase = (days % _SYNODIC) / _SYNODIC  # 0=new, 0.5=full
    illum = (1 - math.cos(2 * math.pi * phase)) / 2
    idx = int((phase * 8) + 0.5) % 8
    return {
        "phase": phase,
        "illumination": illum,
        "name": _MOON_NAMES[idx],
        "glyph": _MOON_GLYPHS[idx],
    }


class WeatherService(PolledService):
    def __init__(self, interval: float = 600.0, units: str = "metric", location: str = "auto"):
        super().__init__(interval, name="weather", cache_key="weather", cache_ttl=3 * 3600)
        self.units = units
        self.location_pref = location
        # Resolved lazily on first poll. Do NOT eagerly seed from cache — a stale
        # cached location would otherwise override a newly-configured city.
        self._loc: dict | None = None
        self._aq_checked = 0.0
        self._aq: dict | None = None

    def set_options(self, *, units: str | None = None, location: str | None = None) -> None:
        changed = False
        if units and units != self.units:
            self.units = units
            changed = True
        if location is not None and location != self.location_pref:
            self.location_pref = location
            self._loc = None  # force re-resolve
            changed = True
        if changed:
            self.request_now()

    # ----- location -----
    def _resolve_location(self) -> dict:
        pref = (self.location_pref or "auto").strip()
        # Reuse only if it was resolved from the SAME preference string.
        if isinstance(self._loc, dict) and self._loc.get("_pref") == pref:
            return self._loc
        loc = self._geocode(pref) if pref.lower() != "auto" else self._geolocate_ip()
        if loc:
            loc["_pref"] = pref
            self._loc = loc
            write_cache("weather_loc", loc)
            return loc
        # offline fallback: only a cache that matches the current preference
        cached = read_cache("weather_loc")
        if isinstance(cached, dict) and cached.get("_pref") == pref:
            self._loc = cached
            return cached
        raise RuntimeError(f"could not resolve location: {pref!r}")

    def _geocode(self, pref: str) -> dict | None:
        """Resolve 'City, State, Country' — use the state/country tokens to pick
        the right match when a city name is ambiguous."""
        try:
            parts = [t.strip() for t in pref.split(",") if t.strip()]
            if not parts:
                return None
            city = parts[0]
            hints = {t.lower() for t in parts[1:]}
            data = get_json(_GEOCODE, params={"name": city, "count": 10})
            results = data.get("results") or []
            if not results:
                return None
            best = results[0]
            if hints:
                for r in results:
                    fields = {
                        str(r.get("country_code", "")).lower(),
                        str(r.get("country", "")).lower(),
                        str(r.get("admin1", "")).lower(),
                        str(r.get("admin2", "")).lower(),
                    }
                    if fields & hints:
                        best = r
                        break
            return {
                "lat": best["latitude"],
                "lon": best["longitude"],
                "name": best.get("name", city),
                "country": best.get("country_code", ""),
            }
        except Exception as e:
            print(f"[weather] geocode failed for {pref!r}: {e}")
            return None

    def _geolocate_ip(self) -> dict | None:
        try:
            data = get_json(_IPAPI, params={"fields": "status,city,regionName,countryCode,lat,lon"})
            if data.get("status") != "success":
                return None
            return {
                "lat": data["lat"],
                "lon": data["lon"],
                "name": data.get("city") or data.get("regionName") or "Local",
                "country": data.get("countryCode", ""),
            }
        except Exception:
            return None

    # ----- poll -----
    def poll(self) -> dict:
        loc = self._resolve_location()
        imperial = self.units == "imperial"
        params = {
            "latitude": loc["lat"],
            "longitude": loc["lon"],
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,"
                       "precipitation,weather_code,wind_speed_10m,wind_direction_10m",
            "hourly": "temperature_2m,weather_code,precipitation_probability",
            "daily": "sunrise,sunset,temperature_2m_max,temperature_2m_min",
            "timezone": "auto",
            "forecast_days": 1,
        }
        if imperial:
            params["temperature_unit"] = "fahrenheit"
            params["wind_speed_unit"] = "mph"
            params["precipitation_unit"] = "inch"
        data = get_json(_FORECAST, params=params)
        cur = data.get("current", {})
        hourly = data.get("hourly", {})
        daily = data.get("daily", {})

        forecast = self._next_hours(hourly, n=6)
        aq = self._air_quality(loc)

        sunrise = (daily.get("sunrise") or [None])[0]
        sunset = (daily.get("sunset") or [None])[0]

        return {
            "location": loc,
            "units": self.units,
            "temp_unit": "°F" if imperial else "°C",
            "wind_unit": "mph" if imperial else "km/h",
            "temp": cur.get("temperature_2m"),
            "feels_like": cur.get("apparent_temperature"),
            "humidity": cur.get("relative_humidity_2m"),
            "precip": cur.get("precipitation"),
            "is_day": bool(cur.get("is_day", 1)),
            "code": cur.get("weather_code"),
            "wind_speed": cur.get("wind_speed_10m"),
            "wind_dir": cur.get("wind_direction_10m"),
            "hi": (daily.get("temperature_2m_max") or [None])[0],
            "lo": (daily.get("temperature_2m_min") or [None])[0],
            "sunrise": sunrise,
            "sunset": sunset,
            "forecast": forecast,
            "air_quality": aq,
            "moon": moon_phase(),
            "fetched": time.time(),
        }

    def _next_hours(self, hourly: dict, n: int = 6) -> list[dict]:
        times = hourly.get("time") or []
        temps = hourly.get("temperature_2m") or []
        codes = hourly.get("weather_code") or []
        probs = hourly.get("precipitation_probability") or []
        if not times:
            return []
        now = datetime.now()
        # Find first index at or after the current hour.
        start = 0
        for i, t in enumerate(times):
            try:
                dt = datetime.fromisoformat(t)
            except ValueError:
                continue
            if dt >= now.replace(minute=0, second=0, microsecond=0):
                start = i
                break
        out = []
        for i in range(start, min(start + n, len(times))):
            try:
                hh = datetime.fromisoformat(times[i]).strftime("%H")
            except (ValueError, IndexError):
                hh = "--"
            out.append({
                "hour": hh,
                "temp": temps[i] if i < len(temps) else None,
                "code": codes[i] if i < len(codes) else None,
                "precip_prob": probs[i] if i < len(probs) else None,
            })
        return out

    def _air_quality(self, loc: dict) -> dict | None:
        # AQ changes slowly; refresh at most every 30 min.
        if self._aq and (time.time() - self._aq_checked) < 1800:
            return self._aq
        try:
            data = get_json(_AIRQ, params={
                "latitude": loc["lat"],
                "longitude": loc["lon"],
                "current": "european_aqi,us_aqi,pm2_5",
            })
            cur = data.get("current", {})
            self._aq = {
                "european_aqi": cur.get("european_aqi"),
                "us_aqi": cur.get("us_aqi"),
                "pm2_5": cur.get("pm2_5"),
            }
            self._aq_checked = time.time()
        except Exception:
            pass
        return self._aq


def aqi_band(european_aqi: float | None) -> tuple[str, str]:
    """Map European AQI to (label, color-key). color-key indexes theme.C.AQI_*."""
    if european_aqi is None:
        return ("—", "AQI_MOD")
    v = european_aqi
    if v <= 20:
        return ("GOOD", "AQI_GOOD")
    if v <= 40:
        return ("FAIR", "AQI_GOOD")
    if v <= 60:
        return ("MODERATE", "AQI_MOD")
    if v <= 80:
        return ("POOR", "AQI_BAD")
    if v <= 100:
        return ("V.POOR", "AQI_BAD")
    return ("EXTREME", "AQI_VBAD")
