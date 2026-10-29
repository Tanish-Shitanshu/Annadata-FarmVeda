# 🌾 Annadata FarmVeda

A human-in-the-loop AI farming companion for Indian smallholder farmers. It predicts, advises, and helps plan — crop choice, weather-driven timing, climate risk, and available government support — while final decisions stay with the farmer.

This README is deliberately specific about what's real and what isn't. Every feature below is either genuinely working (real weather data, real translation, real logic against curated reference data) or explicitly marked as a roadmap preview with no functionality behind it yet.

## ✅ Implemented (working, not mocked)

| Feature | What it actually does |
|---|---|
| 🌱 **Smart Crop Recommendation** | Rule-based match of your soil type and season against a reference table of 24 Indian crops (Kharif, Rabi and Zaid). Temperature and rainfall come from the **average of the last 3 complete seasons at your location** (Open-Meteo historical data), not from extrapolating one week. If the history can't be fetched it falls back to scaling the 7-day forecast and says so on screen. |
| 🌦️ **Weather-Based Farming Advice** | Live 7-day forecast (Open-Meteo, no API key needed) with rule-based sowing, irrigation, spraying, and harvest timing guidance. Each advisory comes with a **suggested reminder you accept or dismiss** (see Human-in-the-loop below). Same-named villages are disambiguated: you pick from matches shown with district and state. |
| 💧 **Water Management Advisor** | Irrigation timing folded into the Weather Advisory page, driven by the same live forecast. |
| ⚠️ **Climate Risk Prediction** | Heat / cold / heavy-rain / dry-spell / water-gap signals scored from the live forecast. Heat and cold thresholds come from **the selected crop's own temperature range** (36°C stresses wheat, not sugarcane). A one-week dry spell is reported as a dry spell, not a drought. |
| 📉 **Yield Prediction & Loss Prevention Analytics** | Heuristic yield estimate and value-at-risk, derived from climate risk score × a static crop yield/price reference table (clearly labeled as illustrative, not live mandi prices). |
| 🩺 **AI Crop Health Scanner** | Upload a leaf photo — a real HSV color/texture analysis flags likely nutrient deficiency, fungal/pest damage, or water stress, with a treatment recommendation. This is a heuristic, **not** a trained deep-learning disease classifier — see the in-app disclaimer. |
| 🤖 **Fasal Guru (AI Chat)** | Real LLM-backed chat via Google Gemini. Needs your own `GEMINI_API_KEY` (free) — without one, the page explains that clearly instead of faking a response. Answers are grounded in the farmer's village, state, soil, land size, recent crops and (optionally) the live forecast — never their name — and come back in the farmer's chosen language. The model is configurable (`GEMINI_MODEL`) with a fallback chain, because Gemini model names get retired. |
| 🏛️ **Yojana Sathi (Govt. Scheme Assistant)** | Curated reference data on 9 major central government schemes (PM-KISAN, PMFBY, KCC, PM-KUSUM, PMKSY, e-NAM, Soil Health Card, AIF, NFSM) with category-based matching. Static data — always verify current terms on the official site. |
| 📚 **Farmer Learning Hub** | 8 practical guides (crop rotation, IPM, drip irrigation, soil health, post-harvest storage, NPK, climate adaptation, seed treatment). |
| 👤 **Farmer Profile & Farm Records** | Real local SQLite persistence — profile, land/soil details, farm records, and reminders. |
| 🔔 **Smart Notifications** | In-app reminders (sowing, irrigation, spraying, fertilizer, harvest) stored in SQLite. Not push/SMS notifications — see roadmap. |
| 🧭 **Advice history** | Every suggestion shown and whether the farmer accepted or dismissed it, on the Farmer Profile page. |
| 🌐 **Regional Language Support** | Live translation (via `deep-translator`) across English, Hindi, Bengali, Telugu, Marathi, Tamil, Gujarati, Kannada, Malayalam, Punjabi, Odia, Assamese, and Urdu — applied to the whole UI, not just a few strings. |

