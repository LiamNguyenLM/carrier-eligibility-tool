"""Round 38 step 1 (Liam, 2026-10-11): on his LANDLORD profile (PPC 7, station 4 miles, hydrant Unknown) all three
SageSure DP3 cards said "Held: if the fire station is more than 5 miles away ... Confirm the distance." -- but he
had entered 4 miles; what was open was the hydrant and the table's visibility / alarm / 10-ft access conditions. A
held reason is now built from the rows that hold the card and the facts they still lack, and names the 5-mile rule
only when the distance is blank. Zero API."""
import itertools
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import eligibility_check as ec  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
LANDLORD = {"year_built": 1986, "roof_age": 17, "roof_type": "Composition Shingle", "roof_shape": "Gable",
            "construction_type": "Frame", "plumbing_type": "PVC", "occupancy_type": "Tenant Occupied",
            "ownership_type": "LLC", "coastal_tier": "Tier 2", "swimming_pool": "No Pool", "pool_accessories": "None",
            "pool_fence_4ft": False, "pool_gate_locking": False, "has_dogs": "No", "dog_breeds": [],
            "solar_panels": "No", "ppc": "7", "fire_station_miles": 4.0, "hydrant_1000ft": "Unknown",
            "zip": "77493", "county": "Harris", "harris_east_146": "Unknown", "dwelling_amount": None,
            "dwelling_type": "House", "losses_5yr": "1", "loss_types": ["Theft"], "loss_year": 2022, "losses_3yr": "0"}
HOME = dict(LANDLORD, occupancy_type="Owner Occupied", ownership_type="Individual Owner", losses_5yr="0")
SAGE = [c for c in rv.PILOT_CARRIERS.values() if c.startswith("Sage_")] + \
       [c for b in ("sage", "dp") for c in rv.BATCHES[b]["carriers"].values() if c.startswith("Sage_")]
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


@pytest.fixture
def live(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    monkeypatch.setattr(ec, "_complete", fake)


def test_liams_landlord_reason(live):
    res = {r["carrier"]: r for r in ec.check_eligibility(dict(LANDLORD))}
    for c in ("Sage_-_Occidental_DP3", "Sage_-_SURE_DP-3_-_01.31.2026", "Sage_-_SafePort_DP-3_-_01.31.2026"):
        reason = res[c]["reasons"][0]
        assert res[c]["status"] == "INSUFFICIENT_INFORMATION"
        assert reason.startswith("Held: this guide's fire-protection table needs to know whether a hydrant is within "
                                 "1,000 ft"), reason
        assert "5 miles" not in reason and "distance" not in reason


@pytest.mark.parametrize("base", ["landlord", "home"])
@pytest.mark.parametrize("miles,hydrant", list(itertools.product([None, 4.0, 7.0], ["Yes", "No", "Unknown"])))
def test_no_held_reason_mentions_an_answered_fact(live, base, miles, hydrant):
    pd = dict(LANDLORD if base == "landlord" else HOME, fire_station_miles=miles, hydrant_1000ft=hydrant)
    res = {r["carrier"]: r for r in ec.check_eligibility(pd)}
    held = {c: r["reasons"][0] for c, r in res.items() if c in SAGE and r["status"] == "INSUFFICIENT_INFORMATION"
            and r["reasons"] and r["reasons"][0].startswith("Held:")}
    for c, reason in held.items():
        if miles is not None:
            assert "5 miles" not in reason and "fire station" not in reason, (c, reason)
        else:
            assert "5 miles" in reason, (c, reason)
        if hydrant != "Unknown":
            assert "hydrant" not in reason, (c, reason)


def test_the_open_fact_names_only_what_is_still_open():
    assert rv._open_fact_now("station / hydrant distance if not given; fire losses", ["hydrant_1000ft"]) == \
        "hydrant within 1,000 ft if not given; fire losses"
    assert rv._open_fact_now("station / hydrant distance if not given", ["fire_station_miles"]) == \
        "station distance if not given"
    assert rv._open_fact_now("station / hydrant distance if not given", ["fire_station_miles", "hydrant_1000ft"]) == \
        "station / hydrant distance if not given"
    assert rv._open_fact_now("station / hydrant distance if not given; visibility, alarm, access", []) == \
        "visibility, alarm, access"
