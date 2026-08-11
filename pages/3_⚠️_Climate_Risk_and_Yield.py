import streamlit as st

from core.crop_recommender import load_crop_profiles
from core.i18n import t
from core.risk_yield import assess_climate_risk, estimate_loss, estimate_yield
from core.state import init_session, require_farmer
from core.weather import geocode, get_forecast

lang = init_session()
farmer = require_farmer(lang)

st.title("⚠️ " + t("Climate Risk, Yield & Loss Prevention", lang))
st.caption(t("Heuristic estimates derived from the live weather forecast and a static crop yield/price "
             "reference table — for planning purposes, not a precision forecast.", lang))

crop_names = [c.crop for c in load_crop_profiles()]

col1, col2 = st.columns(2)
with col1:
    place = st.text_input(t("Location", lang), value=farmer["village"] or "")
with col2:
    crop = st.selectbox(t("Crop", lang), crop_names)

if st.button(t("Assess Risk", lang), type="primary") and place:
    with st.spinner(t("Analyzing forecast...", lang)):
        loc = geocode(place)
        if not loc:
            st.error(t("Couldn't find that location.", lang))
        else:
            forecast = get_forecast(loc)
            risk = assess_climate_risk(forecast)
            yield_est = estimate_yield(crop, risk)
            loss_est = estimate_loss(crop, farmer["land_size_acres"] or 1.0, yield_est) if yield_est else None

            level_color = {"Low": "green", "Medium": "orange", "High": "red"}[risk.level]
            st.markdown(f"### {t('Climate Risk Level', lang)}: :{level_color}[{t(risk.level, lang)}] ({risk.score}/100)")
            for f in risk.factors:
                st.markdown(f"- {t(f, lang)}")

            if yield_est:
                st.divider()
                c1, c2, c3 = st.columns(3)
                c1.metric(t("Baseline Yield", lang), f"{yield_est.baseline_yield_quintal_per_acre:.1f} q/acre")
                c2.metric(t("Estimated Yield", lang), f"{yield_est.estimated_yield_quintal_per_acre:.1f} q/acre",
                           delta=f"{yield_est.yield_change_pct:.1f}%")
                if loss_est:
                    c3.metric(t("Estimated Value at Risk", lang), f"₹{loss_est.estimated_loss_inr:,.0f}")

                if loss_est and loss_est.estimated_loss_inr > 0:
                    st.warning(t(f"Based on current risk signals, your {farmer['land_size_acres']:.1f}-acre "
                                 f"{crop} crop could see a value impact of roughly "
                                 f"₹{loss_est.estimated_loss_inr:,.0f} if conditions persist. "
                                 f"Consider the mitigation steps in the Weather Advisory page "
                                 f"(irrigation/spraying timing) to reduce this.", lang))
                else:
                    st.success(t("No significant loss signal from current weather risk.", lang))
                st.caption(t(loss_est.note, lang) if loss_est else "")
