"""Multi-language support for the FarmVeda UI.

Translates UI strings and AI-generated text on the fly using deep-translator
(Google Translate backend, no API key required). Results are cached in-memory
per (text, language) pair so repeated UI renders don't re-hit the network,
and any translation failure falls back to the original English text rather
than breaking the page.
"""

from __future__ import annotations

from functools import lru_cache

from deep_translator import GoogleTranslator

# Official/widely-spoken Indian languages, matching what Indian farmers across
# regions are most likely to actually use.
SUPPORTED_LANGUAGES: dict[str, str] = {
    "English": "en",
    "Hindi": "hi",
    "Bengali": "bn",
    "Telugu": "te",
    "Marathi": "mr",
    "Tamil": "ta",
    "Gujarati": "gu",
    "Kannada": "kn",
    "Malayalam": "ml",
    "Punjabi": "pa",
    "Odia": "or",
    "Assamese": "as",
    "Urdu": "ur",
}


@lru_cache(maxsize=4096)
def _translate_cached(text: str, target_code: str) -> str:
    if target_code == "en" or not text.strip():
        return text
    try:
        return GoogleTranslator(source="en", target=target_code).translate(text)
    except Exception:
        # Network hiccup, unsupported string, or rate limit - never break the page.
        return text


def t(text: str, language: str) -> str:
    """Translate `text` (written in English) into `language`."""
    code = SUPPORTED_LANGUAGES.get(language, "en")
    return _translate_cached(text, code)


def language_selector_options() -> list[str]:
    return list(SUPPORTED_LANGUAGES.keys())
