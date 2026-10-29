import json
from datetime import date

import pytest

from core import eligibility as el
from core.eligibility import CHECK, LIKELY, NA, UNLIKELY, evaluate
from core.schemes import load_schemes

TODAY = date(2026, 10, 29)
OWNER = {"land_ownership": "owner", "owned_since_2019": True, "pm_kisan_exclusions": [],
         "bank_aadhaar_linked": True}


def result(scheme_id, answers=None, acres=3.0, crops=None, coops=None, today=TODAY):
    res = evaluate(acres, "Punjab", answers if answers is not None else OWNER, crops, coops, today)
    return {r.scheme.id: r for r in res}[scheme_id]


def test_every_scheme_in_the_data_has_a_rule_and_data_is_complete():
    ids = {s.id for s in load_schemes()}
    assert ids == set(el._RULES)
    for s in load_schemes():
        assert s.benefit and s.eligibility_summary and s.how_to_apply and s.source_note, s.id
        assert s.documents, s.id


def test_every_result_has_a_valid_status_and_headline_for_many_profiles():
    import itertools
    combos = itertools.product(
        [None, "owner", "tenant", "sharecropper", "landless"], [None, True, False], [None, [], ["income_tax"]],
        [None, [], ["solar_pump", "micro_irrigation", "storage_processing"]], [None, True, False])
    for own, since, excl, plans, kcc in combos:
        answers = {k: v for k, v in {"land_ownership": own, "owned_since_2019": since, "pm_kisan_exclusions": excl,
                                     "plans": plans, "has_kcc": kcc}.items() if v is not None}
        for r in evaluate(2.0, "Bihar", answers, ["Rice (Paddy)"], [], TODAY):
            assert r.status in el.STATUS_LABELS and r.headline, (r.scheme.id, answers)
            if r.status == LIKELY:
                assert r.next_steps, (r.scheme.id, "a 'likely' result must tell the farmer what to do")
            if r.reminder:
                assert r.reminder.due_date >= TODAY


def test_no_answers_never_claims_eligibility_without_basis():
    res = evaluate(2.0, "Punjab", {}, [], [], TODAY)
    assert all(r.status in (CHECK, NA) for r in res)
    assert {r.scheme.id: r for r in res}["pm-kisan"].missing == ["land_ownership"]


# ── PM-KISAN ────────────────────────────────────────────────────────────────

def test_pm_kisan_likely_for_owner_with_no_exclusions():
    r = result("pm-kisan")
    assert r.status == LIKELY and r.reminder and any("e-KYC" in s for s in r.next_steps)


@pytest.mark.parametrize("own", ["tenant", "sharecropper", "landless"])
def test_pm_kisan_not_for_non_owners(own):
    assert result("pm-kisan", {"land_ownership": own}).status == UNLIKELY


@pytest.mark.parametrize("flag", ["income_tax", "govt_job", "professional", "constitutional"])
def test_pm_kisan_exclusions(flag):
    r = result("pm-kisan", {**OWNER, "pm_kisan_exclusions": [flag]})
    assert r.status == UNLIKELY and len(r.reasons) == 1


def test_pm_kisan_land_after_2019_needs_checking_and_missing_answers_are_asked():
    assert result("pm-kisan", {**OWNER, "owned_since_2019": False}).status == CHECK
    r = result("pm-kisan", {"land_ownership": "owner"})
    assert r.status == CHECK and set(r.missing) == {"pm_kisan_exclusions", "owned_since_2019"}


def test_pm_kisan_unlinked_bank_becomes_the_first_step():
    r = result("pm-kisan", {**OWNER, "bank_aadhaar_linked": False})
    assert r.status == LIKELY and "Aadhaar" in r.next_steps[0]


# ── PMFBY ───────────────────────────────────────────────────────────────────

def test_pmfby_cutoffs():
    assert el.pmfby_next_cutoff(date(2026, 3, 1)) == (date(2026, 7, 31), "Kharif")
    assert el.pmfby_next_cutoff(date(2026, 10, 29)) == (date(2026, 12, 31), "Rabi")
    assert el.pmfby_next_cutoff(date(2026, 12, 31)) == (date(2026, 12, 31), "Rabi")
    assert el.pmfby_next_cutoff(date(2027, 1, 5)) == (date(2027, 7, 31), "Kharif")


def test_pmfby_reminder_is_before_the_deadline_and_never_in_the_past():
    r = result("pmfby")
    assert r.status == LIKELY and r.reminder.due_date == date(2026, 12, 17) and "Rabi" in r.headline
    late = result("pmfby", today=date(2026, 12, 30))
    assert late.reminder.due_date == date(2026, 12, 30)


