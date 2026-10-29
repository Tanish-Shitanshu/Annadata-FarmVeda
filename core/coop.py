"""Farmer cooperatives: a group of farmers who pool produce under one name.

What a cooperative gives on this platform:
  * a shared storefront - buyers see the group's combined stock per product;
  * bulk orders - a large quantity is split across members' listings, cheapest
    first, producing one normal order per farmer (each farmer still confirms
    their own part);
  * a headcount toward formal schemes (an FPO needs 300 farmers in the plains,
    100 in hilly/North-Eastern areas).

Joining is by invite code, so nobody can be added without knowing it, and only
admins can remove members or change roles. This is a lightweight in-app group,
not a legally registered cooperative society or FPO.
"""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass

from core import db
from core.market import MarketError, _text, checkout

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # no 0/O/1/I
MAX_COOPS_PER_FARMER = 5


class CoopError(MarketError):
    """A problem the user can be told about."""


def _new_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))


def _role(conn, coop_id: int, farmer_id: int) -> str | None:
    row = conn.execute("SELECT role FROM coop_members WHERE coop_id = ? AND farmer_id = ?",
                       (coop_id, farmer_id)).fetchone()
    return row["role"] if row else None


def _require_admin(conn, coop_id: int, farmer_id: int) -> None:
    if _role(conn, coop_id, farmer_id) != "admin":
        raise CoopError("Only a cooperative admin can do that.")


