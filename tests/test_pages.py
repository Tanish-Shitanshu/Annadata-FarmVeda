"""End-to-end Streamlit smoke tests (in-process, via streamlit.testing) with the
network faked. These click the real buttons on the real pages."""

import glob
import os

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from conftest import ROOT, forecast_payload

TIMEOUT = 30


def page(prefix):
    return glob.glob(os.path.join(ROOT, "pages", f"{prefix}_*.py"))[0]


@pytest.fixture(autouse=True)
def fresh_caches(net):
    st.cache_data.clear()
    net.add_place("Jaipur", admin1="Rajasthan", admin2="Jaipur")
    yield
    st.cache_data.clear()


def open_page(prefix, farmer_id):
    """Open a page signed in as the farmer that owns `farmer_id`."""
    from core import db
    at = AppTest.from_file(page(prefix), default_timeout=TIMEOUT)
    at.session_state["account_id"] = db.get_farmer(farmer_id)["account_id"]
    at.session_state["language"] = "English"
    return at.run()


def click(at, label):
    [b for b in at.button if b.label == label][0].click()
    return at.run()


def labels(at):
    return [b.label for b in at.button]


def md(at):
    return " ".join(m.value for m in at.markdown)


# ── Home ────────────────────────────────────────────────────────────────────

def test_home_page_renders(tmp_db):
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=TIMEOUT).run()
    assert not at.exception


def test_pages_ask_for_a_profile_when_none_selected(tmp_db):
    at = AppTest.from_file(page(2), default_timeout=TIMEOUT).run()
    assert not at.exception and any("sign in" in w.value.lower() for w in at.warning)


# ── Weather advisory + human-in-the-loop ────────────────────────────────────

def test_advisory_accept_creates_reminder_and_logs_decision(tmp_db, farmer_id):
    at = open_page(2, farmer_id)
    assert not at.exception and not tmp_db.list_reminders(farmer_id)
    at = click(at, "Get Advisory")
    assert not at.exception
    assert labels(at).count("Add to reminders") == 1          # only the open advisory (sowing) is shown

    at = click(at, "Add to reminders")
    assert not at.exception
    reminders = tmp_db.list_reminders(farmer_id)
    assert len(reminders) == 1 and reminders[0]["category"] == "Sowing"
    log = tmp_db.list_advice_log(farmer_id)
    assert len(log) == 1 and log[0]["decision"] == "accepted" and log[0]["kind"] == "sowing"
    assert labels(at).count("Add to reminders") == 0           # replaced by the outcome
    assert any("Added to your reminders" in s.value for s in at.success)
    assert at.radio(key="wx_section").value == "sowing"        # and the page stays on the advisory just acted on

    at.radio(key="wx_section").set_value("irrigation").run()   # the other advisories offer their own suggestions
    assert labels(at).count("Add to reminders") == 1
    at = click(at, "Add to reminders")
    assert at.radio(key="wx_section").value == "irrigation"
    assert {r["category"] for r in tmp_db.list_reminders(farmer_id)} == {"Sowing", "Irrigation"}

    at.run()                                                   # a plain rerun must not double-save
    assert len(tmp_db.list_reminders(farmer_id)) == 2 and len(tmp_db.list_advice_log(farmer_id)) == 2


def test_advisory_dismiss_logs_without_reminder(tmp_db, farmer_id):
    at = click(open_page(2, farmer_id), "Get Advisory")
    at = click(at, "Dismiss")
    assert not at.exception
    assert tmp_db.list_reminders(farmer_id) == []
    assert [e["decision"] for e in tmp_db.list_advice_log(farmer_id)] == ["dismissed"]


def test_advisory_does_nothing_on_its_own(tmp_db, farmer_id):
    click(open_page(2, farmer_id), "Get Advisory")
    assert tmp_db.list_reminders(farmer_id) == [] and tmp_db.list_advice_log(farmer_id) == []