def test_pmfby_tenants_get_the_document_note_and_premium_depends_on_crop():
    r = result("pmfby", {"land_ownership": "tenant"}, crops=["Tomato"])
    assert r.status == LIKELY and any("tenancy" in x for x in r.reasons) and any("5%" in x for x in r.reasons)
    assert any("1.5-2%" in x for x in result("pmfby", crops=["Wheat"]).reasons)


def test_pmfby_not_for_non_cultivators():
    assert result("pmfby", {"land_ownership": "landless"}).status == UNLIKELY


# ── KCC / Soil card / eNAM ──────────────────────────────────────────────────

def test_kcc_cases():
    assert result("kcc", {**OWNER, "has_kcc": True}).status == NA
    assert result("kcc", {"land_ownership": "tenant"}).status == LIKELY
    assert result("kcc", {"land_ownership": "landless", "allied_activity": True}).status == LIKELY
    assert result("kcc", {"land_ownership": "landless", "allied_activity": False, "group_member": False}).status == UNLIKELY
    assert result("kcc", {"land_ownership": "landless"}).status == CHECK


def test_soil_health_and_enam():
    assert result("soil-health-card").status == LIKELY
    assert result("soil-health-card", {"land_ownership": "landless"}).status == UNLIKELY
    assert result("e-nam").status == CHECK                       # depends on whether the local mandi is on e-NAM


# ── PMKSY ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("acres,rate", [(0.5, "55%"), (2.4, "55%"), (2.5, "55%"), (4.9, "55%"), (5.0, "45%"), (20, "45%")])
def test_pmksy_rate_by_holding_size(acres, rate):
    r = result("pmksy", {**OWNER, "plans": ["micro_irrigation"]}, acres=acres)
    assert r.status == LIKELY and rate in r.headline


def test_pmksy_only_if_they_plan_it():
    assert result("pmksy", {**OWNER, "plans": []}).status == NA
    assert result("pmksy", OWNER).status == NA and result("pmksy", OWNER).missing == ["plans"]
    assert result("pmksy", {**OWNER, "plans": ["micro_irrigation"]}, acres=0).status == LIKELY   # no land size: no rate claimed
    assert "55%" not in result("pmksy", {**OWNER, "plans": ["micro_irrigation"]}, acres=0).headline


# ── KUSUM / AIF / NFSM / FPO ────────────────────────────────────────────────

def test_kusum_is_never_stronger_than_check():
    assert result("pm-kusum", {**OWNER, "plans": ["solar_pump"]}).status == CHECK
    assert result("pm-kusum", {**OWNER, "plans": []}).status == NA


def test_aif_individual_vs_group():
    assert result("aif", {**OWNER, "plans": ["storage_processing"]}).status == LIKELY
    assert result("aif", {**OWNER, "plans": []}).status == NA
    assert result("aif", {**OWNER, "plans": []}, coops=[{"name": "X", "member_count": 4}]).status == CHECK


def test_nfsm_depends_on_crops():
    assert result("nfsm", crops=["Wheat"]).status == CHECK
    assert result("nfsm", crops=["Banana"]).status == NA and result("nfsm").status == NA


def test_fpo_uses_cooperative_headcount_honestly():
    assert result("fpo-scheme").status == NA
    r = result("fpo-scheme", coops=[{"name": "Khanna Growers", "member_count": 7}])
    assert r.status == CHECK and "7 member" in r.reasons[0] and "300" in r.reasons[0]


# ── Plumbing ────────────────────────────────────────────────────────────────

def test_results_sorted_best_first():
    order = [el.STATUS_ORDER[r.status] for r in evaluate(3, "Punjab", OWNER, ["Wheat"], [], TODAY)]
    assert order == sorted(order)


def test_clean_answers_drops_junk():
    cleaned = el.clean_answers({"land_ownership": "emperor", "has_kcc": "yes", "plans": ["solar_pump", "magic"],
                                "bogus": 1, "owned_since_2019": True, "pm_kisan_exclusions": "income_tax"})
    assert cleaned == {"plans": ["solar_pump"], "owned_since_2019": True}


def test_unanswered_questions():
    assert "land_ownership" not in el.unanswered_questions({"land_ownership": "owner"})
    assert set(el.unanswered_questions({})) == el.QUESTION_IDS
    assert "plans" not in el.unanswered_questions({"plans": []})          # "nothing" is an answer


def test_scheme_data_is_json_safe():
    json.dumps([s.__dict__ for s in load_schemes()], ensure_ascii=False)
