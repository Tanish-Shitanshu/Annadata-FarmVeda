import streamlit as st

from core import coop, market
from core.i18n import t
from core.safe import md_escape
from core.state import current_account, init_session

lang = init_session()
account = current_account()

st.title("🛒 " + t("Marketplace — buy directly from farmers", lang))
st.caption(t("Fresh produce straight from the farmer. FarmVeda does not handle money: you pay the farmer directly "
             "(cash/UPI) when you collect or receive your order. Prices are set by the farmers.", lang))

st.session_state.setdefault("cart", {})
st.session_state.setdefault("shop_view", None)
st.session_state.setdefault("coop_view", None)
st.session_state.setdefault("last_orders", None)


# ── Cart helpers ────────────────────────────────────────────────────────────
def add_to_cart(listing_id: int, qty_key: str) -> None:
    qty = st.session_state.get(qty_key, 0)
    cart = st.session_state.cart
    cart[listing_id] = round(cart.get(listing_id, 0) + float(qty), 2)


def remove_from_cart(listing_id: int) -> None:
    st.session_state.cart.pop(listing_id, None)


def open_shop(farmer_id: int) -> None:
    st.session_state.shop_view = farmer_id


def close_shop() -> None:
    st.session_state.shop_view = None


def open_coop(coop_id: int) -> None:
    st.session_state.coop_view = coop_id


def close_coop() -> None:
    st.session_state.coop_view = None


def stars(rating, count) -> str:
    if not count:
        return t("No reviews yet", lang)
    return f"{'★' * round(rating)}{'☆' * (5 - round(rating))} {rating:.1f} ({count})"


FULFILMENT_TEXT = {"pickup": "Pickup only", "delivery": "Delivery only", "both": "Pickup or delivery"}


def render_listing(row, prefix: str) -> None:
    with st.container(border=True):
        badges = []
        if row["organic"]:
            badges.append("🌿 " + t("Organic", lang))
        if row["coop_name"]:
            badges.append("🤝 " + md_escape(row["coop_name"]))
        st.markdown(f"### {md_escape(row['title'])}")
        st.markdown(f"**₹{row['price_per_unit']:g} / {row['unit']}**  ·  {row['quantity_available']:g} {row['unit']} {t('available', lang)}")
        if badges:
            st.caption("  ·  ".join(badges))
        st.caption(f"{md_escape(row['farmer_name'])}, {md_escape(row['village'] or '')} {md_escape(row['state'] or '')}  ·  "
                   f"{stars(row['farmer_rating'], row['farmer_review_count'])}")
        if row["description"]:
            st.caption(md_escape(row["description"]))
        extra = [t(FULFILMENT_TEXT[row["fulfilment"]], lang)]
        if row["harvest_date"]:
            extra.append(t("Harvested", lang) + f" {md_escape(row['harvest_date'])}")
        st.caption(" · ".join(extra))

        qty_key = f"{prefix}_qty_{row['id']}"
        step = 1.0 if row["unit"] in ("dozen", "piece") else 0.5
        low = min(step, row["quantity_available"])
        c1, c2, c3 = st.columns([2, 2, 2])
        c1.number_input(t("Quantity", lang), min_value=low, max_value=float(row["quantity_available"]),
                        value=low, step=step, key=qty_key, label_visibility="collapsed")
        c2.button("➕ " + t("Add to cart", lang), key=f"{prefix}_add_{row['id']}", on_click=add_to_cart,
                  args=(row["id"], qty_key), type="primary")
        c3.button(t("Farmer's shop", lang), key=f"{prefix}_shop_{row['id']}", on_click=open_shop, args=(row["farmer_id"],))


# Shown above the tabs: after a rerun Streamlit returns to the first tab, so a message inside the Cart tab would be missed.
if st.session_state.last_orders:
    st.success("✅ " + t(f"Order placed ({len(st.session_state.last_orders)} order(s)). Track it in My Orders.", lang))
    st.session_state.last_orders = None

cart_count = len(st.session_state.cart)
# A radio (not st.tabs): its choice lives in session_state, so clicking a button inside a section never
# bounces the visitor back to the first tab.
SECTION_LABELS = {"browse": t("Browse", lang), "coops": t("Cooperatives", lang),
                  "cart": "🧺 " + t("Cart", lang) + f" ({cart_count})"}
