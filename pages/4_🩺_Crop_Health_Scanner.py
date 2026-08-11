import streamlit as st

from core.health_scanner import analyze_image
from core.i18n import t
from core.state import init_session, require_farmer

lang = init_session()
farmer = require_farmer(lang)

st.title("🩺 " + t("AI Crop Health Scanner", lang))
st.info(t("This scanner reads real color/texture signals from your photo (a heuristic analysis), "
          "not a trained deep-learning disease classifier. Treat results as a first-pass visual "
          "check, and confirm with your local Krishi Vigyan Kendra before acting.", lang), icon="ℹ️")

uploaded = st.file_uploader(t("Upload a leaf/crop photo", lang), type=["jpg", "jpeg", "png"])

if uploaded:
    col1, col2 = st.columns([1, 1])
    with col1:
        st.image(uploaded, caption=t("Uploaded photo", lang), use_container_width=True)

    with col2:
        with st.spinner(t("Analyzing image...", lang)):
            result = analyze_image(uploaded.getvalue())

        color = {"Healthy": "green", "Possible Nutrient Deficiency": "orange",
                 "Possible Fungal or Pest Damage": "red", "Possible Water Stress": "orange",
                 "Inconclusive": "gray"}[result.category]

        st.markdown(f"### :{color}[{t(result.category, lang)}]")
        st.progress(result.confidence_pct / 100, text=f"{t('Confidence', lang)}: {result.confidence_pct}%")
        st.write(t(result.summary, lang))

        st.markdown(f"**{t('Recommendation', lang)}:**")
        st.write(t(result.recommendation, lang))

        with st.expander(t("Technical detail", lang)):
            st.write(f"Green ratio: {result.green_ratio:.2f}")
            st.write(f"Yellow ratio: {result.yellow_ratio:.2f}")
            st.write(f"Dark-spot ratio: {result.dark_spot_ratio:.2f}")
            st.write(f"Mean saturation: {result.saturation_mean:.1f}/255")
