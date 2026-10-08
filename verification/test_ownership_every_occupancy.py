"""Round 31 step 5 (Liam, 2026-10-08, decision 3): the ownership question shows for every occupancy, and
its answer reaches the prompt and the rules tables for Tenant Occupied, Vacant, Seasonal and Secondary Home
as it does for Owner Occupied. Zero API."""
import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import eligibility_check as ec  # noqa: E402
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval
BASE = {"year_built": 2010, "roof_age": 5, "roof_type": "Architectural Shingle", "roof_shape": "Gable",
        "construction_type": "Masonry", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "aggressive_breed": "No", "solar_panels": "No",
        "ppc": "3", "dwelling_type": "House", "county": "Bexar", "dwelling_amount": 450000,
        "fire_station_miles": "2", "hydrant_1000ft": "Yes"}


def test_the_form_asks_ownership_for_every_occupancy():
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    radio = src.index('"Ownership Structure"')
    before = src[src.rindex("occupancy_type = st.selectbox", 0, radio):radio]
    assert 'if occupancy_type == "Owner Occupied"' not in before
    assert 'ownership_type = "Individual Owner"' not in src


@pytest.mark.parametrize("occupancy", ["Tenant Occupied", "Vacant", "Seasonal", "Secondary Home"])
@pytest.mark.parametrize("ownership", ["Trust", "LLC"])
def test_the_answer_reaches_the_prompt_for_every_occupancy(occupancy, ownership):
    pd = dict(BASE, occupancy_type=occupancy, ownership_type=ownership)
    text = ec._property_details_text(pd, 16, occupancy, ownership, ec.topics.normalize(None))
    assert f"Ownership Structure: {ownership}" in text


@pytest.mark.parametrize("canon,row,want", [
    ("Progressive_DP3_-_10.01.2024", "PDP-120", "FAIL"),         # LLC: prior underwriting approval (refer)
    ("Centauri_-_DP3_-_11.16.2022", "CDP-071", "FAIL"),          # LLC: underwriting approval before binding
    ("Centauri_-_DP3_-_11.16.2022", "CDP-072", "PASS"),          # LLC: the home must be tenant occupied
    ("Sage_-_Vave_DP3_-_07.01.2026", "VDP-063", "NOTE"),         # LLC conditions not asked: confirm
])
def test_a_tenant_home_owned_by_an_llc_reaches_the_dwelling_fire_rows(canon, row, want):
    out = ev.evaluate_carrier(canon, dict(BASE, occupancy_type="Tenant Occupied", ownership_type="LLC"))
    assert out[row][0] == want


@pytest.mark.parametrize("occupancy,want", [("Owner Occupied", "PASS"), ("Seasonal", "PASS"),
                                            ("Secondary Home", "PASS"), ("Tenant Occupied", "FAIL")])
def test_sag_019_a_trust_home_occupied_by_its_trustee_includes_a_seasonal_one(occupancy, want):
    # "Residence Held in Trust if the residence is occupied by the trustee, the grantor ... or the beneficiary"
    f = ev.facts(dict(BASE, ownership_type="Trust", occupancy_type=occupancy))
    assert ev.evaluate_row(ev._map()["SAG-019"], f)[0] == want


def test_a_tenant_trust_home_on_vave_dp3_is_declined_by_its_own_row():
    # VDP-062 "eligible only when the trustee, grantor, or beneficiary resides at the residence" (step 4: declines)
    rec, _ = ev.code_record("Sage_-_Vave_DP3_-_07.01.2026", ev.evaluate_carrier(
        "Sage_-_Vave_DP3_-_07.01.2026", dict(BASE, occupancy_type="Tenant Occupied", ownership_type="Trust")))
    assert rec["status"] == "INELIGIBLE" and any(re.match(r"\[VDP-062\] declines", x) for x in rec["reasons"])
