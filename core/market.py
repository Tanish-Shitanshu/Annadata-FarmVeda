"""Direct farmer-to-consumer marketplace: listings, cart checkout, orders,
order messages and reviews.

Design rules that the tests pin down:
  * Authorization lives here, not in the UI. Every function that changes data
    takes the acting account and checks it owns the thing being changed.
  * Prices come from the database at checkout, never from the client/cart.
  * Stock is reserved when an order is placed, in the same transaction as the
    order, so two buyers can't both get the last kilo. Cancelling/rejecting
    puts it back.
  * Money never passes through the platform. Orders are "pay on pickup/delivery";
    the farmer records receipt. There is no payment gateway.
  * A buyer's phone and address are visible only to the farmer on that order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core import db

CATEGORIES = ["Vegetables", "Fruits", "Grains & Cereals", "Pulses", "Oilseeds", "Spices", "Dairy", "Other"]
UNITS = ["kg", "quintal", "dozen", "litre", "piece"]
FULFILMENT_OPTIONS = ["pickup", "delivery", "both"]
ORDER_STATUSES = ["placed", "confirmed", "ready", "delivered", "cancelled", "rejected"]
SORTS = {"newest": "l.id DESC", "price_asc": "l.price_per_unit ASC, l.id DESC",
         "price_desc": "l.price_per_unit DESC, l.id DESC"}

MAX_PRICE = 1_000_000
MAX_QUANTITY = 1_000_000
MAX_CART_LINES = 30

# who may move an order from one status to another
_FARMER_TRANSITIONS = {
    "placed": {"confirmed", "rejected"},
    "confirmed": {"ready", "delivered", "cancelled"},
    "ready": {"delivered", "cancelled"},
}
_CONSUMER_TRANSITIONS = {"placed": {"cancelled"}}

_PHONE_RE = re.compile(r"^\+?[0-9]{10,13}$")


class MarketError(Exception):
    """A problem the user can be told about (message is safe to display)."""


# ── Validation helpers ──────────────────────────────────────────────────────

def _text(value, label: str, max_len: int, required: bool = False) -> str:
    value = (value or "").strip()
    if required and not value:
        raise MarketError(f"{label} is required.")
    if len(value) > max_len:
        raise MarketError(f"{label} must be at most {max_len} characters.")
    return value


def _number(value, label: str, minimum: float, maximum: float, allow_equal_min: bool) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise MarketError(f"{label} must be a number.") from None
    if number != number or number in (float("inf"), float("-inf")):   # NaN / inf
        raise MarketError(f"{label} must be a number.")
    if number < minimum or (number == minimum and not allow_equal_min):
        raise MarketError(f"{label} must be {'at least' if allow_equal_min else 'more than'} {minimum:g}.")
    if number > maximum:
        raise MarketError(f"{label} must be at most {maximum:g}.")
    return round(number, 2)


def _one_of(value, label: str, options: list[str]) -> str:
    if value not in options:
        raise MarketError(f"{label} must be one of: {', '.join(options)}.")
    return value


def _is_member(conn, farmer_id: int, coop_id: int) -> bool:
    return conn.execute("SELECT 1 FROM coop_members WHERE coop_id = ? AND farmer_id = ?",
                        (coop_id, farmer_id)).fetchone() is not None


def _like_escape(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# ── Listings ────────────────────────────────────────────────────────────────

def _clean_listing_fields(fields: dict) -> dict:
    cleaned = {}
    if "title" in fields:
        cleaned["title"] = _text(fields["title"], "Product name", 80, required=True)
    if "category" in fields:
        cleaned["category"] = _one_of(fields["category"], "Category", CATEGORIES)
    if "description" in fields:
        cleaned["description"] = _text(fields["description"], "Description", 500)
    if "unit" in fields:
        cleaned["unit"] = _one_of(fields["unit"], "Unit", UNITS)
    if "price_per_unit" in fields:
        cleaned["price_per_unit"] = _number(fields["price_per_unit"], "Price", 0, MAX_PRICE, False)
    if "quantity_available" in fields:
        cleaned["quantity_available"] = _number(fields["quantity_available"], "Quantity", 0, MAX_QUANTITY, True)
    if "fulfilment" in fields:
        cleaned["fulfilment"] = _one_of(fields["fulfilment"], "Pickup/delivery option", FULFILMENT_OPTIONS)
    if "organic" in fields:
        cleaned["organic"] = 1 if fields["organic"] else 0
    if "harvest_date" in fields:
        cleaned["harvest_date"] = _text(fields["harvest_date"], "Harvest date", 10) or None
    if "status" in fields:
        cleaned["status"] = _one_of(fields["status"], "Status", ["active", "paused"])
    if "coop_id" in fields:
        cleaned["coop_id"] = fields["coop_id"]
    return cleaned


def create_listing(farmer_id: int, title: str, category: str, unit: str, price_per_unit: float,
                   quantity: float, fulfilment: str = "both", description: str = "",
                   organic: bool = False, harvest_date: str | None = None,
                   coop_id: int | None = None) -> int:
    fields = _clean_listing_fields({
        "title": title, "category": category, "unit": unit, "price_per_unit": price_per_unit,
        "quantity_available": quantity, "fulfilment": fulfilment, "description": description,
        "organic": organic, "harvest_date": harvest_date})
    now = db._now()
    with db.get_conn() as conn:
        if conn.execute("SELECT 1 FROM farmers WHERE id = ?", (farmer_id,)).fetchone() is None:
            raise MarketError("Only farmer accounts can create listings.")
        if coop_id is not None and not _is_member(conn, farmer_id, coop_id):
            raise MarketError("You can only list under a cooperative you belong to.")
        cur = conn.execute(
            """INSERT INTO listings (farmer_id, coop_id, title, category, description, unit,
                                     price_per_unit, quantity_available, fulfilment, organic,
                                     harvest_date, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (farmer_id, coop_id, fields["title"], fields["category"], fields["description"],
             fields["unit"], fields["price_per_unit"], fields["quantity_available"],
             fields["fulfilment"], fields["organic"], fields["harvest_date"], now, now))
        return cur.lastrowid


