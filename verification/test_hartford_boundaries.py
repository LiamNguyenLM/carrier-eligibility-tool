"""Round 39 step 5a: The Hartford's deciding rows at their boundaries, zero API (rules_evaluator only, no pipeline).

Each case: a complete owner's home (or rental) changed in one answer, and the outcome one row must have -- the value
just inside a limit passes, the value just outside fails, and a blank answer is the row's confirm or hold as the map
says. verification/test_hartford.py runs the same rows through check_eligibility (cases a-k)."""
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import intake_fields as I  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
H, WB = "The_Hartford_HO3_-_07.09.2026", "The Hartford HO3"
OWN = {"year_built": 1995, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
       "construction_type": "Frame", "plumbing_type": "PVC", "occupancy_type": "Owner Occupied",
       "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
       "pool_accessories": "None", "pool_fence_4ft": False, "pool_gate_locking": False, "has_dogs": "No",
       "dog_breeds": [], "solar_panels": "No", "ppc": "4", "fire_station_miles": 3.0, "hydrant_1000ft": "Yes",
       "zip": "", "county": "Travis", "dwelling_amount": 400000, "dwelling_type": "House", "losses_5yr": "0",
       "electrical": ["Circuit breakers"]}
RENT = dict(OWN, occupancy_type="Tenant Occupied", primary_home_carrier="The Hartford", rental_units_total="1-4",
            rental_term="Long-term")
LOSS = dict(losses_5yr="1", losses_3yr="1", loss_year=2025)


def outcome(pd, rid):
    return rv.evaluate_carrier(H, pd, wb=WB)[rid][0]


def status(pd):
    out = rv.evaluate_carrier(H, pd, wb=WB)
    return rv.code_record(H, out, pd)[0]["status"]


