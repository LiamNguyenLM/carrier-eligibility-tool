"""Round 40 step 2 (Liam, 2026-10-16): the right NatGen Custom360 HO3 (09/02/2026) and SageSure Occidental HO3
(revised 12/2/2025) guides, each with its rules table. Zero API.

For each carrier: every deciding row has a map line (none left to the model); every row decided by a form field has
a passing and a failing profile at its boundary; every confirm row is reached on some profile; a "decided by" row
names a row that has a line. Liam's decisions for each guide are tested by name, with two phrasings where the rule
is general. Rows that cannot be reached are listed (UNREACHABLE) with the reason."""
import csv
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rules_data"))
sys.path.insert(0, HERE)
import build_natgen_c360_map  # noqa: E402
import build_occidental_counties  # noqa: E402
import build_occidental_map  # noqa: E402
import eligibility_check as ec  # noqa: E402
import intake_fields  # noqa: E402
import rules_evaluator as rv  # noqa: E402
import structured_rules  # noqa: E402
from build_sage_batch_map import kind  # noqa: E402
from test_held_reasons import HOME  # noqa: E402

pytestmark = pytest.mark.retrieval
NG = "NatGen_Custom360_HO3_-_09.02.2026"
OC = "Sage_-_Occidental_HO3_-_12.02.2025"
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
# A plain Harris home both programs write: PC 7, 4 miles from the station, one family, breakers, no losses.
BASE = dict(HOME, county="Harris", zip="77493", dwelling_amount=400000, units_in_building="1",
            electrical=["Circuit breakers"], loss_year=None)
WOOD = intake_fields.ROOF_WOOD
NOT_HARRIS = dict(harris_east_146=None, zip="")
SEAM = intake_fields.ROOF_METAL_SEAM


def out(canon, **kw):
    return rv.evaluate_carrier(canon, dict(BASE, **kw))


def row(canon, rid, **kw):
    return out(canon, **kw)[rid]


def status(canon, **kw):
    pd = dict(BASE, **kw)
    return rv.code_record(canon, rv.evaluate_carrier(canon, pd), pd)[0]


def lines(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(l for l in fh if not l.startswith("#")))


# ==================================================================== every deciding row has a line
@pytest.mark.parametrize("rules_csv,map_csv,n", [
    (rv.NATGEN_C360_RULES_CSV, rv.NATGEN_C360_MAP_CSV, 158), (rv.OCCIDENTAL_RULES_CSV, rv.OCCIDENTAL_MAP_CSV, 89)])
def test_every_deciding_row_has_a_map_line_and_none_is_left_to_the_model(rules_csv, map_csv, n):
    deciding = [r["Rule ID"] for r in lines(rules_csv) if r["Tool handling"] in rv.DECIDING]
    fmap = {m["row_id"]: m for m in lines(map_csv)}
    assert len(deciding) == n and sorted(fmap) == sorted(deciding)
    assert [rid for rid, m in fmap.items() if m["field"] == "NONE"] == []
    kinds = {rid: kind((m["field"], m["test"], m["gate"], m["open_fact"], m["map_note"])) for rid, m in fmap.items()}
    assert "AMBIGUOUS" not in kinds.values()
    for rid, m in fmap.items():                     # a "decided by" row names rows that have their own line
        if m["map_note"].startswith("decided by"):
            named = re.findall(r"\b[A-Z][A-Z0-9]{2}-\d{3}\b", m["map_note"])
            assert named and all(x in fmap and not fmap[x]["map_note"].startswith("decided by") for x in named), rid


@pytest.mark.parametrize("builder,map_csv", [(build_natgen_c360_map, rv.NATGEN_C360_MAP_CSV),
                                             (build_occidental_map, rv.OCCIDENTAL_MAP_CSV)])
def test_the_map_file_is_what_its_builder_writes(builder, map_csv, tmp_path, monkeypatch):
    monkeypatch.setattr(builder, "OUT", str(tmp_path / "m.csv"))
    builder.main()
    assert open(tmp_path / "m.csv", encoding="utf-8").read().splitlines()[1:] == \
        open(map_csv, encoding="utf-8").read().splitlines()[1:]


def test_every_map_line_parses():
    f = rv.facts({})
    for path in (rv.NATGEN_C360_MAP_CSV, rv.OCCIDENTAL_MAP_CSV):
        for m in lines(path):
            for t in m["test"].split("||") + [m["gate"]]:
                if t not in ("", "always"):
                    rv.evaluate_expr(t, f)


