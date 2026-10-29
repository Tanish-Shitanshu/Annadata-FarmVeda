import pytest
import requests

from conftest import forecast_payload
from core import weather
from core.weather import (Location, geocode, geocode_candidates, get_forecast, harvest_advisory,
                          irrigation_advisory, sowing_advisory, spraying_advisory)


def fc(net, **kw):
    net.forecast = forecast_payload(**kw)
    return get_forecast(Location("X", "India", 1.0, 2.0))


# ── Geocoding ───────────────────────────────────────────────────────────────

def test_candidates_search_india_first(net):
    net.add_place("Rampur", admin1="Uttar Pradesh", admin2="Rampur")
    net.add_place("Rampur", admin1="Himachal Pradesh", admin2="Shimla")
    out = geocode_candidates("Rampur")
    assert [c.admin1 for c in out] == ["Uttar Pradesh", "Himachal Pradesh"]
    url, params = net.calls[0]
    assert params["countryCode"] == "IN" and params["name"] == "Rampur"


def test_candidates_retry_worldwide_when_none_in_india(net):
    net.add_place("Paris", admin1="Île-de-France", country="France", country_code="FR", worldwide_only=True)
    out = geocode_candidates("Paris")
    assert [c.country for c in out] == ["France"]
    assert "countryCode" in net.calls[0][1] and "countryCode" not in net.calls[1][1]


def test_candidates_blank_input_makes_no_request(net):
    assert geocode_candidates("   ") == []
    assert net.calls == []


def test_geocode_returns_first_or_none(net):
    net.add_place("Jaipur")
    assert geocode("Jaipur").name == "Jaipur"
    assert geocode("Nowhereville") is None


def test_geocode_http_error_propagates(net):
    net.fail.add("geocode")
    with pytest.raises(requests.HTTPError):
        geocode_candidates("Jaipur")


def test_label_deduplicates_repeated_parts():
    loc = Location("Mumbai", "India", 0, 0, admin1="Maharashtra", admin2="Mumbai")
    assert loc.label == "Mumbai, Maharashtra, India"


# ── Forecast parsing ────────────────────────────────────────────────────────

def test_forecast_parses_days_and_null_probability(net):
    result = fc(net, days=5, overrides={2: {"precipitation_probability_max": None}})
    assert len(result.days) == 5
    assert result.days[2].precipitation_probability_pct == 0
    assert result.days[0].temp_max_c == 32.0


# ── Advisory rules ──────────────────────────────────────────────────────────

def test_sowing_wait_on_heavy_rain(net):
    a = sowing_advisory(fc(net, overrides={2: {"precipitation_sum": 20}}))
    assert a["verdict"] == "Wait" and "20mm" in a["reason"]


def test_sowing_irrigation_when_dry(net):
    assert sowing_advisory(fc(net, rain=0))["verdict"] == "Sow with irrigation planned"


def test_sowing_good_window_with_moderate_rain(net):
    assert sowing_advisory(fc(net, rain=2.0))["verdict"] == "Good window"


def test_sowing_ignores_heavy_rain_after_day_five(net):
    assert sowing_advisory(fc(net, rain=1.0, overrides={6: {"precipitation_sum": 40}}))["verdict"] == "Good window"


def test_irrigation_hold_off_after_rain(net):
    assert irrigation_advisory(fc(net, overrides={0: {"precipitation_sum": 12}}))["verdict"] == "Hold off"


def test_irrigation_soon_when_hot_and_dry(net):
    assert irrigation_advisory(fc(net, tmax=38, rain=0))["verdict"] == "Irrigate soon"


def test_irrigation_monitor_otherwise(net):
    assert irrigation_advisory(fc(net, tmax=30, rain=1))["verdict"] == "Monitor"


def test_spraying_rain_wind_and_suitable(net):
    out = spraying_advisory(fc(net, overrides={0: {"precipitation_probability_max": 80},
                                               1: {"wind_speed_10m_max": 25}}))
    assert [d["verdict"] for d in out[:3]] == ["Avoid", "Avoid", "Suitable"]
    assert "rain" in out[0]["reason"] and "Wind" in out[1]["reason"]


def test_harvest_verdicts(net):
    assert harvest_advisory(fc(net, prob=10))["verdict"] == "Dry window"
    assert harvest_advisory(fc(net, overrides={3: {"precipitation_probability_max": 60}}))["verdict"] \
        == "Harvest before rain if crop is ready"
