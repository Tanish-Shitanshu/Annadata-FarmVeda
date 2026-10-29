"""Shared fixtures. No test touches the real network: `requests.get` is replaced
by a router that serves canned Open-Meteo responses."""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import db  # noqa: E402


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self.payload


def forecast_payload(days=7, tmax=32.0, tmin=22.0, rain=0.0, prob=10, wind=8.0, overrides=None):
    """Open-Meteo-shaped forecast starting today. `overrides` = {day_index: {field: value}}."""
    fields = {"temperature_2m_max": tmax, "temperature_2m_min": tmin, "precipitation_sum": rain,
              "precipitation_probability_max": prob, "wind_speed_10m_max": wind}
    daily = {"time": [(date.today() + timedelta(days=i)).isoformat() for i in range(days)]}
    for name, value in fields.items():
        daily[name] = [value] * days
    for idx, changes in (overrides or {}).items():
        for name, value in changes.items():
            daily[name][idx] = value
    return {"daily": daily}


def archive_payload(start: str, end: str, rain_per_day=5.0, temp=27.0, missing=0.0):
    """Daily history between two ISO dates. `missing` = fraction of days returned as null."""
    d0, d1 = datetime.fromisoformat(start).date(), datetime.fromisoformat(end).date()
    n = (d1 - d0).days + 1
    cut = int(n * missing)
    times = [(d0 + timedelta(days=i)).isoformat() for i in range(n)]
    return {"daily": {
        "time": times,
        "precipitation_sum": [None if i < cut else rain_per_day for i in range(n)],
        "temperature_2m_mean": [None if i < cut else temp for i in range(n)],
    }}


class Net:
    """Programmable fake for the three Open-Meteo endpoints."""

    def __init__(self):
        self.calls = []
        self.places = {}        # (lowercased name, country code or None) -> [result dicts]
        self.forecast = forecast_payload()
        self.archive = lambda params: archive_payload(params["start_date"], params["end_date"])
        self.fail = set()       # any of {"geocode", "forecast", "archive"} -> HTTP 500

    def __call__(self, url, params=None, timeout=None, **kw):
        params = params or {}
        self.calls.append((url, dict(params)))
        if "geocoding" in url:
            kind, body = "geocode", None
            if kind in self.fail:
                return FakeResponse({}, 500)
            key = (params["name"].lower(), params.get("countryCode"))
            results = self.places.get(key, [])
            return FakeResponse({"results": results} if results else {})
        if "archive" in url:
            if "archive" in self.fail:
                return FakeResponse({}, 500)
            return FakeResponse(self.archive(params))
        if "forecast" in url:
            if "forecast" in self.fail:
                return FakeResponse({}, 500)
            return FakeResponse(self.forecast)
        raise AssertionError(f"Unexpected URL in test: {url}")

    def add_place(self, name, lat=26.9, lon=75.8, admin1="Rajasthan", admin2="", country="India",
                  country_code="IN", worldwide_only=False):
        entry = {"name": name, "latitude": lat, "longitude": lon, "admin1": admin1,
                 "admin2": admin2, "country": country}
        if not worldwide_only:
            self.places.setdefault((name.lower(), country_code), []).append(entry)
        self.places.setdefault((name.lower(), None), []).append(entry)


@pytest.fixture
def net(monkeypatch):
    fake = Net()
    monkeypatch.setattr(requests, "get", fake)
    return fake


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    return db


@pytest.fixture
def farmer_id(tmp_db):
    """A farmer profile that belongs to a real account (so pages can sign in as them)."""
    _acct, farmer = new_farmer("test.farmer@example.com", "Test Farmer", "Rajasthan", "Jaipur", 4.0, "Sandy Loam")
    return farmer["id"]


# ── People helpers (use inside tests that take the tmp_db fixture) ──────────

def new_farmer(email="farmer@example.com", name="Ravi Kumar", state="Punjab", village="Khanna",
               land=3.0, soil="Alluvial"):
    """Create a farmer account + profile. Returns (account, farmer_row)."""
    from core import auth
    acct = auth.register(email, "s3cure-pass", "farmer", name,
                         {"village": village, "state": state, "land_size_acres": land, "soil_type": soil})
    return acct, db.get_farmer_by_account(acct.id)


def new_consumer(email="buyer@example.com", name="Asha Verma"):
    from core import auth
    return auth.register(email, "s3cure-pass", "consumer", name)


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch):
    """scrypt is deliberately slow; use the cheapest parameters in tests."""
    from core import auth
    monkeypatch.setattr(auth, "_SCRYPT_N", 2 ** 4)
