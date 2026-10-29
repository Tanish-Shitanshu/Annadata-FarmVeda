"""Sign-up / sign-in / sign-out and page guards, through the real Streamlit pages."""

import glob
import os

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from conftest import ROOT, new_consumer, new_farmer
from core import auth, db

APP = os.path.join(ROOT, "app.py")


def page(prefix):
    return glob.glob(os.path.join(ROOT, "pages", f"{prefix}_*.py"))[0]


@pytest.fixture(autouse=True)
def fresh(tmp_db):
    st.cache_data.clear()


def button(at, label):
    return [b for b in at.button if b.label == label][0]


def home():
    return AppTest.from_file(APP, default_timeout=30).run()


def test_farmer_signup_creates_account_profile_and_signs_in():
    at = home()
    at.text_input(key="su_name").set_value("Ravi Kumar")
    at.text_input(key="signup_email").set_value("Ravi@Example.com")
    at.text_input(key="signup_pw").set_value("s3cure-pass")
    at.text_input(key="signup_pw2").set_value("s3cure-pass")
    at.text_input(key="su_village").set_value("Khanna")
    at.text_input(key="su_state").set_value("Punjab")
    at.number_input(key="su_land").set_value(3.5)
    at.selectbox(key="su_soil").select("Alluvial")
    button(at, "Create account").click()
    at.run()
    assert not at.exception and not at.error
    account = auth.login("ravi@example.com", "s3cure-pass")
    farmer = db.get_farmer_by_account(account.id)
    assert farmer["village"] == "Khanna" and farmer["land_size_acres"] == 3.5
    assert at.session_state["account_id"] == account.id and at.session_state["farmer_id"] == farmer["id"]
    assert any(m.label == "New Orders" for m in at.metric)          # farmer dashboard


def test_consumer_signup_gets_consumer_dashboard():
    at = home()
    at.radio(key="signup_role").set_value("Consumer").run()
    at.text_input(key="su_name").set_value("Asha Verma")
    at.text_input(key="signup_email").set_value("asha@example.com")
    at.text_input(key="signup_pw").set_value("s3cure-pass")
    at.text_input(key="signup_pw2").set_value("s3cure-pass")
    button(at, "Create account").click()
    at.run()
    assert not at.exception and not at.error
    assert at.session_state["role"] == "consumer" and at.session_state["farmer_id"] is None
    assert any(m.label == "Open orders" for m in at.metric)
    assert db.list_farmers() == []


def test_signup_validation_messages():
    at = home()
    at.text_input(key="su_name").set_value("X")
    at.text_input(key="signup_email").set_value("not-an-email")
    at.text_input(key="signup_pw").set_value("s3cure-pass")
    at.text_input(key="signup_pw2").set_value("different")
    button(at, "Create account").click()
    at.run()
    assert any("don't match" in e.value for e in at.error) and at.session_state["account_id"] is None
    at.text_input(key="signup_pw2").set_value("s3cure-pass")
    button(at, "Create account").click()
    at.run()
    assert any("valid email" in e.value for e in at.error)


def test_sign_in_and_generic_error_and_sign_out():
    new_consumer("asha@example.com", "Asha Verma")
    at = home()
    at.text_input(key="si_email").set_value("asha@example.com")
    at.text_input(key="si_password").set_value("wrong-password")
    button(at, "Sign in").click()
    at.run()
    assert any(e.value == auth.GENERIC_LOGIN_ERROR for e in at.error) and at.session_state["account_id"] is None
    at.text_input(key="si_password").set_value("s3cure-pass")
    button(at, "Sign in").click()
    at.run()
    assert not at.error and at.session_state["role"] == "consumer"
    button(at, "Sign out").click()
    at.run()
    assert at.session_state["account_id"] is None and at.session_state["cart"] == {}
    assert any(b.label == "Sign in" for b in at.button)             # back to the sign-in form


def test_sign_out_clears_the_previous_users_data_for_the_next_user():
    new_consumer("a@example.com", "Asha"); new_consumer("b@example.com", "Ben")
    at = home()
    at.session_state["cart"] = {1: 2.0}
    at.text_input(key="si_email").set_value("a@example.com")
    at.text_input(key="si_password").set_value("s3cure-pass")
    button(at, "Sign in").click()
    at.run()
    assert at.session_state["cart"] == {}                            # a stale cart never carries into a new session


@pytest.mark.parametrize("prefix", [1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 13])
def test_every_protected_page_requires_sign_in(prefix):
    at = AppTest.from_file(page(prefix), default_timeout=30).run()
    assert not at.exception and any("sign in" in w.value.lower() for w in at.warning), prefix
    assert len(at.button) <= 1                                       # only the sidebar's note; no page content leaked


@pytest.mark.parametrize("prefix", [1, 2, 3, 5, 6, 8, 11, 12])
def test_consumers_cannot_use_farmer_pages(prefix):
    acct = new_consumer()
    at = AppTest.from_file(page(prefix), default_timeout=30)
    at.session_state["account_id"] = acct.id
    at.run()
    assert not at.exception and any("farmer accounts" in w.value.lower() for w in at.warning), prefix


def test_farmers_cannot_use_consumer_pages():
    acct, _ = new_farmer()
    at = AppTest.from_file(page(13), default_timeout=30)
    at.session_state["account_id"] = acct.id
    at.run()
    assert any("consumer accounts" in w.value.lower() for w in at.warning)


def test_a_forged_farmer_id_in_the_session_grants_nothing():
    """Identity comes from account_id only. Putting someone else's farmer_id in the session does nothing."""
    victim_acct, victim = new_farmer("victim@example.com", "Victim")
    attacker = new_consumer("attacker@example.com", "Mallory")
    at = AppTest.from_file(page(11), default_timeout=30)
    at.session_state["account_id"] = attacker.id
    at.session_state["farmer_id"] = victim["id"]
    at.run()
    assert any("farmer accounts" in w.value.lower() for w in at.warning) and not at.text_input


def test_a_nonexistent_account_in_the_session_is_treated_as_signed_out():
    at = AppTest.from_file(page(6), default_timeout=30)
    at.session_state["account_id"] = 987654
    at.run()
    assert any("sign in" in w.value.lower() for w in at.warning)


def test_demo_seed_script_builds_a_working_world_and_refuses_to_run_twice(tmp_db):
    import runpy
    import pytest as _pytest
    from core import market

    script = os.path.join(ROOT, "scripts", "seed_demo.py")
    runpy.run_path(script, run_name="__main__")
    assert auth.login("asha@example.com", "demo-pass-123").role == "consumer"
    assert auth.login("ravi@example.com", "demo-pass-123").role == "farmer"
    assert len(market.list_listings()) >= 8
    with _pytest.raises(SystemExit):
        runpy.run_path(script, run_name="__main__")
