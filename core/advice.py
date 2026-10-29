"""Turn rule-based advisories into concrete reminders a farmer can accept or dismiss.

FarmVeda is human-in-the-loop by construction: it never acts on its own advice.
Every advisory is shown with a *suggested* reminder; the farmer accepts it
(creating the reminder) or dismisses it, and either decision is logged.

The verdict strings below must stay in sync with core/weather.py - the test
suite checks that every verdict the advisory functions can produce has a
mapping here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# verdict -> (reminder title, days from today, reminder category)
SOWING: dict[str, tuple[str, int, str]] = {
    "Good window": ("Sow now - favourable weather window", 0, "Sowing"),
    "Sow with irrigation planned": ("Sow, then arrange irrigation right after sowing", 0, "Sowing"),
    "Wait": ("Re-check the forecast before sowing (heavy rain expected)", 2, "Sowing"),
}

IRRIGATION: dict[str, tuple[str, int, str]] = {
    "Irrigate soon": ("Irrigate - hot, dry days ahead", 0, "Irrigation"),
    "Monitor": ("Check soil moisture before deciding to irrigate", 1, "Irrigation"),
    "Hold off": ("Re-check irrigation need after the expected rain", 3, "Irrigation"),
}

HARVEST: dict[str, tuple[str, int, str]] = {
    "Harvest before rain if crop is ready": ("Harvest before the rain if the crop is ready", 0, "Harvest"),
    "Dry window": ("Dry days ahead - good time to harvest and dry the crop", 0, "Harvest"),
}

_TABLES = {"sowing": SOWING, "irrigation": IRRIGATION, "harvest": HARVEST}


@dataclass(frozen=True)
class SuggestedReminder:
    title: str
    due_date: date
    category: str


def suggest_reminder(kind: str, advisory: dict, today: date | None = None) -> SuggestedReminder | None:
    """Suggested reminder for a sowing / irrigation / harvest advisory, or None
    if the verdict has no mapping."""
    today = today or date.today()
    entry = _TABLES.get(kind, {}).get(advisory.get("verdict", ""))
    if entry is None:
        return None
    title, offset_days, category = entry
    return SuggestedReminder(title=title, due_date=today + timedelta(days=offset_days), category=category)


def suggest_spraying_reminder(day_advisories: list[dict]) -> SuggestedReminder | None:
    """Suggest spraying on the first suitable day in the forecast, or None if
    every day is unsuitable."""
    for entry in day_advisories:
        if entry["verdict"] == "Suitable":
            day: date = entry["day"]
            return SuggestedReminder(
                title=f"Spray on {day.strftime('%a %d %b')} (low rain chance, calm wind)",
                due_date=day,
                category="Spraying",
            )
    return None