def test_both_carriers_are_registered_on_existing_switches():
    assert rv.BATCHES["natgen_c360"]["carriers"] == {"NatGen Custom360 HO3": NG}
    assert rv.BATCHES["occidental"]["carriers"] == {"Sage Occidental HO3": OC}
    assert ec.RULES_BATCH_SWITCHES["natgen_c360"][0] == "RULES_HO3_BATCH"
    assert ec.RULES_BATCH_SWITCHES["occidental"][0] == "RULES_SAGE_BATCH"
    assert {rv.CANON_TO_WB[NG], rv.CANON_TO_WB[OC]} == {"NatGen Custom360 HO3", "Sage Occidental HO3"}


# ==================================================================== boundaries: every form-decided row
# (carrier, row, passing answers, failing answers, the outcome a fail gives)
BOUNDARY = [
    (NG, "NC3-008", dict(ownership_type="Individual Owner"), dict(ownership_type="Estate"), "DECLINES"),
    (NG, "NC3-022", dict(dwelling_amount=750000), dict(dwelling_amount=1500001), "REFERS_TO_UW"),
    (NG, "NC3-023", dict(ppc="9", dwelling_amount=750000), dict(ppc="9", dwelling_amount=750001), "REFERS_TO_UW"),
    (NG, "NC3-026", dict(occupancy_type="Seasonal", dwelling_amount=750000),
     dict(occupancy_type="Secondary Home", dwelling_amount=750001), "REFERS_TO_UW"),
    (NG, "NC3-033", dict(units_in_building="3-4"), dict(units_in_building="5 or more"), "DECLINES"),
    (NG, "NC3-036", dict(occupancy_type="Seasonal", primary_home_carrier="National General"),
     dict(occupancy_type="Seasonal", primary_home_carrier="Chubb"), "DECLINES"),
    (NG, "NC3-038", dict(ppc="10", fire_station_miles=10), dict(ppc="10", fire_station_miles=10.5), "DECLINES"),
    (NG, "NC3-044", dict(occupancy_type="Owner Occupied"), dict(occupancy_type="Tenant Occupied"), "DECLINES"),
    (NG, "NC3-062", dict(roof_type=WOOD, roof_age=25), dict(roof_type=WOOD, roof_age=26), "DECLINES"),
    (NG, "NC3-084", dict(swimming_pool="In Ground - Fenced", pool_gate_locking=True),
     dict(swimming_pool="In Ground - Unfenced", pool_gate_locking=True), "CONDITION"),
    (NG, "NC3-100", dict(roof_type="Composition Shingle"), dict(roof_type=WOOD), "REFERS_TO_UW"),
    (NG, "NC3-126", dict(construction_type="Frame"), dict(construction_type="Manufactured/Mobile"), "DECLINES"),
    (NG, "NC3-138", dict(electrical=["Circuit breakers"]), dict(electrical=["Knob-and-tube wiring"]), "DECLINES"),
    (NG, "NC3-139", dict(electrical=["Fuses"]), dict(electrical=["Federal Pacific or Zinsco panel"]), "DECLINES"),
    (NG, "NC3-192", dict(dwelling_amount=150000), dict(dwelling_amount=149999), "DECLINES"),
    (OC, "OCC-001", dict(county="Brazos"), dict(county="Burnet"), "DECLINES"),
    (OC, "OCC-020", dict(occupancy_type="Owner Occupied"), dict(occupancy_type="Tenant Occupied"), "DECLINES"),
    (OC, "OCC-023", dict(occupancy_type="Seasonal", units_in_building="1"),
     dict(occupancy_type="Seasonal", units_in_building="2"), "DECLINES"),
    (OC, "OCC-028", dict(occupancy_type="Owner Occupied"), dict(occupancy_type="Vacant"), "DECLINES"),
    (OC, "OCC-041", dict(ownership_type="Trust", trust_type="Family trust"),
     dict(ownership_type="Trust", trust_type="Corporate or business trust"), "DECLINES"),
    (OC, "OCC-044", dict(units_in_building="3-4"), dict(units_in_building="5 or more"), "DECLINES"),
    (OC, "OCC-046", dict(construction_type="Masonry"), dict(construction_type="Manufactured/Mobile"), "DECLINES"),
    (OC, "OCC-058", dict(roof_type="Architectural Shingle"), dict(roof_type="T-lock shingle"), "DECLINES"),
    (OC, "OCC-072", dict(plumbing_type="PVC"), dict(plumbing_type="Polybutylene"), "DECLINES"),
    (OC, "OCC-075", dict(electrical=["Circuit breakers"]), dict(electrical=["Fuses"]), "DECLINES"),
    (OC, "OCC-080", dict(swimming_pool="In Ground - Fenced", pool_fence_4ft=True, pool_gate_locking=True),
     dict(swimming_pool="In Ground - Unfenced", pool_gate_locking=True), "DECLINES"),
    (OC, "OCC-083", dict(swimming_pool="In Ground - Fenced", pool_accessories="None"),
     dict(swimming_pool="In Ground - Fenced", pool_accessories="Slide only"), "DECLINES"),
    (OC, "OCC-097", dict(ppc="9", fire_station_miles=5), dict(ppc="9", fire_station_miles=5.5), "DECLINES"),
    (OC, "OCC-126", dict(dwelling_amount=2000000), dict(dwelling_amount=2000001), "DECLINES"),
    (OC, "OCC-128", dict(dwelling_amount=85000), dict(dwelling_amount=84999), "REFERS_TO_UW"),
]
# Rows a form field decides whose FAIL no form answer can give, and why.
UNREACHABLE_FAIL = {
    "OCC-081": "an unticked 4-ft fence box is unknown, never 'no' (rules_evaluator.facts); an unfenced pool fails "
               "OCC-080 instead",
}