def update_listing(farmer_id: int, listing_id: int, **changes) -> None:
    allowed = {"title", "category", "description", "unit", "price_per_unit", "quantity_available",
               "fulfilment", "organic", "harvest_date", "status", "coop_id"}
    unknown = set(changes) - allowed
    if unknown:
        raise MarketError(f"Can't change: {', '.join(sorted(unknown))}.")
    fields = _clean_listing_fields(changes)
    if not fields:
        return
    with db.get_conn() as conn:
        row = conn.execute("SELECT farmer_id FROM listings WHERE id = ?", (listing_id,)).fetchone()
        if row is None or row["farmer_id"] != farmer_id:
            raise MarketError("Listing not found.")
        coop_id = fields.get("coop_id")
        if coop_id is not None and not _is_member(conn, farmer_id, coop_id):
            raise MarketError("You can only list under a cooperative you belong to.")
        assignments = ", ".join(f"{name} = ?" for name in fields)    # names come from the allow-list above
        conn.execute(f"UPDATE listings SET {assignments}, updated_at = ? WHERE id = ?",
                     (*fields.values(), db._now(), listing_id))


def get_listing(listing_id: int):
    with db.get_conn() as conn:
        return conn.execute(_LISTING_SELECT + " WHERE l.id = ?", (listing_id,)).fetchone()


_LISTING_SELECT = """
SELECT l.*, f.name AS farmer_name, f.village AS village, f.state AS state, c.name AS coop_name,
       (SELECT AVG(r.rating) FROM reviews r WHERE r.farmer_id = l.farmer_id) AS farmer_rating,
       (SELECT COUNT(*) FROM reviews r WHERE r.farmer_id = l.farmer_id) AS farmer_review_count
FROM listings l
JOIN farmers f ON f.id = l.farmer_id
LEFT JOIN cooperatives c ON c.id = l.coop_id
"""


def list_listings(search: str | None = None, category: str | None = None, state: str | None = None,
                  coop_id: int | None = None, farmer_id: int | None = None,
                  include_unavailable: bool = False, sort: str = "newest", limit: int = 60):
    """Public browse (only active, in-stock listings) unless include_unavailable is set,
    which the farmer's own shop view uses."""
    where, params = [], []
    if not include_unavailable:
        where.append("l.status = 'active' AND l.quantity_available > 0")
    if search and search.strip():
        like = f"%{_like_escape(search.strip()[:60])}%"
        where.append("(l.title LIKE ? ESCAPE '\\' OR l.description LIKE ? ESCAPE '\\')")
        params += [like, like]
    if category:
        where.append("l.category = ?")
        params.append(category)
    if state:
        where.append("f.state = ? COLLATE NOCASE")
        params.append(state)
    if coop_id is not None:
        where.append("l.coop_id = ?")
        params.append(coop_id)
    if farmer_id is not None:
        where.append("l.farmer_id = ?")
        params.append(farmer_id)
    order_by = SORTS.get(sort, SORTS["newest"])
    sql = _LISTING_SELECT + (" WHERE " + " AND ".join(where) if where else "") + \
        f" ORDER BY {order_by} LIMIT ?"
    params.append(max(1, min(int(limit), 200)))
    with db.get_conn() as conn:
        return conn.execute(sql, params).fetchall()


