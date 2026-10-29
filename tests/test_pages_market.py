"""Marketplace, My Shop and My Orders flows, driven through the real Streamlit pages."""

import glob
import os

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from conftest import ROOT, new_consumer, new_farmer
from core import db, market

PHONE = "9876543210"


def page(prefix):
    return glob.glob(os.path.join(ROOT, "pages", f"{prefix}_*.py"))[0]


def open_as(prefix, account=None):
    at = AppTest.from_file(page(prefix), default_timeout=30)
    if account is not None:
        at.session_state["account_id"] = account.id
    return at


def btn(at, label=None, key=None):
    for b in at.button:
        if (label is not None and b.label == label) or (key is not None and b.key == key):
            return b
    raise AssertionError(f"no button {label or key!r}; have {[(b.key, b.label) for b in at.button]}")


@pytest.fixture(autouse=True)
def fresh(tmp_db):
    st.cache_data.clear()


@pytest.fixture
def shop(tmp_db):
    fa, ff = new_farmer("ravi@example.com", "Ravi Kumar", "Punjab")
    buyer = new_consumer("asha@example.com", "Asha Verma")
    wheat = market.create_listing(ff["id"], "Wheat", "Grains & Cereals", "kg", 30, 100, "both")
    return type("S", (), dict(fa=fa, ff=ff, buyer=buyer, wheat=wheat))


def show(at, key, value):
    """Switch a section radio (Cart, Add a listing, ...) and rerun."""
    at.radio(key=key).set_value(value).run()
    return at


def fill_checkout(at, fulfilment="pickup", phone=PHONE, address=""):
    at.radio(key="co_ful").set_value(fulfilment)
    at.text_area(key="co_address").set_value(address)
    at.text_input(key="co_phone").set_value(phone)


# ── Marketplace ─────────────────────────────────────────────────────────────

def test_browse_works_signed_out_and_shows_listing():
    _, f = new_farmer()
    market.create_listing(f["id"], "Desi Tomato", "Vegetables", "kg", 25, 10, "both")
    at = open_as(10).run()
    assert not at.exception and any("Desi Tomato" in m.value for m in at.markdown)


def test_add_to_cart_then_checkout_as_consumer(shop):
    at = open_as(10, shop.buyer).run()
    at.number_input(key=f"browse_qty_{shop.wheat}").set_value(4.0)
    btn(at, key=f"browse_add_{shop.wheat}").click()
    at.run()
    assert at.session_state["cart"] == {shop.wheat: 4.0}
    show(at, "market_section", "cart")
    fill_checkout(at)
    [b for b in at.button if b.label == "Place order"][0].click()
    at.run()
    assert not at.exception and not at.error
    orders = market.list_orders_for_consumer(shop.buyer.id)
    assert len(orders) == 1 and orders[0]["total_amount"] == 120.0
    assert market.get_listing(shop.wheat)["quantity_available"] == 96.0
    assert at.session_state["cart"] == {}


def test_adding_twice_accumulates_quantity(shop):
    at = open_as(10, shop.buyer).run()
    at.number_input(key=f"browse_qty_{shop.wheat}").set_value(2.0)
    btn(at, key=f"browse_add_{shop.wheat}").click(); at.run()
    btn(at, key=f"browse_add_{shop.wheat}").click(); at.run()
    assert at.session_state["cart"][shop.wheat] == 4.0


def test_signed_out_user_can_fill_cart_but_not_order(shop):
    at = open_as(10).run()
    btn(at, key=f"browse_add_{shop.wheat}").click(); at.run()
    show(at, "market_section", "cart")
    assert any("sign in" in i.value.lower() for i in at.info)
    assert not any(b.label == "Place order" for b in at.button)


def test_farmer_cannot_place_orders(shop):
    at = open_as(10, shop.fa).run()
    btn(at, key=f"browse_add_{shop.wheat}").click(); at.run()
    show(at, "market_section", "cart")
    assert any("can't place orders" in i.value for i in at.info)
    assert not any(b.label == "Place order" for b in at.button)


def test_delivery_requires_address_and_leaves_stock_untouched_on_failure(shop):
    at = open_as(10, shop.buyer).run()
    btn(at, key=f"browse_add_{shop.wheat}").click(); at.run()
    show(at, "market_section", "cart")
    fill_checkout(at, "delivery", address="")
    [b for b in at.button if b.label == "Place order"][0].click(); at.run()
    assert at.error and market.list_orders_for_consumer(shop.buyer.id) == []
    assert market.get_listing(shop.wheat)["quantity_available"] == 100.0


