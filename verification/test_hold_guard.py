"""Round 29 step 1 (Liam, 2026-10-08): the hold guard. A fact the intake form
never asks is "confirm", never a hold. Zero API."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import eligibility_check as ec  # noqa: E402
import hold_guard as hg  # noqa: E402
from profiles import STANDARD_PROFILE  # noqa: E402

pytestmark = pytest.mark.retrieval


# -- classification -------------------------------------------------------------
@pytest.mark.parametrize("item,kind", [
    # (c) facts the form does not collect -- two phrasings each, from round 28's run data
    ("Roof remaining useful life", "c"), ("Remaining useful life of roof", "c"),
    ("Primary heating/cooling system type", "c"), ("Thermostatically controlled central heating type", "c"),
    ("Brush or wind hazard area status", "c"), ("Hillside, brushfire, or landslide exposure", "c"),
    ("Number of mortgages", "c"), ("Number of mortgagees", "c"),
    ("Prior liability or fire loss history", "c"), ("Water loss history", "c"),
    ("Knob and tube or non-breaker wiring status", "c"), ("Electrical service amperage", "c"),
    ("Commercial exposure within 300 feet", "c"), ("Adjacent commercial exposure", "c"),
    ("Acreage", "c"), ("Lot acreage", "c"),
    ("Plumbing update date", "c"), ("Evidence of plumbing update", "c"),
    ("Solar panel mounting location (roof or ground)", "c"), ("Solar panel mounting type (ground-mounted vs. roof-mounted)", "c"),
    ("Flood zone designation", "c"), ("Flood zone", "c"),
    ("Prior cancellation or non-renewal history", "c"), ("Any lapse in coverage", "c"),
    ("Insured to 100% replacement cost confirmation", "c"), ("Replacement cost estimate for Coverage A", "c"),
    # (a) form fields -- blank or unconfirmed, the agent can answer them on the form
    ("Pool fence height", "a"), ("Pool gate type (self-latching)", "a"), ("Coverage A amount", "a"),
    ("Miles to fire station", "a"), ("Feet to nearest hydrant", "a"), ("Distance to Gulf of Mexico or coastal bay", "a"),
    ("Applicable roof-age timeframe for composition shingles", "a"), ("Confirm dwelling is a condominium/unit-owner risk", "a"),
    # (b) written by code
    ("County -- this guide only writes in specific counties: ...", "b"),
    ("Dwelling amount (Coverage A) -- Chubb ...", "b"),
    ("Pool enclosure specifics are not confirmed by the intake value \"In Ground - Fenced\": fence height.", "b"),
    ("station distance if not given -- [SUR-112] Protection class 1-3 ...", "b"),
    # round 28 wordings that are not property facts, or that the form's answers already cover: kept
    ("Foremost HO3 eligibility rules for galvanized plumbing and heating", "unknown"),
    ("Heating and roof requirements for this program", "unknown"),
    ("Roof material category for replacement cost table", "a"), ("Roof validation for replacement cost", "a"),
    ("Vacancy status", "a"),
    ("Wood or coal stove presence", "c"), ("Prior coverage lapses", "c"), ("Electrician circuit panel check date", "c"),
    # unclassified: kept, as (a)
    ("Foremost HO3 eligibility guidelines", "unknown"), ("Property-specific underwriting approval", "unknown"),
])
def test_classify(item, kind):
    assert hg.classify(item)[0] == kind


def test_an_item_code_added_to_a_model_record_is_code_made():
    assert hg.classify("Number of mortgages", model_items=["Roof remaining useful life"])[0] == "b"
    assert hg.classify("Number of mortgages", model_items=["Number of mortgages"])[0] == "c"


# -- the guard on a record --------------------------------------------------------
def rec(status="INSUFFICIENT_INFORMATION", items=(), **kw):
    r = {"carrier": "Liberty_Mutual_HO3_-_02.21.2026", "status": status, "flaw_count": 0,
         "reasons": ["Brush area unknown."], "citations": [], "missing_info": list(items), "notes": ""}
    r["_model_missing_info"] = list(items)
    r.update(kw)
    return r


def run(*records):
    stats = {}
    hg.apply(list(records), ec._decide_by_code, ec._append_note, stats)
    return stats


def test_only_not_asked_facts_release_the_hold_with_confirm_notes():
    r = rec(items=["Brush or wind hazard area status", "Number of mortgages"])
    stats = run(r)
    assert r["status"] == "ELIGIBLE" and r["missing_info"] == [] and r["flaw_count"] == 0
    assert "Confirm (not asked by the form; never a hold): Brush or wind hazard area status; Number of mortgages." \
        in r["notes"]
    assert r["_code_decisions"][0]["status"] == "ELIGIBLE" and stats["released"] == 1
    assert "_model_missing_info" not in r


def test_mixed_items_move_only_the_not_asked_ones():
    r = rec(items=["Pool fence height", "Roof remaining useful life", "Foremost HO3 eligibility guidelines"])
    run(r)
    assert r["status"] == "INSUFFICIENT_INFORMATION"
    assert r["missing_info"] == ["Pool fence height", "Foremost HO3 eligibility guidelines"]
    assert "Roof remaining useful life" in r["notes"]


def test_unknown_wording_keeps_the_hold():
    r = rec(items=["Foremost HO3 eligibility guidelines"])
    run(r)
    assert r["status"] == "INSUFFICIENT_INFORMATION" and r["missing_info"] == ["Foremost HO3 eligibility guidelines"]
    assert r["notes"] == ""


@pytest.mark.parametrize("extra", [
    {"_code_decisions": [{"status": "INSUFFICIENT_INFORMATION", "reason": "No Coverage A given: Chubb's tier...",
                          "citation": None}]},                                        # CHUBB / county code hold
    {"_code_decisions": [{"status": "INSUFFICIENT_INFORMATION", "reason": "Sage FPC table: ...", "citation": None}]},
    {"rules_table": True},                                                             # the rules table's own hold
    {"reasons": ["[SAG-074] condition not met"]},                                       # cites a rules-table row
])
def test_code_made_and_rules_table_holds_are_untouched(extra):
    r = rec(items=["Visible from the main public road", "Central station fire alarm", "Number of mortgages"], **extra)
    before = dict(r, missing_info=list(r["missing_info"]))
    run(r)
    assert r["status"] == before["status"] and r["missing_info"] == before["missing_info"] and r["notes"] == ""


@pytest.mark.parametrize("status", ["INELIGIBLE", "REFER", "ELIGIBLE"])
def test_other_statuses_are_never_touched(status):
    r = rec(status=status, items=["Number of mortgages"])
    run(r)
    assert r["status"] == status and r["missing_info"] == ["Number of mortgages"]


def test_the_synonym_table():
    facts, patterns = hg.synonym_count()
    assert facts >= 20 and patterns >= 80
    assert set(hg.intake_fields.FORM_FIELDS) >= {"year_built", "roof_age", "plumbing_type", "county",
                                                 "dwelling_amount", "fire_station_miles", "hydrant_1000ft"}


# -- in the pipeline --------------------------------------------------------------
USAGE = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}


def _pipeline(pd, items_for):
    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user))) or re.findall(r"--- (.+?) \(rule check\) ---", user)
        recs = [{"carrier": n, "status": "INSUFFICIENT_INFORMATION" if items_for(n) else "ELIGIBLE", "flaw_count": 0,
                 "reasons": ["fixture"], "citations": [], "missing_info": items_for(n), "notes": ""} for n in names]
        return json.dumps({"carriers": recs}), dict(USAGE)
    real = ec._complete
    ec._complete = fake
    try:
        return {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}
    finally:
        ec._complete = real


def test_in_the_pipeline_a_not_asked_hold_becomes_eligible_and_the_county_hold_stays():
    lib, sage = "Liberty_Mutual_HO3_-_02.21.2026", "Sage_-_SURE_HO-3_-_01.31.2026"
    res = _pipeline(dict(STANDARD_PROFILE, county="", dwelling_type="House"),
                    lambda n: ["Brush or wind hazard area status"] if n in (lib, sage) else [])
    assert res[lib]["status"] == "ELIGIBLE" and res[lib].get("decided_by_code")
    assert "Confirm (not asked by the form; never a hold): Brush or wind hazard area status." in res[lib]["notes"]
    assert res[sage]["status"] == "INSUFFICIENT_INFORMATION"                 # the Sage county hold (code) stays
    assert any(m.startswith("County") for m in res[sage]["missing_info"])
    assert not any("_model_missing_info" in r for r in res.values())
