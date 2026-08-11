import streamlit as st

from core.crop_recommender import recommend_crops
from core.i18n import t
from core.state import init_session, require_farmer
from core.weather import geocode, get_forecast

lang = init_session()
farmer = require_farmer(lang)

st.title("🌱 " + t("Smart Crop Recommendation", lang))
st.caption(t("Rule-based match against published agronomic ranges for soil, season, temperature, and rainfall — "
             "not a substitute for local agronomist advice.", lang))

col1, col2 = st.columns(2)
with col1:
    place = st.text_input(t("Your location (for live temperature/rainfall)", lang),
                           value=farmer["village"] or "")
with col2:
    season = st.selectbox(t("Season", lang), ["Kharif", "Rabi", "Zaid"])

if st.button(t("Get Recommendations", lang), type="primary"):
    if not place:
        st.warning(t("Enter a location first.", lang))
    else:
        with st.spinner(t("Fetching live weather and matching crops...", lang)):
            loc = geocode(place)
            if not loc:
                st.error(t("Couldn't find that location. Try a nearby city name.", lang))
            else:
                forecast = get_forecast(loc)
                avg_temp = sum(d.temp_max_c for d in forecast.days) / len(forecast.days)
                total_rain = sum(d.precipitation_mm for d in forecast.days)
                # Scale the 7-day sample to a rough seasonal figure for matching purposes.
                seasonal_rain_estimate = total_rain * (120 / 7)

                st.success(t(f"Weather near {loc.name}: avg {avg_temp:.0f}°C, "
                             f"~{seasonal_rain_estimate:.0f}mm projected over the season", lang))

                recs = recommend_crops(
                    soil_type=farmer["soil_type"] or "Loamy",
                    season=season,
                    avg_temp_c=avg_temp,
                    seasonal_rainfall_mm=seasonal_rain_estimate,
                )

                for r in recs:
                    with st.container(border=True):
                        c1, c2 = st.columns([3, 1])
                        c1.markdown(f"### {r.crop.crop}")
                        c2.metric(t("Match Score", lang), f"{r.score}/100")
                        st.caption(t(f"Typical duration: {r.crop.duration_days} days", lang))
                        for reason in r.reasons:
                            st.markdown(f"- {t(reason, lang)}")
