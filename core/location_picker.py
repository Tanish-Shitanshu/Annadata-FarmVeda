"""Streamlit location picker shared by the pages that need a place.

Village and town names repeat across Indian states, so the farmer picks from
the matches (shown with district and state) instead of the app silently taking
the first search hit. Network lookups are cached so Streamlit reruns (every
click triggers one) don't re-hit the API.
"""

from __future__ import annotations

from datetime import date

import requests
import streamlit as st

from core.climate import SeasonalClimate, forecast_extrapolation, seasonal_normals
from core.i18n import t
from core.weather import ForecastResult, Location, geocode_candidates, get_forecast


@st.cache_data(ttl=3600, show_spinner=False)
def cached_candidates(place: str) -> list[Location]:
    return geocode_candidates(place, count=5)


@st.cache_data(ttl=600, show_spinner=False)
def _cached_forecast(name: str, country: str, lat: float, lon: float,
                     admin1: str, admin2: str) -> ForecastResult:
    return get_forecast(Location(name=name, country=country, latitude=lat,
                                 longitude=lon, admin1=admin1, admin2=admin2))


def cached_forecast(loc: Location) -> ForecastResult:
    return _cached_forecast(loc.name, loc.country, loc.latitude, loc.longitude,
                            loc.admin1, loc.admin2)


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_normals(name: str, country: str, lat: float, lon: float, admin1: str,
                    admin2: str, season: str, day: str) -> SeasonalClimate:
    loc = Location(name=name, country=country, latitude=lat, longitude=lon, admin1=admin1, admin2=admin2)
    normals = seasonal_normals(loc, season)
    if normals is None:
        # Raising keeps a failed lookup out of the cache so the next run retries.
        raise LookupError("no historical data")
    return normals


def cached_seasonal_climate(loc: Location, season: str, forecast: ForecastResult) -> SeasonalClimate:
    """Historical normals when available, else a clearly-labelled forecast extrapolation."""
    try:
        return _cached_normals(loc.name, loc.country, loc.latitude, loc.longitude,
                               loc.admin1, loc.admin2, season, date.today().isoformat())
    except LookupError:
        return forecast_extrapolation(forecast, season)


def pick_location(lang: str, label: str, default: str = "", key: str = "loc") -> Location | None:
    """Text box + a dropdown of matching places. Returns the chosen Location,
    or None if nothing has been entered / nothing matched / the lookup failed
    (in which case a message has already been shown)."""
    place = st.text_input(label, value=default, key=f"{key}_text")
    if not place.strip():
        return None

    try:
        candidates = cached_candidates(place.strip())
    except requests.RequestException:
        st.error(t("Couldn't reach the location service. Check your connection and try again.", lang))
        return None

    if not candidates:
        st.error(t("Couldn't find that location. Try a nearby city name.", lang))
        return None

    if len(candidates) == 1:
        st.caption("📍 " + candidates[0].label)
        return candidates[0]

    labels = [c.label for c in candidates]
    chosen = st.selectbox(t("Which place do you mean?", lang), labels, key=f"{key}_select")
    return candidates[labels.index(chosen)]
