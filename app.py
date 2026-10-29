import streamlit as st

from core import auth, coop, db, eligibility, market
from core.i18n import language_selector_options, t
from core.safe import md_escape
from core.state import current_account, init_session, sign_in

st.set_page_config(page_title="Annadata FarmVeda", page_icon="🌾", layout="wide")
init_session()

with st.sidebar:
    st.session_state.language = st.selectbox(
        "🌐 " + t("Select Language", st.session_state.language),
        language_selector_options(),
        index=language_selector_options().index(st.session_state.language),
    )
lang = st.session_state.language

st.title("🌾 " + t("Annadata FarmVeda", lang))
st.caption(t("Human-in-the-loop AI farming companion — advises, plans, and connects farmers directly "
             "with buyers. The farmer decides.", lang))

SOIL_TYPES = ["Alluvial", "Black (Regur)", "Red", "Laterite", "Sandy", "Sandy Loam", "Clayey", "Loamy"]


def show_auth_forms() -> None:
    st.info(t("You can browse the Marketplace without an account. Sign in to order, or to use the farm tools.", lang))
    sign_in_tab, create_tab = st.tabs([t("Sign in", lang), t("Create account", lang)])

    with sign_in_tab:
        with st.form("sign_in"):
            email = st.text_input(t("Email", lang), key="si_email")
            password = st.text_input(t("Password", lang), type="password", key="si_password")
            if st.form_submit_button(t("Sign in", lang), type="primary"):
                try:
                    sign_in(auth.login(email, password))
                    st.rerun()
                except auth.AuthError as exc:
                    st.error(t(str(exc), lang))

    with create_tab:
        role_label = st.radio(t("I am a…", lang), [t("Farmer", lang), t("Consumer", lang)], horizontal=True,
                              key="signup_role")
        role = "farmer" if role_label == t("Farmer", lang) else "consumer"
        with st.form("create_account"):
            name = st.text_input(t("Full name", lang), key="su_name")
            email = st.text_input(t("Email", lang), key="signup_email")
            col1, col2 = st.columns(2)
            password = col1.text_input(t("Password (8+ characters)", lang), type="password", key="signup_pw")
            confirm = col2.text_input(t("Confirm password", lang), type="password", key="signup_pw2")
            farm = {}
            if role == "farmer":
                c1, c2 = st.columns(2)
                farm["village"] = c1.text_input(t("Village / Town", lang), key="su_village")
                farm["state"] = c1.text_input(t("State", lang), key="su_state")
                farm["land_size_acres"] = c2.number_input(t("Land size (acres)", lang), min_value=0.0, step=0.5, key="su_land")
                farm["soil_type"] = c2.selectbox(t("Soil type", lang), SOIL_TYPES, key="su_soil")
            if st.form_submit_button(t("Create account", lang), type="primary"):
                if password != confirm:
                    st.error(t("The two passwords don't match.", lang))
                else:
                    try:
                        sign_in(auth.register(email, password, role, name, farm or None, lang))
                        st.rerun()
                    except auth.AuthError as exc:
                        st.error(t(str(exc), lang))
        st.caption(t("There is no email verification or password reset yet, so choose a password you will remember.", lang))


def farmer_dashboard(farmer) -> None:
    due = db.due_soon_count(farmer["id"])
    awaiting = market.count_orders_awaiting_farmer(farmer["id"])
    st.subheader(t(f"Welcome, {farmer['name']}", lang))
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(t("Land Size", lang), f"{(farmer['land_size_acres'] or 0):.1f} acres")
    c2.metric(t("Soil Type", lang), farmer["soil_type"] or "—")
    c3.metric(t("Farm Records", lang), len(db.list_farm_records(farmer["id"])))
    c4.metric(t("Reminders Due Soon", lang), due)
    c5.metric(t("New Orders", lang), awaiting)

    if awaiting:
        st.warning("🛒 " + t(f"{awaiting} new order(s) are waiting for you to confirm — open My Shop.", lang))

    answers = db.get_scheme_profile(farmer["id"])
    if not answers:
        st.info("🏛️ " + t("Answer a few questions in Yojana Sathi to see which government schemes you may qualify for.", lang))
    else:
        results = eligibility.evaluate(farmer["land_size_acres"], farmer["state"], answers,
                                       [r["crop"] for r in db.list_farm_records(farmer["id"])],
                                       [dict(c) for c in coop.my_coops(farmer["id"])])
        decided = db.latest_advice_decisions(farmer["id"], "scheme")
        new_likely = [r for r in results if r.status == eligibility.LIKELY and r.scheme.short_name not in decided]
        if new_likely:
            names = ", ".join(r.scheme.short_name for r in new_likely[:4])
            st.success("🏛️ " + t(f"You may qualify for {len(new_likely)} scheme(s): {names}. Open Yojana Sathi to see what to do.", lang))


