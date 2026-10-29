"""Shared Streamlit session helpers: sign-in state, page guards, the sidebar account box.

Identity lives in `st.session_state.account_id` only; the farmer profile is always
looked up from the account, never trusted from a separate session value. A Streamlit
session is per browser tab, so refreshing the page signs you out (there is no
"remember me" yet).
"""

from __future__ import annotations

import streamlit as st

from core import auth, db

_SESSION_KEYS_CLEARED_ON_SIGN_OUT = ("account_id", "role", "farmer_id", "cart", "chat_history", "advisory",
                                     "decided_advice", "scheme_decided")


def init_session() -> str:
    """Ensure defaults exist, the DB is initialised and the sidebar shows who is signed in.
    Returns the active language."""
    db.init_db()
    st.session_state.setdefault("language", "English")
    st.session_state.setdefault("account_id", None)
    st.session_state.setdefault("farmer_id", None)
    st.session_state.setdefault("cart", {})
    _render_account_box()
    return st.session_state.language


def sign_in(account: auth.Account) -> None:
    for key in _SESSION_KEYS_CLEARED_ON_SIGN_OUT:
        st.session_state.pop(key, None)
    st.session_state.account_id = account.id
    st.session_state.role = account.role
    st.session_state.cart = {}
    farmer = db.get_farmer_by_account(account.id) if account.role == "farmer" else None
    st.session_state.farmer_id = farmer["id"] if farmer else None


def sign_out() -> None:
    for key in _SESSION_KEYS_CLEARED_ON_SIGN_OUT:
        st.session_state.pop(key, None)
    st.session_state.account_id = None
    st.session_state.farmer_id = None
    st.session_state.cart = {}


def current_account() -> auth.Account | None:
    account_id = st.session_state.get("account_id")
    return auth.get_account(account_id) if account_id else None


def _render_account_box() -> None:
    account = current_account()
    with st.sidebar:
        if account is None:
            st.caption("Not signed in — sign in on the Home page to use your farm or orders.")
        else:
            icon = "🧑‍🌾" if account.role == "farmer" else "🛍️"
            st.markdown(f"{icon} **{_plain(account.full_name)}**  \n_{account.role} account_")
            st.button("Sign out", key="sidebar_sign_out", on_click=sign_out)


def _plain(text: str) -> str:
    from core.safe import md_escape
    return md_escape(text)


def require_login(lang: str) -> auth.Account:
    from core.i18n import t

    account = current_account()
    if account is None:
        st.warning(t("Please sign in on the Home page first.", lang))
        st.stop()
    return account


def require_farmer(lang: str):
    """The signed-in farmer's profile row, or stop the page with a friendly message."""
    from core.i18n import t

    account = require_login(lang)
    if account.role != "farmer":
        st.warning(t("This page is for farmer accounts. You're signed in as a consumer.", lang))
        st.stop()
    farmer = db.get_farmer_by_account(account.id)
    if farmer is None:
        st.warning(t("Your farmer profile couldn't be found. Please contact support.", lang))
        st.stop()
    st.session_state.farmer_id = farmer["id"]
    return farmer


def require_consumer(lang: str) -> auth.Account:
    from core.i18n import t

    account = require_login(lang)
    if account.role != "consumer":
        st.warning(t("This page is for consumer accounts. Farmers manage orders in My Shop.", lang))
        st.stop()
    return account
