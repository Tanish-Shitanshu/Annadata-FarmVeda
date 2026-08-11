"""Fasal Guru - AI chat assistant backed by Google Gemini.

Requires GEMINI_API_KEY to be set (see .env.example). Without a key, the
chat page still loads and explains clearly that AI chat needs a key,
rather than crashing or silently pretending to answer.
"""

from __future__ import annotations

import os

SYSTEM_PROMPT = (
    "You are Fasal Guru, an AI farming guide for Indian farmers, part of the "
    "Annadata FarmVeda platform. Give practical, step-by-step advice on sowing, "
    "irrigation, pest/disease management, fertilization, and harvest timing. "
    "Keep answers concise, actionable, and appropriate for a smallholder Indian "
    "farming context. When you're not certain, say so and recommend consulting "
    "the local Krishi Vigyan Kendra (agricultural extension office)."
)


def is_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def ask(question: str, history: list[dict] | None = None) -> str:
    """Ask Fasal Guru a question. Returns the reply, or an explanatory
    message if no API key is configured or the call fails."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return (
            "Fasal Guru's AI chat isn't configured yet - add a GEMINI_API_KEY "
            "to your .env file to enable it (free key: "
            "https://aistudio.google.com/apikey). In the meantime, try the "
            "Crop Recommendation, Weather Advisory, or Crop Health Scanner "
            "pages, which work without any API key."
        )

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        chat_history = []
        for turn in (history or []):
            role = "user" if turn["role"] == "user" else "model"
            chat_history.append(types.Content(role=role, parts=[types.Part(text=turn["content"])]))

        chat = client.chats.create(
            model="gemini-2.0-flash",
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
            history=chat_history,
        )
        response = chat.send_message(question)
        return response.text
    except Exception as exc:
        return f"Fasal Guru couldn't reach the AI service right now ({exc}). Please try again shortly."
