from io import BytesIO

import pytest
from google import genai
from PIL import Image, UnidentifiedImageError

from conftest import forecast_payload
from core import chat
from core.chat import FarmContext, build_system_prompt, candidate_models, summarize_forecast
from core.health_scanner import analyze_image
from core.weather import Location, get_forecast


# ── Prompt & model selection ────────────────────────────────────────────────

def test_candidate_models_order_and_dedup(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert candidate_models() == list(chat.DEFAULT_MODELS)
    monkeypatch.setenv("GEMINI_MODEL", "my-model")
    assert candidate_models() == ["my-model", *chat.DEFAULT_MODELS]
    monkeypatch.setenv("GEMINI_MODEL", chat.DEFAULT_MODELS[1])
    assert candidate_models()[0] == chat.DEFAULT_MODELS[1] and len(set(candidate_models())) == len(candidate_models())


def test_prompt_is_grounded_in_the_farm_and_language():
    ctx = FarmContext(state="Punjab", village="Khanna", soil_type="Alluvial", land_size_acres=4.5,
                      recent_crops=["Wheat", "Rice (Paddy)"], weather_summary="Next 7 days: hot.")
    p = build_system_prompt(ctx, "Hindi")
    for expected in ("Punjab", "Khanna", "Alluvial", "4.5 acres", "Wheat", "Next 7 days: hot.", "Respond in Hindi"):
        assert expected in p


def test_prompt_has_no_language_line_for_english_and_no_name_field():
    p = build_system_prompt(FarmContext(state="Punjab"), "English")
    assert "Respond in" not in p
    assert "name" not in FarmContext.__dataclass_fields__


def test_prompt_without_context_is_just_the_base():
    assert build_system_prompt() == chat.BASE_PROMPT


def test_summarize_forecast(net):
    net.forecast = forecast_payload(tmax=36, tmin=24, rain=1)
    s = summarize_forecast(get_forecast(Location("Jaipur", "India", 1, 2, admin1="Rajasthan")))
    assert "Jaipur" in s and "24-36°C" in s and "sowing" in s and "irrigation" in s


# ── ask(): model fallback with a fake Gemini client ─────────────────────────

class FakeClient:
    """Scripted per-model behaviour: value is a reply string or an Exception to raise."""
    script: dict = {}
    seen: list = []

    def __init__(self, api_key=None):
        self.chats = self

    def create(self, model, config, history):
        FakeClient.seen.append({"model": model, "system": config.system_instruction, "history": history})
        outcome = FakeClient.script[model]

        class _Chat:
            def send_message(self, q):
                if isinstance(outcome, Exception):
                    raise outcome
                return type("R", (), {"text": outcome})()
        return _Chat()


@pytest.fixture
def fake_gemini(monkeypatch):
    FakeClient.script, FakeClient.seen = {}, []
    monkeypatch.setattr(genai, "Client", FakeClient)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    return FakeClient


def test_ask_without_key_explains_instead_of_crashing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert "GEMINI_API_KEY" in chat.ask("hi") and not chat.is_available()


def test_ask_uses_first_model_when_it_works(fake_gemini):
    fake_gemini.script = {m: f"reply from {m}" for m in chat.DEFAULT_MODELS}
    assert chat.ask("q") == f"reply from {chat.DEFAULT_MODELS[0]}"
    assert len(fake_gemini.seen) == 1


def test_ask_falls_through_when_a_model_is_retired(fake_gemini):
    a, b = chat.DEFAULT_MODELS
    fake_gemini.script = {a: RuntimeError("404 NOT_FOUND: model is no longer available"), b: "from b"}
    assert chat.ask("q") == "from b"
    assert [s["model"] for s in fake_gemini.seen] == [a, b]


def test_ask_does_not_hide_quota_or_key_errors_behind_fallback(fake_gemini):
    a, b = chat.DEFAULT_MODELS
    fake_gemini.script = {a: RuntimeError("429 RESOURCE_EXHAUSTED quota"), b: "from b"}
    out = chat.ask("q")
    assert "429" in out and "couldn't reach" in out and len(fake_gemini.seen) == 1


def test_ask_reports_all_tried_models_when_none_exist(fake_gemini):
    fake_gemini.script = {m: RuntimeError("404 not found") for m in chat.DEFAULT_MODELS}
    out = chat.ask("q")
    assert all(m in out for m in chat.DEFAULT_MODELS) and "GEMINI_MODEL" in out


def test_ask_sends_grounded_prompt_and_history(fake_gemini):
    fake_gemini.script = {chat.DEFAULT_MODELS[0]: "ok"}
    history = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "namaste"}]
    chat.ask("q", history, context=FarmContext(state="Punjab"), language="Hindi")
    call = fake_gemini.seen[0]
    assert "Punjab" in call["system"] and "Respond in Hindi" in call["system"]
    assert [c.role for c in call["history"]] == ["user", "model"]


def test_empty_model_text_is_handled(fake_gemini):
    fake_gemini.script = {chat.DEFAULT_MODELS[0]: None}
    assert "empty" in chat.ask("q")


# ── Health scanner on synthetic images ──────────────────────────────────────

def png(color):
    buf = BytesIO()
    Image.new("RGB", (64, 64), color).save(buf, "PNG")
    return buf.getvalue()


def test_scanner_distinguishes_images():
    assert analyze_image(png((40, 160, 50))).category == "Healthy"
    assert analyze_image(png((200, 190, 40))).category == "Possible Nutrient Deficiency"
    assert analyze_image(png((20, 20, 20))).category == "Possible Fungal or Pest Damage"
    assert analyze_image(png((255, 255, 255))).category == "Inconclusive"


def test_scanner_rejects_non_images():
    with pytest.raises(UnidentifiedImageError):
        analyze_image(b"not an image")
