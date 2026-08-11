"""Yojana Sathi - government scheme assistant.

Uses a curated, static reference list of major central government
agricultural schemes (data/schemes.json). This is general public
information about scheme categories and headline benefits, not a live
eligibility engine connected to any government database - always verify
current terms and application windows on the official scheme website
before applying.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "schemes.json")


@dataclass
class Scheme:
    id: str
    name: str
    category: str
    benefit: str
    eligibility_summary: str
    official_site: str | None


def load_schemes() -> list[Scheme]:
    with open(DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return [
        Scheme(
            id=s["id"], name=s["name"], category=s["category"],
            benefit=s["benefit"], eligibility_summary=s["eligibility_summary"],
            official_site=s.get("official_site"),
        )
        for s in raw
    ]


def all_categories() -> list[str]:
    return sorted({s.category for s in load_schemes()})


def match_schemes(interested_categories: list[str] | None = None) -> list[Scheme]:
    """Return schemes, with any matching `interested_categories` sorted first."""
    schemes = load_schemes()
    if not interested_categories:
        return schemes

    def sort_key(s: Scheme) -> tuple[int, str]:
        matched = s.category in interested_categories
        return (0 if matched else 1, s.name)

    return sorted(schemes, key=sort_key)