@pytest.mark.parametrize("canon,rid,ok,bad,effect", BOUNDARY, ids=[b[1] for b in BOUNDARY])
def test_a_form_decided_row_passes_and_fails_at_its_boundary(canon, rid, ok, bad, effect):
    # a row whose line also confirms a fact the form never asks passes the form's part as a confirm (round 40 step 3b)
    assert row(canon, rid, **ok)[0] in (("PASS", "NOTE") if "FACT(" in rv._map()[rid]["test"] else ("PASS",))
    assert row(canon, rid, **bad)[0] == "FAIL"
    assert rv._map()[rid]["outcome_if_fail"] == effect
    rec = status(canon, **bad)
    assert any(f"[{rid}]" in r for r in rec["reasons"]), rec["reasons"]
    assert rec["status"] == ("INELIGIBLE" if effect == "DECLINES" else "REFER") or (
        rec["status"] == "INELIGIBLE" and effect != "DECLINES")      # another row may decline the same profile


def test_every_form_decided_row_has_a_boundary_case_or_a_reason():
    decided = {m["row_id"] for path in (rv.NATGEN_C360_MAP_CSV, rv.OCCIDENTAL_MAP_CSV) for m in lines(path)
               if kind((m["field"], m["test"], m["gate"], m["open_fact"], m["map_note"])) == "decided by a form field"}
    assert decided - set(UNREACHABLE_FAIL) <= {b[1] for b in BOUNDARY}
    assert set(UNREACHABLE_FAIL) <= decided


def test_occ_081_is_reached_as_a_hold_on_an_unticked_box_never_a_fail():
    assert row(OC, "OCC-081", swimming_pool="In Ground - Fenced", pool_fence_4ft=True)[0] == "PASS"
    assert row(OC, "OCC-081", swimming_pool="In Ground - Fenced", pool_fence_4ft=False)[0] == "OPEN"


# ==================================================================== every confirm row is reached
LIBRARY = [
    {}, dict(occupancy_type="Seasonal", primary_home_carrier="National General"),
    dict(occupancy_type="Secondary Home", primary_home_carrier="National General"),
    dict(ownership_type="Trust", trust_type="Family trust"), dict(ownership_type="LLC"),
    dict(ownership_type="Corporation / partnership"), dict(coastal_tier="Tier 1", county="Galveston"),
    dict(ppc="9"), dict(ppc="10"), dict(dwelling_amount=2100000, year_built=1920),
    dict(dwelling_amount=2100000, ppc="9"), dict(occupancy_type="Seasonal", dwelling_amount=900000),
    dict(swimming_pool="Above Ground - Fenced", pool_accessories="Both slide and diving board"),
    dict(swimming_pool="In Ground - Fenced", pool_accessories="Diving board only"),
    dict(roof_type=WOOD, roof_age=10), dict(roof_type=SEAM), dict(roof_type="Tile"), dict(roof_type="Other"),
    dict(roof_shape="Flat"), dict(dwelling_type="Townhome", construction_type="Frame", year_built=1975),
    dict(losses_5yr="2", losses_3yr="2", loss_types=["Water"], loss_year=2025),
    dict(losses_5yr="1", losses_3yr="1", loss_types=["Fire"], loss_year=2025),
    dict(year_built=1935), dict(year_built=2015), dict(units_in_building="3-4"), dict(ownership_type="Trust"),
    dict(losses_5yr="3 or more", losses_3yr="3 or more", loss_types=["Water"], loss_year=2025),
    dict(ppc="2", fire_station_miles=7), dict(ppc="2", fire_station_miles=3, hydrant_1000ft="No"),
    dict(fire_station_miles=7, year_built=2015), dict(fire_station_miles=3, hydrant_1000ft="No", year_built=2015),
    dict(swimming_pool="In Ground - Fenced", units_in_building="2"), dict(dwelling_amount=900000),
]


