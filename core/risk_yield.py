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

from core.weather import ForecastResult

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "crop_yield_price_reference.csv")

HEATWAVE_TEMP_C = 40.0
FROST_TEMP_C = 4.0
HEAVY_RAIN_MM = 30.0
DROUGHT_RAIN_MM_PER_WEEK = 5.0


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


def assess_climate_risk(forecast: ForecastResult) -> ClimateRisk:
    factors = []
    score = 0

    heatwave_days = [d for d in forecast.days if d.temp_max_c >= HEATWAVE_TEMP_C]
    if heatwave_days:
        score += 30
        factors.append(f"Heatwave risk: {len(heatwave_days)} day(s) >= {HEATWAVE_TEMP_C:.0f}°C")

    frost_days = [d for d in forecast.days if d.temp_min_c <= FROST_TEMP_C]
    if frost_days:
        score += 30
        factors.append(f"Frost risk: {len(frost_days)} day(s) <= {FROST_TEMP_C:.0f}°C")

    heavy_rain_days = [d for d in forecast.days if d.precipitation_mm >= HEAVY_RAIN_MM]
    if heavy_rain_days:
        score += 25
        factors.append(f"Heavy rainfall risk: {heavy_rain_days[0].precipitation_mm:.0f}mm on "
                        f"{heavy_rain_days[0].day.strftime('%b %d')} - flooding/lodging risk")

    total_rain = sum(d.precipitation_mm for d in forecast.days)
    weeks = max(len(forecast.days) / 7, 1)
    if total_rain / weeks < DROUGHT_RAIN_MM_PER_WEEK:
        score += 20
        factors.append(f"Drought risk: only {total_rain:.0f}mm total over the forecast window")

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
