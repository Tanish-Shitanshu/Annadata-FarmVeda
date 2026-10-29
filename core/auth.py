"""Email + password accounts for farmers and consumers.

Deliberately small and self-contained (stdlib only):
  * passwords are stored as salted scrypt hashes, never in plain text;
  * login errors are generic, so they don't reveal whether an email exists;
  * 5 wrong passwords lock the account for 10 minutes (basic brute-force brake).

Known gaps, because there is no email service wired up: no email verification
and no "forgot password" flow. A hosted deployment should move to a managed
identity provider (e.g. Entra External ID) rather than grow this module.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from core import db

ROLES = ("farmer", "consumer")
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 128
MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 10

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2 ** 14, 8, 1
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")
_COMMON_PASSWORDS = {"password", "password1", "12345678", "123456789", "qwertyui", "iloveyou",
                     "11111111", "00000000", "abcd1234", "farmveda1"}
GENERIC_LOGIN_ERROR = "Invalid email or password."


class AuthError(Exception):
    """A problem the user can be told about (message is safe to display)."""


@dataclass(frozen=True)
class Account:
    id: int
    email: str
    role: str
    full_name: str


# ── Password hashing ────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R,
                            p=_SCRYPT_P, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                                n=int(n), r=int(r), p=int(p), dklen=len(digest_hex) // 2)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


_DUMMY_HASH = hash_password("not-a-real-password")  # spends the same time for unknown emails


# ── Validation ──────────────────────────────────────────────────────────────

def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_password(password: str, email: str = "") -> None:
    if len(password) < MIN_PASSWORD_LEN:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
    if len(password) > MAX_PASSWORD_LEN:
        raise AuthError(f"Password must be at most {MAX_PASSWORD_LEN} characters.")
    if password.lower() in _COMMON_PASSWORDS or (email and password.lower() == email.lower()):
        raise AuthError("That password is too easy to guess. Please choose another.")


# ── Registration / login ────────────────────────────────────────────────────

def register(email: str, password: str, role: str, full_name: str,
             farm: dict | None = None, language: str = "English") -> Account:
    """Create an account. For role='farmer', `farm` holds village/state/land_size_acres/soil_type
    and a farmer profile is created in the same transaction."""
    email = normalize_email(email)
    full_name = (full_name or "").strip()
    if role not in ROLES:
        raise AuthError("Choose whether you are a farmer or a consumer.")
    if not _EMAIL_RE.match(email) or len(email) > 254:
        raise AuthError("Enter a valid email address.")
    if not full_name or len(full_name) > 80:
        raise AuthError("Enter your name (up to 80 characters).")
    validate_password(password, email)

    farm = farm or {}
    land = farm.get("land_size_acres", 0) or 0
    if role == "farmer" and not (0 <= float(land) <= 100000):
        raise AuthError("Enter a valid land size in acres.")

    try:
        with db.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO accounts (email, password_hash, role, full_name, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (email, hash_password(password), role, full_name, db._now()),
            )
            account_id = cur.lastrowid
            if role == "farmer":
                conn.execute(
                    """INSERT INTO farmers (name, village, state, land_size_acres, soil_type,
                                             preferred_language, created_at, account_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (full_name, (farm.get("village") or "").strip()[:80], (farm.get("state") or "").strip()[:80],
                     float(land), farm.get("soil_type") or "Loamy", language, db._now(), account_id),
                )
    except sqlite3.IntegrityError:
        raise AuthError("An account with this email already exists. Try signing in instead.") from None
    return Account(id=account_id, email=email, role=role, full_name=full_name)


def login(email: str, password: str) -> Account:
    email = normalize_email(email)
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
        if row is None:
            verify_password(password, _DUMMY_HASH)
            raise AuthError(GENERIC_LOGIN_ERROR)

        now = datetime.now(timezone.utc)
        if row["locked_until"]:
            locked_until = datetime.fromisoformat(row["locked_until"])
            if locked_until > now:
                minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
                raise AuthError(f"Too many failed attempts. Try again in about {minutes} minute(s).")

        if verify_password(password, row["password_hash"]):
            conn.execute("UPDATE accounts SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
                         (row["id"],))
            return Account(id=row["id"], email=row["email"], role=row["role"], full_name=row["full_name"])

        attempts = row["failed_attempts"] + 1
        if attempts >= MAX_FAILED_ATTEMPTS:
            conn.execute("UPDATE accounts SET failed_attempts = 0, locked_until = ? WHERE id = ?",
                         ((now + timedelta(minutes=LOCK_MINUTES)).isoformat(), row["id"]))
        else:
            conn.execute("UPDATE accounts SET failed_attempts = ? WHERE id = ?", (attempts, row["id"]))
    # The failed-attempt counter must be committed, so raise after leaving the connection block.
    raise AuthError(GENERIC_LOGIN_ERROR)


def get_account(account_id: int) -> Account | None:
    with db.get_conn() as conn:
        row = conn.execute("SELECT id, email, role, full_name FROM accounts WHERE id = ?",
                           (account_id,)).fetchone()
    return Account(**dict(row)) if row else None


def change_password(account_id: int, old_password: str, new_password: str) -> None:
    with db.get_conn() as conn:
        row = conn.execute("SELECT email, password_hash FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if row is None or not verify_password(old_password, row["password_hash"]):
            raise AuthError("Your current password is incorrect.")
        validate_password(new_password, row["email"])
        conn.execute("UPDATE accounts SET password_hash = ?, failed_attempts = 0, locked_until = NULL "
                     "WHERE id = ?", (hash_password(new_password), account_id))