@pytest.mark.parametrize("canon,map_csv", [(NG, rv.NATGEN_C360_MAP_CSV), (OC, rv.OCCIDENTAL_MAP_CSV)])
def test_every_confirm_row_is_reached_on_some_profile(canon, map_csv):
    fmap = {m["row_id"]: m for m in lines(map_csv)}
    reached = {}
    for kw in LIBRARY:
        for rid, (o, _) in out(canon, **kw).items():
            reached.setdefault(rid, set()).add(o)
    confirms = [rid for rid, m in fmap.items() if "FACT(" in m["test"] and not m["map_note"].startswith("decided by")]
    assert confirms
    never = [rid for rid in confirms if not reached.get(rid, set()) & {"NOTE", "OPEN"}]
    assert never == []
    # a "decided by" row never decides on its own
    for rid, m in fmap.items():
        if m["map_note"].startswith("decided by"):
            assert reached[rid] <= {"PASS", "N/A"}, (rid, reached[rid])


# ==================================================================== NatGen: Liam's decisions
def test_coverage_a_below_the_minimum_declines_two_ways():
    for amount in (149999, 90000):
        rec = status(NG, dwelling_amount=amount)
        assert rec["status"] == "INELIGIBLE" and any("[NC3-192]" in r for r in rec["reasons"])


@pytest.mark.parametrize("kw,rid", [
    (dict(dwelling_amount=1600000), "NC3-022"), (dict(dwelling_amount=3000000, ppc="3"), "NC3-022"),
    (dict(dwelling_amount=800000, ppc="9"), "NC3-023"), (dict(dwelling_amount=800000, ppc="10"), "NC3-023"),
    (dict(dwelling_amount=760000, occupancy_type="Seasonal"), "NC3-026"),
    (dict(dwelling_amount=1000000, occupancy_type="Secondary Home"), "NC3-026")])
def test_coverage_a_above_the_approval_threshold_refers_never_declines(kw, rid):
    kw = dict(kw, primary_home_carrier="National General")
    rec = status(NG, **kw)
    assert rec["status"] == "REFER" and any(f"[{rid}]" in r for r in rec["reasons"]), rec["reasons"]


def test_premier_client_is_not_asked_read_as_non_premier_with_a_confirm():
    o = out(NG, dwelling_amount=2100000)
    assert o["NC3-024"][0] == "NOTE" and "Premier" in o["NC3-024"][1]
    assert out(NG, units_in_building="3-4")["NC3-034"][0] == "NOTE"
    assert out(NG, units_in_building="2")["NC3-034"][0] == "PASS"


def test_nc3_115_non_remediated_damage_is_a_condition_note_never_a_decline():
    assert rv._rules()["NC3-115"]["Tool handling"] == "CONDITION_STANDARD"
    assert "NC3-115" not in rv._map()
    rec = status(NG, losses_5yr="1", losses_3yr="1", loss_types=["Fire"], loss_year=2025)
    assert rec["status"] != "INELIGIBLE"


LOSS = dict(loss_year=2025)


@pytest.mark.parametrize("n,types,rid", [("2", ["Theft"], "NC3-110"), ("3 or more", ["Theft"], "NC3-109"),
                                         ("3 or more", ["Fire", "Liability"], "NC3-109")])
def test_losses_both_readings_rule_out_decline(n, types, rid):
    rec = status(NG, losses_5yr=n, losses_3yr=n, loss_types=types, **LOSS)
    assert rec["status"] == "INELIGIBLE" and any(f"[{rid}]" in r for r in rec["reasons"]), rec["reasons"]


@pytest.mark.parametrize("n,types", [("2", ["Water"]), ("2", ["Theft", "Water"]), ("2", ["Fire", "Liability"]),
                                     ("2", ["Other"])])
