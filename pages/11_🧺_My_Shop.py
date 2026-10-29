import streamlit as st

from core import coop, market
from core.i18n import t
from core.safe import md_escape
from core.state import init_session, require_farmer

lang = init_session()
farmer = require_farmer(lang)
account_id = st.session_state.account_id

st.title("🧺 " + t("My Shop", lang))
st.caption(t("List what you grow, set your own price, and confirm each order yourself. Buyers pay you directly "
             "when they collect or receive their order; FarmVeda takes no cut and handles no money.", lang))

my_coops = coop.my_coops(farmer["id"])
awaiting = market.count_orders_awaiting_farmer(farmer["id"])
SECTION_LABELS = {"orders": "📥 " + t("Orders", lang) + (f" ({awaiting} new)" if awaiting else ""),
                  "listings": "📦 " + t("My listings", lang), "add": "➕ " + t("Add a listing", lang)}
section = st.radio("section", list(SECTION_LABELS), format_func=SECTION_LABELS.get, horizontal=True,
                   key="shop_section", label_visibility="collapsed")

STATUS_TEXT = {"placed": "New - waiting for you", "confirmed": "Confirmed", "ready": "Ready for pickup/delivery",
               "delivered": "Delivered", "cancelled": "Cancelled", "rejected": "Rejected"}


def move(order_id: int, new_status: str, reason: str = "") -> None:
    try:
        market.update_order_status(account_id, order_id, new_status, reason)
        st.rerun()
    except market.MarketError as exc:
        st.error(t(str(exc), lang))


# ── Orders ──────────────────────────────────────────────────────────────────
if section == "orders":
    orders = market.list_orders_for_farmer(farmer["id"])
    if not orders:
        st.info(t("No orders yet. Once you list produce, buyers' orders appear here.", lang))
    for o in orders:
        oid = o["id"]
        header = f"#{oid} · {md_escape(o['consumer_name'])} · ₹{o['total_amount']:,.2f} · {t(STATUS_TEXT[o['status']], lang)}"
        with st.expander(header, expanded=o["status"] in ("placed", "confirmed", "ready")):
            for item in market.order_items(account_id, oid):
                st.markdown(f"- {md_escape(item['title'])} — {item['quantity']:g} {item['unit']} × ₹{item['unit_price']:g}")
            st.markdown(f"**{t('Buyer wants', lang)}:** {t('pickup' if o['fulfilment'] == 'pickup' else 'delivery', lang)}")
            st.markdown(f"**{t('Phone', lang)}:** {md_escape(o['contact_phone'])}")
            if o["delivery_address"]:
                st.markdown(f"**{t('Address', lang)}:** {md_escape(o['delivery_address'])}")
            if o["note"]:
                st.markdown(f"**{t('Note', lang)}:** {md_escape(o['note'])}")
            if o["cancel_reason"]:
                st.caption(t("Reason given:", lang) + f" {md_escape(o['cancel_reason'])}")
            st.caption(("✅ " + t("Payment received", lang)) if o["paid"] else ("💵 " + t("Payment due on pickup/delivery", lang)))

            status = o["status"]
            if status == "placed":
                reason = st.text_input(t("If rejecting, tell the buyer why", lang), key=f"rej_reason_{oid}")
                c1, c2, _ = st.columns([1, 1, 3])
                if c1.button(t("Confirm order", lang), key=f"confirm_{oid}", type="primary"):
                    move(oid, "confirmed")
                if c2.button(t("Reject", lang), key=f"reject_{oid}"):
                    move(oid, "rejected", reason)
            elif status in ("confirmed", "ready"):
                reason = st.text_input(t("If cancelling, tell the buyer why", lang), key=f"can_reason_{oid}")
                c1, c2, c3 = st.columns(3)
                if status == "confirmed" and c1.button(t("Mark ready", lang), key=f"ready_{oid}", type="primary"):
                    move(oid, "ready")
                if c2.button(t("Mark delivered", lang), key=f"deliv_{oid}"):
                    move(oid, "delivered")
                if c3.button(t("Cancel order", lang), key=f"cancel_{oid}"):
                    move(oid, "cancelled", reason)
            if status in ("confirmed", "ready", "delivered") and not o["paid"]:
                if st.button(t("I received the payment", lang), key=f"paid_{oid}"):
                    try:
                        market.mark_paid(account_id, oid)
                        st.rerun()
                    except market.MarketError as exc:
                        st.error(t(str(exc), lang))

            st.markdown(f"**{t('Messages', lang)}**")
            for m in market.list_messages(account_id, oid):
                who = t("You", lang) if m["mine"] else md_escape(m["sender_name"])
                st.markdown(f"**{who}:** {md_escape(m['body'])}")
            with st.form(f"msg_{oid}", clear_on_submit=True):
                body = st.text_input(t("Message the buyer", lang), key=f"msg_body_{oid}")
                if st.form_submit_button(t("Send", lang)) and body.strip():
                    try:
                        market.post_message(account_id, oid, body)
                        st.rerun()
                    except market.MarketError as exc:
                        st.error(t(str(exc), lang))

