"""Round 27 step 5 (Liam's decision 4, 2026-10-06): the Sage batch's rules
table data and map lines (rules_data/carrier_rules_sage_batch_v1.csv,
rules_data/sage_batch_field_map.csv). Zero API. The rows are not yet
reviewed; nothing in the app reads them unless ELIGIBILITY_RULES_SAGE_BATCH is
"1" (step 6)."""
import collections
import itertools
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rules_data"))
import build_sage_batch_map as builder  # noqa: E402
import rules_evaluator as ev  # noqa: E402
from structured_rules import sage_fpc_with_distance  # noqa: E402

pytestmark = pytest.mark.retrieval

RULES_CSV = os.path.join(ROOT, "rules_data", "carrier_rules_sage_batch_v1.csv")
MAP_CSV = os.path.join(ROOT, "rules_data", "sage_batch_field_map.csv")
RULES = {r["Rule ID"]: r for r in ev._read_csv(RULES_CSV)}
FMAP = {m["row_id"]: m for m in ev._read_csv(MAP_CSV)}
BASE = {"year_built": 2010, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "aggressive_breed": "No", "solar_panels": "No",
        "ppc": "3", "dwelling_type": "House", "county": "Bexar", "dwelling_amount": 450000}
CARRIERS = {"SUR": "Sage SURE HO-3", "SFP": "Sage SafePort HO-3", "WIL": "Sage Wilshire HO3",
            "TRI": "Sage Trium Lloyd's HO3/HO5", "MKL": "Sage Markel HO3", "VAV": "Sage Vave HO3"}
SISTERS = ("SUR", "SFP", "WIL", "TRI")


def outcomes(prefix, **pd):
    f = ev.facts(dict(BASE, **pd))
    return {rid: ev.evaluate_row(m, f) for rid, m in FMAP.items() if rid.startswith(prefix)}


def fails(prefix, **pd):
    return sorted(rid for rid, (o, _) in outcomes(prefix, **pd).items() if o == "FAIL")


# -- the data -------------------------------------------------------------------
def test_data_files_carry_their_source_header():
    for path in (RULES_CSV, MAP_CSV):
        first = open(path, encoding="utf-8-sig").readline()
        assert first.startswith("# source:") and "Sage batch version 1" in first and "2026-10-06" in first
        assert "not yet reviewed" in first.lower()


def test_every_deciding_row_has_exactly_one_map_line():
    deciding = {rid for rid, r in RULES.items() if r["Tool handling"] in ev.DECIDING}
    assert len(RULES) == 1033 and len(deciding) == 564
    assert set(FMAP) == deciding
    assert {r["Carrier"] for r in RULES.values()} == set(CARRIERS.values())
    assert all(rid[:3] in CARRIERS and RULES[rid]["Carrier"] == CARRIERS[rid[:3]] for rid in RULES)
    # no id collides with the six-carrier pilot's rows
    assert not set(RULES) & set(ev.load_rules())


def test_ignored_rows_are_never_mapped():
    for rid in FMAP:
        assert RULES[rid]["Tool handling"] not in ("IGNORE_INSPECTION", "NOT_ELIGIBILITY", "CONDITION_STANDARD")


def test_the_map_file_is_what_the_builder_writes():
    for rid, m in FMAP.items():
        want = builder.MAP.get(rid)
        if want is None:
            assert m["field"] == "NONE"
        else:
            assert (m["field"], m["test"], m["gate"], m["open_fact"], m["map_note"]) == want


@pytest.mark.parametrize("pd", [BASE, dict(BASE, county="", dwelling_amount=None, ppc="N/A", plumbing_type="Unknown"),
                                dict(BASE, fire_station_miles="7", hydrant_1000ft="No", ppc="6", year_built=1970)])
def test_every_expression_parses(pd):
    f = ev.facts(pd)
    for m in FMAP.values():
        if m["field"] != "NONE":
            ev.evaluate_expr(m["gate"] or "always", f)
            for t in m["test"].split("||"):
                ev.evaluate_expr(t, f)
            assert set(ev.row_topics(m)) <= set(ev.FIELD_TOPIC.values()) | {None}


