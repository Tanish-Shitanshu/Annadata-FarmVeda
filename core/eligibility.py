"""First-pass scheme eligibility for a farmer.

Turns what we know (profile, saved answers, crops, cooperative membership) into
one result per scheme: Likely eligible / Check details / Probably not eligible /
Not relevant right now, with the reasons, the next steps and what is still unknown.

This is guidance, not a government decision:
  * Rules are a summary of published criteria (see data/schemes.json for the
    source and verification date of each) and states add their own conditions.
  * When an answer is missing, the result says "Check details" instead of guessing.
  * Nothing is submitted anywhere. The farmer decides whether to act; the page
    offers a reminder they can accept or dismiss.
Answers (income tax, government job...) stay in the local database and are never
sent to the chat model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from core.schemes import Scheme, load_schemes

ACRES_PER_HECTARE = 2.47105
LIKELY, CHECK, UNLIKELY, NA = "likely", "check", "unlikely", "na"
STATUS_LABELS = {LIKELY: "Likely eligible", CHECK: "Check details", UNLIKELY: "Probably not eligible",
                 NA: "Not relevant right now"}
STATUS_ORDER = {LIKELY: 0, CHECK: 1, UNLIKELY: 2, NA: 3}

CULTIVATOR_TYPES = ("owner", "tenant", "sharecropper")
OWNERSHIP_LABELS = {"owner": "I own the land I farm",
                    "tenant": "I farm leased land (registered or oral lease)",
                    "sharecropper": "I am a sharecropper",
                    "landless": "I don't cultivate land (e.g. livestock/fisheries only)"}

# kind: choice | bool | multi
QUESTIONS: list[dict] = [
    {"id": "land_ownership", "kind": "choice", "label": "How do you farm?", "options": OWNERSHIP_LABELS},
    {"id": "owned_since_2019", "kind": "bool",
     "label": "Did your family own this land on 1 February 2019 (or did you inherit it from someone who did)?",
     "help": "PM-KISAN generally covers land held on that date and its inheritors."},
    {"id": "bank_aadhaar_linked", "kind": "bool",
     "label": "Is your bank account linked to your Aadhaar (NPCI seeding)?"},
    {"id": "pm_kisan_exclusions", "kind": "multi",
     "label": "Do any of these apply to you, your spouse or your minor children?",
     "options": {"income_tax": "Paid income tax last year",
                 "govt_job": "Government employee, or pensioner drawing ₹10,000+ a month (not Group D/MTS)",
                 "professional": "Registered doctor, engineer, lawyer, chartered accountant or architect",
                 "constitutional": "Current/former minister, MP/MLA, mayor or district panchayat chairperson"}},
    {"id": "has_kcc", "kind": "bool", "label": "Do you already have a Kisan Credit Card?"},
    {"id": "allied_activity", "kind": "bool", "label": "Do you keep livestock or run fisheries/poultry?"},
    {"id": "group_member", "kind": "bool",
     "label": "Are you a member of an SHG, JLG, FPO or cooperative society outside this app?"},
    {"id": "plans", "kind": "multi", "label": "What are you thinking of investing in?",
     "options": {"solar_pump": "A solar irrigation pump", "micro_irrigation": "Drip or sprinkler irrigation",
                 "storage_processing": "Storage, cold chain or processing (post-harvest)"}},
]
QUESTION_IDS = {q["id"] for q in QUESTIONS}

HORTICULTURE_OR_COMMERCIAL = {"tomato", "potato", "onion", "banana", "chili", "cotton", "sugarcane",
                              "watermelon", "muskmelon", "cucumber"}
NFSM_CROP_WORDS = ("rice", "wheat", "chickpea", "gram", "pigeon pea", "tur", "arhar", "moong", "maize",
                   "sorghum", "jowar", "bajra", "millet", "barley")


@dataclass
class SuggestedReminder:
    title: str
    due_date: date
    category: str = "Schemes"


@dataclass
class SchemeResult:
    scheme: Scheme
    status: str
    headline: str
    reasons: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)       # question ids that would sharpen the answer
    reminder: SuggestedReminder | None = None

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]


@dataclass
class Context:
    land_acres: float | None
    state: str
    answers: dict
    crops: list[str]
    coops: list[dict]            # [{"name":..., "member_count":...}]
    today: date

    def get(self, key):
        return self.answers.get(key)

    @property
    def ownership(self):
        return self.answers.get("land_ownership")

    @property
    def is_cultivator(self) -> bool:
        return self.ownership in CULTIVATOR_TYPES

    @property
    def plans(self):
        return self.answers.get("plans")

    @property
    def holding_class(self) -> str | None:
        if not self.land_acres or self.land_acres <= 0:
            return None
        hectares = self.land_acres / ACRES_PER_HECTARE
        return "marginal" if hectares < 1 else "small" if hectares < 2 else "other"


def pmfby_next_cutoff(today: date) -> tuple[date, str]:
    """Typical enrolment cut-offs: ~31 July (Kharif), ~31 December (Rabi). States and crops differ."""
    for month, day, season in ((7, 31, "Kharif"), (12, 31, "Rabi")):
        cutoff = date(today.year, month, day)
        if cutoff >= today:
            return cutoff, season
    return date(today.year + 1, 7, 31), "Kharif"


def _remind(title: str, today: date, days: int = 7, due: date | None = None) -> SuggestedReminder:
    return SuggestedReminder(title=title, due_date=due or today + timedelta(days=days))


# ── Per-scheme rules ────────────────────────────────────────────────────────

def _pm_kisan(s: Scheme, c: Context) -> SchemeResult:
    own = c.ownership
    if own is None:
        return SchemeResult(s, CHECK, "Tell us how you farm to check this.", missing=["land_ownership"])
    if own != "owner":
        return SchemeResult(s, UNLIKELY, "PM-KISAN pays landowning families.",
                            [f"You said: {OWNERSHIP_LABELS[own].lower()}."],
                            ["If your family does hold land in the state records, correct your answer."])
    exclusions = c.get("pm_kisan_exclusions")
    if exclusions:
        labels = {q["id"]: q for q in QUESTIONS}["pm_kisan_exclusions"]["options"]
        return SchemeResult(s, UNLIKELY, "An exclusion rule probably applies.",
                            [labels[e] for e in exclusions if e in labels],
                            ["Confirm with your local agriculture office; the rules treat the whole family together."])
    missing = [q for q in ("pm_kisan_exclusions", "owned_since_2019") if c.get(q) is None]
    if c.get("owned_since_2019") is False:
        return SchemeResult(s, CHECK, "Land acquired after 1 Feb 2019 is generally excluded unless inherited.",
                            ["You said your family didn't hold this land on that date."],
                            ["Ask your local agriculture office whether your case (e.g. inheritance) qualifies."])
    if missing:
        return SchemeResult(s, CHECK, "Likely, but a couple of answers are missing.",
                            ["You own land."], missing=missing)
    steps = ["Register on the PM-KISAN portal or at a Common Service Centre.",
             "Complete e-KYC (mandatory) - OTP on the portal, or biometric at a CSC."]
    if c.get("bank_aadhaar_linked") is False:
        steps.insert(0, "Link your bank account to Aadhaar (NPCI seeding) at your bank first.")
    return SchemeResult(s, LIKELY, "You look eligible for ₹6,000 a year.",
                        ["You own land.", "None of the exclusions apply to you.",
                         "Your family held the land on 1 Feb 2019 (or inherited it)."], steps,
                        reminder=_remind("Register for PM-KISAN and finish e-KYC", c.today))


def _pmfby(s: Scheme, c: Context) -> SchemeResult:
    cutoff, season = pmfby_next_cutoff(c.today)
    if c.ownership is None:
        return SchemeResult(s, CHECK, "Tell us how you farm to check this.", missing=["land_ownership"])
    if not c.is_cultivator:
        return SchemeResult(s, UNLIKELY, "Crop insurance is for people who grow crops.",
                            [f"You said: {OWNERSHIP_LABELS[c.ownership].lower()}."])
    crop_words = " ".join(c.crops).lower()
    commercial = any(w in crop_words for w in HORTICULTURE_OR_COMMERCIAL)
    reasons = ["You cultivate land, so you can insure your crop."]
    if c.ownership in ("tenant", "sharecropper"):
        reasons.append("Tenants and sharecroppers can enrol with a tenancy document or certificate (state rules differ).")
    if c.crops:
        reasons.append(f"Premium for you: about {'up to 5% for commercial/horticultural crops' if commercial else '1.5-2% for food grains and oilseeds'} of the sum insured.")
    days_left = (cutoff - c.today).days
    steps = [f"Enrol before the {season} cut-off, typically around {cutoff:%d %b %Y} ({days_left} days). "
             "The exact date depends on your state and crop.",
             "Confirm your crop and village are notified for the season on pmfby.gov.in or with your bank/CSC."]
    return SchemeResult(s, LIKELY, f"You can insure your crop; the {season} cut-off is near." if days_left <= 75
                        else "You can insure your crop.", reasons, steps,
                        reminder=_remind(f"Enrol in PMFBY crop insurance ({season} cut-off ~{cutoff:%d %b})", c.today,
                                         due=max(c.today, cutoff - timedelta(days=14))))


def _kcc(s: Scheme, c: Context) -> SchemeResult:
    if c.get("has_kcc"):
        return SchemeResult(s, NA, "You already have a Kisan Credit Card.",
                            next_steps=["Ask your bank about renewal or a higher limit."])
    if c.ownership is None:
        return SchemeResult(s, CHECK, "Tell us how you farm to check this.", missing=["land_ownership"])
    if c.is_cultivator:
        return SchemeResult(s, LIKELY, "Cultivators, including tenants and sharecroppers, can get a KCC.",
                            [f"You said: {OWNERSHIP_LABELS[c.ownership].lower()}."],
                            ["Visit your bank branch or PACS with Aadhaar, land/tenancy proof and a photo."],
                            reminder=_remind("Visit the bank to apply for a Kisan Credit Card", c.today))
    if c.get("allied_activity") or c.get("group_member"):
        return SchemeResult(s, LIKELY, "KCC also covers livestock, fisheries and farmer groups.",
                            ["You keep livestock/fisheries or belong to a group."],
                            ["Ask your bank for the animal husbandry/fisheries or group KCC."],
                            reminder=_remind("Visit the bank to apply for a Kisan Credit Card", c.today))
    missing = [q for q in ("allied_activity", "group_member") if c.get(q) is None]
    return SchemeResult(s, UNLIKELY if not missing else CHECK, "KCC needs farming, livestock/fisheries or group membership.",
                        missing=missing)


def _soil_health(s: Scheme, c: Context) -> SchemeResult:
    if c.ownership is None:
        return SchemeResult(s, CHECK, "Tell us how you farm to check this.", missing=["land_ownership"])
    if not c.is_cultivator:
        return SchemeResult(s, UNLIKELY, "Soil testing is for people who cultivate land.")
    return SchemeResult(s, LIKELY, "Free soil testing is open to farmers who cultivate land.",
                        next_steps=["Ask your agriculture department or Krishi Vigyan Kendra to take a soil sample.",
                                    "Do it before you sow, so the nutrient advice can be used this season."],
                        reminder=_remind("Get a free soil test (Soil Health Card)", c.today, days=10))


def _pm_kusum(s: Scheme, c: Context) -> SchemeResult:
    plans = c.plans
    if plans is None:
        return SchemeResult(s, NA, "Relevant if you want a solar pump.", missing=["plans"])
    if "solar_pump" not in plans:
        return SchemeResult(s, NA, "You haven't said you want a solar pump.")
    if not (c.is_cultivator or c.get("group_member") or c.coops):
        return SchemeResult(s, CHECK, "Needs land (or a farmer group) for the installation.", missing=["land_ownership"])
    return SchemeResult(s, CHECK, "Possible - depends on whether your state has an open window.",
                        ["You plan a solar pump and have land or a group."],
                        ["Ask your state nodal agency or discom what is open and what the subsidy rate is.",
                         "Newer central timelines were reported extended to March 2027 for some projects, but rates were not re-verified."],
                        reminder=_remind("Ask the state nodal agency about PM-KUSUM solar pump subsidy", c.today, days=10))


def _e_nam(s: Scheme, c: Context) -> SchemeResult:
    if c.ownership is None:
        return SchemeResult(s, CHECK, "Tell us how you farm to check this.", missing=["land_ownership"])
    if not c.is_cultivator:
        return SchemeResult(s, UNLIKELY, "e-NAM is for farmers selling produce at a mandi.")
    return SchemeResult(s, CHECK, "You can register, but your nearest mandi must be on e-NAM.",
                        ["You grow produce to sell."],
                        ["Look up your nearest e-NAM mandi on enam.gov.in.",
                         "Register as a farmer (Aadhaar-linked mobile, bank proof, land and crop details); the mandi approves it."])


def _pmksy(s: Scheme, c: Context) -> SchemeResult:
    plans = c.plans
    if plans is None:
        return SchemeResult(s, NA, "Relevant if you plan drip or sprinkler irrigation.", missing=["plans"])
    if "micro_irrigation" not in plans:
        return SchemeResult(s, NA, "You haven't said you plan drip or sprinkler irrigation.")
    if not c.is_cultivator:
        return SchemeResult(s, UNLIKELY, "Micro-irrigation support is for people who farm land.")
    klass = c.holding_class
    rate = "55%" if klass in ("marginal", "small") else "45%"
    reasons = ["You plan drip or sprinkler irrigation."]
    if klass:
        reasons.append(f"With about {c.land_acres:g} acres you count as a {klass} holding, so the indicative subsidy is "
                       f"{rate} of the unit cost." if klass != "other" else
                       f"With about {c.land_acres:g} acres the indicative subsidy is {rate} of the unit cost.")
    else:
        reasons.append("Add your land size to see whether the 55% (small/marginal) or 45% rate applies.")
    return SchemeResult(s, LIKELY, f"You may get about {rate} off drip or sprinkler systems." if klass else
                        "You may get a subsidy on drip or sprinkler systems.", reasons,
                        ["Ask your state horticulture/agriculture department how to apply and which suppliers are approved.",
                         "Get the application in before you buy - most states subsidise only approved purchases."],
                        reminder=_remind("Apply for micro-irrigation (drip/sprinkler) subsidy before buying", c.today, days=10))


def _aif(s: Scheme, c: Context) -> SchemeResult:
    plans = c.plans
    in_group = bool(c.coops) or bool(c.get("group_member"))
    if plans is not None and "storage_processing" in plans:
        reasons = ["You plan storage, cold-chain or processing."]
        if in_group:
            reasons.append("Groups, cooperatives and FPOs are eligible borrowers too.")
        return SchemeResult(s, LIKELY, "A loan with 3% interest subvention may fit your plan.", reasons,
                            ["Prepare a simple project report (cost, site, expected income).",
                             "Apply through a participating bank on the AIF portal."],
                            reminder=_remind("Prepare a project report for an AIF storage/processing loan", c.today, days=14))
    if plans is None:
        return SchemeResult(s, NA, "Relevant if you plan storage or processing.", missing=["plans"])
    if in_group:
        return SchemeResult(s, CHECK, "Your group could borrow for shared storage or processing.",
                            ["You belong to a cooperative or farmer group."],
                            ["Discuss a shared warehouse or processing unit with your group first."])
    return SchemeResult(s, NA, "You haven't said you plan storage or processing.")


def _nfsm(s: Scheme, c: Context) -> SchemeResult:
    crops = " ".join(c.crops).lower()
    if c.crops and any(w in crops for w in NFSM_CROP_WORDS):
        return SchemeResult(s, CHECK, "You grow a crop this mission targets - confirm your district.",
                            ["Your recorded crops include rice, wheat, pulses or coarse cereals."],
                            ["Ask your district agriculture office whether your district is covered and what inputs are on offer.",
                             "This scheme's current structure was not re-checked in 2026."])
    return SchemeResult(s, NA, "Relevant if you grow rice, wheat, pulses or coarse cereals in a covered district.")


def _fpo(s: Scheme, c: Context) -> SchemeResult:
    if not c.coops:
        return SchemeResult(s, NA, "Relevant once you and other farmers form a group.",
                            next_steps=["Form or join a cooperative in this app to start building your group."])
    best = max(c.coops, key=lambda x: x["member_count"])
    return SchemeResult(s, CHECK, "A formal FPO needs many more members than a small group.",
                        [f"'{best['name']}' has {best['member_count']} member(s) here; an FPO needs 300 farmers in the plains "
                         "(100 in hilly/North-Eastern areas)."],
                        ["Ask your district agriculture office or an implementing agency (e.g. NABARD, SFAC) about FPO formation."])


_RULES = {"pm-kisan": _pm_kisan, "pmfby": _pmfby, "kcc": _kcc, "soil-health-card": _soil_health,
          "pm-kusum": _pm_kusum, "e-nam": _e_nam, "pmksy": _pmksy, "aif": _aif, "nfsm": _nfsm, "fpo-scheme": _fpo}


def clean_answers(raw: dict) -> dict:
    """Keep only known question ids with valid values."""
    out = {}
    for q in QUESTIONS:
        if q["id"] not in raw or raw[q["id"]] is None:
            continue
        value = raw[q["id"]]
        if q["kind"] == "choice" and value in q["options"]:
            out[q["id"]] = value
        elif q["kind"] == "bool" and isinstance(value, bool):
            out[q["id"]] = value
        elif q["kind"] == "multi" and isinstance(value, list):
            out[q["id"]] = [v for v in value if v in q["options"]]
    return out


def evaluate(land_acres: float | None, state: str, answers: dict, crops: list[str] | None = None,
             coops: list[dict] | None = None, today: date | None = None) -> list[SchemeResult]:
    ctx = Context(land_acres=land_acres, state=state or "", answers=clean_answers(answers or {}),
                  crops=crops or [], coops=coops or [], today=today or date.today())
    results = []
    for scheme in load_schemes():
        rule = _RULES.get(scheme.id)
        if rule is None:        # a scheme added to the data without a rule must not be silently "eligible"
            results.append(SchemeResult(scheme, CHECK, "Check the eligibility on the official site."))
        else:
            results.append(rule(scheme, ctx))
    return sorted(results, key=lambda r: (STATUS_ORDER[r.status], r.scheme.name))


def unanswered_questions(answers: dict) -> list[str]:
    return [q["id"] for q in QUESTIONS if q["id"] not in clean_answers(answers or {})]
