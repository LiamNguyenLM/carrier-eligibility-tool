"""Round 38b (Liam's decisions, 2026-10-12): each verdict change, end to end through check_eligibility with a fake model
(zero API), on Liam's Harris home (test_held_reasons.HOME) and LANDLORD."""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import eligibility_check as ec  # noqa: E402
from test_held_reasons import HOME, LANDLORD  # noqa: E402

pytestmark = pytest.mark.retrieval
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
TRAVELERS, MERCURY = "Travelers_HO3_-_06.12.2026", "Mercury_HO3_-_01.01.2026"


@pytest.fixture
def check(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    monkeypatch.setattr(ec, "_complete", fake)
    return lambda pd: {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}


def _rows(rec, rid):
    return [x for x in rec.get("reasons") or [] if f"[{rid}]" in x]


def _confirms(rec, rid):
    return [x for x in rec.get("confirm_items") or [] if x.get("row") == rid]


ONE_LOSS = dict(HOME, losses_5yr="1", loss_year=2025, losses_3yr="1")


# ---- 1. Travelers TRV-066: "1 or more water damage claim(s)" refers (round 38 step 3 had made it a confirm)
def test_one_water_loss_refers_travelers(check):
    r = check(dict(ONE_LOSS, loss_types=["Water"]))[TRAVELERS]
    assert r["status"] == "REFER" and _rows(r, "TRV-066"), r["reasons"]


def test_an_other_loss_is_a_travelers_confirm_not_a_referral(check):
    r = check(dict(ONE_LOSS, loss_types=["Other"]))[TRAVELERS]
    assert not _rows(r, "TRV-066") and _confirms(r, "TRV-066")


# ---- Mercury MER-087: theft is non-weather, but the footnote counts only paid losses -> a confirm, not a decline
@pytest.mark.parametrize("types", [["Theft"], ["Fire"]])
def test_one_non_weather_loss_is_a_mercury_confirm_because_only_paid_losses_count(check, types):
    r = check(dict(ONE_LOSS, loss_types=types))[MERCURY]
    assert not _rows(r, "MER-087") and _confirms(r, "MER-087")
    assert any("paid" in x["rule"].lower() or "paid" in (x.get("detail") or "").lower() for x in _confirms(r, "MER-087")) \
        or "paid" in json.dumps(_confirms(r, "MER-087")).lower()