section = st.radio("section", list(SECTION_LABELS), format_func=SECTION_LABELS.get, horizontal=True,
                   key="market_section", label_visibility="collapsed")

# ── Browse ──────────────────────────────────────────────────────────────────
if section == "browse":
    shop_id = st.session_state.shop_view
    if shop_id is not None:
        profile = market.farmer_public_profile(shop_id)
        st.button("← " + t("Back to all produce", lang), on_click=close_shop, key="back_from_shop")
        if profile is None:
            st.warning(t("That shop no longer exists.", lang))
        else:
            st.subheader(f"🧑‍🌾 {md_escape(profile['name'])}")
            st.caption(f"{md_escape(profile['village'] or '')} {md_escape(profile['state'] or '')}  ·  "
                       f"{stars(profile['rating'], profile['review_count'])}")
            if profile["cooperatives"]:
                st.caption("🤝 " + ", ".join(md_escape(c["name"]) for c in profile["cooperatives"]))
            for rev in profile["reviews"]:
                st.markdown(f"> {'★' * rev['rating']} — {md_escape(rev['comment'] or '')} _({md_escape(rev['buyer'])}, {rev['date']})_")
            rows = market.list_listings(farmer_id=shop_id)
            if not rows:
                st.info(t("Nothing in stock right now.", lang))
            for i in range(0, len(rows), 2):
                cols = st.columns(2)
                for col, row in zip(cols, rows[i:i + 2]):
                    with col:
                        render_listing(row, "shop")
    else:
        f1, f2, f3, f4 = st.columns([3, 2, 2, 2])
        search = f1.text_input(t("Search", lang), placeholder=t("e.g. tomato, wheat, honey", lang))
        category = f2.selectbox(t("Category", lang), [""] + market.CATEGORIES,
                                format_func=lambda c: t("All", lang) if c == "" else t(c, lang))
        state = f3.selectbox(t("State", lang), [""] + market.listing_states(),
                             format_func=lambda s: t("All", lang) if s == "" else s)
        sort = f4.selectbox(t("Sort by", lang), list(market.SORTS),
                            format_func=lambda s: {"newest": t("Newest", lang), "price_asc": t("Price: low to high", lang),
                                                   "price_desc": t("Price: high to low", lang)}[s])
        rows = market.list_listings(search=search, category=category or None, state=state or None, sort=sort)
        if not rows:
            st.info(t("No produce matches yet. Try clearing the filters — farmers add listings from My Shop.", lang))
        for i in range(0, len(rows), 2):
            cols = st.columns(2)
            for col, row in zip(cols, rows[i:i + 2]):
                with col:
                    render_listing(row, "browse")

# ── Cooperatives ────────────────────────────────────────────────────────────
if section == "coops":
    coop_id = st.session_state.coop_view
    if coop_id is None:
        coops = coop.list_coops()
        if not coops:
            st.info(t("No cooperatives yet. Farmers can form one from the Cooperatives page.", lang))
        for c in coops:
            with st.container(border=True):
                st.markdown(f"### 🤝 {md_escape(c['name'])}")
                st.caption(f"{md_escape(c['district'] or '')} {md_escape(c['state'] or '')}  ·  "
                           f"{c['member_count']} {t('farmers', lang)}  ·  {c['active_listings']} {t('products in stock', lang)}")
                if c["description"]:
                    st.caption(md_escape(c["description"]))
                st.button(t("See pooled stock", lang), key=f"opencoop_{c['id']}", on_click=open_coop, args=(c["id"],))
    else:
        info = coop.get_coop(coop_id)
        st.button("← " + t("All cooperatives", lang), on_click=close_coop, key="back_from_coop")
        if info is None:
            st.warning(t("That cooperative no longer exists.", lang))
        else:
            st.subheader(f"🤝 {md_escape(info['name'])}")
            st.caption(f"{info['member_count']} {t('farmers', lang)}. " +
                       t("Stock from all members is pooled, so you can order more than one farmer has. "
                         "Each farmer confirms their own part of your order.", lang))
            pooled = coop.pooled_stock(coop_id)
            if not pooled:
                st.info(t("No stock listed right now.", lang))
            for p in pooled:
                with st.container(border=True):
                    price = f"₹{p.min_price:g}" if p.min_price == p.max_price else f"₹{p.min_price:g}–{p.max_price:g}"
                    st.markdown(f"**{md_escape(p.title)}** — {p.total_quantity:g} {p.unit} {t('from', lang)} {p.farmers} "
                                f"{t('farmer(s)', lang)} · {price} / {p.unit}")
                    qty_key = f"pool_qty_{p.key}"
                    c1, c2 = st.columns([2, 2])
                    c1.number_input(t("Quantity", lang), min_value=0.5, max_value=float(p.total_quantity),
                                    value=min(1.0, float(p.total_quantity)), step=0.5, key=qty_key,
                                    label_visibility="collapsed")
                    if account is not None and account.role == "consumer":
                        with c2.popover(t("Bulk order", lang)):
                            fulfilment = st.radio(t("How do you want it?", lang), ["pickup", "delivery"],
                                                  format_func=lambda f: t("Pickup" if f == "pickup" else "Delivery", lang),
                                                  key=f"pool_ful_{p.key}", horizontal=True)
                            address = st.text_area(t("Delivery address", lang), key=f"pool_addr_{p.key}")
                            phone = st.text_input(t("Phone", lang), key=f"pool_phone_{p.key}")
                            note = st.text_input(t("Note for the farmers (optional)", lang), key=f"pool_note_{p.key}")
                            if st.button(t("Place bulk order", lang), key=f"pool_go_{p.key}", type="primary"):
                                try:
                                    ids = coop.bulk_order(account.id, coop_id, p.key, st.session_state[qty_key],
                                                          fulfilment, address, phone, note)
                                    st.session_state.last_orders = ids
                                    st.success(t(f"Order placed with {len(ids)} farmer(s). Track it in My Orders.", lang))
                                except market.MarketError as exc:
                                    st.error(t(str(exc), lang))
                    else:
                        c2.caption(t("Sign in with a consumer account to order.", lang))

