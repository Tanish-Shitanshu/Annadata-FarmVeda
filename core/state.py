"""Shared Streamlit session-state helpers, so every page (not just app.py)
works correctly even if a user lands directly on a sub-page."""

from __future__ import annotations

import streamlit as st

from core import db


def init_session() -> str:
    """Ensure session defaults exist and the DB is initialized. Returns the active language."""
    db.init_db()
    if "language" not in st.session_state:
        st.session_state.language = "English"
    if "farmer_id" not in st.session_state:
        st.session_state.farmer_id = None
    return st.session_state.language


def require_farmer(lang: str):
    """Returns the active farmer row, or stops page execution with a friendly message."""
    from core.i18n import t

    farmer_id = st.session_state.get("farmer_id")
    if not farmer_id:
        st.warning(t("Create or select a farmer profile on the Home page first.", lang))
        st.stop()
    farmer = db.get_farmer(farmer_id)
    if farmer is None:
        st.warning(t("Selected profile not found — please pick one again on the Home page.", lang))
        st.stop()
    return farmer
