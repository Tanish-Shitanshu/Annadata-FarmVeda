import csv
import os

import pytest

from conftest import forecast_payload
from core.crop_recommender import DATA_PATH, get_profile, load_crop_profiles, recommend_crops
from core.risk_yield import (DATA_PATH as REF_PATH, assess_climate_risk, estimate_loss, estimate_yield)
from core.weather import Location, get_forecast

ZAID = {"Watermelon", "Muskmelon", "Cucumber", "Green Gram (Moong)"}


def forecast(net, **kw):
    net.forecast = forecast_payload(**kw)
    return get_forecast(Location("X", "India", 1, 2))


# ── Data integrity ──────────────────────────────────────────────────────────

def test_every_crop_has_a_yield_price_row_and_vice_versa():
    with open(REF_PATH, newline="", encoding="utf-8") as f:
        ref = {r["crop"] for r in csv.DictReader(f)}
    assert ref == {p.crop for p in load_crop_profiles()}


def test_crop_rows_are_sane():
    for p in load_crop_profiles():
        assert p.season in {"Kharif", "Rabi", "Zaid", "Year-round"}, p
        assert p.min_temp_c < p.max_temp_c and p.min_rainfall_mm < p.max_rainfall_mm, p
        assert p.duration_days > 0 and p.soil_types, p


def test_all_three_seasons_have_crops():
    seasons = {p.season for p in load_crop_profiles()}
    assert {"Kharif", "Rabi", "Zaid"} <= seasons


def test_get_profile():
    assert get_profile("Wheat").season == "Rabi"
    assert get_profile("Unobtainium") is None


# ── Recommender ─────────────────────────────────────────────────────────────

def test_zaid_season_recommends_zaid_crops_first():
    recs = recommend_crops("Sandy Loam", "Zaid", avg_temp_c=30, seasonal_rainfall_mm=450, top_n=4)
    assert {r.crop.crop for r in recs} == ZAID


def test_season_mismatch_scores_lower():
    top = {r.crop.crop: r.score for r in recommend_crops("Alluvial", "Rabi", 18, 500, top_n=30)}
    assert top["Wheat"] > top["Rice (Paddy)"]


def test_scores_capped_and_sorted():
    recs = recommend_crops("Alluvial", "Kharif", 28, 1200, top_n=20)
    assert all(0 <= r.score <= 100 for r in recs)
    assert [r.score for r in recs] == sorted((r.score for r in recs), reverse=True)


# ── Climate risk ────────────────────────────────────────────────────────────

def test_generic_thresholds_still_work_without_crop(net):
    r = assess_climate_risk(forecast(net, tmax=41, rain=3))
    assert any("Heat" in f for f in r.factors) and r.level in {"Medium", "High"}


def test_calm_weather_is_low_risk(net):
    r = assess_climate_risk(forecast(net, tmax=28, tmin=14, rain=4), crop=get_profile("Wheat"))
    assert r.level == "Low" and r.score == 0 and "No major" in r.factors[0]


def test_heat_threshold_depends_on_the_crop(net):
    f = forecast(net, tmax=36, tmin=22, rain=4)
    assert any("Heat stress for Wheat" in x for x in assess_climate_risk(f, get_profile("Wheat")).factors)
    assert not any("Heat" in x for x in assess_climate_risk(f, get_profile("Sugarcane")).factors)
    assert not any("Heat" in x for x in assess_climate_risk(f).factors)   # generic 40°C


def test_cold_threshold_depends_on_the_crop(net):
    f = forecast(net, tmax=26, tmin=12, rain=4)
    assert any("Cold stress for Rice" in x for x in assess_climate_risk(f, get_profile("Rice (Paddy)")).factors)
    assert not any("Cold" in x or "Frost" in x for x in assess_climate_risk(f, get_profile("Wheat")).factors)


def test_true_frost_is_labelled_frost(net):
    f = forecast(net, tmax=18, tmin=2, rain=4)
    assert any(x.startswith("Frost risk for Wheat") for x in assess_climate_risk(f, get_profile("Wheat")).factors)


def test_water_gap_only_with_crop_and_rainfall(net):
    f = forecast(net, tmax=30, tmin=22, rain=4)
    rice = get_profile("Rice (Paddy)")
    assert any("Water gap" in x for x in assess_climate_risk(f, rice, seasonal_rainfall_mm=300).factors)
    assert not any("Water gap" in x for x in assess_climate_risk(f, rice, seasonal_rainfall_mm=1500).factors)
    assert not any("Water gap" in x for x in assess_climate_risk(f, rice).factors)
    assert not any("Water gap" in x for x in assess_climate_risk(f, seasonal_rainfall_mm=300).factors)


def test_one_dry_week_is_not_called_drought(net):
    r = assess_climate_risk(forecast(net, tmax=30, tmin=22, rain=0))
    assert any("Dry spell" in x for x in r.factors) and not any("rought risk" in x for x in r.factors)
    assert r.level == "Low"


def test_score_is_capped_at_100(net):
    f = forecast(net, tmax=48, tmin=0, rain=0, overrides={1: {"precipitation_sum": 50}})
    assert assess_climate_risk(f, get_profile("Rice (Paddy)"), seasonal_rainfall_mm=100).score <= 100


# ── Yield & loss ────────────────────────────────────────────────────────────

def test_yield_and_loss_for_new_zaid_crops(net):
    risk = assess_climate_risk(forecast(net, tmax=48, tmin=22, rain=0), get_profile("Watermelon"))
    for crop in ZAID:
        y = estimate_yield(crop, risk)
        assert y is not None and y.estimated_yield_quintal_per_acre <= y.baseline_yield_quintal_per_acre
        assert estimate_loss(crop, 2.0, y).estimated_loss_inr >= 0


def test_unknown_crop_has_no_estimate(net):
    risk = assess_climate_risk(forecast(net))
    assert estimate_yield("Unobtainium", risk) is None and estimate_loss("Unobtainium", 1, None) is None


def test_loss_scales_with_land(net):
    risk = assess_climate_risk(forecast(net, tmax=48, rain=0))
    y = estimate_yield("Wheat", risk)
    assert estimate_loss("Wheat", 4, y).estimated_loss_inr == pytest.approx(4 * estimate_loss("Wheat", 1, y).estimated_loss_inr)
