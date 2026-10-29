import streamlit as st

from core.i18n import t
from core.state import init_session

lang = init_session()

st.title("🚧 " + t("Coming Soon", lang))
st.caption(t("These features are on the roadmap. They're shown here as previews so you can see the "
             "intended design, but nothing below is functional yet — no live data is fetched or stored.", lang))

roadmap = [
    ("💹", "Market Price Intelligence", "Live mandi price feeds and trend charts so farmers can price their listings. "
     "Needs integration with a live commodity price API (e.g. Agmarknet / data.gov.in) — not wired up yet."),
    ("💳", "Online Payments", "Pay inside the app (UPI / cards) with the money held until delivery. Today buyers pay the "
     "farmer directly. Needs a payment gateway (e.g. Razorpay), KYC for farmers and a refund process."),
    ("🚚", "Delivery & Logistics", "Courier or shared-transport delivery. Today the farmer arranges pickup or delivery "
     "themselves."),
    ("🤲", "Donations to Farmers", "Letting people support farmers directly. Deliberately NOT built: collecting money "
     "for others in India raises KYC, payout-verification and possibly registered-entity (and FCRA) questions that need a "
     "lawyer or CA first."),
    ("📡", "Live Kheti Watch", "Real-time push/SMS alerts for rainfall, pests and weather. Needs a notification "
     "backend (SMS/push) that isn't built — the Weather Advisory page gives the same forecast on demand."),
    ("📍", "Nearby Input Store Locator", "Find nearby shops for seeds, fertilizer and equipment. Needs a maps/places "
     "API integration."),
    ("🎙️", "Voice-Based AI Assistant", "Ask farming questions by voice. Needs speech-to-text/text-to-speech "
     "infrastructure — Fasal Guru covers the same assistant by text today."),
    ("🪪", "Email Verification & Password Reset", "Accounts use email + password today with no email verification or "
     "password reset, because there is no email service connected."),
]

for icon, name, desc in roadmap:
    with st.container(border=True):
        st.markdown(f"### {icon} {t(name, lang)}")
        st.write(t(desc, lang))
        st.caption(t("Status: Planned, not yet implemented", lang))