def listing_states() -> list[str]:
    with db.get_conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT f.state FROM listings l JOIN farmers f ON f.id = l.farmer_id
               WHERE l.status = 'active' AND l.quantity_available > 0 AND f.state IS NOT NULL AND f.state != ''
               ORDER BY f.state COLLATE NOCASE""").fetchall()
    return [r["state"] for r in rows]


# ── Cart & checkout ─────────────────────────────────────────────────────────

@dataclass
class CartLine:
    listing_id: int
    title: str
    unit: str
    unit_price: float
    quantity: float
    farmer_id: int
    farmer_name: str
    fulfilment: str
    available: float

    @property
    def subtotal(self) -> float:
        return round(self.unit_price * self.quantity, 2)


def price_cart(cart: dict[int, float]) -> tuple[list[CartLine], list[str]]:
    """Look up current price/stock for each cart line. Returns (lines, problems);
    lines with problems are still returned so the UI can show what to fix."""
    lines, problems = [], []
    for listing_id, qty in cart.items():
        row = get_listing(int(listing_id))
        if row is None:
            problems.append("An item in your cart no longer exists.")
            continue
        line = CartLine(listing_id=row["id"], title=row["title"], unit=row["unit"],
                        unit_price=row["price_per_unit"], quantity=float(qty), farmer_id=row["farmer_id"],
                        farmer_name=row["farmer_name"], fulfilment=row["fulfilment"],
                        available=row["quantity_available"] if row["status"] == "active" else 0)
        if line.available <= 0:
            problems.append(f"{row['title']} is no longer available.")
        elif line.quantity > line.available:
            problems.append(f"Only {line.available:g} {row['unit']} of {row['title']} left.")
        lines.append(line)
    return lines, problems


def checkout(consumer_account_id: int, cart: dict[int, float], fulfilment: str,
             delivery_address: str = "", contact_phone: str = "", note: str = "") -> list[int]:
    """Turn a cart into one order per farmer, atomically. Returns the new order ids.
    Raises MarketError (and changes nothing) if anything can't be fulfilled."""
    if not cart:
        raise MarketError("Your cart is empty.")
    if len(cart) > MAX_CART_LINES:
        raise MarketError(f"A cart can hold at most {MAX_CART_LINES} different items.")
    _one_of(fulfilment, "Pickup/delivery option", ["pickup", "delivery"])
    phone = re.sub(r"[ \-()]", "", contact_phone or "")
    if not _PHONE_RE.match(phone):
        raise MarketError("Enter a valid phone number so the farmer can reach you.")
    address = _text(delivery_address, "Delivery address", 300)
    if fulfilment == "delivery" and len(address) < 10:
        raise MarketError("Enter your full delivery address.")
    note = _text(note, "Note", 300)

    wanted = {int(lid): _number(qty, "Quantity", 0, MAX_QUANTITY, False) for lid, qty in cart.items()}
    now = db._now()
    by_farmer: dict[int, list[tuple[int, str, str, float, float]]] = {}
    with db.get_conn() as conn:
        account = conn.execute("SELECT role FROM accounts WHERE id = ?", (consumer_account_id,)).fetchone()
        if account is None or account["role"] != "consumer":
            raise MarketError("Only consumer accounts can place orders.")

        for listing_id in sorted(wanted):
            qty = wanted[listing_id]
            row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
            if row is None or row["status"] != "active":
                raise MarketError("An item in your cart is no longer available.")
            if row["fulfilment"] not in (fulfilment, "both"):
                raise MarketError(f"{row['title']} is not offered for {fulfilment}.")
            # Atomic reserve: succeeds only if enough stock is still there.
            reserved = conn.execute(
                "UPDATE listings SET quantity_available = quantity_available - ?, updated_at = ? "
                "WHERE id = ? AND status = 'active' AND quantity_available >= ?",
                (qty, now, listing_id, qty)).rowcount
            if not reserved:
                raise MarketError(f"Only {row['quantity_available']:g} {row['unit']} of {row['title']} left.")
            by_farmer.setdefault(row["farmer_id"], []).append(
                (listing_id, row["title"], row["unit"], qty, row["price_per_unit"]))

        order_ids = []
        for farmer_id, items in by_farmer.items():
            total = round(sum(qty * price for _l, _t, _u, qty, price in items), 2)
            cur = conn.execute(
                """INSERT INTO orders (consumer_account_id, farmer_id, status, fulfilment, delivery_address,
                                       contact_phone, note, total_amount, created_at, updated_at)
                   VALUES (?, ?, 'placed', ?, ?, ?, ?, ?, ?, ?)""",
                (consumer_account_id, farmer_id, fulfilment, address if fulfilment == "delivery" else None,
                 phone, note or None, total, now, now))
            order_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO order_items (order_id, listing_id, title, unit, quantity, unit_price) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [(order_id, lid, title, unit, qty, price) for lid, title, unit, qty, price in items])
            order_ids.append(order_id)
    return order_ids


