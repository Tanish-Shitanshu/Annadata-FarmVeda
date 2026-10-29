"""Yojana Sathi - scheme reference data.

A curated list of major central agricultural schemes (data/schemes.json) with
the headline benefit, who can apply, how, which documents, and where each fact
came from (`source_note`, `verified_on`). It is NOT connected to any government
database, and the rules change: the eligibility engine in core/eligibility.py
only gives a first indication. Always confirm on the official site or with the
local agriculture office before applying.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "schemes.json")


@dataclass
class Scheme:
    id: str
    short_name: str
    name: str
    category: str
    benefit: str
    eligibility_summary: str
    how_to_apply: str = ""
    documents: list[str] = field(default_factory=list)
    official_site: str | None = None
    verified_on: str | None = None
    source_note: str = ""


def load_schemes() -> list[Scheme]:
    with open(DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return [
        Scheme(
            id=s["id"], short_name=s.get("short_name", s["name"]), name=s["name"], category=s["category"],
            benefit=s["benefit"], eligibility_summary=s["eligibility_summary"],
            how_to_apply=s.get("how_to_apply", ""), documents=list(s.get("documents", [])),
            official_site=s.get("official_site"), verified_on=s.get("verified_on"),
            source_note=s.get("source_note", ""),
        )
        for s in raw
    ]


def get_scheme(scheme_id: str) -> Scheme | None:
    return next((s for s in load_schemes() if s.id == scheme_id), None)


def all_categories() -> list[str]:
    return sorted({s.category for s in load_schemes()})


def match_schemes(interested_categories: list[str] | None = None) -> list[Scheme]:
    """Return schemes, with any matching `interested_categories` sorted first."""
    schemes = load_schemes()
    if not interested_categories:
        return schemes

    def sort_key(s: Scheme) -> tuple[int, str]:
        return (0 if s.category in interested_categories else 1, s.name)

    return sorted(schemes, key=sort_key)
