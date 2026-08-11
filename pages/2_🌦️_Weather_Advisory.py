import streamlit as st

from core.i18n import t
from core.state import init_session, require_farmer
from core.weather import (geocode, get_forecast, harvest_advisory,
                           irrigation_advisory, sowing_advisory, spraying_advisory)

lang = init_session()
farmer = require_farmer(lang)

st.title("🌦️ " + t("Weather-Based Farming Advice", lang))
st.caption(t("Live 7-day forecast (Open-Meteo) with rule-based sowing, irrigation, spraying, "
             "and harvest timing guidance.", lang))

place = st.text_input(t("Location", lang), value=farmer["village"] or "")

if st.button(t("Get Advisory", lang), type="primary") and place:
    with st.spinner(t("Fetching forecast...", lang)):
        loc = geocode(place)
        if not loc:
            st.error(t("Couldn't find that location.", lang))
        else:
            forecast = get_forecast(loc)

            st.subheader(t(f"7-day forecast for {loc.name}, {loc.country}", lang))
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

            with tabs[1]:
                a = irrigation_advisory(forecast)
                st.metric(t("Verdict", lang), t(a["verdict"], lang))
                st.write(t(a["reason"], lang))

            with tabs[2]:
                for day_advisory in spraying_advisory(forecast):
                    icon = "✅" if day_advisory["verdict"] == "Suitable" else "⛔"
                    st.markdown(f"{icon} **{day_advisory['day'].strftime('%a %d %b')}** — "
                                f"{t(day_advisory['verdict'], lang)}: {t(day_advisory['reason'], lang)}")

            with tabs[3]:
                a = harvest_advisory(forecast)
                st.metric(t("Verdict", lang), t(a["verdict"], lang))
                st.write(t(a["reason"], lang))