# ── Orders ──────────────────────────────────────────────────────────────────

def _actor_side(conn, actor_account_id: int, order) -> str | None:
    """'consumer', 'farmer', or None if the actor isn't a party to this order."""
    if order["consumer_account_id"] == actor_account_id:
        return "consumer"
    farmer = conn.execute("SELECT account_id FROM farmers WHERE id = ?", (order["farmer_id"],)).fetchone()
    if farmer is not None and farmer["account_id"] == actor_account_id:
        return "farmer"
    return None


def _order_for_actor(conn, actor_account_id: int, order_id: int):
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    side = _actor_side(conn, actor_account_id, order) if order else None
    if side is None:
        raise MarketError("Order not found.")      # same message whether it exists or not
    return order, side


def update_order_status(actor_account_id: int, order_id: int, new_status: str, reason: str = "") -> None:
    if new_status not in ORDER_STATUSES:
        raise MarketError("Unknown order status.")
    reason = _text(reason, "Reason", 200)
    with db.get_conn() as conn:
        order, side = _order_for_actor(conn, actor_account_id, order_id)
        table = _FARMER_TRANSITIONS if side == "farmer" else _CONSUMER_TRANSITIONS
        if new_status not in table.get(order["status"], set()):
            raise MarketError(f"You can't change a '{order['status']}' order to '{new_status}'.")
        if side == "farmer" and new_status in ("cancelled", "rejected") and len(reason) < 3:
            raise MarketError("Please tell the buyer why (a few words).")
        if new_status in ("cancelled", "rejected"):
            # return the reserved stock
            conn.execute(
                """UPDATE listings SET quantity_available = quantity_available +
                       (SELECT SUM(oi.quantity) FROM order_items oi
                        WHERE oi.order_id = ? AND oi.listing_id = listings.id)
                   WHERE id IN (SELECT listing_id FROM order_items WHERE order_id = ?)""",
                (order_id, order_id))
        conn.execute("UPDATE orders SET status = ?, cancel_reason = ?, updated_at = ? WHERE id = ?",
                     (new_status, reason or order["cancel_reason"], db._now(), order_id))


def mark_paid(actor_account_id: int, order_id: int, paid: bool = True) -> None:
    """Farmer records that they received payment (cash/UPI) directly from the buyer."""
    with db.get_conn() as conn:
        order, side = _order_for_actor(conn, actor_account_id, order_id)
        if side != "farmer":
            raise MarketError("Only the farmer can record a payment.")
        if order["status"] in ("cancelled", "rejected", "placed"):
            raise MarketError("Confirm the order before recording payment.")
        conn.execute("UPDATE orders SET paid = ?, updated_at = ? WHERE id = ?",
                     (1 if paid else 0, db._now(), order_id))


_ORDER_SELECT = """
SELECT o.*, f.name AS farmer_name, f.village AS farmer_village, f.state AS farmer_state,
       a.full_name AS consumer_name,
       (SELECT 1 FROM reviews r WHERE r.order_id = o.id) AS reviewed
FROM orders o JOIN farmers f ON f.id = o.farmer_id JOIN accounts a ON a.id = o.consumer_account_id
"""


def list_orders_for_consumer(consumer_account_id: int):
    with db.get_conn() as conn:
        return conn.execute(_ORDER_SELECT + " WHERE o.consumer_account_id = ? ORDER BY o.id DESC",
                            (consumer_account_id,)).fetchall()


