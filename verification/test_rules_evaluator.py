"""Round 25 (Liam, 2026-10-03/04): the rules-table evaluator and its data.
Zero API. Ported from round 24's experiments/test_rule_evaluator.py, plus
decisions 1 and 2."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval

BASE = {"year_built": 2000, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "aggressive_breed": "No", "solar_panels": "No",
        "ppc": "3", "dwelling_type": "House", "county": "Travis", "dwelling_amount": 450000}
ALLIED, SAGE, CHUBB = "Allied_Trust_HO3", "Sage_-_Auros_HO3", "CHUBB_HO_-_05.22.2026"


def line(field, test, gate="always", outcome="DECLINES", open_fact="", note=""):
    return {"row_id": "X-1", "field": field, "test": test, "gate": gate, "outcome_if_fail": outcome,
            "open_fact": open_fact, "map_note": note}


def run(m, **pd):
    return ev.evaluate_row(m, ev.facts(dict(BASE, **pd)))[0]


# -- the data -------------------------------------------------------------------
def test_data_files_carry_their_source_header():
    for path in (ev.RULES_CSV, ev.MAP_CSV):
        first = open(path, encoding="utf-8-sig").readline()
        assert first.startswith("# source:") and "version 3" in first and "2026-10-04" in first


def test_every_deciding_row_has_exactly_one_map_line():
    rules, fmap = ev.load_rules(), ev.load_map()
    deciding = {rid for rid, r in rules.items() if r["Tool handling"] in ev.DECIDING}
    assert len(rules) == 790 and len(deciding) == 541
    assert set(fmap) == deciding


def test_ignored_rows_are_never_used():
    rules, fmap = ev.load_rules(), ev.load_map()
    for rid in fmap:
        assert rules[rid]["Tool handling"] not in ("IGNORE_INSPECTION", "NOT_ELIGIBILITY")
    for rid in ("PRO-018", "SWY-018", "ALL-067"):                 # the v3 changes
        assert rid not in fmap
    assert ev.load_map()["PRO-038"]["field"] == "NONE"


def test_every_expression_parses():
    f = ev.facts(BASE)
    for m in ev.load_map().values():
        if m["field"] != "NONE":
            ev.evaluate_expr(m["gate"] or "always", f)
            for t in m["test"].split("||"):
                ev.evaluate_expr(t, f)


# -- outcomes -------------------------------------------------------------------
def test_pass_fail_na():
    m = line("roof_age", "roof_age <= 30")
    assert run(m, roof_age=12) == "PASS" and run(m, roof_age=31) == "FAIL"
    g = line("year_built;plumbing_type", "plumbing_type != Galvanized", gate="home_age between 40 and 75")
    assert run(g, year_built=2000, plumbing_type="Galvanized") == "N/A"         # home 26
    assert run(g, year_built=1970, plumbing_type="Galvanized") == "FAIL"


def test_open_on_a_fact_the_form_lacks():
    m = line("ppc", "FACT(paved road)", gate="ppc_num between 9 and 10", open_fact="paved road")
    assert run(m, ppc="9") == "OPEN" and run(m, ppc="3") == "N/A"


def test_unticked_pool_box_is_unknown():
    m = line("swimming_pool;pool_fence_4ft;pool_gate_locking",
             "pool_fence_4ft == True and pool_gate_locking == True", gate="swimming_pool != No Pool")
    assert run(m, swimming_pool="In Ground - Fenced") == "OPEN"
    assert run(m, swimming_pool="In Ground - Fenced", pool_fence_4ft=True, pool_gate_locking=True) == "PASS"


def test_ambiguous_readings():
    m = line("roof_type", "roof_type != Wood Shake || roof_type not in {Wood Shake, Metal}")
    assert [run(m, roof_type=t) for t in ("Composition Shingle", "Wood Shake", "Metal")] == ["PASS", "FAIL", "OPEN"]


def test_skip_when_the_topic_is_unchecked():
    m = line("roof_age", "roof_age <= 30")
    f = ev.facts(dict(BASE, roof_age=40))
    assert ev.evaluate_row(m, f, checked={"ppc"})[0] == "SKIP"
    assert ev.evaluate_row(m, f, checked={"roof_age"})[0] == "FAIL"


# -- decision 1: blank Coverage A / County is a note, never a hold ---------------
@pytest.mark.parametrize("pd", [{"dwelling_amount": None}, {"dwelling_amount": ""}])
def test_blank_coverage_a_on_allieds_limit_rows_is_a_note_and_no_hold(pd):
    out = ev.evaluate_carrier(ALLIED, dict(BASE, **pd))
    assert out["ALL-133"][0] == "NOTE" and out["ALL-134"][0] == "NOTE"
    assert "confirm" in out["ALL-133"][1]
    rec, decided = ev.code_record(ALLIED, out)
    assert decided and rec["status"] == "ELIGIBLE"
    assert any("[ALL-133] Coverage A minimum is $200,000" in n for n in rec["also_confirm"])


def test_filled_coverage_a_still_decides():
    out = ev.evaluate_carrier(ALLIED, dict(BASE, dwelling_amount=150000))
    assert out["ALL-133"][0] == "FAIL"
    rec, _ = ev.code_record(ALLIED, out)
    assert rec["status"] == "INELIGIBLE" and rec["citations"][0].startswith("Allied_Trust_HO3: [ALL-133] p.")


def test_blank_county_on_sages_territory_rows_is_a_note_in_the_evaluator():
    """The evaluator notes it; the round 19 Sage county HOLD is the pipeline's
    and still fires (test_eligibility_matrix, TestRulesPilotWiring)."""
    out = ev.evaluate_carrier(SAGE, dict(BASE, county=""))
    assert out["SAG-081"][0] == "NOTE" and out["SAG-082"][0] == "NOTE"


def test_a_real_fact_still_opens():
    out = ev.evaluate_carrier("Progressive_HO3_-_04.01.2026", dict(BASE, ppc="9"))
    assert out["PRO-068"][0] == "OPEN"


# -- decision 2: condition standards are notes ----------------------------------
def test_condition_standard_rows_are_also_confirm_notes():
    rules = ev.load_rules()
    std = [rid for rid, r in rules.items() if r["Carrier"] == "Allied Trust HO3"
           and r["Tool handling"] == "CONDITION_STANDARD"]
    assert std
    rec, _ = ev.code_record(ALLIED, ev.evaluate_carrier(ALLIED, BASE))
    blob = " ".join(rec["also_confirm"])
    assert all(rid in blob for rid in std) and "never a hold" in blob


# -- cure is an inspection ----------------------------------------------------------
def test_cure_is_inspection_fail_is_a_note_naming_the_cure():
    out = ev.evaluate_carrier(ALLIED, dict(BASE, year_built=1970, plumbing_type="Galvanized"))
    assert out["ALL-058"] == ("NOTE", "cure is an inspection (not checked)")
    assert out["ALL-057"][0] == "FAIL"                      # the band-free row still declines
    rec, _ = ev.code_record(ALLIED, out)
    assert rec["status"] == "INELIGIBLE"
    assert any(n.startswith("[ALL-058]") and "inspection" in n for n in rec["also_confirm"])


def test_home_age_26_does_not_trigger_a_40_75_row():
    out = ev.evaluate_carrier(ALLIED, dict(BASE, year_built=2000, plumbing_type="Galvanized"))
    assert out["ALL-058"][0] == "N/A" and out["ALL-028"][0] == "N/A"


# -- carrier result ---------------------------------------------------------------
def test_open_rows_leave_the_carrier_to_the_model():
    out = ev.evaluate_carrier("Swyfft_-_Benchmark_(Admitted)_HO3",
                              dict(BASE, swimming_pool="In Ground - Fenced"))
    rec, decided = ev.code_record("Swyfft_-_Benchmark_(Admitted)_HO3", out)
    assert not decided and rec["status"] == "INSUFFICIENT_INFORMATION"
    assert "[SWY-035]" in ev.evidence_text({"Swyfft_-_Benchmark_(Admitted)_HO3": out})


def test_a_fail_decides_even_with_open_rows():
    out = ev.evaluate_carrier(ALLIED, dict(BASE, year_built=1970, plumbing_type="Galvanized", roof_age=20))
    rec, decided = ev.code_record(ALLIED, out)
    assert decided and rec["status"] == "INELIGIBLE"


def test_chubb_below_one_million_is_refer_by_its_row():
    rec, decided = ev.code_record(CHUBB, ev.evaluate_carrier(CHUBB, BASE))
    assert decided and rec["status"] == "REFER" and "[CHU-056]" in rec["reasons"][0]


def test_model_record_gets_quotes_for_the_row_ids_it_names():
    out = ev.evaluate_carrier("Progressive_HO3_-_04.01.2026", dict(BASE, ppc="9"))
    rec = ev.finish_model_record({"carrier": "Progressive HO3", "status": "INSUFFICIENT_INFORMATION",
                                  "reasons": ["[PRO-068] needs a paved road; [ALL-001] is not this carrier's"],
                                  "citations": [], "missing_info": [], "notes": "", "flaw_count": 0},
                                 "Progressive_HO3_-_04.01.2026", out)
    assert rec["citations"] and rec["citations"][0].startswith("Progressive_HO3_-_04.01.2026: [PRO-068] p.")
    assert not any("ALL-001" in c for c in rec["citations"])
    assert rec["rules_table"] and rec["carrier"] == "Progressive_HO3_-_04.01.2026"
