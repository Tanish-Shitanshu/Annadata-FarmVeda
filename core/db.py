"""SQLite persistence: accounts, farmer profiles, farm records, reminders, advice log,
marketplace listings/orders, cooperatives.

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
-- Login accounts. A farmer account owns one farmers row; a consumer account
-- only buys. Passwords are stored as salted scrypt hashes (core/auth.py).
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('farmer', 'consumer')),
    full_name TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    token_hash TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cooperatives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT,
    state TEXT,
    district TEXT,
    invite_code TEXT NOT NULL UNIQUE,
    created_by_farmer_id INTEGER NOT NULL REFERENCES farmers(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coop_members (
    coop_id INTEGER NOT NULL REFERENCES cooperatives(id) ON DELETE CASCADE,
    farmer_id INTEGER NOT NULL REFERENCES farmers(id),
    role TEXT NOT NULL CHECK (role IN ('admin', 'member')),
    joined_at TEXT NOT NULL,
    PRIMARY KEY (coop_id, farmer_id)
);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    farmer_id INTEGER NOT NULL REFERENCES farmers(id),
    coop_id INTEGER REFERENCES cooperatives(id),
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    unit TEXT NOT NULL,
    price_per_unit REAL NOT NULL CHECK (price_per_unit > 0),
    quantity_available REAL NOT NULL CHECK (quantity_available >= 0),
    fulfilment TEXT NOT NULL CHECK (fulfilment IN ('pickup', 'delivery', 'both')),
    organic INTEGER NOT NULL DEFAULT 0,
    harvest_date TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- One order per (checkout, farmer). Money never passes through the platform:
-- payment is settled between buyer and farmer on pickup/delivery.
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consumer_account_id INTEGER NOT NULL REFERENCES accounts(id),
    farmer_id INTEGER NOT NULL REFERENCES farmers(id),
    status TEXT NOT NULL CHECK (status IN
        ('placed', 'confirmed', 'ready', 'delivered', 'cancelled', 'rejected')),
    fulfilment TEXT NOT NULL CHECK (fulfilment IN ('pickup', 'delivery')),
    delivery_address TEXT,
    contact_phone TEXT,
    note TEXT,
    total_amount REAL NOT NULL,
    payment_method TEXT NOT NULL DEFAULT 'pay_on_delivery',
    paid INTEGER NOT NULL DEFAULT 0,
    cancel_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    title TEXT NOT NULL,
    unit TEXT NOT NULL,
    quantity REAL NOT NULL CHECK (quantity > 0),
    unit_price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS order_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    sender_account_id INTEGER NOT NULL REFERENCES accounts(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    consumer_account_id INTEGER NOT NULL REFERENCES accounts(id),
    farmer_id INTEGER NOT NULL REFERENCES farmers(id),
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
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


# Columns added to `farmers` after the first release. CREATE TABLE IF NOT EXISTS
# does not alter an existing table, so they are added here when missing.
_FARMER_COLUMNS = {
    "account_id": "INTEGER REFERENCES accounts(id)",
    "scheme_profile": "TEXT",   # JSON answers to the scheme-eligibility questions
}


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(farmers)")}
        for column, ddl in _FARMER_COLUMNS.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE farmers ADD COLUMN {column} {ddl}")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_farmers_account ON farmers(account_id) "
                     "WHERE account_id IS NOT NULL")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_farmer ON listings(farmer_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_consumer ON orders(consumer_account_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_farmer ON orders(farmer_id)")


def create_farmer(name: str, village: str, state: str, land_size_acres: float,
                   soil_type: str, preferred_language: str = "English",
                   account_id: int | None = None) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO farmers (name, village, state, land_size_acres, soil_type,
                                     preferred_language, created_at, account_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, village, state, land_size_acres, soil_type, preferred_language,
             _now(), account_id),
        )
        return cur.lastrowid


def get_farmer_by_account(account_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM farmers WHERE account_id = ?", (account_id,)).fetchone()


def get_scheme_profile(farmer_id: int) -> dict:
    """The farmer's saved answers to the scheme-eligibility questions ({} if none)."""
    import json
    with get_conn() as conn:
        row = conn.execute("SELECT scheme_profile FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
    if not row or not row["scheme_profile"]:
        return {}
    try:
        data = json.loads(row["scheme_profile"])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save_scheme_profile(farmer_id: int, answers: dict) -> None:
    import json
    with get_conn() as conn:
        conn.execute("UPDATE farmers SET scheme_profile = ? WHERE id = ?",
                     (json.dumps(answers, ensure_ascii=False), farmer_id))


def list_farmers() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM farmers ORDER BY created_at DESC").fetchall()


def get_farmer(farmer_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM farmers WHERE id = ?", (farmer_id,)).fetchone()


def update_farmer_profile(farmer_id: int, name: str, village: str, state: str,
                          land_size_acres: float, soil_type: str) -> None:
    """Edit a farmer's own profile (the account's display name is kept in step). Raises ValueError with a
    message that is safe to show."""
    name, village, state = (name or "").strip(), (village or "").strip(), (state or "").strip()
    if not name or len(name) > 80:
        raise ValueError("Enter your name (up to 80 characters).")
    if len(village) > 80 or len(state) > 80:
        raise ValueError("Village and state can be at most 80 characters.")
    try:
        land = float(land_size_acres)
    except (TypeError, ValueError):
        raise ValueError("Enter a valid land size in acres.") from None
    if not (0 <= land <= 100000):
        raise ValueError("Enter a valid land size in acres.")
    if not (soil_type or "").strip():
        raise ValueError("Choose a soil type.")
    with get_conn() as conn:
        row = conn.execute("SELECT account_id FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
        if row is None:
            raise ValueError("Farmer profile not found.")
        conn.execute("UPDATE farmers SET name = ?, village = ?, state = ?, land_size_acres = ?, soil_type = ? "
                     "WHERE id = ?", (name, village, state, land, soil_type.strip(), farmer_id))
        if row["account_id"]:
            conn.execute("UPDATE accounts SET full_name = ? WHERE id = ?", (name, row["account_id"]))


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


def latest_advice_decisions(farmer_id: int, kind: str) -> dict[str, str]:
    """{verdict: 'accepted'|'dismissed'} - the most recent decision per verdict for one kind of advice.
    Used so a dismissed scheme stays dismissed in later sessions."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT verdict, decision FROM advice_log WHERE farmer_id = ? AND kind = ? ORDER BY id",
            (farmer_id, kind)).fetchall()
    return {r["verdict"]: r["decision"] for r in rows}