# ── Listings ────────────────────────────────────────────────────────────────
coop_choices = [None] + [c["id"] for c in my_coops]
coop_names = {c["id"]: c["name"] for c in my_coops}


def coop_label(cid) -> str:
    return t("Not in a cooperative", lang) if cid is None else coop_names[cid]


if section == "listings":
    rows = market.list_listings(farmer_id=farmer["id"], include_unavailable=True)
    if not rows:
        st.info(t("You haven't listed anything yet. Use the 'Add a listing' tab.", lang))
    for row in rows:
        lid = row["id"]
        state_text = "⏸️ " + t("Paused", lang) if row["status"] == "paused" else (
            "⚠️ " + t("Sold out", lang) if row["quantity_available"] <= 0 else "🟢 " + t("Live", lang))
        with st.expander(f"{md_escape(row['title'])} — ₹{row['price_per_unit']:g}/{row['unit']} · "
                         f"{row['quantity_available']:g} {t('left', lang)} · {state_text}"):
            with st.form(f"edit_{lid}"):
                c1, c2, c3 = st.columns(3)
                price = c1.number_input(t("Price per unit (₹)", lang), min_value=0.01, value=float(row["price_per_unit"]), step=1.0, key=f"e_price_{lid}")
                qty = c2.number_input(t("Quantity available", lang), min_value=0.0, value=float(row["quantity_available"]), step=1.0, key=f"e_qty_{lid}")
                status = c3.selectbox(t("Status", lang), ["active", "paused"], index=0 if row["status"] == "active" else 1,
                                      format_func=lambda s: t("Live" if s == "active" else "Paused", lang), key=f"e_status_{lid}")
                desc = st.text_area(t("Description", lang), value=row["description"] or "", key=f"e_desc_{lid}")
                c4, c5, c6 = st.columns(3)
                fulfil = c4.selectbox(t("Pickup / delivery", lang), market.FULFILMENT_OPTIONS,
                                      index=market.FULFILMENT_OPTIONS.index(row["fulfilment"]), key=f"e_ful_{lid}")
                organic = c5.checkbox(t("Organic", lang), value=bool(row["organic"]), key=f"e_org_{lid}")
                coop_id = c6.selectbox(t("Cooperative", lang), coop_choices,
                                       index=coop_choices.index(row["coop_id"]) if row["coop_id"] in coop_choices else 0,
                                       format_func=coop_label, key=f"e_coop_{lid}")
                if st.form_submit_button(t("Save changes", lang), type="primary"):
                    try:
                        market.update_listing(farmer["id"], lid, price_per_unit=price, quantity_available=qty,
                                              status=status, description=desc, fulfilment=fulfil,
                                              organic=organic, coop_id=coop_id)
                        st.success(t("Saved.", lang))
                    except market.MarketError as exc:
                        st.error(t(str(exc), lang))

# ── Add listing ─────────────────────────────────────────────────────────────
if section == "add":
    with st.form("new_listing", clear_on_submit=True):
        title = st.text_input(t("Product name", lang), placeholder=t("e.g. Desi tomato", lang), key="nl_title")
        c1, c2, c3, c4 = st.columns(4)
        category = c1.selectbox(t("Category", lang), market.CATEGORIES, format_func=lambda c: t(c, lang), key="nl_category")
        unit = c2.selectbox(t("Unit", lang), market.UNITS, key="nl_unit")
        price = c3.number_input(t("Price per unit (₹)", lang), min_value=0.0, step=1.0, key="nl_price")
        quantity = c4.number_input(t("Quantity available", lang), min_value=0.0, step=1.0, key="nl_qty")
        description = st.text_area(t("Description (variety, how it's grown, packing)", lang), key="nl_desc")
        c5, c6, c7, c8 = st.columns(4)
        fulfilment = c5.selectbox(t("Pickup / delivery", lang), market.FULFILMENT_OPTIONS, index=2,
                                  format_func=lambda f: {"pickup": t("Pickup only", lang), "delivery": t("Delivery only", lang),
                                                         "both": t("Pickup or delivery", lang)}[f])
        organic = c6.checkbox(t("Organic", lang))
        harvest = c7.date_input(t("Harvest date", lang), value=None)
        list_coop = c8.selectbox(t("List under a cooperative", lang), coop_choices, format_func=coop_label)
        if st.form_submit_button(t("Publish listing", lang), type="primary"):
            try:
                market.create_listing(farmer["id"], title, category, unit, price, quantity, fulfilment, description,
                                      organic, harvest.isoformat() if harvest else None, list_coop)
                st.success(t("Your listing is live on the Marketplace.", lang))
            except market.MarketError as exc:
                st.error(t(str(exc), lang))
