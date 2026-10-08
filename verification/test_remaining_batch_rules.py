"""Round 29 step 8 (2026-10-08): the remaining (dwelling fire) batch's rules-table data,
map lines, registry entry and switch (ELIGIBILITY_RULES_DP_BATCH, exactly "1", only with
the pilot on), and NatGen Premier DP3's closed-program row. Zero API."""
import collections
import json
import os
import re
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rules_data"))
sys.path.insert(0, os.path.dirname(__file__))
import build_remaining_batch_map as builder  # noqa: E402
import eligibility_check as ec  # noqa: E402
import measure_rules_pilot as M  # noqa: E402
import rules_evaluator as ev  # noqa: E402
from profiles import STANDARD_PROFILE  # noqa: E402

pytestmark = pytest.mark.retrieval

RULES = ev._load("rules", ev.DP_BATCH_RULES_CSV)
FMAP = ev._load("map", ev.DP_BATCH_MAP_CSV)
FOREMOST = "Foremost_DP3_and_HO3_-_07.01.2026"
NPD = "NatGen_Premier_OneChoice_DP3_-_02.26.2025"
# The dwelling-fire programs (not Centauri HO3 or Progressive HO6).
DP = {wb: c for wb, c in ev.DP_BATCH_CARRIERS.items() if wb not in ("Centauri HO3 (scanned, OCR)",
                                                                    "Progressive HO6 (condo)")}


def test_data_files_carry_their_source_header():
    for path in (ev.DP_BATCH_RULES_CSV, ev.DP_BATCH_MAP_CSV):
        first = open(path, encoding="utf-8-sig").readline()
        assert first.startswith("# source:") and "remaining batch version 1" in first and "2026-10-08" in first


def test_every_deciding_row_has_exactly_one_map_line():
    deciding = {rid for rid, r in RULES.items() if r["Tool handling"] in ev.DECIDING}
    assert len(RULES) == 1655 and len(deciding) == 990
    assert set(FMAP) == deciding
    other = set(ev.load_rules()) | set(ev.load_batch_rules()) | set(ev._load("rules", ev.HO3_BATCH_RULES_CSV))
    assert not set(RULES) & other
    # every workbook carrier but the closed NatGen Premier DP3 is in the registry
    assert {r["Carrier"] for r in RULES.values()} == set(ev.DP_BATCH_CARRIERS) | {"NatGen Premier Dwelling Fire (closed)"}


def test_ignored_rows_are_never_mapped_and_the_file_is_the_builders():
    for rid, m in FMAP.items():
        assert RULES[rid]["Tool handling"] not in ("IGNORE_INSPECTION", "NOT_ELIGIBILITY", "CONDITION_STANDARD")
        want = builder.MAP.get(rid)
        if want is None or want[0] == "NONE":
            assert m["field"] == "NONE"
        else:
            assert (m["field"], m["test"], m["gate"], m["open_fact"], m["map_note"]) == want


@pytest.mark.parametrize("prof", ["OLD", "CLEAN", "STRESS", "ALT"])
def test_every_expression_parses(prof):
    f = ev.facts(M.PROFILES[prof])
    for m in FMAP.values():
        if m["field"] != "NONE":
            ev.evaluate_expr(m["gate"] or "always", f)
            for t in m["test"].split("||"):
                ev.evaluate_expr(t, f)


def test_coverage():
    kinds = collections.Counter(builder.kind(builder.MAP.get(rid, ("NONE", "", "", "", ""))) for rid in FMAP)
    assert kinds == {"decided by a form field": 106, "gated-but-open": 55, "AMBIGUOUS": 17,
                     "same rule as another row": 40, "NONE": 772}


# -- the map's readings ----------------------------------------------------------------------
def _occupancy_outcomes(occupancy, prefixes):
    f = ev.facts(dict(STANDARD_PROFILE, county="Bexar", ppc="3", fire_station_miles="2", hydrant_1000ft="Yes",
                      occupancy_type=occupancy))
    out = collections.defaultdict(set)
    for rid, m in FMAP.items():
        if rid[:3] in prefixes and "occupancy_type" in m["field"]:
            out[ev.evaluate_row(m, f)[0]].add(rid)
    return out


