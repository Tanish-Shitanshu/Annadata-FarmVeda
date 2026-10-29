import streamlit as st

from core import coop
from core.i18n import t
from core.market import MarketError
from core.safe import md_escape
from core.state import init_session, require_farmer

lang = init_session()
farmer = require_farmer(lang)
fid = farmer["id"]

st.title("🤝 " + t("Cooperatives", lang))
st.caption(t("Pool your produce with other farmers under one name. Buyers see the group's combined stock and can "
             "place bulk orders; each farmer still confirms their own part. This is an in-app group, not a legally "
             "registered cooperative society or FPO.", lang))

mine = coop.my_coops(fid)
SECTION_LABELS = {"mine": "🤝 " + t("My cooperatives", lang), "new": "➕ " + t("Create or join", lang)}
section = st.radio("section", list(SECTION_LABELS), format_func=SECTION_LABELS.get, horizontal=True,
                   key="coop_section", label_visibility="collapsed")


def attempt(action, *args, success: str = "") -> None:
    try:
        action(*args)
        if success:
            st.success(t(success, lang))
        st.rerun()
    except MarketError as exc:       # CoopError is a MarketError
        st.error(t(str(exc), lang))


if section == "mine":
    if not mine:
        st.info(t("You're not in a cooperative yet. Create one, or join with an invite code from its admin.", lang))
    for c in mine:
        cid = c["id"]
        is_admin = c["my_role"] == "admin"
        with st.expander(f"{md_escape(c['name'])} — {c['member_count']} {t('member(s)', lang)} · {t(c['my_role'], lang)}", expanded=True):
            if c["description"]:
                st.caption(md_escape(c["description"]))
            st.caption(f"{md_escape(c['district'] or '')} {md_escape(c['state'] or '')}")

            if c["member_count"] < coop.FPO_MIN_MEMBERS_HILLY_NE:
                st.caption("🏛️ " + t(f"A formal FPO needs {coop.FPO_MIN_MEMBERS_PLAINS} farmers in the plains "
                                      f"({coop.FPO_MIN_MEMBERS_HILLY_NE} in hilly/North-Eastern areas). See Yojana Sathi.", lang))

            if is_admin:
                info = coop.get_coop(cid, fid)
                st.markdown(f"**{t('Invite code', lang)}:** `{info['invite_code']}`  — {t('share it only with farmers you want in the group', lang)}")
                if st.button(t("Make a new invite code (old one stops working)", lang), key=f"regen_{cid}"):
                    attempt(coop.regenerate_invite, fid, cid, success="New invite code created.")

            st.markdown(f"**{t('Members', lang)}**")
            for m in coop.members(cid):
                row = st.columns([4, 2, 2, 2])
                row[0].markdown(f"{md_escape(m['name'])} — {md_escape(m['village'] or '')} {md_escape(m['state'] or '')}")
                row[1].caption(t(m["role"], lang))
                if is_admin and m["id"] != fid:
                    new_role = "member" if m["role"] == "admin" else "admin"
                    if row[2].button(t("Make " + new_role, lang), key=f"role_{cid}_{m['id']}"):
                        attempt(coop.set_member_role, fid, cid, m["id"], new_role)
                    if row[3].button(t("Remove", lang), key=f"rm_{cid}_{m['id']}"):
                        attempt(coop.remove_member, fid, cid, m["id"])

            pooled = coop.pooled_stock(cid)
            st.markdown(f"**{t('Pooled stock', lang)}**")
            if not pooled:
                st.caption(t("Nothing listed under this cooperative yet. Choose it when you add a listing in My Shop.", lang))
            for p in pooled:
                st.markdown(f"- {md_escape(p.title)}: {p.total_quantity:g} {p.unit} from {p.farmers} farmer(s)")

            if st.button(t("Leave this cooperative", lang), key=f"leave_{cid}"):
                attempt(coop.leave_coop, fid, cid)

if section == "new":
    c1, c2 = st.columns(2)
    with c1:
        st.subheader(t("Create a cooperative", lang))
        with st.form("create_coop", clear_on_submit=True):
            name = st.text_input(t("Name", lang), key="cc_name")
            description = st.text_area(t("What does the group grow or sell?", lang), key="cc_desc")
            state = st.text_input(t("State", lang), value=farmer["state"] or "")
            district = st.text_input(t("District", lang))
            if st.form_submit_button(t("Create", lang), type="primary"):
                attempt(coop.create_coop, fid, name, description, state, district, success="Cooperative created.")
    with c2:
        st.subheader(t("Join with an invite code", lang))
        with st.form("join_coop", clear_on_submit=True):
            code = st.text_input(t("Invite code", lang), key="jc_code")
            if st.form_submit_button(t("Join", lang), type="primary"):
                attempt(coop.join_coop, fid, code, success="You joined the cooperative.")