# ── Cart ────────────────────────────────────────────────────────────────────
if section == "cart":
    if not st.session_state.cart:
        st.info(t("Your cart is empty.", lang))
    else:
        lines, problems = market.price_cart(st.session_state.cart)
        by_farmer: dict[int, list] = {}
        for line in lines:
            by_farmer.setdefault(line.farmer_id, []).append(line)
        grand_total = 0.0
        for farmer_lines in by_farmer.values():
            st.markdown(f"**{t('From', lang)} {md_escape(farmer_lines[0].farmer_name)}**")
            for line in farmer_lines:
                c1, c2, c3 = st.columns([5, 2, 1])
                c1.markdown(f"{md_escape(line.title)} — {line.quantity:g} {line.unit} × ₹{line.unit_price:g}")
                c2.markdown(f"₹{line.subtotal:,.2f}")
                c3.button("🗑️", key=f"rm_{line.listing_id}", on_click=remove_from_cart, args=(line.listing_id,))
                grand_total += line.subtotal
        for problem in problems:
            st.warning(t(problem, lang))
        st.markdown(f"### {t('Total', lang)}: ₹{grand_total:,.2f}")
        st.caption(t("Pay the farmer directly when you collect or receive your order. FarmVeda does not take payment.", lang))

        if account is None:
            st.info(t("Sign in with a consumer account on the Home page to place this order.", lang))
        elif account.role != "consumer":
            st.info(t("Farmer accounts can't place orders. Sign in with a consumer account.", lang))
        else:
            allowed = [f for f in ("pickup", "delivery")
                       if all(line.fulfilment in (f, "both") for line in lines)]
            if not allowed:
                st.error(t("These items can't be fulfilled the same way. Order them separately.", lang))
            else:
                with st.form("checkout"):
                    fulfilment = st.radio(t("How do you want it?", lang), allowed, horizontal=True, key="co_ful",
                                          format_func=lambda f: t("Pickup" if f == "pickup" else "Delivery", lang))
                    address = st.text_area(t("Delivery address (needed for delivery)", lang), key="co_address")
                    phone = st.text_input(t("Phone number (shared only with the farmers on your order)", lang), key="co_phone")
                    note = st.text_input(t("Note for the farmer (optional)", lang), key="co_note")
                    if st.form_submit_button(t("Place order", lang), type="primary", disabled=bool(problems)):
                        try:
                            ids = market.checkout(account.id, dict(st.session_state.cart), fulfilment,
                                                  address, phone, note)
                            st.session_state.cart = {}
                            st.session_state.last_orders = ids
                            st.rerun()
                        except market.MarketError as exc:
                            st.error(t(str(exc), lang))
