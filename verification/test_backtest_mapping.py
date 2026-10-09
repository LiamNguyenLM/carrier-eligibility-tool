"""Round 32 step 3 (2026-10-09): the HawkSoft-row -> intake-form mapping of
verification/run_backtest_eligibility.py. Made-up rows only (the export is untracked). Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import run_backtest_eligibility as bt  # noqa: E402

pytestmark = pytest.mark.retrieval
ROW = {"home_id": "X1", "zip": "78628", "county": "Williamson", "year_built": "1998", "roof_type_raw": "Composition",
       "roof_year": "2020", "ppc_raw": "02", "construction_raw": "MasonryVeneer", "residence_raw": "Dwelling",
       "pool_raw": "None", "plumbing_raw": "Complete", "occupancy_raw": "Owner", "use_raw": "PrimaryNonSeasonal",
       "coverage_a": "500000.0", "miles_to_fire_station": "5", "feet_to_hydrant": "1000"}


def _p(**kw):
    return bt.profile(dict(ROW, **kw))


def test_a_complete_row():
    pd, checked, notes = _p()
    assert (pd["year_built"], pd["roof_age"], pd["roof_type"], pd["construction_type"]) == \
           (1998, 6, "Composition Shingle", "Masonry Veneer")
    assert (pd["ppc"], pd["fire_station_miles"], pd["hydrant_1000ft"]) == ("2", 5.0, "Yes")
    assert (pd["county"], pd["dwelling_amount"], pd["dwelling_type"], pd["swimming_pool"]) == \
           ("Williamson", 500000, "House", "No Pool")
    assert pd["plumbing_type"] == "Unknown"                       # update status is not a material
    assert pd["occupancy_type"] == "Owner Occupied" and pd["ownership_type"] == "Individual Owner"
    assert {"home_age", "roof_age", "roof_type", "construction", "pool", "ppc", "plumbing", "county",
            "dwelling_amount"} <= set(checked)
    assert not {"roof_shape", "coastal", "dogs", "solar"} & set(checked) and not notes


@pytest.mark.parametrize("raw,want", [("Metal", "Metal"), ("SteelPorcelainShingles", "Metal"), ("Tile", "Tile"),
                                      ("ClayTile", "Tile"), ("WoodShakeShingle", "Wood Shake")])
def test_roof_types_the_form_has(raw, want):
    pd, checked, _ = _p(roof_type_raw=raw)
    assert pd["roof_type"] == want and "roof_type" in checked


@pytest.mark.parametrize("raw", ["Unknown", "Other", "None", "Copper", ""])
def test_any_other_roof_type_is_left_blank(raw):
    assert "roof_type" not in _p(roof_type_raw=raw)[1]


@pytest.mark.parametrize("raw,want", [("01", "1"), ("10", "10"), ("", "N/A"), ("None", "N/A"), ("4Y", "N/A"),
                                      ("8.1", "N/A")])
def test_ppc(raw, want):
    assert _p(ppc_raw=raw)[0]["ppc"] == want


@pytest.mark.parametrize("raw,pool,fence", [
    ("IngroundUnfenced", "In Ground - Unfenced", False), ("AboveGroundUnfenced", "Above Ground - Unfenced", False),
    ("InGroundApprovedFenceHeight", "In Ground - Fenced", True)])
def test_pools(raw, pool, fence):
    pd, checked, _ = _p(pool_raw=raw)
    assert (pd["swimming_pool"], pd["pool_fence_4ft"], pd["pool_gate_locking"]) == (pool, fence, fence)
    assert "pool" in checked


def test_an_unknown_pool_is_left_blank():
    assert "pool" not in _p(pool_raw="Unknown")[1]


@pytest.mark.parametrize("feet,want", [("1000", "Yes"), ("1001", "No"), ("", "Unknown")])
def test_hydrant(feet, want):
    assert _p(feet_to_hydrant=feet)[0]["hydrant_1000ft"] == want


@pytest.mark.parametrize("occ,use,want", [("Owner", "SecondaryNonSeasonal", "Secondary Home"),
                                          ("Unknown", "SeasonalSecondary", "Seasonal"),
                                          ("Vacant", "PrimaryNonSeasonal", "Vacant"), ("Owner", "Vacant", "Vacant"),
                                          ("Unknown", "OccasionallyOccupied", "Owner Occupied")])
def test_occupancy(occ, use, want):
    pd = _p(occupancy_raw=occ, use_raw=use)[0]
    assert pd["occupancy_type"] == want
    assert ("primary_home_carrier" in pd) == (want in ("Seasonal", "Secondary Home"))


@pytest.mark.parametrize("raw,want", [("Frame", "Frame"), ("Masonry", "Masonry"), ("JoistedMasonry", "Masonry")])
def test_construction(raw, want):
    assert _p(construction_raw=raw)[0]["construction_type"] == want


@pytest.mark.parametrize("raw", ["Unknown", "TrailerMobileHome", ""])
def test_any_other_construction_is_left_blank(raw):
    assert "construction" not in _p(construction_raw=raw)[1]


def test_blank_year_and_roof_year_are_left_blank_and_a_blank_county_comes_from_the_zip():
    pd, checked, notes = _p(year_built="", roof_year="", county="", residence_raw="Other")
    assert "home_age" not in checked and "roof_age" not in checked
    assert pd["county"] == "Williamson" and "county from ZIP" in notes and pd["dwelling_type"] == ""


@pytest.mark.parametrize("rec,want", [({"status": "INELIGIBLE", "fixed_row": True}, "CLOSED"),
                                      ({"status": "INELIGIBLE"}, "INELIGIBLE"),
                                      ({"status": "GUIDE_UNAVAILABLE", "fixed_row": True}, "GUIDE_UNAVAILABLE")])
def test_status_column(rec, want):
    assert bt.status_of(rec) == want
