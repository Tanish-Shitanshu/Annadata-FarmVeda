"""Climate risk, yield, and loss-prevention heuristics.

All three are derived from the same live weather forecast (core/weather.py)
plus a static reference table of typical yields and illustrative crop
prices (data/crop_yield_price_reference.csv). These are heuristic
estimates for planning purposes, not calibrated agronomic or financial
models - and the reference prices are NOT live mandi data (that's tracked
separately as a roadmap item).
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass

from core.crop_recommender import CropProfile
from core.weather import ForecastResult

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "crop_yield_price_reference.csv")

HEATWAVE_TEMP_C = 40.0
FROST_TEMP_C = 4.0
HEAVY_RAIN_MM = 30.0
DRY_SPELL_RAIN_MM_PER_WEEK = 5.0
HEAT_MARGIN_C = 5.0        # heat stress this far above a crop's upper ideal temperature
COLD_MARGIN_C = 6.0        # cold stress this far below a crop's lower ideal temperature
WATER_GAP_FRACTION = 0.6   # seasonal rainfall under 60% of the crop's minimum need


@dataclass
class ClimateRisk:
    level: str  # Low / Medium / High
    score: int  # 0-100, higher = riskier
    factors: list[str]


@dataclass
class YieldEstimate:
    crop: str
    baseline_yield_quintal_per_acre: float
    estimated_yield_quintal_per_acre: float
    yield_change_pct: float


@dataclass
class LossEstimate:
    crop: str
    reference_price_per_quintal_inr: float
    estimated_loss_inr: float
    note: str


def _load_reference() -> dict[str, tuple[float, float]]:
    table = {}
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            table[row["crop"]] = (
                float(row["baseline_yield_quintal_per_acre"]),
                float(row["reference_price_per_quintal_inr"]),
            )
    return table


def assess_climate_risk(forecast: ForecastResult, crop: CropProfile | None = None,
                        seasonal_rainfall_mm: float | None = None) -> ClimateRisk:
    """Score weather stress over the forecast window.

    With no `crop`, generic thresholds are used (heatwave >= 40°C, frost <= 4°C).
    With a crop, thresholds come from that crop's own temperature range
    (heat stress 5°C above its upper limit, cold stress 6°C below its lower
    limit) - 38°C is routine for cotton but damaging for wheat. If a seasonal
    rainfall figure is supplied it is compared with the crop's water need.

    Still a heuristic: it reads one week of forecast, not crop stage, soil
    moisture or variety.
    """
    factors = []
    score = 0

    heat_c = crop.max_temp_c + HEAT_MARGIN_C if crop else HEATWAVE_TEMP_C
    cold_c = crop.min_temp_c - COLD_MARGIN_C if crop else FROST_TEMP_C
    subject = f" for {crop.crop}" if crop else ""

    hot_days = [d for d in forecast.days if d.temp_max_c >= heat_c]
    if hot_days:
        score += 30
        factors.append(f"Heat stress{subject}: {len(hot_days)} day(s) >= {heat_c:.0f}°C")

    cold_days = [d for d in forecast.days if d.temp_min_c <= cold_c]
    if cold_days:
        score += 30
        label = "Frost risk" if cold_c <= 4 else "Cold stress"
        factors.append(f"{label}{subject}: {len(cold_days)} night(s) <= {cold_c:.0f}°C")

    heavy_rain_days = [d for d in forecast.days if d.precipitation_mm >= HEAVY_RAIN_MM]
    if heavy_rain_days:
        score += 25
        factors.append(f"Heavy rainfall risk: {heavy_rain_days[0].precipitation_mm:.0f}mm on "
                        f"{heavy_rain_days[0].day.strftime('%b %d')} - flooding/lodging risk")

    total_rain = sum(d.precipitation_mm for d in forecast.days)
    weeks = max(len(forecast.days) / 7, 1)
    if total_rain / weeks < DRY_SPELL_RAIN_MM_PER_WEEK:
        score += 10
        factors.append(f"Dry spell: only {total_rain:.0f}mm over the forecast window - "
                        f"one dry week is not a drought, but check soil moisture")

    if crop is not None and seasonal_rainfall_mm is not None:
        need = crop.min_rainfall_mm
        if seasonal_rainfall_mm < need * WATER_GAP_FRACTION:
            score += 15
            factors.append(f"Water gap: typical seasonal rainfall here (~{seasonal_rainfall_mm:.0f}mm) is well "
                            f"below {crop.crop}'s ~{need:.0f}mm need - plan on irrigation")

    if not factors:
        factors.append("No major climate stress signals in the forecast window")

    score = min(score, 100)
    level = "High" if score >= 55 else "Medium" if score >= 25 else "Low"
    return ClimateRisk(level=level, score=score, factors=factors)


def estimate_yield(crop: str, climate_risk: ClimateRisk) -> YieldEstimate | None:
    table = _load_reference()
    if crop not in table:
        return None
    baseline, _price = table[crop]

    # Simplified penalty: yield drops roughly in proportion to climate risk score.
    penalty_pct = climate_risk.score * 0.4  # High risk (100) -> up to 40% penalty
    estimated = baseline * (1 - penalty_pct / 100)

    return YieldEstimate(
        crop=crop,
        baseline_yield_quintal_per_acre=baseline,
        estimated_yield_quintal_per_acre=round(estimated, 1),
        yield_change_pct=round(-penalty_pct, 1),
    )


def estimate_loss(crop: str, land_size_acres: float, yield_estimate: YieldEstimate) -> LossEstimate | None:
    table = _load_reference()
    if crop not in table:
        return None
    _baseline, price = table[crop]

    lost_quintals = (yield_estimate.baseline_yield_quintal_per_acre -
                      yield_estimate.estimated_yield_quintal_per_acre) * land_size_acres
    loss_value = round(lost_quintals * price, 0)

    return LossEstimate(
        crop=crop,
        reference_price_per_quintal_inr=price,
        estimated_loss_inr=loss_value,
        note="Based on an illustrative reference price, not live mandi rates.",
    )
