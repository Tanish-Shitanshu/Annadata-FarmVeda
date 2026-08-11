import json
import os

import streamlit as st

from core.i18n import t
from core.state import init_session, require_farmer

lang = init_session()
farmer = require_farmer(lang)

st.title("📚 " + t("Farmer Learning Hub", lang))
st.caption(t("Practical guides on modern farming practices.", lang))

with open(os.path.join(os.path.dirname(__file__), "..", "data", "learning_content.json"), encoding="utf-8") as f:
    articles = json.load(f)

categories = sorted({a["category"] for a in articles})
selected_cat = st.selectbox(t("Category", lang), [t("All", lang)] + [t(c, lang) for c in categories])

for a in articles:
    if selected_cat != t("All", lang) and t(a["category"], lang) != selected_cat:
        continue
    with st.expander(f"📖 {t(a['title'], lang)}  —  _{t(a['category'], lang)}_"):
        st.write(t(a["summary"], lang))
        st.markdown(f"**{t('Practical tips', lang)}:**")
        for tip in a["tips"]:
            st.markdown(f"- {t(tip, lang)}")
