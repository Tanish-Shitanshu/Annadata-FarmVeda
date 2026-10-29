import sqlite3

import pytest

from conftest import new_consumer, new_farmer
from core import db, market
from core.market import MarketError

PHONE = "9876543210"
ADDR = "12 Green Park Road, Delhi 110016"


@pytest.fixture
def shop(tmp_db):
    """Two farmers, two consumers, a few listings."""
    fa, ff = new_farmer("ravi@example.com", "Ravi Kumar", "Punjab")
    fb, fbf = new_farmer("sita@example.com", "Sita Devi", "Haryana", "Karnal")
    c1, c2 = new_consumer("asha@example.com", "Asha Verma"), new_consumer("ben@example.com", "Ben Thomas")
    wheat = market.create_listing(ff["id"], "Wheat", "Grains & Cereals", "kg", 30, 100, "both", "Fresh wheat")
    tomato = market.create_listing(ff["id"], "Tomato", "Vegetables", "kg", 25, 20, "pickup", organic=True)
    onion = market.create_listing(fbf["id"], "Onion", "Vegetables", "kg", 18, 50, "delivery")
    return type("S", (), dict(fa=fa, ff=ff, fb=fb, fbf=fbf, c1=c1, c2=c2, wheat=wheat, tomato=tomato, onion=onion))


def stock(listing_id):
    return market.get_listing(listing_id)["quantity_available"]


# ── Listings ────────────────────────────────────────────────────────────────

def test_browse_shows_active_in_stock_listings_with_seller_info(shop):
    rows = market.list_listings()
    assert {r["title"] for r in rows} == {"Wheat", "Tomato", "Onion"}
    wheat = [r for r in rows if r["title"] == "Wheat"][0]
    assert wheat["farmer_name"] == "Ravi Kumar" and wheat["state"] == "Punjab"
    assert "phone" not in wheat.keys() and "email" not in wheat.keys()


def test_filters_search_sort(shop):
    assert [r["title"] for r in market.list_listings(category="Vegetables", sort="price_asc")] == ["Onion", "Tomato"]
    assert [r["title"] for r in market.list_listings(state="haryana")] == ["Onion"]
    assert [r["title"] for r in market.list_listings(search="whe")] == ["Wheat"]
    assert [r["title"] for r in market.list_listings(search="fresh")] == ["Wheat"]       # matches description
    assert market.list_listings(search="%") == [] and market.list_listings(search="_") == []   # LIKE wildcards are literal
    assert market.list_listings(search="' OR 1=1 --") == []


def test_sold_out_and_paused_hidden_from_public_but_visible_to_owner(shop):
    market.update_listing(shop.ff["id"], shop.tomato, status="paused")
    market.update_listing(shop.ff["id"], shop.wheat, quantity_available=0)
    assert {r["title"] for r in market.list_listings()} == {"Onion"}
    assert {r["title"] for r in market.list_listings(farmer_id=shop.ff["id"], include_unavailable=True)} == {"Wheat", "Tomato"}


@pytest.mark.parametrize("field,value", [
    ("price_per_unit", 0), ("price_per_unit", -5), ("price_per_unit", "abc"), ("price_per_unit", float("nan")),
    ("price_per_unit", 10 ** 9), ("quantity_available", -1), ("title", "  "), ("title", "x" * 81),
    ("category", "Weapons"), ("unit", "tonne"), ("fulfilment", "teleport"), ("status", "deleted")])
def test_invalid_listing_input_rejected(shop, field, value):
    with pytest.raises(MarketError):
        market.update_listing(shop.ff["id"], shop.wheat, **{field: value})
    assert market.get_listing(shop.wheat)["title"] == "Wheat"


def test_create_listing_validation(shop):
    with pytest.raises(MarketError):
        market.create_listing(shop.ff["id"], "Rice", "Grains & Cereals", "kg", 0, 10)
    with pytest.raises(MarketError):
        market.create_listing(99999, "Rice", "Grains & Cereals", "kg", 10, 10)      # no such farmer


def test_farmer_cannot_edit_another_farmers_listing(shop):
    with pytest.raises(MarketError, match="not found"):
        market.update_listing(shop.fbf["id"], shop.wheat, price_per_unit=1)
    assert market.get_listing(shop.wheat)["price_per_unit"] == 30


