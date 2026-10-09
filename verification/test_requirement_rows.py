"""Round 31 step 4 (Liam, 2026-10-08, decision 2): a requirement the form shows is NOT met is Ineligible,
unless the row's own guide text names an underwriting / referral / approval path (then Refer). Unknown /
blank behaves as before (a hold, or a confirm note); an unticked pool box is unknown, never "no".
Zero API. The full row list, with the words that decided each, is rules_evaluator.REQUIREMENT_OUTCOMES
(and REQUIREMENT_UNCHANGED for the rows left as they were)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval

BASE = {"year_built": 2010, "roof_age": 5, "roof_type": "Architectural Shingle", "roof_shape": "Gable",
        "construction_type": "Masonry", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "aggressive_breed": "No", "solar_panels": "No",
        "ppc": "3", "dwelling_type": "House", "county": "Bexar", "dwelling_amount": 450000,
        "fire_station_miles": "2", "hydrant_1000ft": "Yes"}
FENCED_UNTICKED = {"swimming_pool": "In Ground - Fenced"}


def _card(canon, **pd):
    rec, _ = ev.code_record(canon, ev.evaluate_carrier(canon, dict(BASE, **pd)))
    return rec


def _row(rid, **pd):
    return ev.evaluate_row(ev._map()[rid], ev.facts(dict(BASE, **pd)))[0]


def test_every_listed_row_is_a_mapped_line_and_the_list_is_complete():
    m = ev._map()
    assert all(rid in m for rid in ev.REQUIREMENT_OUTCOMES)
    # CHANGED 2026-10-09 (round 32 step 1, Claude review): ALL-061 is a coverage row now, not a requirement
    # row (55 -> 54). Was: == 55.
    assert len(ev.REQUIREMENT_OUTCOMES) + len(ev.REQUIREMENT_UNCHANGED) == 54
    assert "ALL-061" not in ev.REQUIREMENT_OUTCOMES and "ALL-061" not in ev.REQUIREMENT_UNCHANGED
    assert all(m[rid]["outcome_if_fail"] == out for rid, (out, _) in ev.REQUIREMENT_OUTCOMES.items())
    assert {out for out, _ in ev.REQUIREMENT_OUTCOMES.values()} == {"DECLINES", "REFERS_TO_UW"}


# -- Ineligible: no path named ------------------------------------------------------------------
@pytest.mark.parametrize("canon,row,pd", [
    ("CHUBB_HO_-_05.22.2026", "CHU-004", {"occupancy_type": "Seasonal", "primary_home_carrier": "Travelers"}),
    ("Sage_-_SURE_HO-3_-_01.31.2026", "SUR-019", {"ownership_type": "Trust", "occupancy_type": "Tenant Occupied"}),
    ("Sage_-_Vave_HO3_-_07.01.2026", "VAV-014", {"ownership_type": "Trust", "occupancy_type": "Tenant Occupied"}),
    ("Centauri_-_DP3_-_11.16.2022", "CDP-072", {"ownership_type": "LLC", "occupancy_type": "Seasonal"}),
    ("Swyfft_-_Benchmark_(Surplus)_HO3", "SBS-008", {"swimming_pool": "In Ground - Unfenced"}),
    ("Swyfft_-_Benchmark_(Admitted)_HO3", "SWY-035", {"swimming_pool": "Above Ground - Unfenced"}),
    ("Sage_-_SURE_HO-3_-_01.31.2026", "SUR-116", {"ppc": "6", "fire_station_miles": "7", "year_built": 1990}),
])
def test_an_unmet_requirement_with_no_path_named_is_ineligible(canon, row, pd):
    rec = _card(canon, **pd)
    assert rec["status"] == "INELIGIBLE", rec["reasons"]
    assert any(x.startswith(f"[{row}] declines") for x in rec["reasons"]), rec["reasons"]


# -- Refer: the row names an approval path ------------------------------------------------------
@pytest.mark.parametrize("canon,row", [("Progressive_HO3_-_04.01.2026", "PRO-051"),
                                       ("Progressive_DP3_-_10.01.2024", "PDP-103")])
def test_an_unmet_requirement_with_an_approval_path_is_refer(canon, row):
    pd = {"swimming_pool": "In Ground - Unfenced"}
    if canon.startswith("Progressive_DP3"):
        pd["occupancy_type"] = "Tenant Occupied"
    out = ev.evaluate_carrier(canon, dict(BASE, **pd))
    assert out[row][0] == "FAIL" and ev._map()[row]["outcome_if_fail"] == "REFERS_TO_UW"


# -- unknown / blank: as before -----------------------------------------------------------------
@pytest.mark.parametrize("row,pd", [("PRO-051", FENCED_UNTICKED), ("SWY-035", FENCED_UNTICKED),
                                    ("SBS-008", FENCED_UNTICKED),
                                    ("CHU-004", {"occupancy_type": "Seasonal", "primary_home_carrier": ""})])
def test_an_unticked_box_or_a_blank_answer_still_holds(row, pd):
    assert _row(row, **pd) == "OPEN"


def test_an_fpc_row_holds_on_its_unasked_conditions_and_declines_only_on_age_or_occupancy():
    band_c = {"ppc": "6", "fire_station_miles": "7"}
    assert _row("SUR-113", **band_c, year_built=2010) == "N/A"            # band B row, not C
    assert _row("SUR-114", **band_c, year_built=2010) == "OPEN"           # visibility / alarm / access: held
    assert _row("SUR-114", **band_c, year_built=1990) == "FAIL"           # age 25+: the form answers it
    assert _row("SUR-117", **band_c, occupancy_type="Seasonal") == "FAIL"


def test_one_failing_row_per_fact_for_an_unfenced_in_ground_swyfft_pool():
    out = ev.evaluate_carrier("Swyfft_-_Benchmark_(Admitted)_HO3", dict(BASE, swimming_pool="In Ground - Unfenced"))
    assert out["SWY-036"][0] == "FAIL" and out["SWY-035"][0] != "FAIL"


@pytest.mark.parametrize("row,pd,want", [("HDP-002", {"year_built": 1960}, "NOTE"),
                                         ("VDP-042", {"year_built": 1915}, "NOTE"),
                                         ("SLL-007", {"swimming_pool": "In Ground - Fenced",
                                                      "pool_accessories": "Slide only"}, "NOTE")])
def test_rows_the_form_cannot_show_unmet_are_unchanged(row, pd, want):
    assert row in ev.REQUIREMENT_UNCHANGED and _row(row, **pd) == want


def test_the_rules_check_prompt_shows_the_effect_code_applies():
    line = ev._row_line(ev._rules()["SUR-117"])
    assert " | DECLINES | " in line and " | CONDITION | " not in line


# -- round 32 step 1 (Claude review, 2026-10-09): ALL-061 is a coverage row, not a requirement ----
# Allied p.10: "Homes 76 years and older are subject to Limited Water Damage Coverage unless they have been
# completely re-plumbed above the slab within the last 20 years ... Copper tubing or PVC plumbing is
# required." Copper / PVC is what counts as the re-plumb; it is not a rule for writing the home.
@pytest.mark.parametrize("plumbing", ["PEX", "Other"])
def test_a_76_year_old_home_without_copper_or_pvc_is_not_declined_by_all_061(plumbing):
    out = ev.evaluate_carrier("Allied_Trust_HO3", dict(BASE, year_built=1945, plumbing_type=plumbing))
    assert "ALL-061" not in out and "ALL-061" not in ev._map()
    rec, _ = ev.code_record("Allied_Trust_HO3", out)
    assert not any("ALL-061" in x for x in rec["reasons"] + rec.get("citations", [])), rec["reasons"]


def test_galvanized_in_the_same_home_is_still_declined():
    # ALL-057 (every age) declines it; ALL-060 (76+) is a NOTE because its cure is a service inspection
    out = ev.evaluate_carrier("Allied_Trust_HO3", dict(BASE, year_built=1945, plumbing_type="Galvanized"))
    rec, _ = ev.code_record("Allied_Trust_HO3", out)
    assert rec["status"] == "INELIGIBLE" and any(x.startswith("[ALL-057] declines") for x in rec["reasons"])
    assert out["ALL-060"][0] == "NOTE"


def test_all_061_is_a_coverage_row_in_the_table():
    r = ev._rules()["ALL-061"]
    assert (r["Effect"], r["Tool handling"]) == ("COVERAGE_ONLY", "NOT_ELIGIBILITY")
    assert r["Review note"].startswith("CHANGED 2026-10-09")
