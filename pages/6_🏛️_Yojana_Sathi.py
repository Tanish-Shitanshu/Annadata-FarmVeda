import streamlit as st

from core import coop, db, eligibility
from core.eligibility import LIKELY, QUESTIONS, STATUS_LABELS
from core.i18n import t
from core.safe import md_escape
from core.state import init_session, require_farmer

lang = init_session()
farmer = require_farmer(lang)

st.title("🏛️ " + t("Yojana Sathi — Government Scheme Assistant", lang))
st.caption(t("A first check of which central schemes you may qualify for, from your answers below. It is guidance, "
             "not a government decision: rules differ by state and change, so confirm on the official site or with "
             "your agriculture office before applying. Your answers stay on this device's database and are never sent "
             "to the AI chat.", lang))

saved = db.get_scheme_profile(farmer["id"])
UNKNOWN = "—"
NONE_OF_THESE = "__none__"
YES, NO = t("Yes", lang), t("No", lang)

# ── Questions ───────────────────────────────────────────────────────────────
with st.expander(t("Your answers (the more you answer, the better the check)", lang), expanded=not saved):
    with st.form("scheme_answers"):
        entered: dict = {}
        for q in QUESTIONS:
            label = t(q["label"], lang)
            current = saved.get(q["id"])
            if q["kind"] == "choice":
                keys = [UNKNOWN] + list(q["options"])
                choice = st.selectbox(label, keys, index=keys.index(current) if current in keys else 0,
                                      format_func=lambda k, q=q: UNKNOWN if k == UNKNOWN else t(q["options"][k], lang),
                                      key=f"q_{q['id']}")
                entered[q["id"]] = None if choice == UNKNOWN else choice
            elif q["kind"] == "bool":
                options = [UNKNOWN, YES, NO]
                idx = 0 if current is None else (1 if current else 2)
                choice = st.selectbox(label, options, index=idx, key=f"q_{q['id']}", help=t(q.get("help", ""), lang) or None)
                entered[q["id"]] = None if choice == UNKNOWN else choice == YES
            else:
                # "None of these" is an explicit answer; leaving the box empty means "not answered",
                # so an untouched question can never be mistaken for "no exclusions apply".
                default = [NONE_OF_THESE] if current == [] else (current or [])
                picked = st.multiselect(label, [NONE_OF_THESE] + list(q["options"]), default=default,
                                        format_func=lambda k, q=q: t("None of these", lang) if k == NONE_OF_THESE
                                        else t(q["options"][k], lang), key=f"q_{q['id']}")
                real = [k for k in picked if k != NONE_OF_THESE]
                entered[q["id"]] = real if real else ([] if NONE_OF_THESE in picked else None)
        if st.form_submit_button(t("Save my answers", lang), type="primary"):
            db.save_scheme_profile(farmer["id"], eligibility.clean_answers(entered))
            saved = db.get_scheme_profile(farmer["id"])
            st.success(t("Saved.", lang))

# ── Results ─────────────────────────────────────────────────────────────────
coops = [dict(c) for c in coop.my_coops(farmer["id"])]
crops = list(dict.fromkeys(r["crop"] for r in db.list_farm_records(farmer["id"])))
results = eligibility.evaluate(farmer["land_size_acres"], farmer["state"], saved, crops, coops)

if "scheme_decided" not in st.session_state:
    st.session_state.scheme_decided = {}


def _accept(short_name: str, headline: str, title: str, due_iso: str, category: str) -> None:
    db.accept_advice(farmer["id"], "scheme", short_name, headline, "", title, due_iso, category)
    st.session_state.scheme_decided[short_name] = "accepted"


def _dismiss(short_name: str, headline: str) -> None:
    db.dismiss_advice(farmer["id"], "scheme", short_name, headline, "")
    st.session_state.scheme_decided[short_name] = "dismissed"


decided = {**db.latest_advice_decisions(farmer["id"], "scheme"), **st.session_state.scheme_decided}

counts = {s: sum(1 for r in results if r.status == s) for s in STATUS_LABELS}
cols = st.columns(4)
for col, status in zip(cols, (LIKELY, "check", "unlikely", "na")):
    col.metric(t(STATUS_LABELS[status], lang), counts[status])

if not saved:
    st.info(t("Answer the questions above to turn 'Check details' into a clearer result.", lang))

question_labels = {q["id"]: q["label"] for q in QUESTIONS}
ICONS = {"likely": "🟢", "check": "🟡", "unlikely": "⚪", "na": "⚫"}

for r in results:
    s = r.scheme
    with st.expander(f"{ICONS[r.status]} {s.short_name} — {t(r.headline, lang)}", expanded=(r.status == LIKELY)):
        st.markdown(f"**{md_escape(s.name)}**  ·  {t(STATUS_LABELS[r.status], lang)}")
        st.markdown(f"**{t('Benefit', lang)}:** {t(s.benefit, lang)}")
        if r.reasons:
            st.markdown(f"**{t('Why', lang)}**")
            for reason in r.reasons:
                st.markdown(f"- {t(reason, lang)}")
        if r.next_steps:
            st.markdown(f"**{t('What to do', lang)}**")
            for step in r.next_steps:
                st.markdown(f"- {t(step, lang)}")
        if r.missing:
            st.caption("❓ " + t("Answer to sharpen this: ", lang) + "; ".join(t(question_labels[m], lang) for m in r.missing))
        st.markdown(f"**{t('Who can apply', lang)}:** {t(s.eligibility_summary, lang)}")
        if s.how_to_apply:
            st.markdown(f"**{t('How to apply', lang)}:** {t(s.how_to_apply, lang)}")
        if s.documents:
            st.markdown(f"**{t('Documents', lang)}:** " + ", ".join(t(d, lang) for d in s.documents))
        links = f"🔗 {s.official_site}  ·  " if s.official_site else ""
        verified = f"checked {s.verified_on}" if s.verified_on else "not re-checked in 2026"
        st.caption(f"{links}{verified} · {s.source_note}")

        if r.reminder:
            decision = decided.get(s.short_name)
            if decision == "accepted":
                st.success("✅ " + t("Reminder added:", lang) + f" {t(r.reminder.title, lang)}")
            elif decision == "dismissed":
                st.caption("✖️ " + t("You dismissed this suggestion.", lang))
                st.button(t("Remind me anyway", lang), key=f"again_{s.id}", on_click=_accept,
                          args=(s.short_name, r.headline, t(r.reminder.title, lang),
                                r.reminder.due_date.isoformat(), r.reminder.category))
            else:
                st.info("🔔 " + t("Suggested reminder:", lang) + f" **{md_escape(t(r.reminder.title, lang))}** — {r.reminder.due_date:%a %d %b}")
                c1, c2, _ = st.columns([1, 1, 3])
                c1.button(t("Add to reminders", lang), key=f"acc_{s.id}", type="primary", on_click=_accept,
                          args=(s.short_name, r.headline, t(r.reminder.title, lang),
                                r.reminder.due_date.isoformat(), r.reminder.category))
                c2.button(t("Not interested", lang), key=f"dis_{s.id}", on_click=_dismiss, args=(s.short_name, r.headline))
