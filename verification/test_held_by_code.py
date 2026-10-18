"""Round 41 B4 (Liam, 2026-10-17): a rules-table carrier held only on blank answers gets no model call -- code holds
it, the verdict the model's answer would come to (rules_evaluator.only_blank_holds; round 39 step 5e did the same when
the model left such a carrier out). A carrier with a row the model can decide (ambiguous readings, an UNKNOWN effect)
still goes to the rule check. Zero API."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
OC = "Sage_-_Occidental_HO3_-_12.02.2025"
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
# Liam's Harris HO3 profile (scratchpad r36/s8_liam): Coverage A and the station distance blank, hydrant Yes
LIAM = {"year_built": 1994, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "pool_fence_4ft": False, "pool_gate_locking": False, "has_dogs": "No",
        "dog_breeds": [], "solar_panels": "No", "ppc": "5", "fire_station_miles": None, "hydrant_1000ft": "Yes",
        "zip": "77248", "county": "Harris", "dwelling_amount": None, "dwelling_type": "House",
        "harris_east_146": "Unknown"}


@pytest.fixture
def run(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))
    asked = []

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        asked.extend(names)
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    monkeypatch.setattr(ec, "_complete", fake)

    def go(pd):
        asked.clear()
        res = {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}
        return res, list(asked)
    return go


@pytest.mark.parametrize("pd", [dict(LIAM), dict(LIAM, county="Bexar", zip="78201", harris_east_146=None)],
                         ids=["Harris", "Bexar"])
def test_a_carrier_held_only_on_a_blank_answer_gets_no_model_call(run, pd):
    res, asked = run(pd)
    r = res[OC]                                   # held on the station distance (the FPC table)
    assert r["status"] == "INSUFFICIENT_INFORMATION" and (r.get("diagnostics") or {}).get("held_by_code")
    assert not any("Occidental" in a and "HO3" in a for a in asked), asked
    assert "station" in r["reasons"][0].lower()


def test_liams_profile_makes_no_rule_check_call_when_every_open_carrier_is_held_on_blanks(run):
    res, asked = run(LIAM)
    held = [c for c, r in res.items() if (r.get("diagnostics") or {}).get("held_by_code")]
    assert held and asked == []
    assert ec.LAST_CALL_USAGE.get("pilot") is None


def test_a_row_the_model_can_decide_still_goes_to_the_rule_check():
    o = {"X-1": ("OPEN", "ambiguous: the readings disagree"), "X-2": ("OPEN", "station distance")}
    assert not rv.only_blank_holds(o)
    assert rv.only_blank_holds({"X-2": ("OPEN", "station distance"), "X-3": ("PASS", "")})
