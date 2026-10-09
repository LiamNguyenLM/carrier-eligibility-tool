"""Round 35 step 2 (2026-10-09): the map-line fixes from Claude's audit, each checked against its row's
quote. Zero API."""
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


def row(rid, **pd):
    return ev.evaluate_row(ev._map()[rid], ev.facts(dict(BASE, **pd)))[0]


def card(canon, **pd):
    rec, _ = ev.code_record(canon, ev.evaluate_carrier(canon, dict(BASE, **pd)))
    return rec


# -- above-ground pools under 4 ft (the wall height is not asked) -------------------------------------------
@pytest.mark.parametrize("rid", ["SAG-056", "SUR-062", "SFP-061", "TRI-069"])
@pytest.mark.parametrize("pool,boxes,want", [
    ("Above Ground - Unfenced", False, "NOTE"),       # confirm the wall is 4 ft or higher -- never a hold
    ("Above Ground - Fenced", True, "PASS"),
    ("Above Ground - Fenced", False, "OPEN"),         # a fenced pool with the boxes unticked still holds
    ("In Ground - Unfenced", False, "N/A")])
def test_an_above_ground_pool_under_4_ft(rid, pool, boxes, want):
    assert row(rid, swimming_pool=pool, pool_fence_4ft=boxes, pool_gate_locking=boxes) == want


@pytest.mark.parametrize("pool,want", [("Above Ground - Unfenced", "NOTE"), ("In Ground - Unfenced", "FAIL")])
def test_foremost_s_above_ground_exception(pool, want):
    # "Above-ground pools: a deck at least 4 ft high with a self-locking gate, or (no deck) sides at least 4 ft
    # high with a locking retractable ladder"
    assert row("FOR-053", swimming_pool=pool) == want


def test_allied_refers_an_unfenced_pool():
    # ALL-093: "... or an underwriting approved alternate enclosure"; ALL-094: "Underwriting may approve"
    rec = card("Allied_Trust_HO3", swimming_pool="In Ground - Unfenced")
    assert rec["status"] == "REFER" and any(x.startswith("[ALL-094] refers") for x in rec["reasons"])


@pytest.mark.parametrize("canon,decline", [("Swyfft_-_Topa_(Surplus)_HO3", "STO-052"),
                                           ("Swyfft_-_Benchmark_(Surplus)_HO3", "SBS-049")])
def test_one_failing_row_for_an_unfenced_in_ground_swyfft_pool(canon, decline):
    out = ev.evaluate_carrier(canon, dict(BASE, swimming_pool="In Ground - Unfenced"))
    fails = [rid for rid, (o, _) in out.items() if o == "FAIL"]
    assert fails == [decline]


# -- ARI: a seasonal or secondary home ------------------------------------------------------------------
@pytest.mark.parametrize("prefix,decline,refer", [("ARA", "ARA-029", "ARA-030"), ("ARB", "ARB-036", "ARB-025")])
@pytest.mark.parametrize("occupancy", ["Seasonal", "Secondary Home"])
def test_ari_declines_a_second_home_unless_ari_writes_the_primary(prefix, decline, refer, occupancy):
    other = dict(occupancy_type=occupancy, primary_home_carrier="Other carrier")
    ari = dict(occupancy_type=occupancy, primary_home_carrier="ARI")
    blank = dict(occupancy_type=occupancy, primary_home_carrier="")
    assert (row(decline, **other), row(refer, **other)) == ("FAIL", "N/A")
    assert (row(decline, **ari), row(refer, **ari)) == ("PASS", "FAIL")
    assert row(decline, **blank) == "OPEN"                 # a blank answer holds; no referral outranks it


@pytest.mark.parametrize("rid", ["ARA-085", "ARB-093"])
def test_the_split_class_row_does_not_decline_every_ppc_10(rid):
    assert row(rid, ppc="10", fire_station_miles="") == "PASS"


@pytest.mark.parametrize("canon,decider", [("ARI_(HOA+)", "ARA-014"), ("ARI_(HOB)", "ARB-012")])
def test_more_than_5_miles_still_declines_once(canon, decider):
    out = ev.evaluate_carrier(canon, dict(BASE, ppc="10", fire_station_miles="7"))
    assert out[decider][0] == "FAIL" and out[decider.replace("014", "085").replace("012", "093")][0] == "PASS"


# -- Chubb ------------------------------------------------------------------------------------------------
def test_chubb_does_not_ask_a_primary_condo_about_its_primary_home():
    assert row("CHU-004", dwelling_type="Condo") == "N/A"
    assert row("CHU-004", occupancy_type="Seasonal", primary_home_carrier="Other carrier") == "FAIL"


@pytest.mark.parametrize("county,decline,refer", [("Travis", "FAIL", "N/A"), ("El Paso", "N/A", "FAIL")])
def test_chubb_flat_roof_declines_outside_el_paso_and_refers_in_it(county, decline, refer):
    assert (row("CHU-012", roof_shape="Flat", county=county), row("CHU-111", roof_shape="Flat", county=county)) == \
        (decline, refer)
    rec = card("CHUBB_HO_-_05.22.2026", roof_type="Built-up (tar and gravel)", county=county, dwelling_amount=2000000)
    assert rec["status"] == ("INELIGIBLE" if county == "Travis" else "REFER")


