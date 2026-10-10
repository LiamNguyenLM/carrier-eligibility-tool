"""Round 36 step 4 (Liam's Railway check, 2026-10-10: ZIP 77248, PPC 5, Not Coastal, hydrant Yes, Owner Occupied,
Individual Owner, built 1994, no pool, no solar, House; County blank because 77248 is not in the ZIP table).
Allied was held on "Insurance score" and Progressive HO3 on "County" (its Hidalgo / Webb rule).

Found: with the rules pilot ON (8113499) both are decided in code -- Eligible, PRO-072's blank County and
ALL-209's insurance score among the "also confirm" notes -- and Sage Auros is held on County. Both holds
reproduce exactly with the pilot OFF, where the main model call judges every carrier (two local runs: Allied
held on "Insurance score" + "Coverage A limit" once, Progressive on "County" twice, 72-73 s each). On that
path the hold guard had no entry for an insurance score, and kept a model's "County" item as a form field
even when County was blank. Fixed in code for the model path:
  a. NOT_ASKED gains insurance / credit score, coverages B-F, firewalls / unit separation (the last two from
     the round 34-36 outputs);
  b. a model item on a blank County / Coverage A is a confirm note (Liam, 2026-10-03), except the named
     holds: Sage's territory and CHUBB.
Zero API."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402
import hold_guard  # noqa: E402

pytestmark = pytest.mark.retrieval

# what app.py built from Liam's inputs with "Select All" (captured through AppTest, round 36)
LIAM = {"year_built": 1994, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "pool_fence_4ft": False, "pool_gate_locking": False, "has_dogs": "No",
        "dog_breeds": [], "solar_panels": "No", "ppc": "5", "fire_station_miles": None, "hydrant_1000ft": "Yes",
        "zip": "77248", "county": "", "dwelling_amount": None, "dwelling_type": "House"}
LIAM_CHECKED = ["ppc", "coastal", "home_age", "roof_age", "roof_type", "roof_shape", "construction", "plumbing",
                "pool", "dogs", "solar", "county", "dwelling_amount"]
ALLIED, PROG, AUROS, CHUBB = ("Allied_Trust_HO3", "Progressive_HO3_-_04.01.2026", "Sage_-_Auros_HO3",
                              "CHUBB_HO_-_05.22.2026")
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def run(answers, profile=LIAM, checked=LIAM_CHECKED):
    """check_eligibility with each carrier the model is asked about answered from answers (else ELIGIBLE)."""
    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        recs = [dict({"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"], "citations": [],
                      "missing_info": [], "notes": ""}, **answers.get(n, {})) for n in names]
        return json.dumps({"carriers": recs}), dict(USAGE)
    real = ec._complete
    ec._complete = fake
    try:
        return {r["carrier"]: r for r in ec.check_eligibility(dict(profile), checked_topics=list(checked))}
    finally:
        ec._complete = real


def held(*items):
    return {"status": "INSUFFICIENT_INFORMATION", "flaw_count": 0, "reasons": ["fixture hold"],
            "missing_info": list(items)}


# ---------------------------------------------------------------- a. the synonym table

@pytest.mark.parametrize("item", ["Insurance score", "Insurance Score", "Applicant's insurance score",
                                  "Credit-based insurance score", "Named insured credit report",
                                  "Credit score of the applicant", "Insurance-score tier"])
def test_an_insurance_or_credit_score_is_never_asked(item):
    # (c) is what matters; "Named insured ..." is found by the title / deed entry first
    assert hold_guard.classify(item)[0] == "c"
    assert hold_guard.classify(item.replace("Named insured", "Applicant"))[1] == "insurance / credit score"


@pytest.mark.parametrize("item,want", [
    ("Coverage C amount", "c"), ("Personal property limit", "c"), ("Cov. D amount", "c"),
    ("Fire wall between units", "c"), ("Firewall confirmation if townhouse", "c"),
    ("Fire division family unit count", "c"), ("Unit configuration", "c"),
    # unchanged: Coverage A is a form field, even beside another coverage
    ("Coverage A amount", "a"), ("Coverage A and C amounts", "a"), ("Coverage A limit", "a"),
    # unchanged: Liam's named Sage FPC holds stay holds
    ("Central station fire alarm", "unknown"), ("Visibility from main public road", "unknown"),
])
def test_the_other_items_the_round_34_to_36_outputs_held_on(item, want):
    assert hold_guard.classify(item)[0] == want


# ---------------------------------------------------------------- the exact scenario, model path (pilot OFF)

def test_liams_check_on_the_model_path_holds_only_sage_and_chubb():
    assert not ec.RULES_PILOT                         # the tests' default: every carrier in the main call
    res = run({ALLIED: held("Insurance score", "Coverage A limit"), PROG: held("County"),
               AUROS: held("Driving distance to fire station", "County"), CHUBB: held("County")})
    a, p = res[ALLIED], res[PROG]
    assert a["status"] == "ELIGIBLE" and a["missing_info"] == []
    assert "Confirm (not asked by the form; never a hold): Insurance score." in a["notes"]
    assert hold_guard.BLANK_NOTE + "Coverage A limit." in a["notes"]
    assert p["status"] == "ELIGIBLE" and p["missing_info"] == []
    assert hold_guard.BLANK_NOTE + "County." in p["notes"]
    # the named holds: Sage's territory (the model's own "County" item is kept for it), CHUBB
    assert res[AUROS]["status"] == "INSUFFICIENT_INFORMATION"
    assert any(re.match(r"county\b", m, re.I) for m in res[AUROS]["missing_info"])
    assert res[CHUBB]["status"] == "INSUFFICIENT_INFORMATION"
    assert any(re.match(r"county\b", m, re.I) for m in res[CHUBB]["missing_info"])


@pytest.mark.parametrize("item", ["County (Hidalgo or Webb exclusion)", "Property county",
                                  "County location (not Hidalgo or Webb)"])
def test_other_wordings_of_a_blank_county_are_notes_too(item):
    res = run({PROG: held(item)})
    assert res[PROG]["status"] == "ELIGIBLE" and item in res[PROG]["notes"]


@pytest.mark.parametrize("item", ["Dwelling amount", "Coverage A dwelling limit"])
def test_a_blank_coverage_a_is_a_note_except_for_chubb(item):
    res = run({ALLIED: held(item), CHUBB: held(item)})
    assert res[ALLIED]["status"] == "ELIGIBLE"
    assert res[CHUBB]["status"] == "INSUFFICIENT_INFORMATION"


def test_a_county_the_form_gave_is_not_released():
    res = run({PROG: held("County")}, profile=dict(LIAM, county="Harris", zip="77002"))
    assert res[PROG]["status"] == "INSUFFICIENT_INFORMATION" and res[PROG]["missing_info"] == ["County"]


def test_a_blank_county_never_frees_a_card_held_on_something_else():
    res = run({PROG: held("County", "Distance to fire station")})
    assert res[PROG]["status"] == "INSUFFICIENT_INFORMATION"
    assert res[PROG]["missing_info"] == ["Distance to fire station"]
    assert hold_guard.BLANK_NOTE + "County." in res[PROG]["notes"]


# ---------------------------------------------------------------- the live configuration (pilot + batches ON)

@pytest.fixture
def live(monkeypatch):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)


def test_with_the_live_configuration_code_decides_allied_and_progressive(live):
    res = run({})
    for c, row in ((ALLIED, "ALL-209"), (PROG, "PRO-072")):
        r = res[c]
        assert r.get("rules_table") and r["status"] == "ELIGIBLE", (c, r["status"], r.get("missing_info"))
        assert any(row in n for n in r.get("also_confirm") or []), c
    assert res[AUROS]["status"] == "INSUFFICIENT_INFORMATION"
    assert any(m.startswith("County -- ") for m in res[AUROS]["missing_info"])
