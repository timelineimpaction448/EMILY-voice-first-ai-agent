"""Weather cluster widgets bound to WeatherService (W9-W12)."""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QBrush, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ui.theme import C, hud_font, digital_font, qcol
from ui.widgets.base import DataPanel, draw_no_link
from ui.widgets.dials import paint_compass, paint_sun_arc
from ui.services.weather import wmo_info, aqi_band


def _to_unit(value, unit) -> str:
    return "--" if value is None else f"{value:.0f}{unit}"


class WeatherPanel(DataPanel):
    """Current conditions + feels-like + hi/lo + humidity + 6h strip + AQI."""

    def __init__(self, parent=None):
        super().__init__("LOCAL WEATHER", parent, accent=C.ARC)
        self._svc = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def bind_service(self, svc) -> "WeatherPanel":
        self._svc = svc
        return self.bind(svc)

    def mousePressEvent(self, e):
        if self._svc:
            self._svc.request_now()

    def paint_content(self, p: QPainter, rect: QRectF):
        d = self.data
        if not d or d.get("temp") is None:
            draw_no_link(p, rect, "NO LINK" if self.status_str == "offline" else "…")
            return
        tu = d.get("temp_unit", "°C")
        label, glyph = wmo_info(d.get("code"))
        loc = (d.get("location") or {}).get("name", "")

        # location
        p.setFont(hud_font(7, True))
        p.setPen(QPen(qcol(C.TEXT_MED), 1))
        p.drawText(QRectF(rect.x(), rect.y(), rect.width(), 12),
                   Qt.AlignmentFlag.AlignLeft, f"⌖ {loc}")

        # big temp + glyph
        p.setFont(hud_font(26, True))
        p.setPen(QPen(qcol(C.WHITE), 1))
        p.drawText(QRectF(rect.x(), rect.y() + 12, rect.width() * 0.55, 40),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   _to_unit(d.get("temp"), tu))
        p.setFont(hud_font(22))
        p.drawText(QRectF(rect.right() - rect.width() * 0.4, rect.y() + 12, rect.width() * 0.4, 40),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, glyph)

        # condition + feels/humidity/hi-lo
        y = rect.y() + 54
        p.setFont(hud_font(8, True))
        p.setPen(QPen(qcol(C.ARC), 1))
        p.drawText(QRectF(rect.x(), y, rect.width(), 13), Qt.AlignmentFlag.AlignLeft, label)
        y += 14
        p.setFont(hud_font(7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        feels = _to_unit(d.get("feels_like"), tu)
        hum = d.get("humidity")
        hum_s = "--" if hum is None else f"{hum:.0f}%"
        p.drawText(QRectF(rect.x(), y, rect.width(), 12), Qt.AlignmentFlag.AlignLeft,
                   f"Feels {feels}  ·  Hum {hum_s}")
        y += 12
        hi = _to_unit(d.get("hi"), tu)
        lo = _to_unit(d.get("lo"), tu)
        p.drawText(QRectF(rect.x(), y, rect.width(), 12), Qt.AlignmentFlag.AlignLeft,
                   f"Hi {hi}  ·  Lo {lo}")

        # AQI capsule
        aq = d.get("air_quality") or {}
        eaqi = aq.get("european_aqi")
        if eaqi is not None:
            band, ckey = aqi_band(eaqi)
            col = getattr(C, ckey, C.AQI_MOD)
            cap = QRectF(rect.right() - 84, y - 26, 80, 16)
            p.setBrush(QBrush(qcol(col, 60)))
            p.setPen(QPen(qcol(col), 1))
            p.drawRoundedRect(cap, 7, 7)
            p.setFont(hud_font(6, True))
            p.drawText(cap, Qt.AlignmentFlag.AlignCenter, f"AQI {eaqi:.0f} {band}")

        # 6-hour forecast strip
        strip = QRectF(rect.x(), rect.bottom() - 34, rect.width(), 34)
        fc = d.get("forecast", [])[:6]
        if fc:
            cw = strip.width() / len(fc)
            for i, h in enumerate(fc):
                cell = QRectF(strip.x() + i * cw, strip.y(), cw, strip.height())
                _, g = wmo_info(h.get("code"))
                p.setFont(hud_font(6))
                p.setPen(QPen(qcol(C.TEXT_DIM), 1))
                p.drawText(QRectF(cell.x(), cell.y(), cell.width(), 10),
                           Qt.AlignmentFlag.AlignHCenter, f"{h.get('hour','--')}h")
                p.setFont(hud_font(10))
                p.setPen(QPen(qcol(C.TEXT_MED), 1))
                p.drawText(QRectF(cell.x(), cell.y() + 9, cell.width(), 14),
                           Qt.AlignmentFlag.AlignHCenter, g)
                p.setFont(hud_font(6, True))
                p.setPen(QPen(qcol(C.WHITE), 1))
                p.drawText(QRectF(cell.x(), cell.y() + 22, cell.width(), 11),
                           Qt.AlignmentFlag.AlignHCenter, _to_unit(h.get("temp"), tu))


class WeatherMini(DataPanel):
    """Compact current-conditions card (fits the small sun/moon slot)."""

    def __init__(self, parent=None):
        super().__init__("WEATHER", parent, accent=C.ARC)
        self._svc = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def bind_service(self, svc) -> "WeatherMini":
        self._svc = svc
        return self.bind(svc)

    def mousePressEvent(self, e):
        if self._svc:
            self._svc.request_now()

    def paint_content(self, p: QPainter, rect: QRectF):
        d = self.data
        if not d or d.get("temp") is None:
            draw_no_link(p, rect, "NO LINK" if self.status_str == "offline" else "…")
            return
        tu = d.get("temp_unit", "°C")
        label, glyph = wmo_info(d.get("code"))
        loc = (d.get("location") or {}).get("name", "")

        # glyph + big temp
        p.setFont(hud_font(20))
        p.setPen(QPen(qcol(C.ARC_CORE), 1))
        p.drawText(QRectF(rect.x(), rect.y(), rect.width() * 0.42, rect.height() * 0.5),
                   Qt.AlignmentFlag.AlignCenter, glyph)
        p.setFont(hud_font(19, True))
        p.setPen(QPen(qcol(C.WHITE), 1))
        p.drawText(QRectF(rect.x() + rect.width() * 0.40, rect.y(),
                          rect.width() * 0.60, rect.height() * 0.5),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   _to_unit(d.get("temp"), tu))

        # condition
        p.setFont(hud_font(7, True))
        p.setPen(QPen(qcol(C.ARC), 1))
        p.drawText(QRectF(rect.x(), rect.y() + rect.height() * 0.50, rect.width(), 13),
                   Qt.AlignmentFlag.AlignHCenter, label)

        # feels / hi-lo / loc
        p.setFont(hud_font(6))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        hi, lo = _to_unit(d.get("hi"), tu), _to_unit(d.get("lo"), tu)
        feels = _to_unit(d.get("feels_like"), tu)
        p.drawText(QRectF(rect.x(), rect.y() + rect.height() * 0.50 + 14, rect.width(), 12),
                   Qt.AlignmentFlag.AlignHCenter, f"feels {feels}  ·  H {hi} L {lo}")
        if loc:
            p.setPen(QPen(qcol(C.TEXT_MED), 1))
            p.drawText(QRectF(rect.x(), rect.bottom() - 12, rect.width(), 12),
                       Qt.AlignmentFlag.AlignHCenter, f"⌖ {loc}")


class WindCompass(DataPanel):
    def __init__(self, parent=None):
        super().__init__("WIND", parent, accent=C.PRI)

    def paint_content(self, p: QPainter, rect: QRectF):
        d = self.data
        if not d or d.get("wind_dir") is None:
            draw_no_link(p, rect)
            return
        wu = d.get("wind_unit", "km/h")
        spd = d.get("wind_speed") or 0
        paint_compass(p, rect, d.get("wind_dir", 0), speed_text=f"{spd:.0f} {wu}")


class SkyArc(DataPanel):
    def __init__(self, parent=None):
        super().__init__("SUN · MOON", parent, accent=C.ARC, animated=True)

    def paint_content(self, p: QPainter, rect: QRectF):
        d = self.data
        if not d:
            draw_no_link(p, rect)
            return
        is_day = d.get("is_day", True)
        frac = self._day_frac(d)
        moon = (d.get("moon") or {}).get("glyph", "🌙")
        paint_sun_arc(p, rect, frac, is_day, moon_glyph=moon)
        # sunrise/sunset labels
        sr = self._hhmm(d.get("sunrise"))
        ss = self._hhmm(d.get("sunset"))
        p.setFont(hud_font(6, True))
        p.setPen(QPen(qcol(C.ARC, 200), 1))
        p.drawText(QRectF(rect.x(), rect.bottom() - 12, rect.width() / 2, 12),
                   Qt.AlignmentFlag.AlignLeft, f"↑ {sr}")
        p.drawText(QRectF(rect.center().x(), rect.bottom() - 12, rect.width() / 2, 12),
                   Qt.AlignmentFlag.AlignRight, f"↓ {ss}")

    @staticmethod
    def _day_frac(d: dict) -> float:
        try:
            sr = datetime.fromisoformat(d["sunrise"])
            ss = datetime.fromisoformat(d["sunset"])
            now = datetime.now()
            total = (ss - sr).total_seconds()
            if total <= 0:
                return 0.5
            return max(0.0, min(1.0, (now - sr).total_seconds() / total))
        except Exception:
            return 0.5

    @staticmethod
    def _hhmm(iso) -> str:
        try:
            return datetime.fromisoformat(iso).strftime("%H:%M")
        except Exception:
            return "--:--"