def list_orders_for_farmer(farmer_id: int, only_open: bool = False):
    sql = _ORDER_SELECT + " WHERE o.farmer_id = ?"
    if only_open:
        sql += " AND o.status IN ('placed', 'confirmed', 'ready')"
    with db.get_conn() as conn:
        return conn.execute(sql + " ORDER BY o.id DESC", (farmer_id,)).fetchall()


def order_items(actor_account_id: int, order_id: int):
    with db.get_conn() as conn:
        _order_for_actor(conn, actor_account_id, order_id)
        return conn.execute("SELECT * FROM order_items WHERE order_id = ? ORDER BY id", (order_id,)).fetchall()


def count_orders_awaiting_farmer(farmer_id: int) -> int:
    with db.get_conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM orders WHERE farmer_id = ? AND status = 'placed'",
                            (farmer_id,)).fetchone()[0]


# ── Messages ────────────────────────────────────────────────────────────────

def post_message(actor_account_id: int, order_id: int, body: str) -> int:
    body = _text(body, "Message", 1000, required=True)
    with db.get_conn() as conn:
        _order_for_actor(conn, actor_account_id, order_id)
        cur = conn.execute(
            "INSERT INTO order_messages (order_id, sender_account_id, body, created_at) VALUES (?, ?, ?, ?)",
            (order_id, actor_account_id, body, db._now()))
        return cur.lastrowid


def list_messages(actor_account_id: int, order_id: int):
    with db.get_conn() as conn:
        _order_for_actor(conn, actor_account_id, order_id)
        return conn.execute(
            """SELECT m.*, a.full_name AS sender_name, (m.sender_account_id = ?) AS mine
               FROM order_messages m JOIN accounts a ON a.id = m.sender_account_id
               WHERE m.order_id = ? ORDER BY m.id""", (actor_account_id, order_id)).fetchall()


# ── Reviews ─────────────────────────────────────────────────────────────────

def submit_review(consumer_account_id: int, order_id: int, rating: int, comment: str = "") -> None:
    comment = _text(comment, "Review", 500)
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        raise MarketError("Choose a rating from 1 to 5.") from None
    if not 1 <= rating <= 5:
        raise MarketError("Choose a rating from 1 to 5.")
    with db.get_conn() as conn:
        order, side = _order_for_actor(conn, consumer_account_id, order_id)
        if side != "consumer":
            raise MarketError("Only the buyer can review an order.")
        if order["status"] != "delivered":
            raise MarketError("You can review an order once it has been delivered.")
        if conn.execute("SELECT 1 FROM reviews WHERE order_id = ?", (order_id,)).fetchone():
            raise MarketError("You have already reviewed this order.")
        conn.execute(
            "INSERT INTO reviews (order_id, consumer_account_id, farmer_id, rating, comment, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (order_id, consumer_account_id, order["farmer_id"], rating, comment or None, db._now()))


def farmer_public_profile(farmer_id: int) -> dict | None:
    """What a buyer may see about a farmer: name, place, rating, recent review text.
    Never contact details."""
    with db.get_conn() as conn:
        farmer = conn.execute("SELECT id, name, village, state FROM farmers WHERE id = ?", (farmer_id,)).fetchone()
        if farmer is None:
            return None
        stats = conn.execute("SELECT AVG(rating) AS avg, COUNT(*) AS n FROM reviews WHERE farmer_id = ?",
                             (farmer_id,)).fetchone()
        reviews = conn.execute(
            """SELECT r.rating, r.comment, r.created_at, a.full_name AS buyer
               FROM reviews r JOIN accounts a ON a.id = r.consumer_account_id
               WHERE r.farmer_id = ? ORDER BY r.id DESC LIMIT 5""", (farmer_id,)).fetchall()
        coops = conn.execute(
            """SELECT c.id, c.name FROM coop_members m JOIN cooperatives c ON c.id = m.coop_id
               WHERE m.farmer_id = ?""", (farmer_id,)).fetchall()
    return {"id": farmer["id"], "name": farmer["name"], "village": farmer["village"], "state": farmer["state"],
            "rating": stats["avg"], "review_count": stats["n"],
            "reviews": [{"rating": r["rating"], "comment": r["comment"],
                         "buyer": (r["buyer"] or "").split(" ")[0], "date": r["created_at"][:10]} for r in reviews],
            "cooperatives": [dict(c) for c in coops]}