def test_update_cannot_touch_protected_columns(shop):
    with pytest.raises(MarketError, match="Can't change"):
        market.update_listing(shop.ff["id"], shop.wheat, created_at="2000-01-01")
    with pytest.raises(MarketError, match="Can't change"):
        market.update_listing(shop.ff["id"], shop.wheat, **{"price_per_unit = 1, status": "x"})


# ── Checkout ────────────────────────────────────────────────────────────────

def test_checkout_creates_one_order_per_farmer_and_reserves_stock(shop):
    # tomato is pickup-only, onion delivery-only: split into two checkouts
    ids1 = market.checkout(shop.c1.id, {shop.wheat: 10, shop.tomato: 2}, "pickup", "", PHONE)
    ids2 = market.checkout(shop.c1.id, {shop.onion: 5}, "delivery", ADDR, PHONE)
    assert len(ids1) == 1 and len(ids2) == 1
    assert (stock(shop.wheat), stock(shop.tomato), stock(shop.onion)) == (90, 18, 45)
    order = market.list_orders_for_consumer(shop.c1.id)[-1]
    assert order["total_amount"] == 10 * 30 + 2 * 25 and order["status"] == "placed"
    assert order["delivery_address"] is None                     # pickup order stores no address


def test_one_cart_two_farmers_makes_two_orders(shop):
    ids = market.checkout(shop.c1.id, {shop.wheat: 1, shop.onion: 1}, "delivery", ADDR, PHONE)
    assert len(ids) == 2
    assert {o["farmer_id"] for o in market.list_orders_for_consumer(shop.c1.id)} == {shop.ff["id"], shop.fbf["id"]}


def test_price_comes_from_database_not_cart(shop):
    market.checkout(shop.c1.id, {shop.wheat: 2}, "pickup", "", PHONE)
    market.update_listing(shop.ff["id"], shop.wheat, price_per_unit=99)         # price change after the order
    item = market.order_items(shop.c1.id, market.list_orders_for_consumer(shop.c1.id)[0]["id"])[0]
    assert item["unit_price"] == 30 and item["title"] == "Wheat"                # snapshot taken at order time


def test_cannot_buy_more_than_stock_and_nothing_changes(shop):
    with pytest.raises(MarketError, match="left"):
        market.checkout(shop.c1.id, {shop.wheat: 5, shop.tomato: 21}, "pickup", "", PHONE)
    assert (stock(shop.wheat), stock(shop.tomato)) == (100, 20)                  # first line rolled back too
    assert market.list_orders_for_consumer(shop.c1.id) == []


def test_last_kilo_goes_to_only_one_buyer(shop):
    market.update_listing(shop.ff["id"], shop.tomato, quantity_available=5)
    market.checkout(shop.c1.id, {shop.tomato: 5}, "pickup", "", PHONE)
    with pytest.raises(MarketError):
        market.checkout(shop.c2.id, {shop.tomato: 1}, "pickup", "", PHONE)
    assert stock(shop.tomato) == 0


@pytest.mark.parametrize("qty", [0, -1, "abc", float("inf"), float("nan"), 10 ** 9])
def test_bad_quantities_rejected(shop, qty):
    with pytest.raises(MarketError):
        market.checkout(shop.c1.id, {shop.wheat: qty}, "pickup", "", PHONE)
    assert stock(shop.wheat) == 100


def test_fulfilment_must_be_supported_by_every_item(shop):
    with pytest.raises(MarketError, match="not offered for delivery"):
        market.checkout(shop.c1.id, {shop.tomato: 1}, "delivery", ADDR, PHONE)
    with pytest.raises(MarketError, match="not offered for pickup"):
        market.checkout(shop.c1.id, {shop.onion: 1}, "pickup", "", PHONE)


def test_contact_details_validation(shop):
    with pytest.raises(MarketError, match="phone"):
        market.checkout(shop.c1.id, {shop.wheat: 1}, "pickup", "", "12345")
    with pytest.raises(MarketError, match="address"):
        market.checkout(shop.c1.id, {shop.wheat: 1}, "delivery", "home", PHONE)
    market.checkout(shop.c1.id, {shop.wheat: 1}, "pickup", "", "+91 98765-43210")      # formatted number is fine


