"""Real weather data via the Open-Meteo API (free, no API key required).

Provides geocoding (place name -> lat/lon) and a 7-day daily forecast, plus
rule-based farming advisory derived from that forecast: sowing, irrigation,
spraying, and harvest timing windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 15


@dataclass
class Location:
    name: str
    country: str
    latitude: float
    longitude: float
    admin1: str = ""  # state / region
    admin2: str = ""  # district

    @property
    def label(self) -> str:
        """Human-readable label that disambiguates same-named places."""
        parts = [self.name, self.admin2, self.admin1, self.country]
        seen: list[str] = []
        for p in parts:
            if p and p not in seen:
                seen.append(p)
        return ", ".join(seen)


@dataclass
class DayForecast:
    day: date
    temp_max_c: float
    temp_min_c: float
    precipitation_mm: float
    precipitation_probability_pct: float
    wind_speed_max_kmh: float


@dataclass
class ForecastResult:
    location: Location
    days: list[DayForecast] = field(default_factory=list)


def _search_places(place_name: str, count: int, country_code: str | None) -> list[dict]:
    params = {"name": place_name, "count": count, "language": "en", "format": "json"}
    if country_code:
        params["countryCode"] = country_code
    resp = requests.get(GEOCODE_URL, params=params, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.json().get("results") or []


def geocode_candidates(place_name: str, count: int = 5,
                       country_code: str | None = "IN") -> list[Location]:
    """Return up to `count` places matching `place_name`, India first.

    Village and town names repeat across Indian states, so the caller should
    let the farmer choose rather than silently taking the first hit. If nothing
    matches inside `country_code`, the search is retried worldwide so a
    legitimate non-Indian place still resolves.
    """
    place_name = place_name.strip()
    if not place_name:
        return []

    results = _search_places(place_name, count, country_code)
    if not results and country_code:
        results = _search_places(place_name, count, None)

    return [
        Location(
            name=r.get("name", place_name),
            country=r.get("country", ""),
            latitude=r["latitude"],
            longitude=r["longitude"],
            admin1=r.get("admin1", ""),
            admin2=r.get("admin2", ""),
        )
        for r in results
    ]


def geocode(place_name: str) -> Location | None:
    """Resolve a place name to its best match (first candidate), or None."""
    candidates = geocode_candidates(place_name, count=1)
    return candidates[0] if candidates else None


def get_forecast(location: Location, days: int = 7) -> ForecastResult:
    resp = requests.get(
        FORECAST_URL,
        params={
            "latitude": location.latitude,
            "longitude": location.longitude,
            "daily": ",".join([
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "precipitation_probability_max",
                "wind_speed_10m_max",
            ]),
            "forecast_days": days,
            "timezone": "auto",
        },
        timeout=TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    daily = resp.json()["daily"]

    result = ForecastResult(location=location)
    for i, day_str in enumerate(daily["time"]):
        result.days.append(DayForecast(
            day=datetime.fromisoformat(day_str).date(),
            temp_max_c=daily["temperature_2m_max"][i],
            temp_min_c=daily["temperature_2m_min"][i],
            precipitation_mm=daily["precipitation_sum"][i],
            precipitation_probability_pct=daily["precipitation_probability_max"][i] or 0,
            wind_speed_max_kmh=daily["wind_speed_10m_max"][i],
        ))
    return result


# ── Advisory rules ──────────────────────────────────────────────────────────
# Thresholds are simplified agronomic heuristics (heavy rain / high wind harm
# spraying accuracy and harvest quality; very hot, dry, windless days call for
# irrigation). Presented as guidance, not precision agriculture.

def sowing_advisory(forecast: ForecastResult) -> dict:
    upcoming_rain = sum(d.precipitation_mm for d in forecast.days[:5])
    heavy_rain_days = [d for d in forecast.days[:5] if d.precipitation_mm > 15]

    if heavy_rain_days:
        return {
            "verdict": "Wait",
            "reason": f"Heavy rain ({heavy_rain_days[0].precipitation_mm:.0f}mm) expected "
                      f"on {heavy_rain_days[0].day.strftime('%b %d')} - waterlogging risk for freshly sown seed.",
        }
    if upcoming_rain < 2:
        return {
            "verdict": "Sow with irrigation planned",
            "reason": f"Only {upcoming_rain:.0f}mm rain expected over the next 5 days - "
                      f"budget for irrigation after sowing.",
        }
    return {
        "verdict": "Good window",
        "reason": f"Moderate rain ({upcoming_rain:.0f}mm over 5 days) expected - "
                  f"favorable soil moisture without waterlogging risk.",
    }


def spraying_advisory(forecast: ForecastResult) -> list[dict]:
    out = []
    for d in forecast.days:
        if d.precipitation_probability_pct >= 50:
            verdict, reason = "Avoid", f"{d.precipitation_probability_pct:.0f}% rain chance - spray will wash off"
        elif d.wind_speed_max_kmh >= 15:
            verdict, reason = "Avoid", f"Wind {d.wind_speed_max_kmh:.0f} km/h - spray drift risk"
        else:
            verdict, reason = "Suitable", "Low rain chance, calm wind"
        out.append({"day": d.day, "verdict": verdict, "reason": reason})
    return out


def irrigation_advisory(forecast: ForecastResult) -> dict:
    next3_rain = sum(d.precipitation_mm for d in forecast.days[:3])
    hot_dry_days = sum(1 for d in forecast.days[:3] if d.temp_max_c >= 35 and d.precipitation_mm < 1)

    if next3_rain >= 10:
        return {
            "verdict": "Hold off",
            "reason": f"{next3_rain:.0f}mm rain expected in the next 3 days - skip irrigation to avoid waterlogging.",
        }
    if hot_dry_days >= 2:
        return {
            "verdict": "Irrigate soon",
            "reason": f"{hot_dry_days} hot, dry day(s) ahead (>=35°C, no rain) - crop water stress likely.",
        }
    return {
        "verdict": "Monitor",
        "reason": "Conditions are moderate - irrigate based on soil moisture check, no urgent signal from weather.",
    }


def harvest_advisory(forecast: ForecastResult) -> dict:
    rain_days = [d for d in forecast.days[:5] if d.precipitation_probability_pct >= 40]
    if rain_days:
        return {
            "verdict": "Harvest before rain if crop is ready",
            "reason": f"Rain likely from {rain_days[0].day.strftime('%b %d')} - "
                      f"delaying harvest risks grain moisture damage and lodging.",
        }
    return {
        "verdict": "Dry window",
        "reason": "No significant rain expected in the next 5 days - safe window for harvesting and drying.",
    }