def test_advisory_unknown_place(tmp_db, farmer_id, net):
    at = open_page(2, farmer_id)
    at.text_input(key="wx_loc_text").set_value("Zzzzville").run()
    assert any("find that location" in e.value for e in at.error)


def test_advisory_weather_service_down_shows_message_not_traceback(tmp_db, farmer_id, net):
    at = open_page(2, farmer_id)
    net.fail.add("forecast")
    at = click(at, "Get Advisory")
    assert not at.exception and any("weather service" in e.value for e in at.error)


def test_ambiguous_village_name_lets_farmer_choose(tmp_db, farmer_id, net):
    net.add_place("Rampur", admin1="Uttar Pradesh", admin2="Rampur")
    net.add_place("Rampur", admin1="Himachal Pradesh", admin2="Shimla")
    at = open_page(2, farmer_id)
    at.text_input(key="wx_loc_text").set_value("Rampur").run()
    select = at.selectbox(key="wx_loc_select")
    assert len(select.options) == 2 and "Himachal Pradesh" in select.options[1]
    select.select(select.options[1]).run()
    at = click(at, "Get Advisory")
    assert "Himachal Pradesh" in " ".join(s.value for s in at.subheader)


# ── Crop recommendation ─────────────────────────────────────────────────────

def test_recommendation_uses_historical_normals(tmp_db, farmer_id):
    at = click(open_page(1, farmer_id), "Get Recommendations")
    assert not at.exception
    assert any("historical" in c.value.lower() for c in at.caption)
    assert len([m for m in at.metric if m.label == "Match Score"]) == 5


def test_recommendation_flags_fallback_when_archive_down(tmp_db, farmer_id, net):
    net.fail.add("archive")
    at = click(open_page(1, farmer_id), "Get Recommendations")
    assert not at.exception and any("rough guess" in w.value for w in at.warning)


def test_recommendation_zaid(tmp_db, farmer_id):
    at = open_page(1, farmer_id)
    at.selectbox[0].select("Zaid").run()
    at = click(at, "Get Recommendations")
    assert not at.exception
    assert any(c in md(at) for c in ("Watermelon", "Muskmelon", "Cucumber", "Green Gram"))


# ── Climate risk ────────────────────────────────────────────────────────────

def test_risk_page_runs_and_is_crop_specific(tmp_db, farmer_id, net):
    net.forecast = forecast_payload(tmax=36, tmin=22, rain=4)
    at = open_page(3, farmer_id)
    at.selectbox[0].select("Wheat").run()
    at = click(at, "Assess Risk")
    assert not at.exception and "Heat stress for Wheat" in md(at)
    at.selectbox[0].select("Sugarcane").run()
    at = click(at, "Assess Risk")
    assert "Heat stress" not in md(at)


# ── Chat ────────────────────────────────────────────────────────────────────

def test_chat_without_key_explains(tmp_db, farmer_id, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    at = open_page(5, farmer_id)
    assert any("GEMINI_API_KEY" in w.value for w in at.warning)
    at.chat_input[0].set_value("When should I sow wheat?").run()
    assert not at.exception
    assert any("isn't configured" in m.value for m in at.markdown)


# ── Profile / history ───────────────────────────────────────────────────────

def test_profile_shows_advice_history_and_sowing_category(tmp_db, farmer_id):
    tmp_db.dismiss_advice(farmer_id, "irrigation", "Hold off", "rain", "Jaipur, India")
    at = open_page(8, farmer_id)
    assert not at.exception
    assert "Hold off" in md(at) and "dismissed" in md(at)
    assert "Sowing" in at.selectbox[0].options


def test_scanner_page_loads(tmp_db, farmer_id):
    assert not open_page(4, farmer_id).exception


@pytest.mark.parametrize("n", [6, 7, 11, 12, 14])
def test_other_pages_load(tmp_db, farmer_id, n):
    assert not open_page(n, farmer_id).exception
