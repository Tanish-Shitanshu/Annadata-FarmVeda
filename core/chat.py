"""Fasal Guru - AI chat assistant backed by Google Gemini.

Requires GEMINI_API_KEY to be set (see .env.example). Without a key, the
chat page still loads and explains clearly that AI chat needs a key,
rather than crashing or silently pretending to answer.

Two things make the answers more than generic chatbot output:
  * the system prompt is grounded in the farmer's profile (soil, land size,
    state, recent crops), and optionally the live forecast and risk summary;
  * the reply language follows the farmer's chosen language.
The farmer's name is never sent to the model.

Model names change often. The model comes from GEMINI_MODEL if set, then a
short fallback chain; a "model not found / retired" error moves on to the next
name, any other error is reported as-is.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_MODELS = ("gemini-3.6-flash", "gemini-2.5-flash")

BASE_PROMPT = (
    "You are Fasal Guru, an AI farming guide for Indian farmers, part of the "
    "Annadata FarmVeda platform. Give practical, step-by-step advice on sowing, "
    "irrigation, pest/disease management, fertilization, and harvest timing. "
    "Keep answers concise, actionable, and appropriate for a smallholder Indian "
    "farming context. When you're not certain, say so and recommend consulting "
    "the local Krishi Vigyan Kendra (agricultural extension office). You give "
    "guidance, not instructions: the farmer decides. Never invent prices, "
    "subsidy amounts or pesticide doses - if you are unsure of a dose, say so "
    "and point to the product label or the KVK."
)

# Kept for backwards compatibility with earlier imports.
SYSTEM_PROMPT = BASE_PROMPT

_MODEL_MISSING_HINTS = ("404", "not_found", "not found", "no longer available",
                        "is not supported", "unsupported model", "deprecated", "decommission")


@dataclass
class FarmContext:
    """What the model may know about the farmer. Deliberately has no name field."""
    state: str = ""
    village: str = ""
    soil_type: str = ""
    land_size_acres: float | None = None
    recent_crops: list[str] = field(default_factory=list)
    weather_summary: str = ""


def summarize_forecast(forecast) -> str:
    """One compact paragraph of the live forecast and rule-based verdicts, for the model."""
    from core.risk_yield import assess_climate_risk
    from core.weather import irrigation_advisory, sowing_advisory

    days = forecast.days
    if not days:
        return ""
    lo = min(d.temp_min_c for d in days)
    hi = max(d.temp_max_c for d in days)
    rain = sum(d.precipitation_mm for d in days)
    risk = assess_climate_risk(forecast)
    return (f"Next {len(days)} days near {forecast.location.label}: {lo:.0f}-{hi:.0f}°C, "
            f"{rain:.0f}mm total rain. Weather-rule verdicts: sowing '{sowing_advisory(forecast)['verdict']}', "
            f"irrigation '{irrigation_advisory(forecast)['verdict']}', climate risk {risk.level}.")


def build_system_prompt(context: FarmContext | None = None, language: str = "English") -> str:
    parts = [BASE_PROMPT]
    if context is not None:
        facts = []
        if context.state:
            facts.append(f"State: {context.state}")
        if context.village:
            facts.append(f"Village/area: {context.village}")
        if context.soil_type:
            facts.append(f"Soil type: {context.soil_type}")
        if context.land_size_acres:
            facts.append(f"Land: {context.land_size_acres:g} acres")
        if context.recent_crops:
            facts.append("Recent crops: " + ", ".join(context.recent_crops))
        if facts:
            parts.append("About this farmer (use it when relevant, do not repeat it back): "
                         + "; ".join(facts) + ".")
        if context.weather_summary:
            parts.append("Current local weather outlook: " + context.weather_summary)
    if language and language != "English":
        parts.append(f"Respond in {language}, in simple everyday words.")
    return "\n\n".join(parts)


def candidate_models() -> list[str]:
    """GEMINI_MODEL first (if set), then the defaults, without duplicates."""
    models: list[str] = []
    configured = os.environ.get("GEMINI_MODEL", "").strip()
    for name in ([configured] if configured else []) + list(DEFAULT_MODELS):
        if name and name not in models:
            models.append(name)
    return models


def is_available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def _looks_like_missing_model(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(hint in text for hint in _MODEL_MISSING_HINTS)


def ask(question: str, history: list[dict] | None = None,
        context: FarmContext | None = None, language: str = "English") -> str:
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
    except ImportError:
        return "Fasal Guru needs the google-genai package: pip install -r requirements.txt"

    system_prompt = build_system_prompt(context, language)
    client = genai.Client(api_key=api_key)
    chat_history = []
    for turn in (history or []):
        role = "user" if turn["role"] == "user" else "model"
        chat_history.append(types.Content(role=role, parts=[types.Part(text=turn["content"])]))

    tried: list[str] = []
    last_error: Exception | None = None
    for model in candidate_models():
        try:
            chat = client.chats.create(
                model=model,
                config=types.GenerateContentConfig(system_instruction=system_prompt),
                history=chat_history,
            )
            response = chat.send_message(question)
            return response.text or "Fasal Guru returned an empty answer. Please rephrase and try again."
        except Exception as exc:  # network, quota, bad key, retired model...
            tried.append(model)
            last_error = exc
            if _looks_like_missing_model(exc):
                continue  # try the next model name
            break

    detail = f"{last_error}"
    if last_error is not None and _looks_like_missing_model(last_error):
        detail += f" (tried: {', '.join(tried)}; set GEMINI_MODEL in .env to a model your key can use)"
    return f"Fasal Guru couldn't reach the AI service right now ({detail}). Please try again shortly."