def test_coverage_per_carrier():
    """The coverage table in RULE_FIELD_MAP.md (step 5)."""
    kinds = collections.Counter(builder.kind(builder.MAP.get(rid, ("NONE", "", "", "", ""))) for rid in FMAP)
    assert kinds == {"decided by a form field": 79, "gated-but-open": 71, "AMBIGUOUS": 3,
                     "same rule as another row": 15, "NONE": 396}
    per = collections.Counter(rid[:3] for rid in FMAP)
    assert per == {"SUR": 117, "SFP": 120, "WIL": 95, "TRI": 113, "MKL": 61, "VAV": 58}


# -- owner occupied means the owner's own home: primary, seasonal or secondary ----
@pytest.mark.parametrize("prefix", SISTERS + ("VAV",))
@pytest.mark.parametrize("occupancy", ["Owner Occupied", "Seasonal", "Secondary Home"])
def test_an_owners_seasonal_or_secondary_home_passes_the_owner_occupied_row(prefix, occupancy):
    # Two phrasings: "Homes must be owner occupied" (SURE/SafePort/Wilshire/Trium,
    # under "Dwellings must be owner occupied: Primary ... Seasonal or Secondary")
    # and Vave's "the HO3 is offered only for owner-occupied 1-4 family" (with
    # "Primary, secondary, seasonal ... homes are accepted").
    owner = {"SUR": "SUR-013", "SFP": "SFP-013", "WIL": "WIL-013", "TRI": "TRI-002", "VAV": "VAV-001"}[prefix]
    assert outcomes(prefix, occupancy_type=occupancy)[owner][0] == "PASS"


@pytest.mark.parametrize("prefix", SISTERS + ("VAV", "MKL"))
def test_tenant_and_vacant_each_fail_once_on_occupancy(prefix):
    occ = {rid for rid in FMAP if rid.startswith(prefix) and RULES[rid]["Topic"] == "OCCUPANCY"
           and FMAP[rid]["field"] == "occupancy_type"}
    vacant = [rid for rid in fails(prefix, occupancy_type="Vacant") if rid in occ]
    assert len(vacant) == 1, vacant
    if prefix != "MKL":        # Markel writes rentals (MKL-012/013 are about student and corporate rentals)
        assert len([rid for rid in fails(prefix, occupancy_type="Tenant Occupied") if rid in occ]) == 1


# -- territory: one failing row per fact; Trium has no Nueces exception ------------
@pytest.mark.parametrize("prefix", SISTERS)
def test_a_county_outside_the_territory_fails_one_row(prefix):
    assert len([r for r in fails(prefix, county="Dallas") if RULES[r]["Topic"] == "LOCATION"]) == 1
    assert [r for r in fails(prefix, county="Bexar") if RULES[r]["Topic"] == "LOCATION"] == []
    assert [r for r in fails(prefix, county="Polk") if RULES[r]["Topic"] == "LOCATION"] == []   # East Texas list


@pytest.mark.parametrize("prefix,expected", [("SUR", ["SUR-002"]), ("SFP", ["SFP-002"]), ("WIL", ["WIL-002"]),
                                             ("TRI", [])])
def test_nueces(prefix, expected):
    assert [r for r in fails(prefix, county="Nueces") if RULES[r]["Topic"] == "LOCATION"] == expected


@pytest.mark.parametrize("prefix", SISTERS)
def test_a_blank_county_is_a_note_never_a_hold(prefix):
    out = outcomes(prefix, county="")
    terr = [rid for rid, m in FMAP.items() if rid.startswith(prefix) and "sage_territory" in m["test"]]
    assert terr and all(out[rid][0] == "NOTE" for rid in terr)


# -- the FPC table rows agree with round 27 step 2's sage_fpc_with_distance ------
FPC_IDS = {"SUR": ["SUR-111", "SUR-112", "SUR-113", "SUR-114", "SUR-115", "SUR-116", "SUR-117"],
           "SFP": ["SFP-119", "SFP-120", "SFP-121", "SFP-122", "SFP-123", "SFP-124", "SFP-125"],
           "WIL": ["WIL-116", "WIL-117", "WIL-118", "WIL-119", "WIL-120", "WIL-121", "WIL-122", "WIL-123"],
           "TRI": ["TRI-088", "TRI-089", "TRI-090", "TRI-091", "TRI-092", "TRI-035", "TRI-019", "TRI-020"]}
