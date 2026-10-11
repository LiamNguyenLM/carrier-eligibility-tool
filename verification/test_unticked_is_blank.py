"""Round 37 follow-up (Liam, 2026-10-11): an unticked County or Coverage A box means the same as a blank one, for
every carrier. On Railway his Harris profile (ZIP 77248 pre-filled, both boxes unticked) gave Chubb Eligible --
the unticked topics were skipped, so Chubb's territory rows and Coverage A hold never ran. Now an unticked County
(and its ZIP and East-of-146 answer) or Coverage A is read as blank, so Chubb's and Sage's named holds still
fire. Zero API: the model is a fake that answers every carrier it is asked about from the prompt alone."""
import hashlib
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import eligibility_check as ec  # noqa: E402
import topics  # noqa: E402
from profiles import LIVE_PROFILE, STANDARD_PROFILE  # noqa: E402

pytestmark = pytest.mark.retrieval
CHUBB = "CHUBB_HO_-_05.22.2026"
LIAM = {"year_built": 1994, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "pool_fence_4ft": False, "pool_gate_locking": False, "has_dogs": "No",
        "dog_breeds": [], "solar_panels": "No", "ppc": "5", "fire_station_miles": None, "hydrant_1000ft": "Yes",
        "zip": "77248", "county": "Harris", "harris_east_146": "Unknown", "dwelling_amount": None,
        "dwelling_type": "House"}
PROFILES = {
    "liam_harris": LIAM,
    "liam_harris_500k": dict(LIAM, dwelling_amount=500000),
    "standard_bexar": dict(STANDARD_PROFILE, county="Bexar", zip="78205", dwelling_amount=350000),
    "live_collin": dict(LIVE_PROFILE, dwelling_amount=1200000),
}
ALL = list(topics.TOPIC_KEYS)


@pytest.fixture
def live(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))
    prompts = []

    def fake(system, user, max_tokens):
        # deterministic from the prompt: the same prompt gets the same answer
        prompts.append(user)
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        h = int(hashlib.sha256(user.encode()).hexdigest(), 16)
        status = ("ELIGIBLE", "INSUFFICIENT_INFORMATION")[h % 2]
        return json.dumps({"carriers": [{"carrier": n, "status": status, "flaw_count": 0, "reasons": ["fixture"],
                                         "citations": [], "missing_info": ["Distance to fire station"]
                                         if status != "ELIGIBLE" else [], "notes": ""} for n in names]}), {
            "input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    monkeypatch.setattr(ec, "_complete", fake)
    return prompts


def _run(prompts, pd, checked):
    prompts.clear()
    res = ec.check_eligibility(dict(pd), checked_topics=list(checked))
    return {r["carrier"]: r["status"] for r in res}, list(prompts)


BLANK = {"county": {"county": "", "zip": ""}, "dwelling_amount": {"dwelling_amount": None}}


@pytest.mark.parametrize("profile", list(PROFILES))
@pytest.mark.parametrize("untick", [("county",), ("dwelling_amount",), ("county", "dwelling_amount")])
def test_an_unticked_box_gives_every_carrier_the_blank_verdict(live, profile, untick):
    pd = PROFILES[profile]
    blank_pd = dict(pd)
    for t in untick:
        blank_pd.update(BLANK[t])
    if "county" in untick:
        blank_pd.pop("harris_east_146", None)
    ticked_blank, p1 = _run(live, blank_pd, ALL)
    unticked, p2 = _run(live, pd, [t for t in ALL if t not in untick])
    assert unticked == ticked_blank
    assert p1 == p2                                    # the model is asked exactly the same question


def test_liams_profile_with_both_boxes_unticked_holds_chubb(live):
    unticked, _ = _run(live, LIAM, [t for t in ALL if t not in ("county", "dwelling_amount")])
    assert unticked[CHUBB] == "INSUFFICIENT_INFORMATION"
    res = {r["carrier"]: r for r in ec.check_eligibility(dict(LIAM), checked_topics=[
        t for t in ALL if t not in ("county", "dwelling_amount")])}
    assert any(m.startswith("Dwelling amount (Coverage A)") for m in res[CHUBB]["missing_info"])


@pytest.mark.parametrize("checked,want_pd,want_checked", [
    (None, LIAM, None),
    (ALL, LIAM, ALL),
    ([t for t in ALL if t != "county"], {**{k: v for k, v in LIAM.items() if k != "harris_east_146"},
                                         "county": "", "zip": ""}, ALL),
    ([t for t in ALL if t != "dwelling_amount"], dict(LIAM, dwelling_amount=None), ALL),
])
def test_unticked_is_blank(checked, want_pd, want_checked):
    pd, ck = ec.unticked_is_blank(dict(LIAM), checked)
    assert pd == want_pd
    assert (ck if ck is None else sorted(ck)) == (want_checked if want_checked is None else sorted(want_checked))