## 🧑‍🌾 Human-in-the-loop, concretely

FarmVeda never acts on its own advice. On the Weather Advisory page every sowing / irrigation / spraying / harvest verdict carries a *suggested* reminder (title, date, category). Nothing is saved until the farmer presses **Add to reminders**; **Dismiss** records that they declined. Both decisions go to an `advice_log` table (verdict, reason, place, decision, linked reminder) and are shown back on the Farmer Profile page. Accepting creates the reminder and the log row in one transaction.

## ⚠️ Known limits

- **Everything is a heuristic.** Thresholds are simplified agronomic rules, not calibrated models. They don't know your crop stage, variety, irrigation source or soil moisture.
- **Season windows are national approximations** (Kharif 1 Jun–31 Oct, Rabi 1 Nov–14 Mar, Zaid 15 Mar–15 Jun). Real sowing windows differ by state.
- **Reference data is illustrative.** The yield and price table is not live mandi data. The four Zaid crops (watermelon, muskmelon, cucumber, green gram) were added from approximate published ranges and have **not been checked against an agronomist's source** — verify before relying on them.
- **Solo-farmer scope.** No multi-user accounts, no authentication; the SQLite file is local.
- **No field trial.** This hasn't been tested with working farmers.
- The health scanner is a colour heuristic, not a disease classifier.

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

## Tests

```bash
pip install pytest
pytest
```

90 tests run with the network faked (canned Open-Meteo responses and a fake Gemini client), including in-process Streamlit runs that click the real buttons (`streamlit.testing`). They cover geocoding, every advisory rule, the accept/dismiss flow and its transaction safety, climate normals, crop-specific risk, the chat fallback chain and the scanner. Live API behaviour (real Open-Meteo responses, a real Gemini key) is not covered by the automated tests.

## Getting started

```bash
pip install -r requirements.txt
cp .env.example .env   # optional: add GEMINI_API_KEY to enable Fasal Guru chat
streamlit run app.py
```

Opens at `http://localhost:8501` by default. No API keys are required for crop recommendation, weather advisory, climate risk/yield, the health scanner, Yojana Sathi, or the learning hub — only the AI chat page needs a (free) Gemini key. If chat reports that a model isn't found, set `GEMINI_MODEL` in `.env` to one your key can use.

## Project structure

```
app.py                        Home — profile creation/selection, dashboard
core/
  db.py                       SQLite: farmers, farm_records, reminders, advice_log
  i18n.py                     Live translation (13 languages)
  weather.py                  Open-Meteo geocoding/forecast + advisory rules
  advice.py                   Advisory verdict -> suggested reminder (accept/dismiss)
  climate.py                  Seasonal normals from Open-Meteo historical data
  location_picker.py          Place picker + cached lookups for the pages
  crop_recommender.py         Rule-based crop matching
  risk_yield.py                Crop-specific climate risk + yield + loss heuristics
  health_scanner.py            Leaf photo HSV heuristic analysis
  chat.py                      Fasal Guru (Gemini-backed)
  schemes.py                   Yojana Sathi scheme matching
  state.py                     Shared Streamlit session helpers
data/
  crop_requirements.csv        24 crops: soil/season/temp/rainfall ranges
  crop_yield_price_reference.csv  Illustrative yield & price reference
  schemes.json                 9 real government scheme summaries
  learning_content.json        8 farming practice guides
pages/                         One file per feature (Streamlit auto-routes these)
tests/                         pytest suite (network faked)
```

## Disclaimer

This is a planning and advisory aid, not an agronomic, financial, or medical authority. Crop and risk recommendations are heuristic estimates from published ranges and live weather data — they don't replace a soil test, a visit from your local Krishi Vigyan Kendra, or your own field judgment. Government scheme details change; always confirm current terms on the official scheme website before applying.
