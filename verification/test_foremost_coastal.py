"""Round 38 step 4 (Liam, 2026-10-11): Foremost was Not eligible on his LANDLORD (Katy 77493, Harris, Tier 2, Tenant
Occupied, LLC) on FOD-055, whose reason said TDP-3 "appears to be restricted". No Ineligible may rest on "appears to
be". The decision is made in code (FOD-055: county in the 28-county list), and the guide is clear -- p.20 "Coastal
Areas: The following counties are entirely restricted" (no program qualifier; Harris is listed) with an exception
only for "Foremost Choice Home (excluding Fort Bend and Harris Counties), HOA, TDP1, DF6". The row is now RULE with
a plain reason. The verdict follows the county, not the coastal tier. Zero API."""
import csv
import glob
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import eligibility_check as ec  # noqa: E402
from test_held_reasons import LANDLORD  # noqa: E402

pytestmark = pytest.mark.retrieval
FOREMOST = "Foremost_DP3_and_HO3_-_07.01.2026"
HEDGE = re.compile(r"\b(appears? to|seems? to|likely|probably|presumably)\b", re.I)


@pytest.fixture
def run(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), {
            "input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    monkeypatch.setattr(ec, "_complete", fake)
    return lambda **kw: {r["carrier"]: r for r in ec.check_eligibility(dict(LANDLORD, **kw))}[FOREMOST]


def _fod055(r):
    return [x for x in r["reasons"] if x.startswith("[FOD-055]")]


def test_liams_katy_landlord_is_declined_on_the_coastal_list_in_plain_words(run):
    r = run()
    assert r["status"] == "INELIGIBLE"
    reason = _fod055(r)[0]
    assert not HEDGE.search(reason), reason
    assert "Harris" in reason and "not TDP-3" in reason


@pytest.mark.parametrize("county", ["Montgomery", "Fort Bend", "Galveston"])   # in the 28; only Galveston in FOD-053
def test_a_tdp3_rental_in_another_coastal_county_is_declined_too(run, county):
    r = run(county=county, zip="", harris_east_146=None)
    assert r["status"] == "INELIGIBLE" and _fod055(r), r["reasons"]


@pytest.mark.parametrize("county", ["Bexar", "Travis"])
def test_a_tdp3_rental_inland_is_not_declined_on_the_coastal_list(run, county):
    assert not _fod055(run(county=county, zip="", coastal_tier="Not Coastal", harris_east_146=None))


@pytest.mark.parametrize("tier", ["Tier 1", "Tier 2", "Not Coastal"])
def test_the_verdict_follows_the_county_not_the_tier(run, tier):
    assert run(coastal_tier=tier)["status"] == "INELIGIBLE"
    assert not _fod055(run(coastal_tier=tier, county="Travis", zip="", harris_east_146=None))


def test_a_blank_county_never_declines_on_the_coastal_list(run):
    r = run(county="", zip="", harris_east_146=None)
    assert not _fod055(r) or r["status"] != "INELIGIBLE"


def _deciding_rows():
    maps = {}
    for f in glob.glob(os.path.join(HERE, "..", "rules_data", "*field_map.csv")):
        with open(f, encoding="utf-8-sig") as fh:
            maps.update({m["row_id"]: m for m in csv.DictReader(l for l in fh if not l.startswith("#"))})
    for f in glob.glob(os.path.join(HERE, "..", "rules_data", "carrier_rules_*.csv")):
        with open(f, encoding="utf-8-sig") as fh:
            for r in csv.DictReader(l for l in fh if not l.startswith("#")):
                m = maps.get(r["Rule ID"])
                if r.get("Effect") == "DECLINES" and m and m["field"] not in ("NONE", "") and m["test"] != "always":
                    yield r, m


def test_no_row_that_can_decline_says_appears_or_likely():
    bad = [(r["Rule ID"], r["Plain rule"][:100]) for r, m in _deciding_rows()
           if HEDGE.search(r["Plain rule"]) and not m["test"].startswith("FACT(")]
    assert bad == []
