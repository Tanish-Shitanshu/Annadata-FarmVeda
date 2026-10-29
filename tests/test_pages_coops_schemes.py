"""Cooperatives and Yojana Sathi pages, driven through the real Streamlit pages."""

import glob
import os

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from conftest import ROOT, new_consumer, new_farmer
from core import coop, db, market

PHONE = "9876543210"


def page(prefix):
    return glob.glob(os.path.join(ROOT, "pages", f"{prefix}_*.py"))[0]


def open_as(prefix, account):
    at = AppTest.from_file(page(prefix), default_timeout=30)
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


# ── Cooperatives ────────────────────────────────────────────────────────────

def test_create_coop_shows_invite_code_to_admin():
    acct, f = new_farmer()
    at = open_as(12, acct).run()
    at.text_input(key="cc_name").set_value("Khanna Growers")
    btn(at, "Create").click(); at.run()
    assert not at.exception and not at.error
    [c] = coop.my_coops(f["id"])
    assert c["name"] == "Khanna Growers" and c["my_role"] == "admin"
    code = coop.get_coop(c["id"], f["id"])["invite_code"]
    assert any(code in m.value for m in at.markdown)


def test_create_coop_requires_name():
    acct, f = new_farmer()
    at = open_as(12, acct).run()
    btn(at, "Create").click(); at.run()
    assert at.error and coop.my_coops(f["id"]) == []


def test_join_with_invite_code_and_bad_code():
    a_acct, a = new_farmer("a@example.com", "Admin Farmer")
    b_acct, b = new_farmer("b@example.com", "Joiner")
    cid = coop.create_coop(a["id"], "Group")
    code = coop.get_coop(cid, a["id"])["invite_code"]
    at = open_as(12, b_acct).run()
    at.text_input(key="jc_code").set_value("WRONGCODE")
    btn(at, "Join").click(); at.run()
    assert at.error and not coop.is_member(b["id"], cid)
    at.text_input(key="jc_code").set_value(code)
    btn(at, "Join").click(); at.run()
    assert coop.is_member(b["id"], cid)


def test_members_never_see_the_invite_code_and_cannot_admin():
    a_acct, a = new_farmer("a@example.com", "Admin Farmer")
    b_acct, b = new_farmer("b@example.com", "Joiner")
    cid = coop.create_coop(a["id"], "Group")
    code = coop.get_coop(cid, a["id"])["invite_code"]
    coop.join_coop(b["id"], code)
    at = open_as(12, b_acct).run()
    assert not any(code in m.value for m in at.markdown)
    assert not any(b_.label.startswith("Make a new invite") for b_ in at.button)
    assert not any(b_.key and b_.key.startswith(("role_", "rm_")) for b_ in at.button)


def test_admin_can_remove_member_and_member_can_leave():
    a_acct, a = new_farmer("a@example.com", "Admin Farmer")
    b_acct, b = new_farmer("b@example.com", "Joiner")
    cid = coop.create_coop(a["id"], "Group")
    coop.join_coop(b["id"], coop.get_coop(cid, a["id"])["invite_code"])
    at = open_as(12, a_acct).run()
    btn(at, key=f"rm_{cid}_{b['id']}").click(); at.run()
    assert not coop.is_member(b["id"], cid)
    coop.join_coop(b["id"], coop.get_coop(cid, a["id"])["invite_code"])
    at = open_as(12, b_acct).run()
    btn(at, key=f"leave_{cid}").click(); at.run()
    assert not coop.is_member(b["id"], cid)


def test_marketplace_bulk_order_splits_across_farmers_through_the_page():
    a_acct, a = new_farmer("a@example.com", "Ravi", "Punjab")
    b_acct, b = new_farmer("b@example.com", "Sita", "Punjab", "Ludhiana")
    cid = coop.create_coop(a["id"], "Group")
    coop.join_coop(b["id"], coop.get_coop(cid, a["id"])["invite_code"])
    market.create_listing(a["id"], "Wheat", "Grains & Cereals", "kg", 20, 30, "both", coop_id=cid)
    market.create_listing(b["id"], "Wheat", "Grains & Cereals", "kg", 25, 30, "both", coop_id=cid)
    buyer = new_consumer()
    key = coop.pooled_stock(cid)[0].key
    at = open_as(10, buyer)
    at.session_state["coop_view"] = cid
    at.run()
    at.number_input(key=f"pool_qty_{key}").set_value(45.0)
    at.text_input(key=f"pool_phone_{key}").set_value(PHONE)
    btn(at, key=f"pool_go_{key}").click(); at.run()
    assert not at.exception and not at.error
    orders = market.list_orders_for_consumer(buyer.id)
    assert len(orders) == 2 and sum(o["total_amount"] for o in orders) == 30 * 20 + 15 * 25


# ── Yojana Sathi ────────────────────────────────────────────────────────────

