"""AI Crop Health Scanner - heuristic image analysis.

IMPORTANT: this is a real, working analyzer - it genuinely reads pixel data
from the uploaded photo and produces different results for different images.
But it is a color/texture heuristic (leaf color ratios in HSV space), NOT a
trained deep-learning disease classifier. It can pick up on obvious visual
signals (yellowing, dark leaf spotting, dull/wilted color) but will not
identify specific diseases or pests the way a trained CNN on labeled disease
photos would. Treat its output as a first-pass visual triage signal, not a
diagnosis - always confirm with a local agricultural extension officer
before acting on a treatment recommendation.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import numpy as np
from PIL import Image

TREATMENTS: dict[str, dict] = {
    "Healthy": {
        "summary": "No visual stress signals detected.",
        "recommendation": "Continue regular monitoring and your normal balanced fertilization schedule.",
    },
    "Possible Nutrient Deficiency": {
        "summary": "Significant yellowing detected across the leaf surface, often a nitrogen or "
                    "micronutrient deficiency sign.",
        "recommendation": "Apply a nitrogen-rich fertilizer (e.g. urea top-dressing) and consider a "
                           "micronutrient foliar spray. A soil test will confirm which nutrient is short.",
    },
    "Possible Fungal or Pest Damage": {
        "summary": "Dark spotting/lesion patterns detected, consistent with fungal infection or pest damage.",
        "recommendation": "Remove and destroy visibly affected leaves. Consider a fungicide "
                           "(e.g. Mancozeb or Copper oxychloride) for fungal spotting, or a neem-oil "
                           "spray if pest damage is suspected. Improve field drainage and airflow.",
    },
    "Possible Water Stress": {
        "summary": "Dull, low-saturation leaf color detected, consistent with wilting or water stress.",
        "recommendation": "Check soil moisture and irrigate if dry. Avoid midday watering; "
                           "irrigate early morning or evening to reduce evaporation loss.",
    },
    "Inconclusive": {
        "summary": "The image doesn't show enough clear leaf/plant tissue to analyze.",
        "recommendation": "Retake the photo in good daylight, filling the frame with the affected leaf.",
    },
}


@dataclass
class ScanResult:
    category: str
    confidence_pct: int
    green_ratio: float
    yellow_ratio: float
    dark_spot_ratio: float
    saturation_mean: float
    summary: str
    recommendation: str


def analyze_image(image_bytes: bytes) -> ScanResult:
    img = Image.open(BytesIO(image_bytes)).convert("RGB").resize((256, 256))
    hsv = np.array(img.convert("HSV")).astype(float)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    hue_deg = h * (360.0 / 255.0)
    total = h.size

    green_mask = (hue_deg >= 70) & (hue_deg <= 170) & (s >= 40)
    yellow_mask = (hue_deg >= 40) & (hue_deg < 70) & (s >= 40)
    dark_spot_mask = v < 80
    dull_plant_mask = (s >= 15) & (s < 60) & (v >= 40)

    green_ratio = float(green_mask.mean())
    yellow_ratio = float(yellow_mask.mean())
    dark_spot_ratio = float(dark_spot_mask.mean())
    saturation_mean = float(s.mean())

    plant_like_ratio = float((green_mask | yellow_mask | dark_spot_mask | dull_plant_mask).mean())

    if plant_like_ratio < 0.08:
        category = "Inconclusive"
        confidence = 60
    elif dark_spot_ratio > 0.15:
        category = "Possible Fungal or Pest Damage"
        confidence = min(95, 55 + int(dark_spot_ratio * 100))
    elif yellow_ratio > 0.25:
        category = "Possible Nutrient Deficiency"
        confidence = min(95, 55 + int(yellow_ratio * 100))
    elif green_ratio > 0.5 and yellow_ratio < 0.1 and dark_spot_ratio < 0.05:
        category = "Healthy"
        confidence = min(95, 55 + int(green_ratio * 80))
    elif saturation_mean < 70:
        category = "Possible Water Stress"
        confidence = min(90, 50 + int(max(0, 70 - saturation_mean)))
    else:
        category = "Possible Nutrient Deficiency"
        confidence = 50

    info = TREATMENTS[category]
    return ScanResult(
        category=category,
        confidence_pct=confidence,
        green_ratio=round(green_ratio, 3),
        yellow_ratio=round(yellow_ratio, 3),
        dark_spot_ratio=round(dark_spot_ratio, 3),
        saturation_mean=round(saturation_mean, 1),
        summary=info["summary"],
        recommendation=info["recommendation"],
    )