def test_losses_the_readings_disagree_on_are_confirms_not_declines(n, types):
    """Package: at most two paid losses; monoline: one (the form does not say which); two remediated, certified
    appliance water losses are accepted (WDR-1)."""
    o = out(NG, losses_5yr=n, losses_3yr=n, loss_types=types, **LOSS)
    assert o["NC3-112"][0] == "NOTE" and o["NC3-109"][0] == "PASS"
    assert status(NG, losses_5yr=n, losses_3yr=n, loss_types=types, **LOSS)["status"] != "INELIGIBLE"


def test_one_loss_in_three_years_passes_the_count_rows():
    o = out(NG, losses_5yr="1", losses_3yr="1", loss_types=["Theft"], **LOSS)
    assert [o[r][0] for r in ("NC3-109", "NC3-110", "NC3-112")] == ["PASS"] * 3
    assert o["NC3-111"][0] == "NOTE"                                  # the Insurance Score is never asked


def test_a_blank_loss_answer_is_a_confirm_never_a_hold():
    o = out(NG, losses_5yr="Unknown", losses_3yr=None, loss_types=[])
    assert {o[r][0] for r in ("NC3-106", "NC3-109", "NC3-110", "NC3-112")} == {"NOTE"}


@pytest.mark.parametrize("age,want", [(10, "REFER"), (25, "REFER"), (26, "INELIGIBLE")])
def test_wood_roofs_refer_unless_older_than_25(age, want):
    rec = status(NG, roof_type=WOOD, roof_age=age)
    assert rec["status"] == want
    assert any("[NC3-062]" if want == "INELIGIBLE" else "[NC3-100]" in r for r in rec["reasons"])


def test_a_legacy_wood_shake_answer_is_the_wood_roof():
    assert status(NG, roof_type="Wood Shake", roof_age=12)["status"] == "REFER"


def _notes(canon, **kw):
    pd = dict(BASE, **kw)
    return " ".join(rv.program_notes(canon, rv.evaluate_carrier(canon, pd), pd))


@pytest.mark.parametrize("zip_,east", [("77571", "Yes"), ("77586", "Yes")])
def test_harris_77571_77586_east_of_146_is_coastal_zone_1_and_zone_2_houston(zip_, east):
    text = _notes(NG, zip=zip_, harris_east_146=east)
    assert "Coastal Zone 1 (Harris ZIP 77571 / 77586 east of Highway 146)" in text and "(NC3-091)" in text
    assert "3% Windstorm/Hail deductible" in text and "(NC3-094, NC3-095)" in text


def test_harris_zone_1_follows_the_east_of_146_answer():
    assert "NC3-091" not in _notes(NG, zip="77571", harris_east_146="No")
    assert "if the home is east of Highway 146" in _notes(NG, zip="77586", harris_east_146="Unknown")
    assert "if the home is east of Highway 146" in _notes(NG, zip="77571", harris_east_146=None)
    assert "NC3-091" not in _notes(NG, zip="77493", harris_east_146="Yes")      # another Harris ZIP
    assert "3% Windstorm/Hail deductible" in _notes(NG, zip="77493")          # all of Harris is Zone 2 Houston


@pytest.mark.parametrize("county,words", [("Galveston", "Coastal Zone 1 county"), ("Nueces", "Coastal Zone 1 county"),
                                          ("Hidalgo", "Coastal Zone 2 county"), ("Orange", "Coastal Zone 2 county"),
                                          ("Fort Bend", "Coastal Zone 2 - Houston"),
                                          ("Dallas", "Inland Windstorm/Hail"), ("Tarrant", "Inland Windstorm/Hail")])
def test_natgen_coastal_and_inland_zones_are_notes(county, words):
    assert words in _notes(NG, county=county, zip="")
    assert status(NG, county=county, zip="")["status"] == "ELIGIBLE"


def test_an_acceptable_cat_score_is_a_note_never_a_decline():
    for rid in ("NC3-092", "NC3-094"):
        assert rv._rules()[rid]["Tool handling"] == "NOT_ELIGIBILITY" and rid not in rv._map()
    for county in ("Liberty", "Harris"):
        assert "acceptable CAT score" in _notes(NG, county=county)
        assert status(NG, county=county)["status"] == "ELIGIBLE"


def test_natgen_other_programs_are_unchanged():
    assert rv.DP_BATCH_CARRIERS["NatGen Custom360 Landlord"] == "NatGen_Custom360_DP3_-_06.25.2026"
    assert "NatGen Custom360 HO3" not in rv.HO3_BATCH_CARRIERS


