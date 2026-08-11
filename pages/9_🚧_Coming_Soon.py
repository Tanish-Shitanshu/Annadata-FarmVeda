import streamlit as st

from core.i18n import t
from core.state import init_session

lang = init_session()

st.title("🚧 " + t("Coming Soon", lang))
st.caption(t("These features are on the roadmap. They're shown here as previews so you can see the "
             "intended design, but nothing below is functional yet — no live data is fetched or stored.", lang))

roadmap = [
    ("📡", "Live Kheti Watch", "Real-time push alerts for rainfall, pests, disease outbreaks, and adverse "
     "weather in your area. Needs a notification delivery backend (SMS/push) that isn't built yet — "
     "today's Weather Advisory page covers the same underlying forecast data on-demand instead."),
    ("💹", "Market Price Intelligence", "Live mandi price feeds and trend charts for your crops. "
     "Needs integration with a live commodity price API (e.g. Agmarknet) — not wired up yet."),
    ("🛒", "Seedha Bazaar Marketplace", "A direct farmer-to-buyer marketplace to reduce dependence on "
     "intermediaries. This needs listings, payments, and logistics infrastructure — out of scope for "
     "the current build."),
    ("📍", "Nearby Input Store Locator", "Find nearby shops for seeds, fertilizer, and equipment. "
     "Needs a maps/places API integration — not wired up yet."),
    ("🎙️", "Voice-Based AI Assistant", "Ask farming questions by voice instead of typing. Needs "
     "speech-to-text/text-to-speech infrastructure — the Fasal Guru page covers the same AI assistant "
     "via text chat today."),
]

for icon, name, desc in roadmap:
    with st.container(border=True):
        st.markdown(f"### {icon} {t(name, lang)}")
        st.write(t(desc, lang))
        st.caption(t("Status: Planned, not yet implemented", lang))
