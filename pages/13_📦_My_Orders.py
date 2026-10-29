import streamlit as st

from core import market
from core.i18n import t
from core.safe import md_escape
from core.state import init_session, require_consumer

lang = init_session()
account = require_consumer(lang)

st.title("📦 " + t("My Orders", lang))
st.caption(t("Track your orders, message the farmer, and review once it's delivered. You pay the farmer directly when "
             "you collect or receive the order.", lang))

STATUS_TEXT = {"placed": "Waiting for the farmer to confirm", "confirmed": "Confirmed by the farmer",
               "ready": "Ready for pickup/delivery", "delivered": "Delivered", "cancelled": "Cancelled",
               "rejected": "Rejected by the farmer"}
STATUS_ICON = {"placed": "🕒", "confirmed": "✅", "ready": "📦", "delivered": "🎉", "cancelled": "✖️", "rejected": "⛔"}

orders = market.list_orders_for_consumer(account.id)
if not orders:
    st.info(t("No orders yet. Browse the Marketplace to place your first one.", lang))

for o in orders:
    oid = o["id"]
    header = (f"{STATUS_ICON[o['status']]} #{oid} · {md_escape(o['farmer_name'])} · ₹{o['total_amount']:,.2f} · "
              f"{t(STATUS_TEXT[o['status']], lang)}")
    with st.expander(header, expanded=o["status"] in ("placed", "confirmed", "ready")):
        for item in market.order_items(account.id, oid):
            st.markdown(f"- {md_escape(item['title'])} — {item['quantity']:g} {item['unit']} × ₹{item['unit_price']:g}")
        st.markdown(f"**{t('Farmer', lang)}:** {md_escape(o['farmer_name'])}, {md_escape(o['farmer_village'] or '')} {md_escape(o['farmer_state'] or '')}")
        st.markdown(f"**{t('You chose', lang)}:** {t('pickup' if o['fulfilment'] == 'pickup' else 'delivery', lang)}")
        if o["cancel_reason"]:
            st.warning(t("Reason from the farmer:" if o["status"] in ("rejected", "cancelled") else "Note:", lang) + f" {md_escape(o['cancel_reason'])}")
        if o["status"] in ("placed", "confirmed", "ready"):
            st.caption("💵 " + t(f"Pay ₹{o['total_amount']:,.2f} to the farmer when you collect or receive it.", lang))
        if o["paid"]:
            st.caption("✅ " + t("The farmer has recorded your payment.", lang))

        if o["status"] == "placed" and st.button(t("Cancel this order", lang), key=f"cancel_{oid}"):
            try:
                market.update_order_status(account.id, oid, "cancelled", "Cancelled by buyer")
                st.rerun()
            except market.MarketError as exc:
                st.error(t(str(exc), lang))

        st.markdown(f"**{t('Messages', lang)}**")
        for m in market.list_messages(account.id, oid):
            who = t("You", lang) if m["mine"] else md_escape(m["sender_name"])
            st.markdown(f"**{who}:** {md_escape(m['body'])}")
        with st.form(f"msg_{oid}", clear_on_submit=True):
            body = st.text_input(t("Message the farmer", lang), key=f"msg_body_{oid}")
            if st.form_submit_button(t("Send", lang)) and body.strip():
                try:
                    market.post_message(account.id, oid, body)
                    st.rerun()
                except market.MarketError as exc:
                    st.error(t(str(exc), lang))

        if o["status"] == "delivered":
            if o["reviewed"]:
                st.caption("⭐ " + t("Thanks, you've reviewed this order.", lang))
            else:
                with st.form(f"review_{oid}"):
                    rating = st.slider(t("Rating", lang), 1, 5, 5, key=f"rate_{oid}")
                    comment = st.text_input(t("How was it? (optional)", lang), key=f"rev_{oid}")
                    if st.form_submit_button(t("Submit review", lang), type="primary"):
                        try:
                            market.submit_review(account.id, oid, rating, comment)
                            st.rerun()
                        except market.MarketError as exc:
                            st.error(t(str(exc), lang))
