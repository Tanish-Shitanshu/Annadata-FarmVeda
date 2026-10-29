from datetime import date

import pytest

from conftest import archive_payload, forecast_payload
from core import climate
from core.climate import (complete_season_windows, forecast_extrapolation, get_seasonal_climate,
                          season_window, seasonal_normals)
from core.weather import Location, get_forecast

LOC = Location("Jaipur", "India", 26.9, 75.8)
TODAY = date(2026, 10, 29)


def test_rabi_window_spans_new_year():
    assert season_window("Rabi", 2025) == (date(2025, 11, 1), date(2026, 3, 14))


def test_unknown_season_rejected():
    with pytest.raises(ValueError):
        season_window("Monsoon", 2025)


def test_only_complete_seasons_are_used():
    # Kharif 2026 ends Oct 31 - still running on Oct 29, so it must be excluded.
    assert [s.year for s, _ in complete_season_windows("Kharif", TODAY)] == [2025, 2024, 2023]
    # Rabi 2026-27 hasn't happened yet; 2025-26 is complete.
    assert [s.year for s, _ in complete_season_windows("Rabi", TODAY)] == [2025, 2024, 2023]
    assert [s.year for s, _ in complete_season_windows("Zaid", TODAY)] == [2026, 2025, 2024]


def test_archive_lag_excludes_a_season_that_just_ended():
    # Kharif ended Oct 31; on Nov 2 the archive may not have it yet.
    assert complete_season_windows("Kharif", date(2026, 11, 2))[0][0].year == 2025
    assert complete_season_windows("Kharif", date(2026, 11, 10))[0][0].year == 2026


def test_normals_average_several_years(net):
    by_start = {"2025": (4.0, 26.0), "2024": (6.0, 28.0), "2023": (5.0, 27.0)}
    net.archive = lambda p: archive_payload(p["start_date"], p["end_date"],
                                            rain_per_day=by_start[p["start_date"][:4]][0],
                                            temp=by_start[p["start_date"][:4]][1])
    n = seasonal_normals(LOC, "Kharif", TODAY)
    days = 153  # Jun 1 - Oct 31
    assert n.rainfall_mm == pytest.approx(5.0 * days)
    assert n.avg_temp_c == pytest.approx(27.0)
    assert n.basis == "historical normals" and "3" in n.detail
    # each call asked the archive for exactly the season's dates, with the location
    url, params = net.calls[0]
    assert params["start_date"] == "2025-06-01" and params["end_date"] == "2025-10-31"
    assert params["latitude"] == 26.9 and "precipitation_sum" in params["daily"]


def test_year_with_big_data_gaps_is_skipped_not_treated_as_dry(net):
    net.archive = lambda p: archive_payload(p["start_date"], p["end_date"], rain_per_day=5.0,
                                            missing=0.5 if p["start_date"].startswith("2025") else 0.0)
    n = seasonal_normals(LOC, "Kharif", TODAY)
    assert n.rainfall_mm == pytest.approx(5.0 * 153) and "2025" not in n.detail


def test_normals_none_when_archive_down(net):
    net.fail.add("archive")
    assert seasonal_normals(LOC, "Kharif", TODAY) is None


def test_fallback_to_labelled_extrapolation(net):
    net.fail.add("archive")
    net.forecast = forecast_payload(tmax=34, tmin=24, rain=2.0)
    forecast = get_forecast(LOC)
    c = get_seasonal_climate(LOC, "Kharif", forecast, TODAY)
    assert c.basis == "forecast extrapolation"
    assert c.avg_temp_c == pytest.approx(29.0)            # mean of max & min, not max alone
    assert c.rainfall_mm == pytest.approx(2.0 * 153)      # 14mm/week scaled to the season length
    assert "rough" in c.detail


def test_no_data_at_all_returns_none(net):
    net.fail.add("archive")
    assert get_seasonal_climate(LOC, "Kharif", None, TODAY) is None


def test_extrapolation_requires_days():
    from core.weather import ForecastResult
    with pytest.raises(ValueError):
        forecast_extrapolation(ForecastResult(location=LOC), "Kharif")