DP_PREFIXES = {"CDP", "HDP", "LDP", "NCD", "PDP", "MDP", "ODP", "SDP", "FDP", "VDP", "STD", "FOD"}


def test_a_tenant_home_passes_every_dwelling_fire_occupancy_line():
    # Liam (round 29 step 8): dwelling fire is a landlord's policy; tenant occupancy is normally ELIGIBLE.
    out = _occupancy_outcomes("Tenant Occupied", DP_PREFIXES)
    assert not out["FAIL"] and not out["OPEN"], dict(out)


def test_the_owners_own_homes_fail_only_the_landlord_only_guides():
    # the other direction: Liberty / Safeco and NatGen Custom360 write landlords only
    assert _occupancy_outcomes("Owner Occupied", DP_PREFIXES)["FAIL"] == {"LDP-001", "NCD-047"}
    assert _occupancy_outcomes("Secondary Home", DP_PREFIXES)["FAIL"] == {"LDP-001", "NCD-047"}
    seasonal = _occupancy_outcomes("Seasonal", DP_PREFIXES)
    assert not seasonal["FAIL"] and seasonal["OPEN"] == {"LDP-001", "NCD-047"}   # may be a seasonal rental


def test_a_vacant_home_fails_each_guides_own_vacancy_row_once():
    fails = _occupancy_outcomes("Vacant", DP_PREFIXES)["FAIL"]
    assert fails == {"CDP-066", "LDP-013", "PDP-030", "MDP-006", "ODP-031", "SDP-015", "FDP-032", "VDP-026",
                     "STD-024", "FOD-005"}
    assert len({rid[:3] for rid in fails}) == len(fails)


@pytest.mark.parametrize("phrasing", ["liability coverage", "ineligible for liability"])
def test_liability_only_rows_never_decline_the_home(phrasing):
    rows = [rid for rid, r in RULES.items() if rid in FMAP and phrasing in r["Plain rule"].lower()]
    assert rows
    assert all(FMAP[rid]["field"] == "NONE" for rid in rows), [rid for rid in rows if FMAP[rid]["field"] != "NONE"]


def test_natgen_premier_dwelling_fire_is_closed_like_its_homeowners_program():
    assert ec.closed_programs([NPD]) == [NPD]
    assert all(FMAP[rid]["field"] == "NONE" and "CLOSED_PROGRAMS" in FMAP[rid]["map_note"]
               for rid in FMAP if rid.startswith("NPD-"))
    assert NPD not in ev.DP_BATCH_CARRIERS.values()


# -- the registry: Foremost's dwelling-fire rows apply only to a landlord's check ------------------
@pytest.mark.parametrize("occupancy,wb", [("Tenant Occupied", "Foremost Dwelling Fire (TDP-3)"),
                                         ("Vacant", "Foremost Dwelling Fire (TDP-3)"),
                                         ("Owner Occupied", None), ("Seasonal", None), ("Secondary Home", None)])
def test_foremost_dwelling_fire_rows_apply_only_to_a_landlords_check(occupancy, wb):
    assert ev.rules_table_wb(FOREMOST, {"dp"}, {"occupancy_type": occupancy}) == wb


@pytest.mark.parametrize("occupancy,wb", [("Tenant Occupied", "Foremost Dwelling Fire (TDP-3)"),
                                         ("Owner Occupied", "Foremost Choice Homeowners"),
                                         ("Seasonal", "Foremost Choice Homeowners")])
def test_with_both_batches_on_the_occupancy_picks_foremosts_program(occupancy, wb):
    assert ev.rules_table_wb(FOREMOST, {"ho3", "dp"}, {"occupancy_type": occupancy}) == wb


def test_a_batch_carrier_is_on_the_rules_table_only_with_its_switch():
    pd = {"occupancy_type": "Tenant Occupied"}
    for canon in ev.DP_BATCH_CARRIERS.values():
        assert ev.rules_table_wb(canon, set(), pd) is None
        assert ev.rules_table_wb(canon, {"sage", "ho3"}, pd) in (None, "Foremost Choice Homeowners")
        assert ev.rules_table_wb(canon, {"dp"}, pd) is not None