# ==================================================================== Occidental: Liam's decisions
COUNTIES = {r["county"]: r for r in lines(build_occidental_counties.OUT)}


def test_the_county_list_is_every_texas_county_with_its_source():
    head = open(build_occidental_counties.OUT, encoding="utf-8").readline()
    assert "cb_2023_us_county_500k" in head and "2026-10-16" in head
    assert sorted(COUNTIES) == sorted(intake_fields.COUNTY_MAX_LATITUDE)
    assert sum(1 for r in COUNTIES.values() if r["occidental"] == "IN") == 89


def test_the_county_list_the_card_and_the_structured_check_agree_on_every_county():
    for county, r in COUNTIES.items():
        o = row(OC, "OCC-001", county=county)[0]
        assert o == ("PASS" if r["occidental"] == "IN" else "FAIL"), county
        assert structured_rules.sage_county_in_territory(county, intake_fields.COUNTY_MAX_LATITUDE, True) == \
            r["occidental"], county


@pytest.mark.parametrize("county,want", [("Harris", "IN"), ("Fort Bend", "IN"), ("Bexar", "IN"), ("Galveston", "IN"),
                                         ("Dallas", "OUT"), ("Tarrant", "OUT"), ("Nueces", "OUT"),
                                         ("Polk", "IN"), ("Bell", "IN"), ("Walker", "OUT"), ("Brazos", "IN")])
def test_liams_named_counties(county, want):
    assert COUNTIES[county]["occidental"] == want


@pytest.mark.xfail(strict=True, reason="for Liam (2026-10-16): he expected Travis out, but its northern edge is "
                                       "30.628 N -- entirely south of 31 N, so the guide's rule puts it in")
def test_travis_is_outside_occidental_territory():
    assert COUNTIES["Travis"]["occidental"] == "OUT"


