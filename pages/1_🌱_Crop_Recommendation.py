import requests
import streamlit as st

from core.crop_recommender import recommend_crops
from core.i18n import t
from core.location_picker import cached_forecast, cached_seasonal_climate, pick_location
from core.state import init_session, require_farmer

lang = init_session()
farmer = require_farmer(lang)

st.title("🌱 " + t("Smart Crop Recommendation", lang))
st.caption(t("Rule-based match against published agronomic ranges for soil, season, temperature, and rainfall — "
             "not a substitute for local agronomist advice.", lang))

col1, col2 = st.columns(2)
with col1:
    loc = pick_location(lang, t("Your location (for temperature/rainfall)", lang),
                        default=farmer["village"] or "", key="reco_loc")
with col2:
    season = st.selectbox(t("Season", lang), ["Kharif", "Rabi", "Zaid"])
    st.caption(t("Kharif: Jun–Oct · Rabi: Nov–mid-Mar · Zaid: mid-Mar–mid-Jun (national approximation)", lang))

if st.button(t("Get Recommendations", lang), type="primary"):
    if loc is None:
        st.warning(t("Enter and pick a location first.", lang))
    else:
        try:
            with st.spinner(t("Looking up this location's seasonal climate...", lang)):
                forecast = cached_forecast(loc)
                climate = cached_seasonal_climate(loc, season, forecast)
        except requests.RequestException:
            st.error(t("Couldn't reach the weather service. Check your connection and try again.", lang))
            st.stop()

        st.success(t(f"{season} climate near {loc.label}: mean {climate.avg_temp_c:.0f}°C, "
                     f"~{climate.rainfall_mm:.0f}mm rainfall", lang))
        if climate.basis == "historical normals":
            st.caption("📊 " + t(climate.detail, lang))
        else:
            st.warning("⚠️ " + t(climate.detail, lang))

        recs = recommend_crops(
            soil_type=farmer["soil_type"] or "Loamy",
            season=season,
            avg_temp_c=climate.avg_temp_c,
            seasonal_rainfall_mm=climate.rainfall_mm,
        )

        for r in recs:
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                c1.markdown(f"### {r.crop.crop}")
                c2.metric(t("Match Score", lang), f"{r.score}/100")
                st.caption(t(f"Typical duration: {r.crop.duration_days} days", lang))
                for reason in r.reasons:
                    st.markdown(f"- {t(reason, lang)}")