PROGRAM = {"SUR": "Sage_-_SURE_HO-3_-_01.31.2026", "SFP": "Sage_-_SafePort_HO-3_-_01.31.2026",
           "WIL": "Sage_-_Wilshire_HO3_-_12.02.2025",
           "TRI": "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026"}


def _fpc_status(prefix, pd):
    f = ev.facts(dict(BASE, **pd))
    res = {rid: ev.evaluate_row(FMAP[rid], f) for rid in FPC_IDS[prefix]}
    eff = {rid: FMAP[rid]["outcome_if_fail"] for rid in res}
    if any(o == "FAIL" and eff[r] == "DECLINES" for r, (o, _) in res.items()):
        return "INELIGIBLE"
    if any(o == "FAIL" for o, _ in res.values()):
        return "REFER"
    if any(o == "OPEN" for o, _ in res.values()):
        return "INSUFFICIENT_INFORMATION"
    return "ELIGIBLE"


GRID = list(itertools.product(range(1, 11), (3, 7), ("Yes", "No", None), (2010, 1990)))


@pytest.mark.parametrize("prefix", SISTERS)
def test_fpc_rows_agree_with_the_step_2_table_for_an_owner_occupied_home(prefix):
    bad = []
    for ppc, miles, hydrant, yb in GRID:
        pd = {"ppc": str(ppc), "fire_station_miles": str(miles), "hydrant_1000ft": hydrant or "Unknown",
              "year_built": yb}
        want = sage_fpc_with_distance(str(ppc), miles, hydrant, home_age=ev.facts(dict(BASE, **pd))["home_age"],
                                      occupancy="Owner Occupied", carrier=PROGRAM[prefix])[0]
        got = _fpc_status(prefix, pd)
        if got != want:
            bad.append((ppc, miles, hydrant, yb, want, got))
    assert bad == []


@pytest.mark.xfail(strict=True, reason="round 27: step 2's sage_fpc_with_distance holds a known Seasonal / "
                                        "Tenant home on 'Primary occupancy only'; the rows (as SAG-075) REFER it. "
                                        "Not changed: step 6 must leave the batch-OFF path byte-identical.")
def test_fpc_rows_agree_with_the_step_2_table_for_a_seasonal_home():
    pd = {"ppc": "6", "fire_station_miles": "7", "hydrant_1000ft": "No", "occupancy_type": "Seasonal"}
    want = sage_fpc_with_distance("6", 7, "No", home_age=16, occupancy="Seasonal", carrier=PROGRAM["SUR"])[0]
    assert _fpc_status("SUR", pd) == want


@pytest.mark.parametrize("prefix", SISTERS)
def test_a_blank_distance_leaves_the_fpc_rows_open_never_eligible(prefix):
    # Round 26 decision B: blank / Unknown is unknown, never "no" -- as Auros's rows.
    assert _fpc_status(prefix, {"ppc": "3"}) == "INSUFFICIENT_INFORMATION"
    assert _fpc_status(prefix, {"ppc": "3", "fire_station_miles": "3", "hydrant_1000ft": "Yes"}) == "ELIGIBLE"


# -- Coverage A -------------------------------------------------------------------
@pytest.mark.parametrize("rid,amount,outcome", [
    ("SUR-090", 4000000, "PASS"), ("SUR-090", 4000001, "FAIL"), ("SFP-095", 5000000, "PASS"),
    ("WIL-096", 2000001, "FAIL"), ("TRI-111", 1300000, "FAIL"), ("VAV-079", 2000000, "PASS"),
    ("MKL-079", 99999, "FAIL"), ("VAV-078", 100000, "PASS"), ("SUR-100", 84999, "FAIL")])
def test_coverage_a_limits(rid, amount, outcome):
    assert outcomes(rid[:3], dwelling_amount=amount)[rid][0] == outcome


def test_the_fpc_b_or_c_coverage_cap_applies_only_on_those_rows():
    big = 3000000
    assert outcomes("SUR", dwelling_amount=big, fire_station_miles="3", hydrant_1000ft="Yes")["SUR-091"][0] == "N/A"
    assert outcomes("SUR", dwelling_amount=big, fire_station_miles="7")["SUR-091"][0] == "FAIL"
    assert outcomes("SFP", dwelling_amount=big, fire_station_miles="3", hydrant_1000ft="No")["SFP-097"][0] == "FAIL"