@pytest.fixture
def check(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    monkeypatch.setattr(ec, "_complete", fake)
    return lambda pd, c: {r["carrier"]: r for r in ec.check_eligibility(dict(pd), carrier_subset=[c])}.get(c)


@pytest.mark.parametrize("county", ["", None])
def test_a_blank_county_holds_occidental(check, county):
    rec = check(dict(BASE, county=county, zip="", hydrant_1000ft="Yes"), OC)
    assert rec["status"] == "INSUFFICIENT_INFORMATION", rec


@pytest.mark.parametrize("county,want", [("Dallas", "INELIGIBLE"), ("Nueces", "INELIGIBLE")])
def test_outside_the_territory_occidental_declines_on_occ_001(check, county, want):
    rec = check(dict(BASE, county=county, zip="", hydrant_1000ft="Yes"), OC)
    assert rec["status"] == want


def test_the_fpc_table_holds_as_liam_decided():
    for rid in ("OCC-093", "OCC-094", "OCC-095", "OCC-096"):
        assert rid in rv.HOLD_BY_DECISION
    assert row(OC, "OCC-095", hydrant_1000ft="No", fire_station_miles=3, year_built=2015)[0] == "OPEN"
    assert row(OC, "OCC-093", ppc="2", hydrant_1000ft="No", fire_station_miles=3)[0] == "OPEN"
    assert row(OC, "OCC-095", hydrant_1000ft="Yes", fire_station_miles=3)[0] == "N/A"
    # all of the criteria, no path named: an old home fails as SUR-113 / SUR-114 do
    for rid, kw in (("OCC-095", dict(hydrant_1000ft="No", fire_station_miles=3)), ("OCC-096", dict(fire_station_miles=7))):
        assert row(OC, rid, year_built=1980, **kw)[0] == "FAIL" and rv._map()[rid]["outcome_if_fail"] == "DECLINES"


@pytest.mark.parametrize("tier", ["Tier 1"])
def test_ho_04_70_with_twia_is_a_confirm_not_a_decline(tier):
    o = out(OC, coastal_tier=tier, county="Galveston")
    for rid in ("OCC-006", "OCC-007", "OCC-008", "OCC-009", "OCC-010", "OCC-011", "OCC-012"):
        assert o[rid][0] == "NOTE" and "TWIA" in rv._map()[rid]["test"], rid
    assert status(OC, coastal_tier=tier, county="Galveston")["status"] != "INELIGIBLE"


def test_tier_wording_is_gated_on_the_forms_tier_as_the_sage_batch():
    assert out(OC, coastal_tier="Tier 2")["OCC-010"][0] == "N/A"
    assert out(OC, coastal_tier="Tier 2")["OCC-009"][0] == "NOTE"
    assert out(OC, coastal_tier="Tier 4")["OCC-009"][0] == "N/A"


@pytest.mark.parametrize("occ,want", [("Owner Occupied", "PASS"), ("Tenant Occupied", "FAIL")])
def test_a_tenant_only_home_is_not_eligible_an_owners_2_4_family_is(occ, want):
    assert row(OC, "OCC-020", occupancy_type=occ, units_in_building="3-4")[0] == want


@pytest.mark.parametrize("roof", [SEAM, intake_fields.ROOF_METAL_PANEL])
def test_steel_gauge_is_a_confirm_on_a_metal_roof(roof):
    o = row(OC, "OCC-055", roof_type=roof)
    assert o[0] == "NOTE" and "29 gauge" in rv._map()["OCC-055"]["test"]
    assert row(OC, "OCC-055", roof_type="Tile")[0] == "N/A"


def test_occidental_deductible_and_old_home_notes():
    assert "3% or higher Wind and Hail" in _notes(OC)
    assert "5% Wind and Hail" in _notes(OC, county="Galveston")
    assert "1.5% or higher Wind and Hail" in _notes(OC, county="Bexar") and "OCC-016" not in _notes(OC)
    assert "HO 05 30" in _notes(OC, year_built=1939) and "HO 05 30" not in _notes(OC, year_built=1940)
    assert "HO 05 30" in _notes(OC, year_built="1925")


def test_occidental_trust_terms_decline_when_the_form_shows_them_unmet():
    assert rv._map()["OCC-042"]["outcome_if_fail"] == "DECLINES"
    assert row(OC, "OCC-042", ownership_type="Trust", trust_type="Land trust")[0] == "FAIL"
    assert row(OC, "OCC-042", ownership_type="Trust", trust_type="Family trust")[0] == "NOTE"


# ==================================================================== round 40 step 3b: the second reader's fixes
@pytest.mark.parametrize("amount,want", [(750000, "PASS"), (750001, "NOTE"), (1500000, "NOTE"), (1500001, "FAIL")])
def test_natgen_split_classes_count_as_pc_9_10_a_confirm_where_the_readings_differ(amount, want):
    """p.5 footnotes: "*Includes all PC 9 or 1X - 8X variations"; the form has no X classes."""
    o = row(NG, "NC3-022", dwelling_amount=amount)
    assert o[0] == want and (want != "NOTE" or "1X-8X" in rv._map()["NC3-022"]["test"])
    assert status(NG, dwelling_amount=amount)["status"] == ("REFER" if want == "FAIL" else "ELIGIBLE")


@pytest.mark.parametrize("carrier,want", [("National General", "PASS"), ("Other carrier", "NOTE"),
                                          ("Chubb", "FAIL"), ("Sage: Occidental", "FAIL")])
def test_natgen_seasonal_home_with_an_affiliate_primary(carrier, want):
    """p.6 "or an affiliate company"; p.32: National General, Encompass, or Allstate -- not form choices."""
    o = row(NG, "NC3-036", occupancy_type="Seasonal", primary_home_carrier=carrier)
    assert o[0] == want
    if want == "NOTE":
        assert "Allstate or Encompass" in rv._map()["NC3-036"]["test"]


@pytest.mark.parametrize("ppc,rid", [("10", "NC3-151"), ("10W", "NC3-151"), ("9", "NC3-180"), ("10", "NC3-180")])
def test_natgen_pc_9_10_ineligible_exposures_are_confirms_that_say_so(ppc, rid):
    o = out(NG, ppc=ppc, fire_station_miles=4.0)
    assert o[rid][0] == "NOTE" and "not eligible" in rv._map()[rid]["test"]
    assert out(NG, ppc="7")[rid][0] == "N/A"


def test_natgen_mold_and_island_confirms_show_on_every_home():
    o = out(NG)
    assert o["NC3-113"][0] == "NOTE" and o["NC3-136"][0] == "NOTE"
    assert out(NG, coastal_tier="Not Coastal", county="Bexar", **NOT_HARRIS)["NC3-136"][0] == "NOTE"


def test_natgen_trust_and_flood_rows_decline_when_unmet():
    assert rv._map()["NC3-007"]["outcome_if_fail"] == "DECLINES"
    assert rv._map()["NC3-158"]["outcome_if_fail"] == "DECLINES"


@pytest.mark.parametrize("types", [["Fire"], ["Fire", "Water"]])
def test_occidental_fpc_rows_fail_on_a_fire_loss_the_form_shows(types):
    """p.10: "No prior fire losses" -- the form's loss types name Fire (it held before)."""
    loss = dict(losses_5yr=str(len(types)), losses_3yr=str(len(types)), loss_types=types, loss_year=2025)
    for rid, kw in (("OCC-095", dict(hydrant_1000ft="No", fire_station_miles=3.0)), ("OCC-096", dict(fire_station_miles=7.0))):
        assert row(OC, rid, year_built=2015, **kw, **loss)[0] == "FAIL"
        assert row(OC, rid, year_built=2015, **kw, **dict(loss, loss_types=["Theft"]))[0] == "OPEN"
        assert row(OC, rid, year_built=2015, **kw)[0] == "OPEN"            # no losses: the table's other conditions


@pytest.mark.parametrize("occ,want", [("Seasonal", "NOTE"), ("Secondary Home", "NOTE"), ("Owner Occupied", "N/A")])
def test_occidental_unoccupied_three_months_is_a_confirm_on_a_seasonal_home(occ, want):
    assert row(OC, "OCC-022", occupancy_type=occ, units_in_building="1")[0] == want


@pytest.mark.parametrize("construction,want", [("Frame", "NOTE"), ("Masonry", "NOTE"), ("Manufactured/Mobile", "FAIL")])
def test_occidental_mobile_home_on_the_premises_is_a_confirm(construction, want):
    assert row(OC, "OCC-046", construction_type=construction)[0] == want


# ==================================================================== numeric gates: in the gate vs out of it
# (carrier, row, other answers, field, a value just inside -> outcome, a value just outside -> outcome)
GATE_BOUNDARY = [
    (NG, "NC3-024", {}, "dwelling_amount", 2000001, "NOTE", 2000000, "N/A"),
    (NG, "NC3-025", dict(fire_station_miles=4.0), "ppc", "9", "NOTE", "8", "N/A"),
    (NG, "NC3-039", dict(fire_station_miles=4.0), "ppc", "9", "NOTE", "8", "N/A"),
    (NG, "NC3-051", {}, "dwelling_amount", 1500001, "NOTE", 1500000, "N/A"),
    (NG, "NC3-052", dict(ppc="9", fire_station_miles=4.0), "dwelling_amount", 750001, "NOTE", 750000, "N/A"),
    (NG, "NC3-053", dict(occupancy_type="Seasonal"), "dwelling_amount", 750001, "NOTE", 750000, "N/A"),
    (NG, "NC3-128", dict(dwelling_type="Townhome", construction_type="Frame"), "year_built", 1979, "NOTE", 1980, "N/A"),
    (NG, "NC3-151", dict(fire_station_miles=4.0), "ppc", "10", "NOTE", "9", "N/A"),
    (NG, "NC3-160", dict(dwelling_amount=1600000), "year_built", 1929, "NOTE", 1930, "N/A"),
    (NG, "NC3-161", {}, "dwelling_amount", 1500001, "NOTE", 1500000, "N/A"),
    (NG, "NC3-180", dict(fire_station_miles=4.0), "ppc", "9", "NOTE", "8", "N/A"),
    (OC, "OCC-093", dict(ppc="3", hydrant_1000ft="No"), "fire_station_miles", 5.0, "OPEN", 5.5, "N/A"),
    (OC, "OCC-094", dict(ppc="3"), "fire_station_miles", 5.5, "OPEN", 5.0, "N/A"),
    (OC, "OCC-095", dict(hydrant_1000ft="No", fire_station_miles=5.0), "year_built", 2002, "OPEN", 2001, "FAIL"),
    (OC, "OCC-096", dict(fire_station_miles=5.5, year_built=2015), "ppc", "8", "OPEN", "9", "N/A"),
]
NUMERIC_COVERED = {b[1] for b in BOUNDARY} | {g[1] for g in GATE_BOUNDARY}


@pytest.mark.parametrize("canon,rid,base,field,inside,want_in,outside,want_out", GATE_BOUNDARY,
                         ids=[g[1] for g in GATE_BOUNDARY])
def test_a_numeric_gate_applies_exactly_at_its_number(canon, rid, base, field, inside, want_in, outside, want_out):
    assert row(canon, rid, **dict(base, **{field: inside}))[0] == want_in
    assert row(canon, rid, **dict(base, **{field: outside}))[0] == want_out