def test_only_consumers_can_order_and_empty_carts_fail(shop):
    with pytest.raises(MarketError, match="consumer"):
        market.checkout(shop.fa.id, {shop.onion: 1}, "delivery", ADDR, PHONE)
    with pytest.raises(MarketError, match="consumer"):
        market.checkout(424242, {shop.onion: 1}, "delivery", ADDR, PHONE)
    with pytest.raises(MarketError, match="empty"):
        market.checkout(shop.c1.id, {}, "pickup", "", PHONE)


def test_paused_listing_cannot_be_ordered(shop):
    market.update_listing(shop.ff["id"], shop.wheat, status="paused")
    with pytest.raises(MarketError):
        market.checkout(shop.c1.id, {shop.wheat: 1}, "pickup", "", PHONE)


def test_price_cart_flags_problems(shop):
    lines, problems = market.price_cart({shop.wheat: 5, shop.tomato: 500})
    assert len(lines) == 2 and any("left" in p for p in problems)
    assert lines[0].subtotal == 150


# ── Order lifecycle & authorization ─────────────────────────────────────────

def place(shop, listing=None, qty=10, consumer=None):
    consumer = consumer or shop.c1
    listing = listing or shop.wheat
    return market.checkout(consumer.id, {listing: qty}, "pickup", "", PHONE)[0]


def test_happy_path_to_delivered(shop):
    oid = place(shop)
    market.update_order_status(shop.fa.id, oid, "confirmed")
    market.update_order_status(shop.fa.id, oid, "ready")
    market.update_order_status(shop.fa.id, oid, "delivered")
    market.mark_paid(shop.fa.id, oid)
    order = market.list_orders_for_consumer(shop.c1.id)[0]
    assert order["status"] == "delivered" and order["paid"] == 1
    assert stock(shop.wheat) == 90                                  # sold stock stays gone


def test_rejecting_or_cancelling_restores_stock(shop):
    oid = place(shop)
    assert stock(shop.wheat) == 90
    with pytest.raises(MarketError, match="why"):
        market.update_order_status(shop.fa.id, oid, "rejected")     # farmer must give a reason
    market.update_order_status(shop.fa.id, oid, "rejected", "Out of stock after rain")
    assert stock(shop.wheat) == 100
    o2 = place(shop, qty=7)
    market.update_order_status(shop.c1.id, o2, "cancelled")         # buyer may cancel while 'placed'
    assert stock(shop.wheat) == 100


def test_stock_restored_exactly_once_for_multi_item_orders(shop):
    oid = market.checkout(shop.c1.id, {shop.wheat: 4, shop.tomato: 3}, "pickup", "", PHONE)[0]
    market.update_order_status(shop.fa.id, oid, "confirmed")
    market.update_order_status(shop.fa.id, oid, "cancelled", "Sorry, flood")
    assert (stock(shop.wheat), stock(shop.tomato)) == (100, 20)
    with pytest.raises(MarketError):
        market.update_order_status(shop.fa.id, oid, "cancelled", "again")
    assert (stock(shop.wheat), stock(shop.tomato)) == (100, 20)


@pytest.mark.parametrize("first,second", [("placed", "delivered"), ("placed", "ready"), ("delivered", "confirmed"),
                                          ("cancelled", "confirmed"), ("rejected", "confirmed")])
def test_illegal_transitions_rejected(shop, first, second):
    oid = place(shop)
    path = {"placed": [], "delivered": ["confirmed", "delivered"], "cancelled": ["confirmed", "cancelled"],
            "rejected": ["rejected"]}[first]
    for step in path:
        market.update_order_status(shop.fa.id, oid, step, "reason here")
    with pytest.raises(MarketError):
        market.update_order_status(shop.fa.id, oid, second, "reason here")


def test_buyer_cannot_confirm_and_cannot_cancel_after_confirmation(shop):
    oid = place(shop)
    with pytest.raises(MarketError):
        market.update_order_status(shop.c1.id, oid, "confirmed")
    market.update_order_status(shop.fa.id, oid, "confirmed")
    with pytest.raises(MarketError):
        market.update_order_status(shop.c1.id, oid, "cancelled")


