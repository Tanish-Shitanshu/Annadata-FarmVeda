"""Rule-based crop recommendation engine.

Scores crops from `data/crop_requirements.csv` against a farmer's soil type,
season, expected rainfall, and average temperature. This is a heuristic
match against published agronomic ranges, not a machine-learned model - it
will not account for local micro-climate, market conditions, or field
history the way an agronomist visiting in person would.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "crop_requirements.csv")


@dataclass
class CropProfile:
    crop: str
    season: str
    soil_types: list[str]
    min_temp_c: float
    max_temp_c: float
    min_rainfall_mm: float
    max_rainfall_mm: float
    duration_days: int


@dataclass
class Recommendation:
    crop: CropProfile
    score: int
    reasons: list[str]


def load_crop_profiles() -> list[CropProfile]:
    profiles = []
    with open(DATA_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            profiles.append(CropProfile(
                crop=row["crop"],
                season=row["season"],
                soil_types=[s.strip() for s in row["soil_types"].split(",")],
                min_temp_c=float(row["min_temp_c"]),
                max_temp_c=float(row["max_temp_c"]),
                min_rainfall_mm=float(row["min_rainfall_mm"]),
                max_rainfall_mm=float(row["max_rainfall_mm"]),
                duration_days=int(row["duration_days"]),
            ))
    return profiles


def get_profile(crop: str) -> CropProfile | None:
    """Look up one crop's agronomic profile by name, or None if unknown."""
    for profile in load_crop_profiles():
        if profile.crop == crop:
            return profile
    return None


def recommend_crops(soil_type: str, season: str, avg_temp_c: float,
                     seasonal_rainfall_mm: float, top_n: int = 5) -> list[Recommendation]:
    scored: list[Recommendation] = []

    for profile in load_crop_profiles():
        score = 0
        reasons = []

        if profile.season in (season, "Year-round"):
            score += 40
            reasons.append(f"Matches {season} season")
        else:
            reasons.append(f"Typically grown in {profile.season}, not {season}")

        if soil_type in profile.soil_types:
            score += 30
            reasons.append(f"Suited to {soil_type} soil")
        else:
            reasons.append(f"Prefers {', '.join(profile.soil_types)} soil, not {soil_type}")

        if profile.min_temp_c <= avg_temp_c <= profile.max_temp_c:
            score += 15
            reasons.append(f"Temperature {avg_temp_c:.0f}°C is within ideal range")
        else:
            score += max(0, 15 - int(abs(avg_temp_c - (profile.min_temp_c + profile.max_temp_c) / 2)))
            reasons.append(f"Ideal range is {profile.min_temp_c:.0f}-{profile.max_temp_c:.0f}°C")

        if profile.min_rainfall_mm <= seasonal_rainfall_mm <= profile.max_rainfall_mm:
            score += 15
            reasons.append("Rainfall matches crop water need")
        elif seasonal_rainfall_mm < profile.min_rainfall_mm:
            deficit = profile.min_rainfall_mm - seasonal_rainfall_mm
            score += max(0, 15 - int(deficit / 50))
            reasons.append(f"~{deficit:.0f}mm short of ideal - irrigation needed")
        else:
            score += 10
            reasons.append("Rainfall exceeds typical need - ensure drainage")

        scored.append(Recommendation(crop=profile, score=min(score, 100), reasons=reasons))

    scored.sort(key=lambda r: r.score, reverse=True)
    return scored[:top_n]
