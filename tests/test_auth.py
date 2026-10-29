import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core import auth, db
from core.auth import AuthError

FARM = {"village": "Khanna", "state": "Punjab", "land_size_acres": 3.5, "soil_type": "Alluvial"}


def test_password_hash_is_salted_and_verifies():
    h1, h2 = auth.hash_password("correct horse"), auth.hash_password("correct horse")
    assert h1 != h2 and "correct horse" not in h1
    assert auth.verify_password("correct horse", h1) and not auth.verify_password("wrong", h1)


@pytest.mark.parametrize("stored", ["", "plain", "scrypt$x$y", "md5$1$2$3$aa$bb", "scrypt$16384$8$1$zz$00"])
def test_verify_rejects_malformed_hashes(stored):
    assert auth.verify_password("x", stored) is False


def test_register_farmer_creates_account_and_profile_together(tmp_db):
    acct = auth.register("  Ravi@Example.COM ", "s3cure-pass", "farmer", "Ravi", FARM)
    assert acct.email == "ravi@example.com" and acct.role == "farmer"
    farmer = db.get_farmer_by_account(acct.id)
    assert farmer["name"] == "Ravi" and farmer["village"] == "Khanna" and farmer["land_size_acres"] == 3.5


def test_register_consumer_has_no_farm_profile(tmp_db):
    acct = auth.register("c@example.com", "s3cure-pass", "consumer", "Asha")
    assert db.get_farmer_by_account(acct.id) is None and auth.get_account(acct.id).role == "consumer"


def test_password_is_never_stored_in_plain_text(tmp_db):
    auth.register("c@example.com", "s3cure-pass", "consumer", "Asha")
    with db.get_conn() as conn:
        stored = conn.execute("SELECT password_hash FROM accounts").fetchone()[0]
    assert "s3cure-pass" not in stored and stored.startswith("scrypt$")


@pytest.mark.parametrize("email", ["", "nope", "a@b", "a b@c.com", "@c.com", "a@c..com"])
def test_bad_emails_rejected(tmp_db, email):
    with pytest.raises(AuthError, match="valid email"):
        auth.register(email, "s3cure-pass", "consumer", "X")


@pytest.mark.parametrize("pw", ["short", "password", "12345678", "a" * 200])
def test_bad_passwords_rejected(tmp_db, pw):
    with pytest.raises(AuthError):
        auth.register("a@example.com", pw, "consumer", "X")


def test_password_equal_to_email_rejected(tmp_db):
    with pytest.raises(AuthError, match="easy to guess"):
        auth.register("someone@example.com", "someone@example.com", "consumer", "X")


def test_duplicate_email_rejected_case_insensitively_and_creates_nothing(tmp_db):
    auth.register("a@example.com", "s3cure-pass", "farmer", "A", FARM)
    with pytest.raises(AuthError, match="already exists"):
        auth.register("A@EXAMPLE.com", "s3cure-pass", "farmer", "A2", FARM)
    assert len(db.list_farmers()) == 1


def test_bad_role_and_name_rejected(tmp_db):
    with pytest.raises(AuthError):
        auth.register("a@example.com", "s3cure-pass", "admin", "X")
    with pytest.raises(AuthError):
        auth.register("a@example.com", "s3cure-pass", "consumer", "   ")


def test_farmer_land_size_validated(tmp_db):
    with pytest.raises(AuthError, match="land size"):
        auth.register("a@example.com", "s3cure-pass", "farmer", "A", {**FARM, "land_size_acres": -3})


def test_login_success_and_email_normalisation(tmp_db):
    acct = auth.register("a@example.com", "s3cure-pass", "consumer", "A")
    assert auth.login(" A@Example.com ", "s3cure-pass").id == acct.id


def test_login_errors_do_not_reveal_whether_email_exists(tmp_db):
    auth.register("a@example.com", "s3cure-pass", "consumer", "A")
    with pytest.raises(AuthError) as wrong_pw:
        auth.login("a@example.com", "bad-password")
    with pytest.raises(AuthError) as no_user:
        auth.login("ghost@example.com", "bad-password")
    assert str(wrong_pw.value) == str(no_user.value) == auth.GENERIC_LOGIN_ERROR


def test_lockout_after_repeated_failures_even_with_right_password(tmp_db):
    auth.register("a@example.com", "s3cure-pass", "consumer", "A")
    for _ in range(auth.MAX_FAILED_ATTEMPTS):
        with pytest.raises(AuthError):
            auth.login("a@example.com", "wrong-pass")
    with pytest.raises(AuthError, match="Too many failed attempts"):
        auth.login("a@example.com", "s3cure-pass")


def test_lockout_expires(tmp_db):
    acct = auth.register("a@example.com", "s3cure-pass", "consumer", "A")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with db.get_conn() as conn:
        conn.execute("UPDATE accounts SET locked_until = ? WHERE id = ?", (past, acct.id))
    assert auth.login("a@example.com", "s3cure-pass").id == acct.id


def test_successful_login_resets_failure_counter(tmp_db):
    auth.register("a@example.com", "s3cure-pass", "consumer", "A")
    for _ in range(auth.MAX_FAILED_ATTEMPTS - 1):
        with pytest.raises(AuthError):
            auth.login("a@example.com", "wrong-pass")
    auth.login("a@example.com", "s3cure-pass")
    with pytest.raises(AuthError, match="Invalid"):          # counter restarted, so not locked yet
        auth.login("a@example.com", "wrong-pass")


def test_change_password(tmp_db):
    acct = auth.register("a@example.com", "s3cure-pass", "consumer", "A")
    with pytest.raises(AuthError, match="current password"):
        auth.change_password(acct.id, "nope", "brand-new-pass")
    auth.change_password(acct.id, "s3cure-pass", "brand-new-pass")
    assert auth.login("a@example.com", "brand-new-pass").id == acct.id
    with pytest.raises(AuthError):
        auth.login("a@example.com", "s3cure-pass")


def test_sql_injection_in_email_is_just_a_bad_email(tmp_db):
    with pytest.raises(AuthError):
        auth.login("' OR 1=1 --", "x")


def test_one_farmer_profile_per_account(tmp_db):
    acct = auth.register("a@example.com", "s3cure-pass", "farmer", "A", FARM)
    with pytest.raises(sqlite3.IntegrityError):
        db.create_farmer("Dup", "v", "s", 1, "Red", account_id=acct.id)


def test_scheme_profile_roundtrip_and_migration(tmp_path, monkeypatch):
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE farmers (id INTEGER PRIMARY KEY, name TEXT NOT NULL, village TEXT, "
                       "state TEXT, land_size_acres REAL, soil_type TEXT, preferred_language TEXT, "
                       "created_at TEXT NOT NULL); INSERT INTO farmers (name, created_at) VALUES ('Old','2024-01-01');")
    conn.commit(); conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db(); db.init_db()                                  # idempotent
    assert db.get_scheme_profile(1) == {}
    db.save_scheme_profile(1, {"land_ownership": "owner", "bank_aadhaar_linked": True})
    assert db.get_scheme_profile(1)["land_ownership"] == "owner"
    assert db.get_farmer_by_account(1) is None
