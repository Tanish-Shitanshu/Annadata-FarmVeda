from datetime import date

import streamlit as st

from core import db
from core.i18n import t
from core.safe import md_escape
from core.state import init_session, require_farmer

lang = init_session()
farmer = require_farmer(lang)

st.title("👤 " + t("Farmer Profile & Farm Records", lang))

col1, col2 = st.columns(2)
with col1:
    st.subheader(t("Profile", lang))
    st.write(f"**{t('Name', lang)}:** {md_escape(farmer['name'])}")
    st.write(f"**{t('Village', lang)}:** {md_escape(farmer['village'] or '—')}")
    st.write(f"**{t('State', lang)}:** {md_escape(farmer['state'] or '—')}")
    st.write(f"**{t('Land Size', lang)}:** {farmer['land_size_acres']} acres")
    st.write(f"**{t('Soil Type', lang)}:** {md_escape(farmer['soil_type'])}")
    with st.expander("✏️ " + t("Edit profile", lang)):
        SOILS = ["Alluvial", "Black (Regur)", "Red", "Laterite", "Sandy", "Sandy Loam", "Clayey", "Loamy"]
        with st.form("edit_profile"):
            e_name = st.text_input(t("Full name", lang), value=farmer["name"], key="ep_name")
            e_village = st.text_input(t("Village / Town", lang), value=farmer["village"] or "", key="ep_village")
            e_state = st.text_input(t("State", lang), value=farmer["state"] or "", key="ep_state")
            e_land = st.number_input(t("Land size (acres)", lang), min_value=0.0, step=0.5,
                                     value=float(farmer["land_size_acres"] or 0), key="ep_land")
            soils = SOILS if farmer["soil_type"] in SOILS else [farmer["soil_type"]] + SOILS
            e_soil = st.selectbox(t("Soil type", lang), soils, index=soils.index(farmer["soil_type"]), key="ep_soil")
            if st.form_submit_button(t("Save profile", lang), type="primary"):
                try:
                    db.update_farmer_profile(farmer["id"], e_name, e_village, e_state, e_land, e_soil)
                    st.rerun()
                except ValueError as exc:
                    st.error(t(str(exc), lang))

with col2:
    st.subheader(t("🔔 Reminders", lang))
    reminders = db.list_reminders(farmer["id"])
    if not reminders:
        st.caption(t("No pending reminders.", lang))
    for r in reminders:
        c1, c2 = st.columns([4, 1])
        c1.markdown(f"**{md_escape(r['title'])}** — {r['due_date']} ({t(r['category'] or '', lang)})")
        if c2.button("✅", key=f"done_{r['id']}"):
            db.mark_reminder_done(r["id"])
            st.rerun()

    with st.form("new_reminder", clear_on_submit=True):
        st.markdown(f"**{t('Add reminder', lang)}**")
        title = st.text_input(t("What", lang), placeholder=t("e.g. Irrigate wheat field", lang))
        due = st.date_input(t("Due date", lang), value=date.today())
        category = st.selectbox(t("Category", lang),
                                 ["Sowing", "Irrigation", "Spraying", "Fertilizer", "Harvest", "Schemes", "Other"])
        if st.form_submit_button(t("Add", lang)) and title:
            db.add_reminder(farmer["id"], title, due.isoformat(), category)
            st.rerun()

st.divider()
st.subheader(t("🌾 Farm Records", lang))

records = db.list_farm_records(farmer["id"])
if records:
    for r in records:
        with st.container(border=True):
            st.markdown(f"**{r['crop']}** — {r['season']} — {t('sown', lang)} {r['sown_on']}")
            if r["notes"]:
                st.caption(r["notes"])
else:
    st.caption(t("No farm records yet.", lang))

with st.form("new_record", clear_on_submit=True):
    st.markdown(f"**{t('Add a farm record', lang)}**")
    c1, c2, c3 = st.columns(3)
    crop = c1.text_input(t("Crop", lang))
    season = c2.selectbox(t("Season", lang), ["Kharif", "Rabi", "Zaid"])
    sown_on = c3.date_input(t("Sown on", lang), value=date.today())
    notes = st.text_area(t("Notes", lang))
    if st.form_submit_button(t("Add Record", lang)) and crop:
        db.add_farm_record(farmer["id"], crop, season, sown_on.isoformat(), notes)
        st.rerun()

st.divider()
st.subheader(t("🧭 Advice history", lang))
st.caption(t("Every suggestion FarmVeda showed you and what you decided. The app never acts on its own.", lang))

log = db.list_advice_log(farmer["id"], limit=20)
if not log:
    st.caption(t("No advice decisions yet. Try the Weather Advisory page.", lang))
for entry in log:
    icon = "✅" if entry["decision"] == "accepted" else "✖️"
    when = entry["created_at"][:10]
    st.markdown(f"{icon} **{t(entry['kind'].title(), lang)}** — {t(entry['verdict'], lang)} "
                f"({entry['location'] or '—'}, {when}) · {t(entry['decision'], lang)}")
