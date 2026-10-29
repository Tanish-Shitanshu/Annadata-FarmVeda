import requests
import streamlit as st

from core import db
from core.chat import FarmContext, ask, is_available, summarize_forecast
from core.i18n import t
from core.location_picker import cached_candidates, cached_forecast
from core.state import init_session, require_farmer

lang = init_session()
farmer = require_farmer(lang)

st.title("🤖 " + t("Fasal Guru — AI Farming Guide", lang))
st.caption(t("Step-by-step guidance through the crop lifecycle, powered by Gemini. It sees your village, state, soil, "
             "land size and recent crops (never your name). It can be wrong — check "
             "pesticide doses on the product label and with your local Krishi Vigyan Kendra.", lang))

if not is_available():
    st.warning(t("AI chat needs a GEMINI_API_KEY in your .env file to work. "
                 "See .env.example for setup — it's free at aistudio.google.com/apikey.", lang))

use_weather = st.sidebar.checkbox(t("Include my local weather in answers", lang), value=True,
                                  help=t("Looks up the forecast for your village and shares a short summary "
                                         "with the AI.", lang))


@st.cache_data(ttl=600, show_spinner=False)
def _weather_summary(village: str) -> str:
    candidates = cached_candidates(village)
    return summarize_forecast(cached_forecast(candidates[0])) if candidates else ""


def build_context() -> FarmContext:
    records = db.list_farm_records(farmer["id"])
    recent: list[str] = []
    for r in records:
        if r["crop"] not in recent:
            recent.append(r["crop"])
        if len(recent) == 3:
            break
    weather = ""
    if use_weather and farmer["village"]:
        try:
            weather = _weather_summary(farmer["village"])
        except requests.RequestException:
            weather = ""  # chat still works without weather
    return FarmContext(state=farmer["state"] or "", village=farmer["village"] or "",
                       soil_type=farmer["soil_type"] or "",
                       land_size_acres=farmer["land_size_acres"], recent_crops=recent,
                       weather_summary=weather)


if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for turn in st.session_state.chat_history:
    with st.chat_message(turn["role"]):
        st.write(turn["content"])

question = st.chat_input(t("Ask about sowing, pests, irrigation, fertilizer...", lang))
if question:
    st.session_state.chat_history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner(t("Thinking...", lang)):
            reply = ask(question, st.session_state.chat_history[:-1],
                        context=build_context(), language=lang)
        st.write(reply)
    st.session_state.chat_history.append({"role": "assistant", "content": reply})
