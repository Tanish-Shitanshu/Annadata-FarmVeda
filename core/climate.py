"""Seasonal climate normals for the crop recommender.

The recommender compares a crop's *seasonal* rainfall need against the
location's expected seasonal rainfall. Extrapolating that from a 7-day
forecast is very noisy (a dry week in July says little about the monsoon), so
the primary source here is the Open-Meteo Historical Weather archive: the
average rainfall total and mean temperature of the same season over the last
few complete years at the farmer's location.

If the archive cannot be reached, `forecast_extrapolation` provides the old
behaviour, clearly labelled so the UI never presents it as a climate normal.

Season windows are national approximations (sowing/growing windows differ by
state and year):
    Kharif  1 Jun - 31 Oct
    Rabi    1 Nov - 14 Mar   (spans two calendar years)
    Zaid   15 Mar - 15 Jun
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import requests

from core.weather import ForecastResult, Location

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
TIMEOUT_SECONDS = 20
ARCHIVE_LAG_DAYS = 5  # the archive trails real time by a few days

SEASONS = ("Kharif", "Rabi", "Zaid")

# season -> (start month, start day, end month, end day, crosses new year)
_WINDOWS = {
    "Kharif": (6, 1, 10, 31, False),
    "Rabi": (11, 1, 3, 14, True),
    "Zaid": (3, 15, 6, 15, False),
}


@dataclass
class SeasonalClimate:
    avg_temp_c: float
    rainfall_mm: float
    basis: str  # "historical normals" or "forecast extrapolation"
    detail: str  # human-readable explanation of how the numbers were derived


def season_window(season: str, start_year: int) -> tuple[date, date]:
    """Start/end dates of `season` whose window begins in `start_year`."""
    if season not in _WINDOWS:
        raise ValueError(f"Unknown season: {season!r}")
    sm, sd, em, ed, crosses = _WINDOWS[season]
    end_year = start_year + 1 if crosses else start_year
    return date(start_year, sm, sd), date(end_year, em, ed)


def complete_season_windows(season: str, today: date | None = None,
                            years: int = 3) -> list[tuple[date, date]]:
    """The most recent `years` windows of `season` that ended safely before
    today (accounting for the archive lag), newest first."""
    today = today or date.today()
    cutoff = today - timedelta(days=ARCHIVE_LAG_DAYS)
    windows: list[tuple[date, date]] = []
    year = today.year
    while len(windows) < years and year > today.year - 15:
        start, end = season_window(season, year)
        if end < cutoff:
            windows.append((start, end))
        year -= 1
    return windows


def _fetch_window(location: Location, start: date, end: date) -> tuple[float, float] | None:
    """(total rainfall mm, mean temperature C) for one window, or None."""
    resp = requests.get(
        ARCHIVE_URL,
        params={
            "latitude": location.latitude,
            "longitude": location.longitude,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "precipitation_sum,temperature_2m_mean",
            "timezone": "auto",
        },
        timeout=TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    daily = resp.json().get("daily") or {}
    rain = [v for v in daily.get("precipitation_sum", []) if v is not None]
    temp = [v for v in daily.get("temperature_2m_mean", []) if v is not None]
    # Require near-complete coverage so a partially missing season is not
    # silently treated as a dry one.
    expected_days = (end - start).days + 1
    if len(rain) < 0.9 * expected_days or not temp:
        return None
    return sum(rain), sum(temp) / len(temp)


def seasonal_normals(location: Location, season: str, today: date | None = None,
                     years: int = 3) -> SeasonalClimate | None:
    """Average seasonal rainfall and mean temperature over recent complete
    seasons, or None if the archive could not provide any."""
    results: list[tuple[float, float]] = []
    labels: list[str] = []
    for start, end in complete_season_windows(season, today, years):
        try:
            got = _fetch_window(location, start, end)
        except (requests.RequestException, ValueError, KeyError):
            got = None
        if got is not None:
            results.append(got)
            labels.append(str(start.year) if start.year == end.year else f"{start.year}-{str(end.year)[2:]}")

    if not results:
        return None

    return SeasonalClimate(
        avg_temp_c=sum(t for _, t in results) / len(results),
        rainfall_mm=sum(r for r, _ in results) / len(results),
        basis="historical normals",
        detail=f"Average of the last {len(results)} {season} season(s) at this location "
               f"({', '.join(labels)}), from Open-Meteo historical data.",
    )


def forecast_extrapolation(forecast: ForecastResult, season: str) -> SeasonalClimate:
    """Fallback: scale the forecast window up to a full season. Crude - one
    week of weather is a poor predictor of a whole season - and labelled as such."""
    days = forecast.days
    if not days:
        raise ValueError("Forecast has no days")
    season_len = (season_window(season, 2001)[1] - season_window(season, 2001)[0]).days + 1
    mean_temp = sum((d.temp_max_c + d.temp_min_c) / 2 for d in days) / len(days)
    rain = sum(d.precipitation_mm for d in days) * season_len / len(days)
    return SeasonalClimate(
        avg_temp_c=mean_temp,
        rainfall_mm=rain,
        basis="forecast extrapolation",
        detail=f"Historical data was unavailable, so the {len(days)}-day forecast was scaled up to a "
               f"{season_len}-day season. This is a rough guess - treat the ranking with caution.",
    )


def get_seasonal_climate(location: Location, season: str, forecast: ForecastResult | None = None,
                         today: date | None = None) -> SeasonalClimate | None:
    """Historical normals if available, else forecast extrapolation, else None."""
    normals = seasonal_normals(location, season, today)
    if normals is not None:
        return normals
    if forecast is not None and forecast.days:
        return forecast_extrapolation(forecast, season)
    return None