CASES = [
    # (row, base, change, outcome)
    ("HAR-002", OWN, {"dwelling_amount": 2500000}, "PASS"),
    ("HAR-002", OWN, {"dwelling_amount": 2500001}, "FAIL"),
    ("HAR-002", OWN, {"dwelling_amount": None}, "NOTE"),
    ("HAR-003", OWN, {"dwelling_amount": 1500000}, "PASS"),
    ("HAR-003", OWN, {"dwelling_amount": 1500001}, "FAIL"),
    ("HAR-005", OWN, {"dwelling_amount": 1499999, "ppc": "9"}, "N/A"),
    ("HAR-005", OWN, {"dwelling_amount": 1500000, "ppc": "8"}, "PASS"),
    ("HAR-005", OWN, {"dwelling_amount": 1500000, "ppc": "9"}, "FAIL"),
    ("HAR-005", OWN, {"dwelling_amount": 1500000, "ppc": "10W"}, "FAIL"),
    ("HAR-006", OWN, {"dwelling_amount": 1499999}, "N/A"),
    ("HAR-006", OWN, {"dwelling_amount": 1500000}, "NOTE"),
    ("HAR-008", OWN, {"electrical": ["Knob-and-tube wiring"]}, "FAIL"),
    ("HAR-008", OWN, {"electrical": ["Aluminum branch wiring"]}, "FAIL"),
    ("HAR-008", OWN, {"electrical": ["Federal Pacific or Zinsco panel"]}, "PASS"),
    ("HAR-008", OWN, {"electrical": []}, "NOTE"),
    ("HAR-009", OWN, {"electrical": ["Fuses"]}, "FAIL"),
    ("HAR-009", OWN, {"electrical": ["Circuit breakers", "Fuses"]}, "FAIL"),
    ("HAR-009", OWN, {"electrical": ["Unknown"]}, "NOTE"),
    ("HAR-009", OWN, {"electrical": ["Circuit breakers"]}, "PASS"),
    ("HAR-016", OWN, {"roof_shape": "Flat"}, "FAIL"),
    ("HAR-016", OWN, {"roof_shape": "Hip"}, "PASS"),
    *[("HAR-017", OWN, {"roof_type": t}, "FAIL") for t in (I.ROOF_WOOD, I.ROOF_ROLLED, I.ROOF_BUILT_UP,
                                                            I.ROOF_MEMBRANE)],
    *[("HAR-017", OWN, {"roof_type": t}, "PASS") for t in ("Composition Shingle", "Architectural Shingle", "Tile",
                                                            "Slate", I.ROOF_METAL_SEAM, I.ROOF_METAL_PANEL)],
    ("HAR-017", OWN, {"roof_type": "Other"}, "NOTE"),
    ("HAR-022", OWN, {"ownership_type": "Estate"}, "NOTE"),
    ("HAR-022", OWN, {}, "N/A"),
    ("HAR-023", OWN, {"ownership_type": "LLC"}, "FAIL"),
    ("HAR-023", OWN, {"ownership_type": "Corporation / partnership"}, "FAIL"),
    ("HAR-023", OWN, {"ownership_type": "Trust", "trust_type": "Family trust"}, "PASS"),
    ("HAR-024", OWN, {"ownership_type": "Trust", "trust_type": "Land trust"}, "NOTE"),
    ("HAR-024", OWN, {"ownership_type": "Trust", "trust_type": "Family trust"}, "PASS"),
    ("HAR-024", OWN, {"ownership_type": "Trust", "trust_type": "Unknown"}, "OPEN"),
    ("HAR-025", OWN, {"ownership_type": "Trust", "trust_type": "Corporate or business trust"}, "FAIL"),
    ("HAR-025", OWN, {"ownership_type": "Trust", "trust_type": "Revocable living trust"}, "PASS"),
    ("HAR-026", OWN, {"ownership_type": "Trust", "trust_type": "Family trust"}, "NOTE"),
    ("HAR-026", RENT, {"ownership_type": "Trust", "trust_type": "Family trust"}, "N/A"),
    ("HAR-027", OWN, dict(LOSS, losses_5yr="2", losses_3yr="1", loss_types=["Theft"]), "PASS"),
    ("HAR-027", OWN, dict(LOSS, losses_5yr="2", losses_3yr="2", loss_types=["Theft"]), "FAIL"),
    ("HAR-027", OWN, dict(LOSS, losses_5yr="2", losses_3yr="2", loss_types=["Water"]), "NOTE"),
    ("HAR-027", OWN, dict(LOSS, losses_5yr="2", losses_3yr="2"), "NOTE"),            # types blank: a confirm
    # step 5b (monotonic invariant, 2026-10-14): one more loss in 5 years never turns a decline into a confirm -- with
    # no water / other loss the 2 recent losses cannot be the appliance or mold exception
    ("HAR-027", OWN, dict(LOSS, losses_5yr="3 or more", losses_3yr="2", loss_types=["Theft", "Wind or hail"]), "FAIL"),
    ("HAR-027", OWN, dict(LOSS, losses_5yr="3 or more", losses_3yr="2", loss_types=["Fire", "Liability"]), "FAIL"),
    ("HAR-027", OWN, dict(LOSS, losses_5yr="3 or more", losses_3yr="2", loss_types=["Water", "Theft"]), "NOTE"),
    ("HAR-028", OWN, dict(LOSS, loss_types=["Fire"]), "FAIL"),
    ("HAR-028", OWN, dict(LOSS, loss_types=["Fire"], loss_year=2021, losses_3yr="0"), "PASS"),
    ("HAR-028", OWN, dict(LOSS, loss_types=["Water"]), "PASS"),
    ("HAR-029", OWN, dict(LOSS, loss_types=["Theft"], ppc="9"), "N/A"),
    ("HAR-029", OWN, dict(LOSS, loss_types=["Theft"], ppc="10"), "FAIL"),
    ("HAR-029", OWN, dict(ppc="10"), "PASS"),
    ("HAR-029", RENT, dict(LOSS, loss_types=["Theft"], ppc="10"), "N/A"),
    ("HAR-030", OWN, dict(LOSS, loss_types=["Liability"]), "FAIL"),
    ("HAR-030", OWN, dict(LOSS, loss_types=["Other"]), "NOTE"),
    ("HAR-030", OWN, dict(LOSS, loss_types=["Water"]), "PASS"),
    ("HAR-036", OWN, {"roof_type": I.ROOF_ASBESTOS}, "FAIL"),
    ("HAR-036", OWN, {}, "NOTE"),
    ("HAR-045", OWN, {"occupancy_type": "Vacant"}, "FAIL"),
    ("HAR-045", OWN, {}, "PASS"),
    ("HAR-046", RENT, {"rental_term": "Short-term"}, "FAIL"),
    ("HAR-046", RENT, {"rental_term": "Long-term"}, "PASS"),
    ("HAR-046", RENT, {"rental_term": "Unknown"}, "NOTE"),
    ("HAR-046", OWN, {}, "N/A"),
    ("HAR-048", OWN, {"construction_type": "Manufactured/Mobile"}, "FAIL"),
    ("HAR-048", OWN, {"construction_type": "Masonry"}, "PASS"),
    ("HAR-052", OWN, {"county": "Galveston"}, "NOTE"),
    ("HAR-052", OWN, {"coastal_tier": "Tier 1"}, "NOTE"),
    ("HAR-052", OWN, {"county": "Harris", "coastal_tier": "Tier 2"}, "N/A"),
    ("HAR-056", OWN, {"county": "Dallas"}, "NOTE"),
    ("HAR-056", OWN, {"county": "Somervell"}, "NOTE"),
    ("HAR-056", OWN, {"county": "Travis"}, "N/A"),
    ("HAR-059", OWN, {"occupancy_type": "Seasonal", "primary_home_carrier": "The Hartford"}, "PASS"),
    ("HAR-059", OWN, {"occupancy_type": "Seasonal", "primary_home_carrier": "Chubb"}, "FAIL"),
    ("HAR-059", OWN, {"occupancy_type": "Secondary Home", "primary_home_carrier": ""}, "OPEN"),
    ("HAR-060", OWN, {"swimming_pool": "In Ground - Unfenced"}, "FAIL"),
    *[("HAR-060", OWN, {"swimming_pool": p}, "PASS") for p in ("In Ground - Fenced", "Above Ground - Fenced",
                                                                "Above Ground - Unfenced", "No Pool")],
    *[("HAR-062", OWN, {"has_dogs": "Yes", "dog_breeds": [b]}, "FAIL") for b in (
        "Pit Bull (American Pit Bull Terrier)", "American Staffordshire Terrier", "Staffordshire Bull Terrier",
        "Presa Canario", "Rottweiler")],
    *[("HAR-062", OWN, {"has_dogs": "Yes", "dog_breeds": [b]}, "PASS") for b in ("Akita", "Chow Chow",
                                                                                  "Doberman Pinscher", I.DOG_NONE)],
    ("HAR-062", OWN, {"has_dogs": "Yes", "dog_breeds": [I.DOG_UNSURE]}, "OPEN"),
    ("HAR-063", OWN, {"has_dogs": "Yes", "dog_breeds": [I.DOG_NONE]}, "NOTE"),
    ("HAR-064", OWN, dict(LOSS, has_dogs="Yes", dog_breeds=[I.DOG_NONE], loss_types=["Liability"]), "NOTE"),
    ("HAR-064", OWN, dict(LOSS, has_dogs="Yes", dog_breeds=[I.DOG_NONE], loss_types=["Water"]), "PASS"),
    ("HAR-070", RENT, {}, "PASS"),
    ("HAR-070", RENT, {"primary_home_carrier": "Travelers"}, "FAIL"),
    ("HAR-070", RENT, {"primary_home_carrier": "Other carrier"}, "FAIL"),
    ("HAR-070", RENT, {"primary_home_carrier": ""}, "OPEN"),
    ("HAR-070", RENT, {"primary_home_carrier": "Unknown"}, "OPEN"),
    ("HAR-070", OWN, {}, "N/A"),
    ("HAR-074", RENT, {"ppc": "9"}, "PASS"),
    ("HAR-074", RENT, {"ppc": "10"}, "FAIL"),
    ("HAR-074", RENT, {"ppc": "10W"}, "FAIL"),
    *[("HAR-076", RENT, {"swimming_pool": p}, "FAIL") for p in ("In Ground - Fenced", "In Ground - Unfenced",
                                                                 "Above Ground - Fenced", "Above Ground - Unfenced")],
    ("HAR-076", OWN, {"swimming_pool": "In Ground - Fenced"}, "N/A"),
    ("HAR-076", RENT, {"swimming_pool": "No Pool"}, "PASS"),
    ("HAR-077", RENT, {"rental_units_total": "1-4"}, "PASS"),
    ("HAR-077", RENT, {"rental_units_total": "5 or more"}, "FAIL"),
    ("HAR-077", RENT, {"rental_units_total": "Unknown"}, "NOTE"),
    ("CFG-001", OWN, {"swimming_pool": "In Ground - Fenced", "pool_accessories": "Diving board only"}, "FAIL"),
    ("CFG-001", OWN, {"swimming_pool": "Above Ground - Fenced", "pool_accessories": "Both slide and diving board"},
     "FAIL"),
    ("CFG-001", OWN, {"swimming_pool": "In Ground - Fenced", "pool_accessories": "Slide only"}, "PASS"),
    ("CFG-001", OWN, {"swimming_pool": "No Pool"}, "N/A"),
    ("CFG-001", RENT, {"swimming_pool": "In Ground - Fenced", "pool_accessories": "Diving board only"}, "N/A"),
]


