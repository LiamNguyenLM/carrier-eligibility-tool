"""Round 41 A6 (Liam, 2026-10-17): "No prior fire losses" in the SageSure fire-protection table declines on a fire
loss the form shows -- as Occidental HO3 has since round 40 -- for Auros, SURE, SafePort, Wilshire, Trium and
Occidental DP3, and the same cell of the SURE and SafePort DP3 guides. A blank or Unknown losses answer still holds (the
rows are named holds). Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
BASE = {"year_built": 2015, "roof_age": 5, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "PVC", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "dog_breeds": [], "solar_panels": "No", "ppc": "6",
        "county": "Bexar", "zip": "78201", "dwelling_amount": 400000, "dwelling_type": "House",
        "units_in_building": "1"}
NEAR_NO_HYDRANT = dict(fire_station_miles=3.0, hydrant_1000ft="No")      # band B: PC 4-10, 5 miles or less
FAR = dict(fire_station_miles=7.0, hydrant_1000ft="Yes")                  # band C: PC 4-8, over 5 miles
# (row, its band, the occupancy that reaches it)
ROWS = [("SAG-075", NEAR_NO_HYDRANT, "Owner Occupied"), ("SAG-076", FAR, "Owner Occupied"),
        ("SUR-113", NEAR_NO_HYDRANT, "Owner Occupied"), ("SUR-114", FAR, "Owner Occupied"),
        ("SFP-121", NEAR_NO_HYDRANT, "Owner Occupied"), ("SFP-122", FAR, "Owner Occupied"),
        ("WIL-118", NEAR_NO_HYDRANT, "Owner Occupied"), ("WIL-119", FAR, "Owner Occupied"),
        ("WIL-123", FAR, "Owner Occupied"),
        ("TRI-090", NEAR_NO_HYDRANT, "Owner Occupied"), ("TRI-091", FAR, "Owner Occupied"),
        ("OCC-095", NEAR_NO_HYDRANT, "Owner Occupied"), ("OCC-096", FAR, "Owner Occupied"),
        ("ODP-115", FAR, "Tenant Occupied"), ("SDP-082", FAR, "Tenant Occupied"), ("FDP-111", FAR, "Tenant Occupied")]
FIRE = [dict(losses_5yr="1", loss_types=["Fire"], loss_year=2024, losses_3yr="1"),          # one fire loss
        dict(losses_5yr="2", loss_types=["Water", "Fire"], loss_year=2021, losses_3yr="0")]  # fire among others, older


def _row(rid, **kw):
    return rv.evaluate_row(rv._map()[rid], rv.facts(dict(BASE, **kw)))[0]


@pytest.mark.parametrize("rid,band,occ", ROWS, ids=[r[0] for r in ROWS])
@pytest.mark.parametrize("loss", FIRE, ids=["one fire loss", "fire among two"])
def test_a_fire_loss_on_the_form_declines_the_fpc_cell(rid, band, occ, loss):
    assert _row(rid, occupancy_type=occ, **band, **loss) == "FAIL"
    assert rv._map()[rid]["outcome_if_fail"] == "DECLINES" and rid in rv.HOLD_BY_DECISION


@pytest.mark.parametrize("rid,band,occ", ROWS, ids=[r[0] for r in ROWS])
@pytest.mark.parametrize("losses", [{}, dict(losses_5yr="Unknown"), dict(losses_5yr="1", loss_types=["Theft"],
                                                                         loss_year=2024, losses_3yr="1")],
                         ids=["blank", "Unknown", "a theft only"])
def test_a_blank_or_other_losses_answer_still_holds(rid, band, occ, losses):
    assert _row(rid, occupancy_type=occ, **band, **losses) == "OPEN"


@pytest.mark.parametrize("rid,band,occ", ROWS, ids=[r[0] for r in ROWS])
def test_outside_its_band_the_cell_does_not_apply(rid, band, occ):
    assert _row(rid, occupancy_type=occ, fire_station_miles=2.0, hydrant_1000ft="Yes", **FIRE[0]) == "N/A"
