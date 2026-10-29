"""SQLite persistence for farmer profiles, farm records, and reminders.

All data stays local (matches the offline-first approach used elsewhere in
this project) - no cloud storage, no external database.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Iterator

DB_PATH = os.environ.get("FARMVEDA_DB_PATH", "farmveda.db")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

SCHEMA = """
CREATE TABLE IF NOT EXISTS farmers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    village TEXT,
    state TEXT,
    land_size_acres REAL,
    soil_type TEXT,
    preferred_language TEXT DEFAULT 'English',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS farm_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farmer_id INTEGER NOT NULL REFERENCES farmers(id),
    crop TEXT NOT NULL,
    season TEXT,
    sown_on TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farmer_id INTEGER NOT NULL REFERENCES farmers(id),
    title TEXT NOT NULL,
    due_date TEXT NOT NULL,
    category TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Every piece of advice shown to a farmer and what the farmer decided to do
-- with it. The app never acts on its own advice: a person accepts or dismisses.
CREATE TABLE IF NOT EXISTS advice_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farmer_id INTEGER NOT NULL REFERENCES farmers(id),
    kind TEXT NOT NULL,
    verdict TEXT NOT NULL,
    reason TEXT,
    location TEXT,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'dismissed')),
    reminder_id INTEGER REFERENCES reminders(id),
    created_at TEXT NOT NULL
);
"""


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def create_farmer(name: str, village: str, state: str, land_size_acres: float,
                   soil_type: str, preferred_language: str = "English") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO farmers (name, village, state, land_size_acres, soil_type,
                                     preferred_language, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, village, state, land_size_acres, soil_type, preferred_language,
             _now()),
        )
        return cur.lastrowid


def list_farmers() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM farmers ORDER BY created_at DESC").fetchall()


def get_farmer(farmer_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM farmers WHERE id = ?", (farmer_id,)).fetchone()


def update_farmer_language(farmer_id: int, language: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE farmers SET preferred_language = ? WHERE id = ?",
                     (language, farmer_id))


def add_farm_record(farmer_id: int, crop: str, season: str, sown_on: str, notes: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO farm_records (farmer_id, crop, season, sown_on, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (farmer_id, crop, season, sown_on, notes, _now()),
        )
        return cur.lastrowid


def list_farm_records(farmer_id: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM farm_records WHERE farmer_id = ? ORDER BY created_at DESC",
            (farmer_id,),
        ).fetchall()


def add_reminder(farmer_id: int, title: str, due_date: str, category: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO reminders (farmer_id, title, due_date, category, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (farmer_id, title, due_date, category, _now()),
        )
        return cur.lastrowid


def list_reminders(farmer_id: int, include_done: bool = False) -> list[sqlite3.Row]:
    with get_conn() as conn:
        query = "SELECT * FROM reminders WHERE farmer_id = ?"
        if not include_done:
            query += " AND done = 0"
        query += " ORDER BY due_date ASC"
        return conn.execute(query, (farmer_id,)).fetchall()


def mark_reminder_done(reminder_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,))


def due_soon_count(farmer_id: int, within_days: int = 3) -> int:
    reminders = list_reminders(farmer_id)
    today = date.today()
    count = 0
    for r in reminders:
        try:
            due = date.fromisoformat(r["due_date"])
        except ValueError:
            continue
        if (due - today).days <= within_days:
            count += 1
    return count


# ── Advice decisions (human-in-the-loop) ────────────────────────────────────

def accept_advice(farmer_id: int, kind: str, verdict: str, reason: str, location: str,
                  reminder_title: str, reminder_due: str, reminder_category: str) -> int:
    """Farmer accepted a suggestion: create the reminder and log the decision
    in one transaction, so the log never points at a reminder that doesn't exist."""
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO reminders (farmer_id, title, due_date, category, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (farmer_id, reminder_title, reminder_due, reminder_category, _now()),
        )
        reminder_id = cur.lastrowid
        conn.execute(
            """INSERT INTO advice_log (farmer_id, kind, verdict, reason, location,
                                       decision, reminder_id, created_at)
               VALUES (?, ?, ?, ?, ?, 'accepted', ?, ?)""",
            (farmer_id, kind, verdict, reason, location, reminder_id, _now()),
        )
        return reminder_id


def dismiss_advice(farmer_id: int, kind: str, verdict: str, reason: str, location: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO advice_log (farmer_id, kind, verdict, reason, location,
                                       decision, created_at)
               VALUES (?, ?, ?, ?, ?, 'dismissed', ?)""",
            (farmer_id, kind, verdict, reason, location, _now()),
        )


def list_advice_log(farmer_id: int, limit: int = 50) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM advice_log WHERE farmer_id = ? ORDER BY id DESC LIMIT ?",
            (farmer_id, limit),
        ).fetchall()
