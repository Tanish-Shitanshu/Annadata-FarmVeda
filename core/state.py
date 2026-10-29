"""Shared Streamlit session helpers: sign-in state, page guards, the sidebar account box.

Identity lives in `st.session_state.account_id` only; the farmer profile is always
looked up from the account, never trusted from a separate session value.

A Streamlit session is per browser tab, so to survive a page refresh the signed-in browser also
carries a random session token in the URL (`?s=...`). Only its hash is stored server-side; it
expires after `auth.SESSION_HOURS`, and is revoked on sign-out and on password change.
"""

from __future__ import annotations

import streamlit as st

from core import auth, db

_SESSION_KEYS_CLEARED_ON_SIGN_OUT = ("account_id", "role", "farmer_id", "cart", "chat_history", "advisory",
                                     "decided_advice", "scheme_decided", "session_token", "last_orders",
                                     "shop_view", "coop_view", "market_section", "shop_section", "coop_section")
TOKEN_PARAM = "s"


def init_session(is_home: bool = False) -> str:
    """Ensure defaults exist, the DB is initialised, a refresh-survivable login is restored, and the
    sidebar shows who is signed in. Returns the active language."""
    db.init_db()
    st.session_state.setdefault("language", "English")
    st.session_state.setdefault("account_id", None)
    st.session_state.setdefault("farmer_id", None)
    st.session_state.setdefault("cart", {})
    _restore_or_refresh_token()
    _render_account_box()
    if not is_home:
        try:
            st.page_link("app.py", label="Back to Home", icon="🏠")
        except st.errors.StreamlitPageNotFoundError:
            pass            # a page run on its own (as in tests) has no Home to link to
    return st.session_state.language


def _restore_or_refresh_token() -> None:
    """Signed out + a valid token in the URL (a page refresh) -> sign back in. Signed in -> keep the
    token in the URL, since Streamlit drops query parameters when you switch pages."""
    token = st.query_params.get(TOKEN_PARAM)
    if st.session_state.account_id is None:
        if token:
            account = auth.resolve_session(token)
            if account is None:
                st.query_params.pop(TOKEN_PARAM, None)           # stale or forged: forget it
            else:
                _set_identity(account)
                st.session_state.session_token = token
        return
    own = st.session_state.get("session_token")
    if own and token != own:
        st.query_params[TOKEN_PARAM] = own


def _set_identity(account: auth.Account) -> None:
    st.session_state.account_id = account.id
    st.session_state.role = account.role
    farmer = db.get_farmer_by_account(account.id) if account.role == "farmer" else None
    st.session_state.farmer_id = farmer["id"] if farmer else None


def sign_in(account: auth.Account) -> None:
    # A cart built while browsing signed-out follows a consumer into their account (sign-out always
    # empties it, so it can never carry from one person to another).
    anonymous_cart = st.session_state.get("cart") if st.session_state.get("account_id") is None else None
    for key in _SESSION_KEYS_CLEARED_ON_SIGN_OUT:
        st.session_state.pop(key, None)
    _set_identity(account)
    st.session_state.cart = dict(anonymous_cart) if (anonymous_cart and account.role == "consumer") else {}
    token = auth.create_session(account.id)
    st.session_state.session_token = token
    st.query_params[TOKEN_PARAM] = token


def sign_out() -> None:
    auth.revoke_session(st.session_state.get("session_token"))
    for key in _SESSION_KEYS_CLEARED_ON_SIGN_OUT:
        st.session_state.pop(key, None)
    st.session_state.account_id = None
    st.session_state.farmer_id = None
    st.session_state.cart = {}
    st.query_params.pop(TOKEN_PARAM, None)
    st.session_state["_go_home"] = True      # handled on the rerun: signing out lands on the Home page


def current_account() -> auth.Account | None:
    account_id = st.session_state.get("account_id")
    return auth.get_account(account_id) if account_id else None


def _render_account_box() -> None:
    if st.session_state.pop("_go_home", False):
        try:
            st.switch_page("app.py")
        except st.errors.StreamlitAPIException:
            pass                              # already on Home (or running outside a multipage app)
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