@pytest.mark.parametrize("rid,pd,want", [
    ("CHU-056", {"occupancy_type": "Seasonal", "dwelling_amount": 500000}, "N/A"),     # primary houses only
    ("CHU-056", {"dwelling_amount": 40000000}, "FAIL"),                                # over the $30M maximum
    ("CHU-056", {"dwelling_amount": 2000000}, "PASS"),
    ("CHU-059", {"dwelling_type": "Condo", "occupancy_type": "Secondary Home"}, "N/A"),
    ("CHU-059", {"dwelling_type": "Condo"}, "FAIL"),
    ("CHU-043", {"county": "Galveston", "occupancy_type": "Seasonal"}, "N/A"),          # CHU-047 is theirs
    ("CHU-044", {"county": "Harris", "occupancy_type": "Secondary Home"}, "N/A"),
    ("CHU-020", {"roof_type": "Wood Shake", "county": "Galveston"}, "N/A"),             # CHU-021 is the coast's
    ("CHU-020", {"roof_type": "Wood Shake", "county": "Travis"}, "FAIL")])
def test_chubb_gates(rid, pd, want):
    assert row(rid, **pd) == want


# -- one fact, one flaw ---------------------------------------------------------------------------------------
@pytest.mark.parametrize("county", ["Hidalgo", "Webb"])
def test_progressive_hidalgo_or_webb_fails_once(county):
    out = ev.evaluate_carrier("Progressive_HO3_-_04.01.2026", dict(BASE, county=county))
    assert out["PRO-072"][0] == "FAIL" and out["PRO-108"][0] == "PASS"


# -- Sage DP fire protection: no hydrant is B or C at any distance --------------------------------------------
@pytest.mark.parametrize("rid", ["SDP-070", "FDP-094"])
def test_the_2m_cap_applies_with_no_hydrant_and_a_blank_distance(rid):
    assert row(rid, hydrant_1000ft="No", fire_station_miles="", dwelling_amount=2500000, occupancy_type="Tenant Occupied") == "FAIL"


@pytest.mark.parametrize("rid,pd", [("SDP-078", {"ppc": "2"}), ("ODP-112", {"ppc": "6"}), ("ODP-113", {"ppc": "6"})])
def test_a_blank_distance_with_no_hydrant_still_reaches_the_fpc_row(rid, pd):
    # the row applies (its conditions are Liam's named FPC holds, so it holds rather than notes)
    assert row(rid, hydrant_1000ft="No", fire_station_miles="", **pd) == "OPEN"
    assert rid in ev.HOLD_BY_DECISION


# -- the rest ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("roof,want", [("Other", "NOTE"), ("Wood Shake", "FAIL"), ("Tile", "PASS")])
def test_orion_s_list_of_eligible_roofs(roof, want):
    assert row("ORI-012", roof_type=roof) == want


@pytest.mark.parametrize("rid,age", [("TRV-044", 12), ("TRV-045", 20), ("TRV-046", 40)])
@pytest.mark.parametrize("roof", ["Tile", "Slate"])
def test_travelers_tile_and_slate_are_exempt(rid, age, roof):
    assert row(rid, roof_type=roof, roof_age=age) == "N/A"
    assert row(rid, roof_type="Architectural Shingle", roof_age=age) != "N/A"


def test_travelers_condo_a_plus_c_and_the_sensor_wording():
    assert row("TRV-075", dwelling_type="Condo", dwelling_amount=450000) == "NOTE"
    assert "water-flow sensor or an automatic main water shut-off valve" in ev._map()["TRV-033"]["test"]


@pytest.mark.parametrize("dtype,want", [("House", "PASS"), ("Townhome", "PASS"), ("Condo", "FAIL")])
def test_centauri_dp_high_value_is_single_family(dtype, want):
    assert row("CDP-094", dwelling_type=dtype, dwelling_amount=1500000, occupancy_type="Tenant Occupied") == want


def test_safeport_s_slide_row_needs_a_pool():
    pd = dict(BASE)
    pd.pop("pool_accessories")
    assert ev.evaluate_row(ev._map()["SFP-065"], ev.facts(pd))[0] == "N/A"


@pytest.mark.parametrize("rid,pd", [("ALL-001", {}), ("SFP-019", {"ownership_type": "Trust"}),
                                    ("SUR-019", {"ownership_type": "Trust", "occupancy_type": "Seasonal"})])
def test_unasked_occupant_facts_are_confirm_notes(rid, pd):
    assert row(rid, **pd) == "NOTE"


# -- the grammar: an unknown in a part that is already decided is dropped (round 35 step 2) -------------------
@pytest.mark.parametrize("expr,f,want", [
    ("(a == 1 and b == 2) or FACT(x)", {"a": 0}, (None, ["x"])),          # the false "and" keeps no b
    ("(a == 1 or b == 2) and FACT(x)", {"a": 1}, (None, ["x"])),          # the true "or" keeps no b
    ("a == 1 and b == 2", {"a": 0}, (False, [])),
    ("a == 1 or b == 2", {"a": 0}, (None, ["b"])),                        # still undecided: b stays
    ("a == 1 and b == 2", {"a": 1}, (None, ["b"]))])
def test_unknowns_of_decided_parts_are_dropped(expr, f, want):
    v, unknown = ev.evaluate_expr(expr, f)
    assert (v, list(unknown)) == want