def test_cart_ignores_tampered_session_price_or_stock(shop):
    """Whatever quantity the session holds, checkout re-checks stock in the database."""
    at = open_as(10, shop.buyer)
    at.session_state["cart"] = {shop.wheat: 5000.0}
    at.session_state["market_section"] = "cart"
    at.run()
    assert at.warning                                              # the cart shows the problem
    fill_checkout(at)
    [b for b in at.button if b.label == "Place order"][0].click(); at.run()
    assert market.list_orders_for_consumer(shop.buyer.id) == []
    assert market.get_listing(shop.wheat)["quantity_available"] == 100.0


def test_remove_from_cart(shop):
    at = open_as(10, shop.buyer)
    at.session_state["cart"] = {shop.wheat: 2.0}
    at.session_state["market_section"] = "cart"
    at.run()
    btn(at, key=f"rm_{shop.wheat}").click(); at.run()
    assert at.session_state["cart"] == {}


def test_listing_text_is_escaped_not_rendered_as_markdown_or_html():
    _, f = new_farmer()
    market.create_listing(f["id"], "[click](http://evil.example) <script>x</script>", "Vegetables", "kg", 10, 5,
                          "both", "![img](http://evil.example/p.png) **bold**")
    at = open_as(10).run()
    assert not at.exception
    shown = " ".join(m.value for m in at.markdown) + " " + " ".join(c.value for c in at.caption)
    assert "\\[click\\]\\(http" in shown          # link syntax is neutralised
    assert "\\<script\\>" in shown                  # no raw HTML tag survives
    assert "\\!\\[img\\]" in shown                # no image embed
    assert "\\*\\*bold\\*\\*" in shown


def test_farmers_shop_view_and_back(shop):
    at = open_as(10, shop.buyer).run()
    btn(at, key=f"browse_shop_{shop.wheat}").click(); at.run()
    assert any("Ravi Kumar" in s.value for s in at.subheader)
    btn(at, key="back_from_shop").click(); at.run()
    assert at.session_state["shop_view"] is None


# ── My Shop (farmer) ────────────────────────────────────────────────────────

def place_order(shop, qty=5.0):
    return market.checkout(shop.buyer.id, {shop.wheat: qty}, "pickup", "", PHONE, "")[0]


def test_my_shop_confirm_order_and_receive_payment(shop):
    oid = place_order(shop)
    at = open_as(11, shop.fa).run()
    assert not at.exception
    btn(at, key=f"confirm_{oid}").click(); at.run()
    assert market.list_orders_for_farmer(shop.ff["id"])[0]["status"] == "confirmed"
    btn(at, key=f"paid_{oid}").click(); at.run()
    assert market.list_orders_for_farmer(shop.ff["id"])[0]["paid"]


def test_my_shop_reject_restores_stock_and_tells_buyer_why(shop):
    oid = place_order(shop, 10)
    assert market.get_listing(shop.wheat)["quantity_available"] == 90.0
    at = open_as(11, shop.fa).run()
    at.text_input(key=f"rej_reason_{oid}").set_value("Crop not ready")
    btn(at, key=f"reject_{oid}").click(); at.run()
    assert market.get_listing(shop.wheat)["quantity_available"] == 100.0
    row = market.list_orders_for_consumer(shop.buyer.id)[0]
    assert row["status"] == "rejected" and "not ready" in row["cancel_reason"]


def test_my_shop_shows_buyer_phone_only_for_own_orders(shop):
    place_order(shop)
    other_acct, other = new_farmer("sita@example.com", "Sita Devi")
    mine = open_as(11, shop.fa).run()
    theirs = open_as(11, other_acct).run()
    assert any(PHONE in m.value for m in mine.markdown)
    assert not any(PHONE in m.value for m in theirs.markdown)


def test_my_shop_message_flow_and_escaping(shop):
    oid = place_order(shop)
    at = open_as(11, shop.fa).run()
    at.text_input(key=f"msg_body_{oid}").set_value("Ready by 5pm **bold** [x](http://e.example)")
    [b for b in at.button if b.label == "Send"][0].click(); at.run()
    msgs = market.list_messages(shop.fa.id, oid)
    assert len(msgs) == 1 and msgs[0]["mine"]
    shown = " ".join(m.value for m in at.markdown)
    assert "Ready by 5pm" in shown and "\\*\\*bold" in shown


