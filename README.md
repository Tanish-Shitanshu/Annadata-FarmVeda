# 🌾 Annadata FarmVeda

A human-in-the-loop AI farming companion for Indian smallholder farmers. It predicts, advises, and helps plan — crop choice, weather-driven timing, climate risk, and available government support — while final decisions stay with the farmer.

This README is deliberately specific about what's real and what isn't. Every feature below is either genuinely working (real weather data, real translation, real logic against curated reference data) or explicitly marked as a roadmap preview with no functionality behind it yet.

## ✅ Implemented (working, not mocked)

| Feature | What it actually does |
|---|---|
| 🌱 **Smart Crop Recommendation** | Rule-based match of your soil type, season, and *live* temperature/rainfall (via Open-Meteo) against a curated reference table of 20 major Indian crops. |
| 🌦️ **Weather-Based Farming Advice** | Live 7-day forecast (Open-Meteo, no API key needed) with rule-based sowing, irrigation, spraying, and harvest timing guidance. |
| 💧 **Water Management Advisor** | Irrigation timing folded into the Weather Advisory page, driven by the same live forecast. |
| ⚠️ **Climate Risk Prediction** | Heatwave / frost / heavy-rain / drought signals scored from the live forecast. |
| 📉 **Yield Prediction & Loss Prevention Analytics** | Heuristic yield estimate and value-at-risk, derived from climate risk score × a static crop yield/price reference table (clearly labeled as illustrative, not live mandi prices). |
| 🩺 **AI Crop Health Scanner** | Upload a leaf photo — a real HSV color/texture analysis flags likely nutrient deficiency, fungal/pest damage, or water stress, with a treatment recommendation. This is a heuristic, **not** a trained deep-learning disease classifier — see the in-app disclaimer. |
| 🤖 **Fasal Guru (AI Chat)** | Real LLM-backed chat via Google Gemini. Needs your own `GEMINI_API_KEY` (free) — without one, the page explains that clearly instead of faking a response. |
| 🏛️ **Yojana Sathi (Govt. Scheme Assistant)** | Curated reference data on 9 major central government schemes (PM-KISAN, PMFBY, KCC, PM-KUSUM, PMKSY, e-NAM, Soil Health Card, AIF, NFSM) with category-based matching. Static data — always verify current terms on the official site. |
| 📚 **Farmer Learning Hub** | 8 practical guides (crop rotation, IPM, drip irrigation, soil health, post-harvest storage, NPK, climate adaptation, seed treatment). |
| 👤 **Farmer Profile & Farm Records** | Real local SQLite persistence — profile, land/soil details, farm records, and reminders. |
| 🔔 **Smart Notifications** | In-app reminders (irrigation, spraying, fertilizer, harvest) stored in SQLite. Not push/SMS notifications — see roadmap. |
| 🌐 **Regional Language Support** | Live translation (via `deep-translator`) across English, Hindi, Bengali, Telugu, Marathi, Tamil, Gujarati, Kannada, Malayalam, Punjabi, Odia, Assamese, and Urdu — applied to the whole UI, not just a few strings. |

## 🚧 Roadmap (previewed in-app, not functional)

These appear on the "Coming Soon" page as design previews. Nothing here fetches or stores real data yet:

- **📡 Live Kheti Watch** — real-time push alerts (needs an SMS/push delivery backend)
- **💹 Market Price Intelligence** — live mandi price feeds (needs a commodity price API integration, e.g. Agmarknet)
- **🛒 Seedha Bazaar Marketplace** — direct farmer-to-buyer trading (needs listings/payments/logistics infra)
- **📍 Nearby Input Store Locator** — needs a maps/places API integration
- **🎙️ Voice-Based AI Assistant** — needs speech-to-text/text-to-speech infra (Fasal Guru covers the same assistant via text today)

## Tech stack

- **UI:** Streamlit (multi-page app)
- **Weather:** Open-Meteo (forecast + geocoding, free, no key)
- **AI Chat:** Google Gemini via `google-genai`
- **Translation:** `deep-translator`
- **Image analysis:** Pillow + NumPy (HSV heuristic)
- **Storage:** SQLite (local, no cloud dependency)

## Getting started

```bash
pip install -r requirements.txt
cp .env.example .env   # optional: add GEMINI_API_KEY to enable Fasal Guru chat
streamlit run app.py
```

Opens at `http://localhost:8501` by default. No API keys are required for crop recommendation, weather advisory, climate risk/yield, the health scanner, Yojana Sathi, or the learning hub — only the AI chat page needs a (free) Gemini key.

## Project structure

```
app.py                        Home — profile creation/selection, dashboard
core/
  db.py                       SQLite: farmers, farm_records, reminders
  i18n.py                     Live translation (13 languages)
  weather.py                  Open-Meteo integration + advisory rules
  crop_recommender.py         Rule-based crop matching
  risk_yield.py                Climate risk + yield + loss heuristics
  health_scanner.py            Leaf photo HSV heuristic analysis
  chat.py                      Fasal Guru (Gemini-backed)
  schemes.py                   Yojana Sathi scheme matching
  state.py                     Shared Streamlit session helpers
data/
  crop_requirements.csv        20 crops: soil/season/temp/rainfall ranges
  crop_yield_price_reference.csv  Illustrative yield & price reference
  schemes.json                 9 real government scheme summaries
  learning_content.json        8 farming practice guides
pages/                         One file per feature (Streamlit auto-routes these)
```

## Disclaimer

This is a planning and advisory aid, not an agronomic, financial, or medical authority. Crop and risk recommendations are heuristic estimates from published ranges and live weather data — they don't replace a soil test, a visit from your local Krishi Vigyan Kendra, or your own field judgment. Government scheme details change; always confirm current terms on the official scheme website before applying.