def create_coop(farmer_id: int, name: str, description: str = "", state: str = "", district: str = "") -> int:
    name = _text(name, "Cooperative name", 60, required=True)
    description = _text(description, "Description", 400)
    state, district = _text(state, "State", 60), _text(district, "District", 60)
    with db.get_conn() as conn:
        if conn.execute("SELECT 1 FROM farmers WHERE id = ?", (farmer_id,)).fetchone() is None:
            raise CoopError("Only farmer accounts can create a cooperative.")
        count = conn.execute("SELECT COUNT(*) FROM coop_members WHERE farmer_id = ?", (farmer_id,)).fetchone()[0]
        if count >= MAX_COOPS_PER_FARMER:
            raise CoopError(f"You can belong to at most {MAX_COOPS_PER_FARMER} cooperatives.")
        try:
            cur = conn.execute(
                "INSERT INTO cooperatives (name, description, state, district, invite_code, "
                "created_by_farmer_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, description, state, district, _new_code(), farmer_id, db._now()))
        except sqlite3.IntegrityError:
            raise CoopError("A cooperative with that name already exists.") from None
        coop_id = cur.lastrowid
        conn.execute("INSERT INTO coop_members (coop_id, farmer_id, role, joined_at) VALUES (?, ?, 'admin', ?)",
                     (coop_id, farmer_id, db._now()))
        return coop_id


def join_coop(farmer_id: int, invite_code: str) -> int:
    code = (invite_code or "").strip().upper()
    with db.get_conn() as conn:
        coop = conn.execute("SELECT id FROM cooperatives WHERE invite_code = ?", (code,)).fetchone()
        if coop is None:
            raise CoopError("That invite code isn't valid.")
        if _role(conn, coop["id"], farmer_id):
            raise CoopError("You are already a member of this cooperative.")
        count = conn.execute("SELECT COUNT(*) FROM coop_members WHERE farmer_id = ?", (farmer_id,)).fetchone()[0]
        if count >= MAX_COOPS_PER_FARMER:
            raise CoopError(f"You can belong to at most {MAX_COOPS_PER_FARMER} cooperatives.")
        conn.execute("INSERT INTO coop_members (coop_id, farmer_id, role, joined_at) VALUES (?, ?, 'member', ?)",
                     (coop["id"], farmer_id, db._now()))
        return coop["id"]


def _detach_listings(conn, coop_id: int, farmer_id: int) -> None:
    conn.execute("UPDATE listings SET coop_id = NULL WHERE coop_id = ? AND farmer_id = ?", (coop_id, farmer_id))


def leave_coop(farmer_id: int, coop_id: int) -> None:
    with db.get_conn() as conn:
        role = _role(conn, coop_id, farmer_id)
        if role is None:
            raise CoopError("You are not a member of this cooperative.")
        others = conn.execute("SELECT COUNT(*) FROM coop_members WHERE coop_id = ? AND farmer_id != ?",
                              (coop_id, farmer_id)).fetchone()[0]
        if role == "admin":
            other_admins = conn.execute(
                "SELECT COUNT(*) FROM coop_members WHERE coop_id = ? AND role = 'admin' AND farmer_id != ?",
                (coop_id, farmer_id)).fetchone()[0]
            if others and not other_admins:
                raise CoopError("Make another member an admin before you leave.")
        _detach_listings(conn, coop_id, farmer_id)
        conn.execute("DELETE FROM coop_members WHERE coop_id = ? AND farmer_id = ?", (coop_id, farmer_id))
        if not others:                       # last member out: remove the empty cooperative
            conn.execute("DELETE FROM cooperatives WHERE id = ?", (coop_id,))


def remove_member(admin_farmer_id: int, coop_id: int, member_farmer_id: int) -> None:
    with db.get_conn() as conn:
        _require_admin(conn, coop_id, admin_farmer_id)
        if member_farmer_id == admin_farmer_id:
            raise CoopError("Use 'Leave' to leave the cooperative yourself.")
        if _role(conn, coop_id, member_farmer_id) is None:
            raise CoopError("That farmer is not a member.")
        _detach_listings(conn, coop_id, member_farmer_id)
        conn.execute("DELETE FROM coop_members WHERE coop_id = ? AND farmer_id = ?", (coop_id, member_farmer_id))


def set_member_role(admin_farmer_id: int, coop_id: int, member_farmer_id: int, role: str) -> None:
    if role not in ("admin", "member"):
        raise CoopError("Role must be admin or member.")
    with db.get_conn() as conn:
        _require_admin(conn, coop_id, admin_farmer_id)
        if _role(conn, coop_id, member_farmer_id) is None:
            raise CoopError("That farmer is not a member.")
        if member_farmer_id == admin_farmer_id and role != "admin":
            admins = conn.execute("SELECT COUNT(*) FROM coop_members WHERE coop_id = ? AND role = 'admin'",
                                  (coop_id,)).fetchone()[0]
            if admins <= 1:
                raise CoopError("A cooperative needs at least one admin.")
        conn.execute("UPDATE coop_members SET role = ? WHERE coop_id = ? AND farmer_id = ?",
                     (role, coop_id, member_farmer_id))


def regenerate_invite(admin_farmer_id: int, coop_id: int) -> str:
    with db.get_conn() as conn:
        _require_admin(conn, coop_id, admin_farmer_id)
        code = _new_code()
        conn.execute("UPDATE cooperatives SET invite_code = ? WHERE id = ?", (code, coop_id))
        return code


# ── Reading ─────────────────────────────────────────────────────────────────

def my_coops(farmer_id: int):
    with db.get_conn() as conn:
        return conn.execute(
            """SELECT c.*, m.role AS my_role,
                      (SELECT COUNT(*) FROM coop_members x WHERE x.coop_id = c.id) AS member_count
               FROM cooperatives c JOIN coop_members m ON m.coop_id = c.id
               WHERE m.farmer_id = ? ORDER BY c.name COLLATE NOCASE""", (farmer_id,)).fetchall()


def get_coop(coop_id: int, viewer_farmer_id: int | None = None):
    """Public view of a cooperative. The invite code is included only for admins."""
    with db.get_conn() as conn:
        row = conn.execute(
            """SELECT c.id, c.name, c.description, c.state, c.district, c.created_at, c.invite_code,
                      (SELECT COUNT(*) FROM coop_members x WHERE x.coop_id = c.id) AS member_count
               FROM cooperatives c WHERE c.id = ?""", (coop_id,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        if viewer_farmer_id is None or _role(conn, coop_id, viewer_farmer_id) != "admin":
            data.pop("invite_code")
        return data


def list_coops(state: str | None = None):
    sql = """SELECT c.id, c.name, c.description, c.state, c.district,
                    (SELECT COUNT(*) FROM coop_members x WHERE x.coop_id = c.id) AS member_count,
                    (SELECT COUNT(*) FROM listings l WHERE l.coop_id = c.id AND l.status = 'active'
                        AND l.quantity_available > 0) AS active_listings
             FROM cooperatives c"""
    params: list = []
    if state:
        sql += " WHERE c.state = ? COLLATE NOCASE"
        params.append(state)
    with db.get_conn() as conn:
        return conn.execute(sql + " ORDER BY member_count DESC, c.name COLLATE NOCASE", params).fetchall()


def members(coop_id: int):
    with db.get_conn() as conn:
        return conn.execute(
            """SELECT f.id, f.name, f.village, f.state, m.role, m.joined_at
               FROM coop_members m JOIN farmers f ON f.id = m.farmer_id
               WHERE m.coop_id = ? ORDER BY m.role, f.name COLLATE NOCASE""", (coop_id,)).fetchall()


def is_member(farmer_id: int, coop_id: int) -> bool:
    with db.get_conn() as conn:
        return _role(conn, coop_id, farmer_id) is not None


# ── Pooled stock & bulk ordering ────────────────────────────────────────────

def product_key(title: str, unit: str) -> str:
    """Listings are 'the same product' when name (case/space-insensitive) and unit match."""
    return f"{' '.join(title.lower().split())}|{unit}"


@dataclass
class PooledProduct:
    key: str
    title: str
    unit: str
    total_quantity: float
    farmers: int
    min_price: float
    max_price: float


def pooled_stock(coop_id: int) -> list[PooledProduct]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM listings WHERE coop_id = ? AND status = 'active' AND quantity_available > 0",
            (coop_id,)).fetchall()
    groups: dict[str, list] = {}
    for row in rows:
        groups.setdefault(product_key(row["title"], row["unit"]), []).append(row)
    pooled = []
    for key, items in groups.items():
        pooled.append(PooledProduct(
            key=key, title=items[0]["title"], unit=items[0]["unit"],
            total_quantity=round(sum(i["quantity_available"] for i in items), 2),
            farmers=len({i["farmer_id"] for i in items}),
            min_price=min(i["price_per_unit"] for i in items), max_price=max(i["price_per_unit"] for i in items)))
    return sorted(pooled, key=lambda p: p.title.lower())


def allocate(coop_id: int, key: str, quantity: float) -> list[tuple[int, float]]:
    """Split `quantity` of one pooled product across members' listings, cheapest first.
    Returns [(listing_id, quantity)]; raises CoopError if the pool can't cover it."""
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        raise CoopError("Quantity must be a number.") from None
    if not quantity > 0:
        raise CoopError("Quantity must be more than 0.")
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM listings WHERE coop_id = ? AND status = 'active' AND quantity_available > 0 "
            "ORDER BY price_per_unit ASC, id ASC", (coop_id,)).fetchall()
    matching = [r for r in rows if product_key(r["title"], r["unit"]) == key]
    return allocate_greedy(matching, quantity)


def allocate_greedy(listings, quantity: float) -> list[tuple[int, float]]:
    """Pure helper: take from the cheapest listings first. `listings` are rows/dicts with
    id, quantity_available, price_per_unit."""
    remaining = round(quantity, 2)
    available = round(sum(l["quantity_available"] for l in listings), 2)
    if remaining > available:
        raise CoopError(f"The cooperative has only {available:g} available.")
    plan: list[tuple[int, float]] = []
    for listing in sorted(listings, key=lambda l: (l["price_per_unit"], l["id"])):
        if remaining <= 0:
            break
        take = round(min(remaining, listing["quantity_available"]), 2)
        if take > 0:
            plan.append((listing["id"], take))
            remaining = round(remaining - take, 2)
    return plan


def bulk_order(consumer_account_id: int, coop_id: int, key: str, quantity: float, fulfilment: str,
               delivery_address: str = "", contact_phone: str = "", note: str = "") -> list[int]:
    """Place a bulk order against the cooperative's pooled stock: one order per farmer involved."""
    plan = allocate(coop_id, key, quantity)
    cart = {listing_id: qty for listing_id, qty in plan}
    return checkout(consumer_account_id, cart, fulfilment, delivery_address, contact_phone, note)


# ── Link to formal FPO thresholds ───────────────────────────────────────────

FPO_MIN_MEMBERS_PLAINS = 300
FPO_MIN_MEMBERS_HILLY_NE = 100
