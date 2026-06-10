"""Weather tool — spoken current conditions via Open-Meteo (keyless).

Resolves the city with Open-Meteo geocoding, fetches current weather, and returns
a natural spoken summary. Falls back to opening a Google search if the API call
fails or no city resolves.
"""

import webbrowser
from urllib.parse import quote_plus

_FORECAST = "https://api.open-meteo.com/v1/forecast"
_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"


def weather_action(
    parameters: dict,
    player=None,
    session_memory=None,
) -> str:
    city = parameters.get("city")
    when = parameters.get("time", "today")

    if not city or not isinstance(city, str) or not city.strip():
        msg = "Sir, the city is missing for the weather report."
        _log(msg, player)
        return msg

    city = city.strip()
    when = (when or "today").strip()

    try:
        summary = _spoken_weather(city)
        if summary:
            _log(summary, player)
            if session_memory:
                try:
                    session_memory.set_last_search(query=f"weather {city}", response=summary)
                except Exception:
                    pass
            return summary
    except Exception as e:
        print(f"[Weather] API path failed ({e}); falling back to browser.")

    # Fallback: open a Google search (legacy behavior).
    return _browser_fallback(city, when, player, session_memory)


def _units() -> tuple[str, str, str]:
    """Return (temp_unit_label, speed_unit_label, imperial_flag)."""
    try:
        from core.config import load_user_config
        imperial = str(load_user_config().get("weather_units", "metric")).lower() == "imperial"
    except Exception:
        imperial = False
    if imperial:
        return "Fahrenheit", "miles per hour", "imperial"
    return "Celsius", "kilometres per hour", "metric"


def _spoken_weather(city: str) -> str:
    import requests
    from ui.services.weather import wmo_info

    temp_label, wind_label, units = _units()
    imperial = units == "imperial"

    geo = requests.get(
        _GEOCODE, params={"name": city, "count": 1}, timeout=5,
        headers={"User-Agent": "EmilyHUD/2.0"},
    )
    geo.raise_for_status()
    results = (geo.json() or {}).get("results") or []
    if not results:
        return ""
    r = results[0]
    lat, lon = r["latitude"], r["longitude"]
    name = r.get("name", city)
    country = r.get("country", "")

    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,"
                   "weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
        "forecast_days": 1,
    }
    if imperial:
        params["temperature_unit"] = "fahrenheit"
        params["wind_speed_unit"] = "mph"
    fc = requests.get(_FORECAST, params=params, timeout=5,
                      headers={"User-Agent": "EmilyHUD/2.0"})
    fc.raise_for_status()
    data = fc.json()
    cur = data.get("current", {})
    daily = data.get("daily", {})

    cond = wmo_info(cur.get("weather_code"))[0]
    temp = cur.get("temperature_2m")
    feels = cur.get("apparent_temperature")
    hum = cur.get("relative_humidity_2m")
    wind = cur.get("wind_speed_10m")
    hi = (daily.get("temperature_2m_max") or [None])[0]
    lo = (daily.get("temperature_2m_min") or [None])[0]

    place = f"{name}, {country}".strip(", ")
    parts = [f"In {place} it's currently {temp:.0f} degrees {temp_label} with {cond.lower()}"]
    if feels is not None and abs((feels or 0) - (temp or 0)) >= 2:
        parts.append(f", feels like {feels:.0f}")
    if hum is not None:
        parts.append(f", humidity {hum:.0f} percent")
    if wind is not None:
        parts.append(f", wind {wind:.0f} {wind_label}")
    sentence = "".join(parts) + "."
    if hi is not None and lo is not None:
        sentence += f" Today's high is {hi:.0f} and low {lo:.0f}, sir."
    else:
        sentence += " Sir."
    return sentence


def _browser_fallback(city: str, when: str, player, session_memory) -> str:
    search_query = f"weather in {city} {when}"
    url = f"https://www.google.com/search?q={quote_plus(search_query)}"
    try:
        opened = webbrowser.open(url)
        if not opened:
            raise RuntimeError("webbrowser.open returned False")
    except Exception as e:
        msg = f"Sir, I couldn't open the browser for the weather report: {e}"
        _log(msg, player)
        return msg
    msg = f"Showing the weather for {city}, {when}, sir."
    _log(msg, player)
    if session_memory:
        try:
            session_memory.set_last_search(query=search_query, response=msg)
        except Exception:
            pass
    return msg


def _log(message: str, player=None) -> None:
    print(f"[Weather] {message}")
    if player:
        try:
            player.write_log(f"EMILY: {message}")
        except Exception:
            pass
