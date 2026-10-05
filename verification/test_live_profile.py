"""Round 26 (Liam, 2026-10-05): Liam's live check on Railway (27870a0) as a
fixed profile. Zero API: the model call is answered by a fake that returns
what the live run returned, so these tests pin the pipeline's handling of it.

LIVE: PPC 3; Owner Occupied; Individual; Year Built 2007; No Pool; PVC;
Solar Yes; ZIP 75094 -> Collin; House. Everything else unchecked."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402
from profiles import LIVE_PROFILE, LIVE_CHECKED  # noqa: E402

pytestmark = pytest.mark.retrieval

USAGE = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}
SAGE_FIVE = ["Sage_-_Auros_HO3", "Sage_-_SURE_HO-3_-_01.31.2026", "Sage_-_SafePort_HO-3_-_01.31.2026",
             "Sage_-_Wilshire_HO3_-_12.02.2025", "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026"]


def run_live(answer, profile=None, checked=None):
    """check_eligibility on LIVE with every carrier in the main prompt answered
    by answer(carrier) -> record fields. Returns ({carrier: record}, prompt)."""
    seen = {}

    def fake(system, user, max_tokens):
        seen["user"] = user
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)))
        recs = []
        for n in names:
            rec = {"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                   "citations": [], "missing_info": [], "notes": ""}
            rec.update(answer(n))
            recs.append(rec)
        return json.dumps({"carriers": recs}), dict(USAGE)

    real = ec._complete
    ec._complete = fake
    try:
        results = ec.check_eligibility(dict(profile or LIVE_PROFILE),
                                       checked_topics=list(checked or LIVE_CHECKED))
    finally:
        ec._complete = real
    return {r["carrier"]: r for r in results}, seen.get("user")


# What the live run returned for the Sage family: an INELIGIBLE on the
# territory for Trium, and Insufficient on fire-station items for the rest.
def live_sage_answer(name):
    if name.startswith("Sage_-_Trium"):
        return {"status": "INELIGIBLE", "flaw_count": 1,
                "reasons": ["Collin County is outside the stated territory."],
                "citations": [], "missing_info": []}
    if name in SAGE_FIVE:
        return {"status": "INSUFFICIENT_INFORMATION", "flaw_count": 0,
                "reasons": ["None states a flat ineligible outcome for PPC 3."],
                "missing_info": ["Driving distance to the responding fire station",
                                 "Distance to the nearest hydrant"]}
    return {}


# -- Step 1: buckets (Liam, 2026-10-05, decision A) --------------------------------
def test_the_five_sage_carriers_on_live_all_land_in_not_eligible():
    res, _ = run_live(live_sage_answer)
    buckets = ec.assign_buckets(list(res.values()))
    not_eligible = {r["carrier"] for r in buckets["not_eligible"]}
    assert set(SAGE_FIVE) <= not_eligible
    # Trium carries two flaws, the others one -- the split that put four of
    # them under "One Issue" on Liam's screen. It no longer matters.
    assert res[SAGE_FIVE[4]]["flaw_count"] == 2 and res[SAGE_FIVE[0]]["flaw_count"] == 1
    assert not any(r["carrier"] in SAGE_FIVE for r in buckets["refer"])


# -- Step 2: a code-decided verdict owns the card ----------------------------------
def test_sage_auros_on_live_shows_one_territory_reason_with_the_quote_and_no_missing_info():
    res, _ = run_live(live_sage_answer)
    r = res["Sage_-_Auros_HO3"]
    assert r["status"] == "INELIGIBLE"
    assert len(r["reasons"]) == 1
    assert r["reasons"][0].startswith("Collin County is outside this carrier's territory. The guide says:")
    assert '"' in r["reasons"][0]                            # the guide's own sentence, quoted
    assert r["missing_info"] == []
    assert not any("flat ineligible" in x for x in r["reasons"])
    # the model's own words are kept, off the card
    assert "None states a flat ineligible outcome for PPC 3." in r["diagnostics"]["model_reasons"]
    assert "Distance to the nearest hydrant" in r["diagnostics"]["model_missing_info"]


@pytest.mark.parametrize("carrier", SAGE_FIVE)
def test_every_sage_carrier_on_live_is_owned_by_the_territory_rule(carrier):
    res, _ = run_live(live_sage_answer)
    r = res[carrier]
    assert r["decided_by_code"] and r["missing_info"] == []
    assert [x for x in r["reasons"] if "outside this carrier's territory" in x] == r["reasons"]


def test_a_code_hold_keeps_its_missing_info_and_leads_with_the_code_reason():
    # County blank: the Sage county hold. A hold can still change, so the open
    # items stay; the code's reason is the first (and only) line.
    profile = dict(LIVE_PROFILE, county="", zip="")
    res, _ = run_live(lambda n: {"status": "ELIGIBLE", "reasons": ["PPC 3 is fine."],
                                 "missing_info": ["Distance to fire station"]}
                      if n == "Sage_-_Auros_HO3" else {}, profile=profile)
    r = res["Sage_-_Auros_HO3"]
    assert r["status"] == "INSUFFICIENT_INFORMATION"
    assert r["reasons"][0].startswith("No County given")
    assert any(m.startswith("County") for m in r["missing_info"])
    assert "Distance to fire station" in r["missing_info"]


def test_a_model_decided_record_is_untouched():
    res, _ = run_live(lambda n: {"status": "INSUFFICIENT_INFORMATION", "reasons": ["own reason"],
                                 "missing_info": ["own item"]} if n.startswith("Travelers") else {})
    t = [r for c, r in res.items() if c.startswith("Travelers")][0]
    assert t["reasons"] == ["own reason"] and t["missing_info"] == ["own item"]
    assert "diagnostics" not in t and not t.get("decided_by_code")
