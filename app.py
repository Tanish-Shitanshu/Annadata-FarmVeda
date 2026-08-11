import streamlit as st

from core import db
from core.i18n import t, language_selector_options
from core.state import init_session

st.set_page_config(page_title="Annadata FarmVeda", page_icon="🌾", layout="wide")
init_session()

with st.sidebar:
    st.session_state.language = st.selectbox(
        "🌐 " + t("Select Language", st.session_state.language),
        language_selector_options(),
        index=language_selector_options().index(st.session_state.language),
    )
lang = st.session_state.language

st.title("🌾 " + t("Annadata FarmVeda", lang))
st.caption(t("Human-in-the-loop AI farming companion — predicts, prevents, plans, and helps you profit.", lang))

farmers = db.list_farmers()

st.subheader(t("Your Farm Profile", lang))

if not farmers:
    st.info(t("No farmer profile yet — create one to get personalized recommendations across the app.", lang))
else:
    names = {f["id"]: f"{f['name']} — {f['village'] or 'N/A'}, {f['state'] or 'N/A'}" for f in farmers}
    selected = st.selectbox(
        t("Active profile", lang),
        options=list(names.keys()),
        format_func=lambda fid: names[fid],
        index=list(names.keys()).index(st.session_state.farmer_id) if st.session_state.farmer_id in names else 0,
    )
    st.session_state.farmer_id = selected

with st.expander(t("➕ Create a new farmer profile", lang), expanded=not farmers):
    with st.form("new_farmer"):
        col1, col2 = st.columns(2)
        with col1:
            name = st.text_input(t("Name", lang))
            village = st.text_input(t("Village / Town", lang))
            state = st.text_input(t("State", lang))
        with col2:
            land_size = st.number_input(t("Land size (acres)", lang), min_value=0.0, step=0.5)
            soil_type = st.selectbox(t("Soil type", lang), [
                "Alluvial", "Black (Regur)", "Red", "Laterite", "Sandy",
                "Sandy Loam", "Clayey", "Loamy",
            ])
        submitted = st.form_submit_button(t("Create Profile", lang))
        if submitted and name:
            new_id = db.create_farmer(name, village, state, land_size, soil_type, lang)
            st.session_state.farmer_id = new_id
            st.success(t("Profile created!", lang))
            st.rerun()

if st.session_state.farmer_id:
    farmer = db.get_farmer(st.session_state.farmer_id)
    due = db.due_soon_count(st.session_state.farmer_id)

    st.divider()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(t("Land Size", lang), f"{farmer['land_size_acres']:.1f} acres")
    c2.metric(t("Soil Type", lang), farmer["soil_type"] or "—")
    c3.metric(t("Farm Records", lang), len(db.list_farm_records(farmer["id"])))
    c4.metric(t("Reminders Due Soon", lang), due)

st.divider()
st.subheader(t("What you can do", lang))

feature_cols = st.columns(4)
features = [
    ("🌱", "Crop Recommendation", "Get crops matched to your soil, season, and weather."),
    ("🌦️", "Weather Advisory", "Live 7-day forecast with sowing/irrigation/spray timing."),
    ("⚠️", "Climate Risk & Yield", "Heatwave/drought/flood risk with yield and loss estimates."),
    ("🩺", "Crop Health Scanner", "Upload a leaf photo for a visual health check."),
    ("🤖", "Fasal Guru Chat", "Ask farming questions to an AI assistant."),
    ("🏛️", "Yojana Sathi", "Find government schemes you may be eligible for."),
    ("📚", "Learning Hub", "Guides on modern farming practices."),
    ("👤", "Farmer Profile", "Manage farm records and reminders."),
]
for i, (icon, name, desc) in enumerate(features):
    with feature_cols[i % 4]:
        st.markdown(f"**{icon} {t(name, lang)}**")
        st.caption(t(desc, lang))

st.divider()
st.caption(t(
    "Some features (Live Kheti Watch, Market Price Intelligence, Seedha Bazaar Marketplace, "
    "Nearby Input Store Locator, and Voice Assistant) are on the roadmap — see the "
    "'Coming Soon' page in the sidebar for details on what's planned.", lang
))
