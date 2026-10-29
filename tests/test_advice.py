import random
from datetime import date

from conftest import forecast_payload
from core import advice
from core.weather import (Location, get_forecast, harvest_advisory, irrigation_advisory,
                          sowing_advisory, spraying_advisory)


def random_forecasts(net, n=400):
    rng = random.Random(7)
    for _ in range(n):
        net.forecast = forecast_payload(
            tmax=rng.uniform(15, 45), tmin=rng.uniform(0, 25), rain=rng.choice([0, 0, 1, 3, 8, 20, 40]),
            prob=rng.choice([0, 20, 45, 60, 90]), wind=rng.uniform(0, 30),
            overrides={rng.randrange(7): {"precipitation_sum": rng.choice([0, 5, 16, 35])}})
        yield get_forecast(Location("X", "India", 1, 2))


def test_every_verdict_the_rules_can_produce_has_a_suggestion(net):
    """If someone adds a verdict to weather.py without a mapping here, this fails."""
    seen = {"sowing": set(), "irrigation": set(), "harvest": set()}
    funcs = {"sowing": sowing_advisory, "irrigation": irrigation_advisory, "harvest": harvest_advisory}
    for forecast in random_forecasts(net):
        for kind, fn in funcs.items():
            a = fn(forecast)
            seen[kind].add(a["verdict"])
            assert advice.suggest_reminder(kind, a) is not None, (kind, a["verdict"])
    assert seen["sowing"] == set(advice.SOWING)
    assert seen["irrigation"] == set(advice.IRRIGATION)
    assert seen["harvest"] == set(advice.HARVEST)


def test_due_date_is_offset_from_today():
    s = advice.suggest_reminder("sowing", {"verdict": "Wait"}, today=date(2026, 6, 10))
    assert s.due_date == date(2026, 6, 12) and s.category == "Sowing"


def test_unknown_verdict_or_kind_gives_none():
    assert advice.suggest_reminder("sowing", {"verdict": "???"}) is None
    assert advice.suggest_reminder("nonsense", {"verdict": "Wait"}) is None


def test_spraying_picks_first_suitable_day(net):
    net.forecast = forecast_payload(overrides={0: {"precipitation_probability_max": 90}})
    days = spraying_advisory(get_forecast(Location("X", "India", 1, 2)))
    s = advice.suggest_spraying_reminder(days)
    assert s.due_date == days[1]["day"] and s.category == "Spraying"


def test_spraying_none_when_no_suitable_day(net):
    net.forecast = forecast_payload(prob=90)
    assert advice.suggest_spraying_reminder(spraying_advisory(get_forecast(Location("X", "India", 1, 2)))) is None
