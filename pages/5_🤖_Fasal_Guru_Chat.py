import streamlit as st

from core.chat import ask, is_available
from core.i18n import t
from core.state import init_session, require_farmer

lang = init_session()
farmer = require_farmer(lang)

st.title("🤖 " + t("Fasal Guru — AI Farming Guide", lang))
st.caption(t("Step-by-step guidance through the crop lifecycle, powered by Gemini.", lang))

if not is_available():
    st.warning(t("AI chat needs a GEMINI_API_KEY in your .env file to work. "
                  "See .env.example for setup — it's free at aistudio.google.com/apikey.", lang))

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for turn in st.session_state.chat_history:
    with st.chat_message(turn["role"]):
        st.write(turn["content"])

question = st.chat_input(t("Ask about sowing, pests, irrigation, fertilizer...", lang))
if question:
    st.session_state.chat_history.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner(t("Thinking...", lang)):
            reply = ask(question, st.session_state.chat_history[:-1])
        st.write(reply)
    st.session_state.chat_history.append({"role": "assistant", "content": reply})