def consumer_dashboard(account) -> None:
    st.subheader(t(f"Welcome, {account.full_name}", lang))
    orders = market.list_orders_for_consumer(account.id)
    open_orders = [o for o in orders if o["status"] in ("placed", "confirmed", "ready")]
    c1, c2, c3 = st.columns(3)
    c1.metric(t("Items in cart", lang), len(st.session_state.get("cart", {})))
    c2.metric(t("Open orders", lang), len(open_orders))
    c3.metric(t("Past orders", lang), len(orders) - len(open_orders))
    st.info("🛒 " + t("Browse fresh produce straight from farmers on the Marketplace page, and track what you "
                      "ordered under My Orders.", lang))


account = current_account()
if account is None:
    show_auth_forms()
elif account.role == "farmer":
    farmer_dashboard(db.get_farmer_by_account(account.id))
else:
    consumer_dashboard(account)

st.divider()
st.subheader(t("What you can do", lang))
farmer_features = [
    ("🌱", "Crop Recommendation", "Crops matched to your soil, season and your area's climate history."),
    ("🌦️", "Weather Advisory", "7-day forecast with sowing/irrigation/spray timing and reminders you accept or dismiss."),
    ("⚠️", "Climate Risk & Yield", "Risk for your chosen crop, with yield and value-at-risk estimates."),
    ("🩺", "Crop Health Scanner", "Upload a leaf photo for a visual health check."),
    ("🤖", "Fasal Guru Chat", "Ask farming questions; answers know your farm."),
    ("🏛️", "Yojana Sathi", "See which government schemes you may qualify for, and what to do next."),
    ("🧺", "My Shop", "List your produce, confirm orders and chat with buyers."),
    ("🤝", "Cooperatives", "Pool produce with other farmers and take bulk orders."),
]
consumer_features = [
    ("🛒", "Marketplace", "Buy directly from farmers, or from a cooperative's pooled stock."),
    ("📦", "My Orders", "Track orders, message the farmer and leave a review."),
]
PAGE_FILES = {
    "Crop Recommendation": "pages/1_🌱_Crop_Recommendation.py",
    "Weather Advisory": "pages/2_🌦️_Weather_Advisory.py",
    "Climate Risk & Yield": "pages/3_⚠️_Climate_Risk_and_Yield.py",
    "Crop Health Scanner": "pages/4_🩺_Crop_Health_Scanner.py",
    "Fasal Guru Chat": "pages/5_🤖_Fasal_Guru_Chat.py",
    "Yojana Sathi": "pages/6_🏛️_Yojana_Sathi.py",
    "My Shop": "pages/11_🧺_My_Shop.py",
    "Cooperatives": "pages/12_🤝_Cooperatives.py",
    "Marketplace": "pages/10_🛒_Marketplace.py",
    "My Orders": "pages/13_📦_My_Orders.py",
}

features = consumer_features if (account and account.role == "consumer") else farmer_features
cols = st.columns(4)
for i, (icon, name, desc) in enumerate(features):
    with cols[i % 4]:
        # Streamlit folds long sidebar menus behind "View more", so every feature is also linked here.
        st.page_link(PAGE_FILES[name], label=t(name, lang), icon=icon)
        st.caption(t(desc, lang))

st.divider()
st.caption(t(
    "Not built yet: live mandi prices, online payments, donations, voice assistant, input-store locator, "
    "push/SMS alerts — see 'Coming Soon' for what each needs.", lang))