def answer_basics(at, **overrides):
    at.selectbox(key="q_land_ownership").select("owner")
    at.selectbox(key="q_owned_since_2019").select("Yes")
    at.selectbox(key="q_bank_aadhaar_linked").select("Yes")
    at.multiselect(key="q_pm_kisan_exclusions").select("__none__")
    for k, v in overrides.items():
        at.selectbox(key=f"q_{k}").select(v)


def test_results_render_before_any_answers_without_claiming_eligibility():
    acct, f = new_farmer()
    at = open_as(6, acct).run()
    assert not at.exception
    assert [m.value for m in at.metric][0] == "0"                   # nothing is "likely" yet
    assert db.get_scheme_profile(f["id"]) == {}


def test_saving_answers_persists_and_marks_pm_kisan_likely():
    acct, f = new_farmer()
    at = open_as(6, acct).run()
    answer_basics(at)
    btn(at, "Save my answers").click(); at.run()
    saved = db.get_scheme_profile(f["id"])
    assert saved["land_ownership"] == "owner" and saved["owned_since_2019"] is True
    assert saved["pm_kisan_exclusions"] == []                       # explicit "None of these"
    assert any("PM-KISAN" in e.label and "🟢" in e.label for e in at.expander)


def test_untouched_exclusions_question_is_not_treated_as_none():
    acct, f = new_farmer()
    at = open_as(6, acct).run()
    at.selectbox(key="q_land_ownership").select("owner")
    at.selectbox(key="q_owned_since_2019").select("Yes")
    btn(at, "Save my answers").click(); at.run()
    assert "pm_kisan_exclusions" not in db.get_scheme_profile(f["id"])
    assert any("PM-KISAN" in e.label and "🟡" in e.label for e in at.expander)   # "check", not "likely"


def test_exclusion_answer_makes_pm_kisan_unlikely():
    acct, f = new_farmer()
    at = open_as(6, acct).run()
    answer_basics(at)
    at.multiselect(key="q_pm_kisan_exclusions").set_value(["income_tax"])
    btn(at, "Save my answers").click(); at.run()
    assert any("PM-KISAN" in e.label and "⚪" in e.label for e in at.expander)


def test_accept_scheme_reminder_creates_a_reminder_and_logs_decision():
    acct, f = new_farmer()
    db.save_scheme_profile(f["id"], {"land_ownership": "owner", "owned_since_2019": True,
                                     "bank_aadhaar_linked": True, "pm_kisan_exclusions": []})
    at = open_as(6, acct).run()
    btn(at, key="acc_pm-kisan").click(); at.run()
    reminders = db.list_reminders(f["id"])
    assert len(reminders) == 1 and "PM-KISAN" in reminders[0]["title"] and reminders[0]["category"] == "Schemes"
    assert db.latest_advice_decisions(f["id"], "scheme")["PM-KISAN"] == "accepted"
    assert not any(b.key == "acc_pm-kisan" for b in open_as(6, acct).run().button)   # no double-add on revisit


def test_dismissal_persists_across_sessions_and_can_be_reversed():
    acct, f = new_farmer()
    db.save_scheme_profile(f["id"], {"land_ownership": "owner", "owned_since_2019": True,
                                     "bank_aadhaar_linked": True, "pm_kisan_exclusions": []})
    at = open_as(6, acct).run()
    btn(at, key="dis_pm-kisan").click(); at.run()
    assert db.list_reminders(f["id"]) == []
    again = open_as(6, acct).run()                                   # a brand-new session
    assert not any(b.key == "acc_pm-kisan" for b in again.button)    # not nagged again
    btn(again, key="again_pm-kisan").click(); again.run()
    assert len(db.list_reminders(f["id"])) == 1


def test_scheme_answers_are_private_to_each_farmer():
    a_acct, a = new_farmer("a@example.com", "A")
    b_acct, b = new_farmer("b@example.com", "B")
    db.save_scheme_profile(a["id"], {"land_ownership": "owner"})
    at = open_as(6, b_acct).run()
    assert at.selectbox(key="q_land_ownership").value == "—"


def test_home_dashboard_flags_new_likely_schemes_then_stops_once_decided():
    acct, f = new_farmer()
    db.save_scheme_profile(f["id"], {"land_ownership": "owner", "owned_since_2019": True,
                                     "bank_aadhaar_linked": True, "pm_kisan_exclusions": []})
    home = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=30)
    home.session_state["account_id"] = acct.id
    home.run()
    assert any("may qualify" in s.value and "PM-KISAN" in s.value for s in home.success)
    db.dismiss_advice(f["id"], "scheme", "PM-KISAN", "x", "")
    home = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=30)
    home.session_state["account_id"] = acct.id
    home.run()
    assert not any("PM-KISAN" in s.value for s in home.success)
