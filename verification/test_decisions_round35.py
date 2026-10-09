"""Round 35 step 4 (Liam, 2026-10-09): decision 2 (Centauri HO3's CHO-013 -- an owner's Seasonal or Secondary
Home counts as owner-occupied; it passes with a confirm note) and decision 3 ("single family" includes a
Townhome; House and Townhome pass, only Condo fails). Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval
M = ev._map()


def row(rid, **pd):
    return ev.evaluate_row(M[rid], ev.facts(pd))[0]


@pytest.mark.parametrize("occupancy,want", [("Owner Occupied", "PASS"), ("Seasonal", "NOTE"),
                                            ("Secondary Home", "NOTE"), ("Tenant Occupied", "FAIL")])
def test_decision_2_centauri_ho3_owner_occupied_includes_the_owner_s_second_home(occupancy, want):
    assert row("CHO-013", occupancy_type=occupancy) == want
    assert "||" not in M["CHO-013"]["test"]


def test_decision_2_the_card_is_eligible_with_the_confirm_note():
    base = {"year_built": 2012, "roof_age": 5, "roof_type": "Architectural Shingle", "roof_shape": "Gable",
            "construction_type": "Masonry", "plumbing_type": "Copper", "ownership_type": "Individual Owner",
            "coastal_tier": "Not Coastal", "swimming_pool": "No Pool", "pool_accessories": "None", "has_dogs": "No",
            "solar_panels": "No", "ppc": "3", "dwelling_type": "House", "county": "Bexar", "dwelling_amount": 450000,
            "fire_station_miles": "2", "hydrant_1000ft": "Yes", "primary_home_carrier": "Other carrier"}
    for occupancy in ("Seasonal", "Secondary Home"):
        out = ev.evaluate_carrier("Centauri_-_HO3_-_05.01.2026", dict(base, occupancy_type=occupancy))
        assert out["CHO-013"][0] == "NOTE"
        assert any("CHO-013" in x for x in ev.also_confirm("Centauri_-_HO3_-_05.01.2026", out))


SINGLE_FAMILY = ["SAG-003", "SUR-016", "SFP-016", "WIL-016", "TRI-004"]


@pytest.mark.parametrize("rid", SINGLE_FAMILY)
@pytest.mark.parametrize("dwelling,want", [("House", "PASS"), ("Townhome", "PASS"), ("Condo", "FAIL")])
@pytest.mark.parametrize("occupancy", ["Seasonal", "Secondary Home"])
def test_decision_3_single_family_includes_a_townhome(rid, dwelling, want, occupancy):
    assert row(rid, occupancy_type=occupancy, dwelling_type=dwelling) == want


@pytest.mark.parametrize("rid,pd", [("ALL-019", {}), ("ALL-020", {}),
                                    ("CDP-094", {"dwelling_amount": 1500000, "occupancy_type": "Tenant Occupied"})])
def test_decision_3_the_other_single_family_lines(rid, pd):
    assert row(rid, dwelling_type="Townhome", **pd) == "PASS"
    assert row(rid, dwelling_type="Condo", **pd) == "FAIL"


def test_no_single_family_test_reads_house_alone():
    import re
    R = ev._rules()
    for rid, m in M.items():
        if re.search(r"single[- ]family", R[rid]["Plain rule"], re.I) and m["field"] not in ("NONE", ""):
            assert "dwelling_type == House" not in m["test"], rid