@pytest.mark.parametrize("pilot,batch,on", [("1", "1", True), ("1", "true", False), ("1", "", False),
                                            ("0", "1", False), ("", "1", False)])
def test_the_dp_batch_needs_exactly_1_and_the_pilot(pilot, batch, on):
    env = dict(os.environ, ELIGIBILITY_RULES_PILOT=pilot, ELIGIBILITY_RULES_DP_BATCH=batch,
               ANTHROPIC_API_KEY="x", OPENAI_API_KEY="x")
    for k in ("ELIGIBILITY_RULES_SAGE_BATCH", "ELIGIBILITY_RULES_HO3_BATCH"):
        env.pop(k, None)
    out = subprocess.run([sys.executable, "-c", "import eligibility_check as e; print(e.RULES_DP_BATCH); "
                                                "print(e.rules_pilot_status_line())"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    flag, line = out.stdout.strip().splitlines()[-2:]
    assert flag == str(on), out.stderr[-500:]
    assert ("DP batch ON (14 more)" in line) == on


def test_the_panel_line_names_each_batch(monkeypatch):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    assert ec.rules_pilot_status_line() == ("Rules pilot: ON (6 carriers) + Sage batch ON (6 more) + HO3 batch ON "
                                            "(11 more) + DP batch ON (14 more)")


# -- in the pipeline -------------------------------------------------------------------------
USAGE = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}
TENANT_C = dict(STANDARD_PROFILE, occupancy_type="Tenant Occupied", county="Bexar", ppc="6",
                fire_station_miles="7", hydrant_1000ft="Yes", year_built=2010)


def _run(pd, dp=True):
    def fake(system, user, max_tokens):
        names = (re.findall(r"--- (.+?) \(rule check\) ---", user) if "RULE CHECK:" in user
                 else sorted(set(re.findall(r"\n--- (.+?) \(page", user))))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    saved = ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH, ec.RULES_DP_BATCH
    ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH, ec.RULES_DP_BATCH = \
        fake, True, True, True, dp
    try:
        return {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}
    finally:
        ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH, ec.RULES_DP_BATCH = saved


@pytest.mark.parametrize("carrier,row", [("Sage_-_SURE_DP-3_-_01.31.2026", "SDP-081"),
                                         ("Sage_-_SafePort_DP-3_-_01.31.2026", "FDP-110")])
def test_with_the_batch_on_a_rental_in_the_fpc_c_band_is_declined_by_the_guides_own_row(carrier, row):
    r = _run(TENANT_C)[carrier]
    assert r["status"] == "INELIGIBLE" and r.get("rules_table")
    assert any(x.startswith(f"[{row}]") for x in r["reasons"]), r["reasons"]


def test_occidental_does_not_decline_a_rental_in_the_same_band():
    # ODP-115 reads "primary occupancy" as primary vs secondary / seasonal (its cell has no rental line)
    r = _run(TENANT_C)["Sage_-_Occidental_DP3"]
    assert not any(x.startswith("[ODP-115]") for x in r["reasons"] if r["status"] == "INELIGIBLE")


def test_with_the_batch_off_the_dwelling_fire_programs_stay_with_the_model():
    res = _run(TENANT_C, dp=False)
    assert not any(res[c].get("rules_table") for c in DP.values() if c in res and c != FOREMOST)


def test_a_foremost_tenant_check_uses_the_dwelling_fire_rows():
    r = _run(dict(TENANT_C, county="Galveston"))[FOREMOST]
    assert r["status"] == "INELIGIBLE" and any(x.startswith("[FOD-055]") for x in r["reasons"]), r["reasons"]
    assert not any(re.search(r"\[FOR-\d{3}\]", x) for x in r["reasons"])


def test_natgen_premier_dp3_shows_closed_on_a_tenant_check():
    r = _run(TENANT_C).get(NPD)
    assert r is not None and r["status"] == "INELIGIBLE" and "Closed to new business" in r["reasons"][0]
