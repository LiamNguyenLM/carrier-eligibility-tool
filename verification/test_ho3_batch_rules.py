"""Round 29 step 7 (2026-10-08): the HO3 batch's rules-table data, map lines,
registry entry and switch (ELIGIBILITY_RULES_HO3_BATCH, exactly "1", only with
the pilot on). Zero API."""
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
import build_ho3_batch_map as builder  # noqa: E402
import eligibility_check as ec  # noqa: E402
import measure_rules_pilot as M  # noqa: E402
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval

RULES = ev._load("rules", ev.HO3_BATCH_RULES_CSV)
FMAP = ev._load("map", ev.HO3_BATCH_MAP_CSV)
PREFIX = {"ARA", "ARB", "FOR", "HOA", "LIB", "ORI", "SBS", "SLL", "STO", "TWI", "TRV"}
FOREMOST = "Foremost_DP3_and_HO3_-_07.01.2026"


def test_data_files_carry_their_source_header():
    for path in (ev.HO3_BATCH_RULES_CSV, ev.HO3_BATCH_MAP_CSV):
        first = open(path, encoding="utf-8-sig").readline()
        assert first.startswith("# source:") and "HO3 batch version 1" in first and "2026-10-08" in first


def test_every_deciding_row_has_exactly_one_map_line():
    deciding = {rid for rid, r in RULES.items() if r["Tool handling"] in ev.DECIDING}
    assert len(RULES) == 964 and len(deciding) == 615
    assert set(FMAP) == deciding
    assert {rid[:3] for rid in RULES} == PREFIX
    assert {r["Carrier"] for r in RULES.values()} == set(ev.HO3_BATCH_CARRIERS)
    assert not set(RULES) & (set(ev.load_rules()) | set(ev.load_batch_rules()))


def test_ignored_rows_are_never_mapped_and_the_file_is_the_builders():
    for rid, m in FMAP.items():
        assert RULES[rid]["Tool handling"] not in ("IGNORE_INSPECTION", "NOT_ELIGIBILITY", "CONDITION_STANDARD")
        want = builder.MAP.get(rid)
        if want is None:
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
    # CHANGED DELIBERATELY (round 30 step 1, 2026-10-08; Liam's decision 1): ARA-029, SBS-027, TWI-005
    # and TRV-039 are decided by the new primary-home questions (were 102 / 61).
    assert kinds == {"decided by a form field": 106, "gated-but-open": 57, "AMBIGUOUS": 14,
                     "same rule as another row": 18, "NONE": 420}


# -- the registry: Foremost's homeowners rows never apply to a dwelling-fire check ------------
@pytest.mark.parametrize("occupancy,wb", [("Owner Occupied", "Foremost Choice Homeowners"),
                                         ("Seasonal", "Foremost Choice Homeowners"),
                                         ("Secondary Home", "Foremost Choice Homeowners"),
                                         ("Tenant Occupied", None), ("Vacant", None)])
def test_foremost_homeowners_rows_apply_only_to_an_owners_home(occupancy, wb):
    assert ev.rules_table_wb(FOREMOST, {"ho3"}, {"occupancy_type": occupancy}) == wb


def test_a_batch_carrier_is_on_the_rules_table_only_with_its_switch():
    pd = {"occupancy_type": "Owner Occupied"}
    for canon in ev.HO3_BATCH_CARRIERS.values():
        assert ev.rules_table_wb(canon, set(), pd) is None
        assert ev.rules_table_wb(canon, {"sage"}, pd) is None
        assert ev.rules_table_wb(canon, {"ho3"}, pd) is not None


@pytest.mark.parametrize("pilot,batch,on", [("1", "1", True), ("1", "true", False), ("1", "", False),
                                            ("0", "1", False), ("", "1", False)])
def test_the_ho3_batch_needs_exactly_1_and_the_pilot(pilot, batch, on):
    env = dict(os.environ, ELIGIBILITY_RULES_PILOT=pilot, ELIGIBILITY_RULES_HO3_BATCH=batch,
               ANTHROPIC_API_KEY="x", OPENAI_API_KEY="x")
    env.pop("ELIGIBILITY_RULES_SAGE_BATCH", None)
    out = subprocess.run([sys.executable, "-c", "import eligibility_check as e; print(e.RULES_HO3_BATCH); "
                                                "print(e.rules_pilot_status_line())"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    flag, line = out.stdout.strip().splitlines()[-2:]
    assert flag == str(on), out.stderr[-500:]
    assert ("HO3 batch ON (11 more)" in line) == on


def test_the_panel_line_names_each_batch(monkeypatch):
    monkeypatch.setattr(ec, "RULES_PILOT", True)
    monkeypatch.setattr(ec, "RULES_SAGE_BATCH", True)
    monkeypatch.setattr(ec, "RULES_HO3_BATCH", True)
    assert ec.rules_pilot_status_line() == "Rules pilot: ON (6 carriers) + Sage batch ON (6 more) + HO3 batch ON (11 more)"
    monkeypatch.setattr(ec, "RULES_SAGE_BATCH", False)
    assert ec.rules_pilot_status_line() == "Rules pilot: ON (6 carriers) + HO3 batch ON (11 more)"


# -- in the pipeline -------------------------------------------------------------------------
USAGE = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}
GALVANIZED_ROWS = {"ARI_(HOA+)": "ARA-050", "ARI_(HOB)": "ARB-048", "Swyfft_-_Benchmark_(Surplus)_HO3": "SBS-030",
                   "Swyfft_-_Topa_(Surplus)_HO3": "STO-032", "Swyfft_-_Lloyds_(Surplus)_HO3": "SLL-045",
                   "TWICO_HO3": "TWI-039", "Travelers_HO3_-_06.12.2026": "TRV-054"}


def _run(pd, ho3=True):
    def fake(system, user, max_tokens):
        names = (re.findall(r"--- (.+?) \(rule check\) ---", user) if "RULE CHECK:" in user
                 else sorted(set(re.findall(r"\n--- (.+?) \(page", user))))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    saved = ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH
    ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH = fake, True, True, ho3
    try:
        return {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}
    finally:
        ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH = saved


@pytest.mark.parametrize("carrier,row", sorted(GALVANIZED_ROWS.items()))
def test_with_the_batch_on_a_galvanized_home_is_declined_by_the_carriers_own_row(carrier, row):
    # Round 28: no model applied these, because the rule never reached the prompt. Code decides now.
    res = _run(M.PROFILES["OLD"])
    r = res[carrier]
    assert r["status"] == "INELIGIBLE" and r.get("rules_table")
    assert any(x.startswith(f"[{row}]") for x in r["reasons"]), r["reasons"]


def test_with_the_batch_off_the_eleven_stay_with_the_model():
    res = _run(M.PROFILES["OLD"], ho3=False)
    assert not any(res[c].get("rules_table") for c in ev.HO3_BATCH_CARRIERS.values() if c in res)


def test_foremost_tenant_check_does_not_use_the_homeowners_rows():
    res = _run(dict(M.PROFILES["OLD"], occupancy_type="Tenant Occupied"))
    assert not res[FOREMOST].get("rules_table")
    assert not any(re.search(r"\[FOR-\d{3}\]", x) for x in res[FOREMOST]["reasons"])