def test_strangers_cannot_touch_or_see_orders(shop):
    oid = place(shop)
    for stranger in (shop.c2, shop.fb):                          # another buyer, another farmer
        for action in (lambda: market.update_order_status(stranger.id, oid, "cancelled"),
                       lambda: market.order_items(stranger.id, oid),
                       lambda: market.post_message(stranger.id, oid, "hi"),
                       lambda: market.list_messages(stranger.id, oid),
                       lambda: market.mark_paid(stranger.id, oid)):
            with pytest.raises(MarketError, match="Order not found"):
                action()
    with pytest.raises(MarketError, match="Order not found"):
        market.update_order_status(shop.c1.id, 99999, "cancelled")      # same error as a real foreign order


def test_buyer_cannot_mark_paid_and_unconfirmed_orders_cannot_be_paid(shop):
    oid = place(shop)
    with pytest.raises(MarketError):
        market.mark_paid(shop.fa.id, oid)
    market.update_order_status(shop.fa.id, oid, "confirmed")
    with pytest.raises(MarketError, match="Only the farmer"):
        market.mark_paid(shop.c1.id, oid)


def test_each_side_only_sees_their_own_orders(shop):
    place(shop)
    assert len(market.list_orders_for_farmer(shop.ff["id"])) == 1
    assert market.list_orders_for_farmer(shop.fbf["id"]) == []
    assert market.list_orders_for_consumer(shop.c2.id) == []
    assert market.count_orders_awaiting_farmer(shop.ff["id"]) == 1


# ── Messages ────────────────────────────────────────────────────────────────

def test_messages_between_buyer_and_farmer(shop):
    oid = place(shop)
    market.post_message(shop.c1.id, oid, "Can you deliver on Saturday?")
    market.post_message(shop.fa.id, oid, "Yes, after 4pm.")
    msgs = market.list_messages(shop.c1.id, oid)
    assert [m["body"] for m in msgs] == ["Can you deliver on Saturday?", "Yes, after 4pm."]
    assert [bool(m["mine"]) for m in msgs] == [True, False]
    assert [bool(m["mine"]) for m in market.list_messages(shop.fa.id, oid)] == [False, True]


@pytest.mark.parametrize("body", ["", "   ", "x" * 1001])
def test_message_length_limits(shop, body):
    with pytest.raises(MarketError):
        market.post_message(shop.c1.id, place(shop), body)


# ── Reviews ─────────────────────────────────────────────────────────────────

def deliver(shop, oid):
    for step in ("confirmed", "ready", "delivered"):
        market.update_order_status(shop.fa.id, oid, step)


def test_review_only_after_delivery_once_and_by_the_buyer(shop):
    oid = place(shop)
    with pytest.raises(MarketError, match="delivered"):
        market.submit_review(shop.c1.id, oid, 5)
    deliver(shop, oid)
    with pytest.raises(MarketError, match="Only the buyer"):
        market.submit_review(shop.fa.id, oid, 5)
    with pytest.raises(MarketError, match="Order not found"):
        market.submit_review(shop.c2.id, oid, 5)
    for bad in (0, 6, "x", None):
        with pytest.raises(MarketError, match="1 to 5"):
            market.submit_review(shop.c1.id, oid, bad)
    market.submit_review(shop.c1.id, oid, 4, "Fresh and on time")
    with pytest.raises(MarketError, match="already"):
        market.submit_review(shop.c1.id, oid, 5)


def test_rating_shows_up_on_listings_and_profile_without_contact_details(shop):
    for qty, stars in ((1, 5), (2, 4)):
        oid = place(shop, qty=qty)
        deliver(shop, oid)
        market.submit_review(shop.c1.id, oid, stars, f"{stars} stars")
    listing = market.get_listing(shop.wheat)
    assert listing["farmer_rating"] == 4.5 and listing["farmer_review_count"] == 2
    profile = market.farmer_public_profile(shop.ff["id"])
    assert profile["rating"] == 4.5 and profile["reviews"][0]["buyer"] == "Asha"
    assert set(profile) == {"id", "name", "village", "state", "rating", "review_count", "reviews", "cooperatives"}
    assert market.farmer_public_profile(9999) is None


def test_database_blocks_bad_data_even_if_code_slips(shop):
    with db.get_conn() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE listings SET quantity_available = -5 WHERE id = ?", (shop.wheat,))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO reviews (order_id, consumer_account_id, farmer_id, rating, created_at) "
                         "VALUES (1, 1, 1, 9, 'x')")
