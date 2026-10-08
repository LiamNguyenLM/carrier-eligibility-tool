"""Round 30 step 2 (Liam, 2026-10-08, decision 2): the project rule on the rules table too -- a
fact the form never asks is a "Confirm:" note, never a hold. Zero API.

  (a) a row open on a BLANK FORM FIELD still holds (station distance, PPC N/A, plumbing Unknown,
      an unticked pool box, a blank primary-home answer);
  (b) a row open ONLY on a fact the form never asks (FACT(...)) is a NOTE: "Confirm: <fact>
      ([row] <the guide's rule>)", and the card's status comes from its other rows;
  (c) holds Liam decided by name stay: the Sage FPC blank distance (2026-10-07) -- the gate's
      blank form field, so it is (a) in the evaluator -- and the pipeline's Sage county and CHUBB
      holds, which are not map lines (test_eligibility_matrix.py keeps those).
A row with a reading that FAILS, or two readings that disagree (AMBIGUOUS), is not touched."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval

BASE = {"year_built": 2005, "roof_age": 5, "roof_type": "Architectural Shingle", "roof_shape": "Gable",
        "construction_type": "Masonry", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "aggressive_breed": "No", "solar_panels": "No",
        "ppc": "3", "dwelling_type": "House", "county": "Bexar", "dwelling_amount": 450000,
        "fire_station_miles": "2", "hydrant_1000ft": "Yes"}


def _row(rid, **pd):
    return ev.evaluate_row(ev._map()[rid], ev.facts(dict(BASE, **pd)))


# -- (b): the round 29 holds the prompt names, each now a confirm note ------------------------------
B_CASES = [
    ("ARA-049", {"plumbing_type": "PEX"}, "no exposed water lines"),           # "are the water lines exposed"
    ("ARB-046", {"plumbing_type": "PEX"}, "no exposed water lines"),
    ("LIB-033", {"year_built": 1970}, "wiring"),                                # fuses / knob and tube / aluminum
    ("TWI-011", {"ownership_type": "Trust"}, "trustee"),
    ("TRV-017", {"ownership_type": "Trust"}, "business"),
    ("SLL-043", {"occupancy_type": "Seasonal"}, "United States"),               # country of the primary home
    ("SAG-004", {"occupancy_type": "Seasonal"}, "checked"),                     # property checks while away
    ("SUR-018", {"occupancy_type": "Secondary Home"}, "checked"),
    ("WIL-018", {"occupancy_type": "Seasonal"}, "checked"),
]


@pytest.mark.parametrize("rid,pd,word", B_CASES, ids=[c[0] for c in B_CASES])
def test_a_never_asked_fact_is_a_confirm_note(rid, pd, word):
    out, detail = _row(rid, **pd)
    assert out == "NOTE" and detail.startswith("confirm: ")
    assert word.lower() in (detail + " " + ev._map()[rid]["test"]).lower()


@pytest.mark.parametrize("canon,wb,pd,rid", [
    ("ARI_(HOA+)", "ARI HOA / HOA Plus", {"plumbing_type": "PEX"}, "ARA-049"),
    ("Liberty_Mutual_HO3_-_02.21.2026", "Liberty Mutual / Safeco HO3", {"year_built": 1970}, "LIB-033")])
def test_the_card_is_eligible_with_the_consequence_visible(canon, wb, pd, rid):
    outcomes = ev.evaluate_carrier(canon, dict(BASE, **pd), wb=wb)
    rec, decided = ev.code_record(canon, outcomes)
    assert decided and rec["status"] == "ELIGIBLE", rec
    line = next(n for n in rec["also_confirm"] if f"[{rid}]" in n)
    assert line.startswith("Confirm: ") and ev._rules()[rid]["Plain rule"] in line   # the guide's rule shows


# -- (a): blank form fields still hold ----------------------------------------------------------
@pytest.mark.parametrize("rid,pd", [
    ("ARA-049", {"plumbing_type": "Unknown"}),                     # plumbing blank + the fact: the field decides
    ("SAG-073", {"ppc": "2", "fire_station_miles": "", "hydrant_1000ft": "No"}),   # FPC: blank distance (c)
    ("MER-003", {"occupancy_type": "Seasonal"}),                   # primary-home answer blank (step 1)
    ("SWY-007", {"occupancy_type": "Seasonal", "primary_home_miles": ""}),
])
def test_a_blank_form_field_still_holds(rid, pd):
    assert _row(rid, **pd)[0] == "OPEN"


# -- (c): held by name ------------------------------------------------------------------------
def test_the_fpc_rows_hold_with_the_distance_blank_or_known():
    # Liam 2026-10-06, re-affirmed 2026-10-08: the FPC conditions hold whatever the distance (class c)
    assert _row("SAG-073", ppc="2", fire_station_miles="", hydrant_1000ft="No")[0] == "OPEN"
    assert _row("SAG-073", ppc="2", fire_station_miles="3", hydrant_1000ft="No")[0] == "OPEN"
    assert _row("SUR-112", ppc="2", fire_station_miles="7")[0] == "OPEN"
    assert _row("SAG-073", ppc="2", fire_station_miles="3", hydrant_1000ft="Yes")[0] == "N/A"


def test_every_named_hold_is_an_fpc_or_chubb_territory_line():
    m = ev._map()
    assert len(ev.FPC_TABLE_HOLDS) == 35
    for rid in ev.FPC_TABLE_HOLDS:
        assert "fire_station_miles" in m[rid]["gate"] or "hydrant_1000ft" in m[rid]["gate"], rid
    for rid in ev.CHUBB_TERRITORY_HOLDS:
        assert m[rid]["field"].startswith("county") and "FACT(" in m[rid]["test"], rid


@pytest.mark.parametrize("rid,pd", [("CHU-043", {"county": "Galveston"}), ("CHU-047", {"county": "Galveston",
                                     "occupancy_type": "Seasonal"}), ("CHU-044", {"county": "Harris"})])
def test_chubb_coastal_sub_territories_still_hold(rid, pd):
    assert _row(rid, **pd)[0] == "OPEN"


# -- never touched: a failing reading, and AMBIGUOUS ----------------------------------------------
@pytest.mark.parametrize("rid,pd,want", [
    ("CDP-023", {"roof_shape": "Flat", "roof_type": "Flat/Built-Up"}, "FAIL"),   # built-up: not poured concrete
    ("SAG-075", {"ppc": "6", "fire_station_miles": "3", "hydrant_1000ft": "No", "year_built": 1980}, "FAIL"),
    ("ARA-007", {"roof_type": "Metal"}, "OPEN"),                                   # AMBIGUOUS: the model decides
])
def test_a_failing_or_ambiguous_row_is_not_turned_into_a_note(rid, pd, want):
    out, detail = _row(rid, **pd)
    assert out == want
    if want == "OPEN":
        assert detail.startswith("ambiguous:")


def test_an_open_row_never_mixes_a_note_with_a_blank_field():
    # every map line in all four tables: a NOTE from this rule rests only on never-asked facts
    pd = dict(BASE, plumbing_type="Unknown", ppc="N/A", fire_station_miles="", hydrant_1000ft="Unknown",
              occupancy_type="Seasonal", ownership_type="Trust", has_dogs="Yes", roof_age=20,
              roof_type="Metal", coastal_tier="Tier 1")
    f = ev.facts(pd)
    for rid, m in ev._map().items():
        out, detail = ev.evaluate_row(m, f)
        if out == "NOTE" and detail.startswith("confirm: "):
            _, unknown = ev.evaluate_expr(m["gate"] or "always", f)
            assert not any(u in f for u in unknown), rid


# -- correction 3 (Liam, 2026-10-08): an unmet TWICO requirement declines, it is not a referral -------
@pytest.mark.parametrize("answer,want", [("Chubb", "INELIGIBLE"), ("Other carrier", "INELIGIBLE"),
                                         ("TWICO", None), ("Unknown", None)])
def test_twico_secondary_home_without_a_twico_primary_is_ineligible_not_refer(answer, want):
    # "Secondary must have an associated primary written in Twico." (TWI-005; effect CONDITION in the
    # workbook, which a failed row shows as Refer -- the map line's outcome is DECLINES)
    pd = dict(BASE, occupancy_type="Seasonal", primary_home_carrier=answer)
    rec, _ = ev.code_record("TWICO_HO3", ev.evaluate_carrier("TWICO_HO3", pd))
    cites = [x for x in rec["reasons"] if x.startswith("[TWI-005]")]
    if want:
        assert rec["status"] == want and cites and "declines" in cites[0]
    else:
        assert not cites and rec["status"] != "REFER"
