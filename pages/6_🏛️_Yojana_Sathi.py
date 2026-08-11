import streamlit as st

from core.i18n import t
from core.schemes import all_categories, match_schemes
from core.state import init_session, require_farmer

lang = init_session()
farmer = require_farmer(lang)

st.title("🏛️ " + t("Yojana Sathi — Government Scheme Assistant", lang))
st.caption(t("Curated reference list of major central government agricultural schemes — always verify "
             "current terms on the official site before applying.", lang))

interests = st.multiselect(t("What are you looking for?", lang), all_categories())

schemes = match_schemes(interests)

for s in schemes:
    with st.container(border=True):
        st.markdown(f"### {s.name}")
        st.markdown(f"**{t('Category', lang)}:** {t(s.category, lang)}")
        st.markdown(f"**{t('Benefit', lang)}:** {t(s.benefit, lang)}")
        st.markdown(f"**{t('Who can apply', lang)}:** {t(s.eligibility_summary, lang)}")
        if s.official_site:
            st.caption(f"🔗 {s.official_site}")
