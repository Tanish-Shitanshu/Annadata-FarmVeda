import sqlite3

import pytest

from core import db


def test_accept_creates_reminder_and_links_log(tmp_db, farmer_id):
    rid = tmp_db.accept_advice(farmer_id, "irrigation", "Irrigate soon", "hot", "Jaipur, India",
                               "Irrigate", "2026-06-01", "Irrigation")
    reminders = tmp_db.list_reminders(farmer_id)
    assert [r["id"] for r in reminders] == [rid] and reminders[0]["category"] == "Irrigation"
    log = tmp_db.list_advice_log(farmer_id)
    assert len(log) == 1 and log[0]["decision"] == "accepted" and log[0]["reminder_id"] == rid


def test_dismiss_logs_without_reminder(tmp_db, farmer_id):
    tmp_db.dismiss_advice(farmer_id, "sowing", "Wait", "rain", "Jaipur")
    assert tmp_db.list_reminders(farmer_id) == []
    entry = tmp_db.list_advice_log(farmer_id)[0]
    assert entry["decision"] == "dismissed" and entry["reminder_id"] is None


def test_log_is_newest_first_and_limited(tmp_db, farmer_id):
    for i in range(5):
        tmp_db.dismiss_advice(farmer_id, "sowing", f"v{i}", "r", "loc")
    assert [e["verdict"] for e in tmp_db.list_advice_log(farmer_id, limit=3)] == ["v4", "v3", "v2"]


def test_log_is_per_farmer(tmp_db, farmer_id):
    other = tmp_db.create_farmer("B", "X", "Y", 1, "Red")
    tmp_db.dismiss_advice(other, "sowing", "Wait", "r", "loc")
    assert tmp_db.list_advice_log(farmer_id) == []


def test_accept_is_atomic_when_log_insert_fails(tmp_db, farmer_id):
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.accept_advice(farmer_id, None, "v", "r", "loc", "T", "2026-06-01", "Sowing")  # kind NOT NULL
    assert tmp_db.list_reminders(farmer_id) == []


def test_accept_rejects_unknown_farmer(tmp_db):
    with pytest.raises(sqlite3.IntegrityError):
        tmp_db.accept_advice(999, "sowing", "Wait", "r", "loc", "T", "2026-06-01", "Sowing")
    assert tmp_db.list_advice_log(999) == []


def test_existing_database_without_advice_log_is_migrated(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE farmers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, village TEXT, "
                       "state TEXT, land_size_acres REAL, soil_type TEXT, preferred_language TEXT, "
                       "created_at TEXT NOT NULL); INSERT INTO farmers (name, created_at) VALUES ('Old','2024-01-01');")
    conn.commit(); conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    assert db.list_advice_log(1) == []
    assert db.get_farmer(1)["name"] == "Old"


def test_timestamps_are_timezone_aware_iso(tmp_db, farmer_id):
    tmp_db.dismiss_advice(farmer_id, "sowing", "Wait", "r", "loc")
    assert tmp_db.list_advice_log(farmer_id)[0]["created_at"].endswith("+00:00")


def test_due_soon_count(tmp_db, farmer_id):
    from datetime import date, timedelta
    tmp_db.add_reminder(farmer_id, "soon", (date.today() + timedelta(days=1)).isoformat(), "Other")
    tmp_db.add_reminder(farmer_id, "later", (date.today() + timedelta(days=30)).isoformat(), "Other")
    assert tmp_db.due_soon_count(farmer_id) == 1