@pytest.mark.parametrize("rid,base,change,want", CASES,
                         ids=[f"{c[0]}-{'-'.join(f'{k}={v}' for k, v in c[2].items())[:60]}-{c[3]}" for c in CASES])
def test_boundary(rid, base, change, want):
    assert outcome(dict(base, **change), rid) == want


def test_every_row_decided_from_a_form_field_has_a_passing_and_a_failing_case():
    """The runbook's rule (one pass and one fail per deciding row), for every row whose map line can FAIL."""
    import collections
    seen = collections.defaultdict(set)
    for rid, _, _, want in CASES:
        seen[rid].add(want)
    fmap = rv._load("map", rv.HARTFORD_MAP_CSV)
    can_fail = [rid for rid, m in fmap.items() if m["field"] != "NONE" and m["test"] != "always"
                and not m["test"].startswith("FACT(")] + ["CFG-001"]
    missing = [rid for rid in can_fail if rid not in ONE_SIDED and not {"PASS", "FAIL"} <= seen[rid]]
    assert not missing, missing
    for rid, (side, _) in ONE_SIDED.items():             # the one side each can reach, and a confirm
        assert {side, "NOTE"} <= seen[rid], rid


# Rows that cannot reach both sides from the form, by design, with the reason.
ONE_SIDED = {
    "HAR-036": ("FAIL", "an asbestos roof fails; any other roof is a confirm (other asbestos materials are not asked)"),
    "HAR-064": ("PASS", "no liability loss passes; a liability loss is a confirm (whether a dog caused it is not asked)"),
    "HAR-022": ("N/A", "an estate is always a confirm on the guide's exception (the settlement is not asked)"),
    "HAR-024": ("PASS", "a land trust is a confirm (whether it is in a person's name is not asked); a corporate trust "
                        "fails HAR-025 instead"),
}


@pytest.mark.parametrize("pd,want", [(OWN, "ELIGIBLE"), (RENT, "ELIGIBLE"),
                                     (dict(OWN, dwelling_amount=2000000), "REFER"),
                                     (dict(RENT, primary_home_carrier=""), "INSUFFICIENT_INFORMATION")])
def test_the_base_profiles(pd, want):
    assert status(pd) == want
