from datetime import date

import requests
import streamlit as st

from core import db
from core.advice import SuggestedReminder, suggest_reminder, suggest_spraying_reminder
from core.i18n import t
from core.location_picker import cached_forecast, pick_location
from core.state import init_session, require_farmer
from core.weather import (harvest_advisory, irrigation_advisory,
                          sowing_advisory, spraying_advisory)

lang = init_session()
farmer = require_farmer(lang)

st.title("🌦️ " + t("Weather-Based Farming Advice", lang))
st.caption(t("Live 7-day forecast (Open-Meteo) with rule-based sowing, irrigation, spraying, "
             "and harvest timing guidance. FarmVeda only suggests — nothing is saved to your "
             "reminders unless you accept it.", lang))

loc = pick_location(lang, t("Location", lang), default=farmer["village"] or "", key="wx_loc")

if "decided_advice" not in st.session_state:
    st.session_state.decided_advice = {}


# ── Accept / dismiss callbacks ──────────────────────────────────────────────
# Run before the page re-renders, so the decision is recorded exactly once and
# the buttons are replaced by the outcome on the same rerun.

def _accept(key: str, kind: str, verdict: str, reason: str, location: str,
            title: str, due_iso: str, category: str) -> None:
    db.accept_advice(st.session_state.farmer_id, kind, verdict, reason, location,
                     title, due_iso, category)
    st.session_state.decided_advice[key] = "accepted"


def _dismiss(key: str, kind: str, verdict: str, reason: str, location: str) -> None:
    db.dismiss_advice(st.session_state.farmer_id, kind, verdict, reason, location)
    st.session_state.decided_advice[key] = "dismissed"


def render_suggestion(kind: str, verdict: str, reason: str, location: str,
                      suggestion: SuggestedReminder | None, forecast_day: str) -> None:
    if suggestion is None:
        return
    key = f"{kind}|{verdict}|{location}|{forecast_day}"
    title = t(suggestion.title, lang)
    decision = st.session_state.decided_advice.get(key)

    if decision == "accepted":
        st.success("✅ " + t("Added to your reminders:", lang) + f" **{title}** ({suggestion.due_date:%d %b})")
    elif decision == "dismissed":
        st.caption("✖️ " + t("Dismissed — noted in your advice history.", lang))
    else:
        st.info("🔔 " + t("Suggested reminder:", lang) + f" **{title}** — {suggestion.due_date:%a %d %b}")
        c1, c2, _ = st.columns([1, 1, 3])
        c1.button(t("Add to reminders", lang), key=f"acc_{key}", type="primary", on_click=_accept,
                  args=(key, kind, verdict, reason, location, title,
                        suggestion.due_date.isoformat(), suggestion.category))
        c2.button(t("Dismiss", lang), key=f"dis_{key}", on_click=_dismiss,
                  args=(key, kind, verdict, reason, location))


# ── Fetch ───────────────────────────────────────────────────────────────────
if st.button(t("Get Advisory", lang), type="primary"):
    if loc is None:
        st.warning(t("Enter and pick a location first.", lang))
    else:
        try:
            with st.spinner(t("Fetching forecast...", lang)):
                forecast = cached_forecast(loc)
            # Held in session state so the advisories (and their accept/dismiss
            # buttons) survive the reruns those buttons cause.
            st.session_state.advisory = {"loc": loc, "forecast": forecast,
                                         "day": date.today().isoformat()}
        except requests.RequestException:
            st.error(t("Couldn't reach the weather service. Check your connection and try again.", lang))

# ── Render ──────────────────────────────────────────────────────────────────
adv = st.session_state.get("advisory")
if adv:
    forecast, adv_loc, adv_day = adv["forecast"], adv["loc"], adv["day"]
    place_label = adv_loc.label

    st.subheader(t(f"7-day forecast for {place_label}", lang))
    cols = st.columns(len(forecast.days))
    for i, d in enumerate(forecast.days):
        with cols[i]:
            st.markdown(f"**{d.day.strftime('%a %d')}**")
            st.markdown(f"🌡️ {d.temp_min_c:.0f}–{d.temp_max_c:.0f}°C")
            st.markdown(f"🌧️ {d.precipitation_probability_pct:.0f}%")
            st.markdown(f"💨 {d.wind_speed_max_kmh:.0f} km/h")

    st.divider()
    tabs = st.tabs([
        t("🌱 Sowing", lang), t("💧 Irrigation", lang),
        t("🧪 Spraying", lang), t("🌾 Harvest", lang),
    ])

    with tabs[0]:
        a = sowing_advisory(forecast)
        st.metric(t("Verdict", lang), t(a["verdict"], lang))
        st.write(t(a["reason"], lang))
        render_suggestion("sowing", a["verdict"], a["reason"], place_label,
                          suggest_reminder("sowing", a), adv_day)

    with tabs[1]:
        a = irrigation_advisory(forecast)
        st.metric(t("Verdict", lang), t(a["verdict"], lang))
        st.write(t(a["reason"], lang))
        render_suggestion("irrigation", a["verdict"], a["reason"], place_label,
                          suggest_reminder("irrigation", a), adv_day)

    with tabs[2]:
        spray_days = spraying_advisory(forecast)
        for day_advisory in spray_days:
            icon = "✅" if day_advisory["verdict"] == "Suitable" else "⛔"
            st.markdown(f"{icon} **{day_advisory['day'].strftime('%a %d %b')}** — "
                        f"{t(day_advisory['verdict'], lang)}: {t(day_advisory['reason'], lang)}")
        spray = suggest_spraying_reminder(spray_days)
        if spray is None:
            st.caption(t("No suitable spraying day in this forecast.", lang))
        else:
            render_suggestion("spraying", "Suitable", f"First suitable day: {spray.due_date:%a %d %b}",
                              place_label, spray, adv_day)

    with tabs[3]:
        a = harvest_advisory(forecast)
        st.metric(t("Verdict", lang), t(a["verdict"], lang))
        st.write(t(a["reason"], lang))
        render_suggestion("harvest", a["verdict"], a["reason"], place_label,
                          suggest_reminder("harvest", a), adv_day)
