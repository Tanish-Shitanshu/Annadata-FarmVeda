import requests
import streamlit as st

from core.crop_recommender import get_profile, load_crop_profiles
from core.i18n import t
from core.location_picker import cached_forecast, cached_seasonal_climate, pick_location
from core.risk_yield import assess_climate_risk, estimate_loss, estimate_yield
from core.state import init_session, require_farmer

lang = init_session()
farmer = require_farmer(lang)

st.title("⚠️ " + t("Climate Risk, Yield & Loss Prevention", lang))
st.caption(t("Heuristic estimates derived from the live weather forecast, the crop's own temperature "
             "and water needs, and a static yield/price reference table — for planning purposes, "
             "not a precision forecast. Reference prices are illustrative, not live mandi rates.", lang))

profiles = load_crop_profiles()
crop_names = [c.crop for c in profiles]

col1, col2 = st.columns(2)
with col1:
    loc = pick_location(lang, t("Location", lang), default=farmer["village"] or "", key="risk_loc")
with col2:
    crop = st.selectbox(t("Crop", lang), crop_names)

if st.button(t("Assess Risk", lang), type="primary"):
    if loc is None:
        st.warning(t("Enter and pick a location first.", lang))
        st.stop()

    profile = get_profile(crop)
    try:
        with st.spinner(t("Analyzing forecast...", lang)):
            forecast = cached_forecast(loc)
            # Seasonal rainfall for the water-gap check: use the crop's own season
            # (year-round crops: Kharif, the main rainfall season).
            season = profile.season if profile.season in ("Kharif", "Rabi", "Zaid") else "Kharif"
            climate = cached_seasonal_climate(loc, season, forecast)
    except requests.RequestException:
        st.error(t("Couldn't reach the weather service. Check your connection and try again.", lang))
        st.stop()

    # Only trust real historical normals for the water-gap check; a one-week
    # extrapolation is too noisy to flag a crop on.
    seasonal_rain = climate.rainfall_mm if climate.basis == "historical normals" else None
    risk = assess_climate_risk(forecast, crop=profile, seasonal_rainfall_mm=seasonal_rain)
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
        if loss_est:
            st.caption(t(loss_est.note, lang))