def test_my_shop_create_listing():
    acct, f = new_farmer()
    at = show(open_as(11, acct).run(), "shop_section", "add")
    at.text_input(key="nl_title").set_value("Raw Milk")
    at.selectbox(key="nl_category").select("Dairy")
    at.selectbox(key="nl_unit").select("litre")
    at.number_input(key="nl_price").set_value(400.0)
    at.number_input(key="nl_qty").set_value(12.0)
    [b for b in at.button if b.label == "Publish listing"][0].click(); at.run()
    assert not at.exception and not at.error
    rows = market.list_listings(farmer_id=f["id"])
    assert len(rows) == 1 and rows[0]["title"] == "Raw Milk" and rows[0]["category"] == "Dairy" and rows[0]["price_per_unit"] == 400.0


def test_my_shop_create_listing_validation_message():
    acct, f = new_farmer()
    at = show(open_as(11, acct).run(), "shop_section", "add")
    at.text_input(key="nl_title").set_value("Free Stuff")
    at.number_input(key="nl_price").set_value(0.0)
    at.number_input(key="nl_qty").set_value(5.0)
    [b for b in at.button if b.label == "Publish listing"][0].click(); at.run()
    assert at.error and market.list_listings(farmer_id=f["id"]) == []


def test_my_shop_edit_listing_pauses_it(shop):
    at = show(open_as(11, shop.fa).run(), "shop_section", "listings")
    at.selectbox(key=f"e_status_{shop.wheat}").select("paused")
    at.number_input(key=f"e_price_{shop.wheat}").set_value(35.0)
    [b for b in at.button if b.label == "Save changes"][0].click(); at.run()
    row = market.get_listing(shop.wheat)
    assert row["status"] == "paused" and row["price_per_unit"] == 35.0
    assert market.list_listings() == []


# ── My Orders (consumer) ────────────────────────────────────────────────────

def test_my_orders_cancel_restores_stock(shop):
    oid = place_order(shop, 7)
    at = open_as(13, shop.buyer).run()
    btn(at, key=f"cancel_{oid}").click(); at.run()
    assert market.list_orders_for_consumer(shop.buyer.id)[0]["status"] == "cancelled"
    assert market.get_listing(shop.wheat)["quantity_available"] == 100.0


def test_my_orders_only_shows_own_orders(shop):
    place_order(shop)
    other = new_consumer("ben@example.com", "Ben Thomas")
    at = open_as(13, other).run()
    assert any("No orders yet" in i.value for i in at.info)


def test_my_orders_review_after_delivery_only_once(shop):
    oid = place_order(shop)
    market.update_order_status(shop.fa.id, oid, "confirmed")
    at = open_as(13, shop.buyer).run()
    assert not at.slider                                            # no review box before delivery
    market.update_order_status(shop.fa.id, oid, "delivered")
    at = open_as(13, shop.buyer).run()
    at.slider(key=f"rate_{oid}").set_value(4)
    at.text_input(key=f"rev_{oid}").set_value("Fresh wheat")
    [b for b in at.button if b.label == "Submit review"][0].click(); at.run()
    assert not at.exception and not at.error
    assert market.farmer_public_profile(shop.ff["id"])["review_count"] == 1
    at = open_as(13, shop.buyer).run()
    assert not at.slider                                            # one review per order


def test_my_orders_message_the_farmer(shop):
    oid = place_order(shop)
    at = open_as(13, shop.buyer).run()
    at.text_input(key=f"msg_body_{oid}").set_value("Can I come at 6?")
    [b for b in at.button if b.label == "Send"][0].click(); at.run()
    assert [m["body"] for m in market.list_messages(shop.fa.id, oid)] == ["Can I come at 6?"]


def test_order_placed_message_is_visible_outside_the_cart_tab(shop):
    """After checkout Streamlit returns to the first tab, so the confirmation must not live inside the Cart tab."""
    at = open_as(10, shop.buyer).run()
    btn(at, key=f"browse_add_{shop.wheat}").click(); at.run()
    show(at, "market_section", "cart")
    fill_checkout(at)
    [b for b in at.button if b.label == "Place order"][0].click(); at.run()
    assert any("Order placed" in s.value for s in at.success)
    top_level = [s for s in at.main.children.values() if getattr(s, "type", "") == "success"]
    assert top_level, "confirmation should be a top-level element, not inside a tab"
