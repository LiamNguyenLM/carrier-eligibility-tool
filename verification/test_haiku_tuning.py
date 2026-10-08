"""Round 31 step 3 (Liam, 2026-10-08, decision 1: optimize for Haiku -- reliability first, then speed).
Zero API.
  a. the structured-output schema is part of Claude's cached prefix, so every call gets the same carrier
     enum (all programs); a main call with no carriers is not made; a record for a carrier the call did
     not ask about is dropped.
  b. the rules check cites rows by id only (code adds the guide's words).
  c. the hold guard also reaches a rules-check record held only on facts the form never asks.
  d. the rules check can be split into parallel calls (ELIGIBILITY_RULES_SPLIT)."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import eligibility_check as ec  # noqa: E402
import hold_guard  # noqa: E402
import rules_evaluator as ev  # noqa: E402
from profiles import STANDARD_PROFILE  # noqa: E402

pytestmark = pytest.mark.retrieval
U = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}
LIVE_PD = dict(STANDARD_PROFILE, county="Bexar", dwelling_type="House")


# -- a. one schema for every Claude call --------------------------------------------------------
def test_two_calls_with_different_carriers_send_the_same_schema(monkeypatch):
    sent = []

    class Resp:
        content, stop_reason = [], "end_turn"
        usage = type("U", (), {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0,
                               "cache_creation_input_tokens": 0})()

    monkeypatch.setattr(ec, "ELIGIBILITY_MODEL", "claude-haiku-5-5")
    monkeypatch.setattr(ec.client.messages, "create", lambda **kw: sent.append(kw) or Resp())
    for carriers in (["Allied_Trust_HO3"], ["TWICO_HO3", "Travelers_HO3_-_06.12.2026"]):
        ec._complete_named(carriers, ec.SYSTEM_INSTRUCTIONS, "u", 100)
    a, b = (kw["output_config"]["format"]["schema"] for kw in sent)
    assert a == b
    enum = a["properties"]["carriers"]["items"]["properties"]["carrier"]["enum"]
    assert {"Allied_Trust_HO3", "TWICO_HO3", "Progressive_HO6_-_10.01.2025"} <= set(enum)


@pytest.mark.parametrize("carriers", [["Allied_Trust_HO3"], ["A carrier not in the store"]])
def test_the_stable_enum_always_holds_the_calls_own_carriers(carriers):
    assert set(carriers) <= set(ec._stable_enum(carriers)) and ec._stable_enum(None) is None


def _run(pd, split=1, extra_main=None):
    calls = []

    def fake(system, user, max_tokens):
        rule = "RULE CHECK:" in user
        names = (re.findall(r"--- (.+?) \(rule check\) ---", user) if rule
                 else sorted(set(re.findall(r"\n--- (.+?) \(page", user))))
        calls.append({"rule": rule, "names": names})
        names = names + ([] if rule or not extra_main else [extra_main])
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(U)
    saved = (ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH, ec.RULES_DP_BATCH, ec.RULES_SPLIT)
    ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH, ec.RULES_DP_BATCH, ec.RULES_SPLIT = \
        fake, True, True, True, True, split
    try:
        return {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}, calls
    finally:
        (ec._complete, ec.RULES_PILOT, ec.RULES_SAGE_BATCH, ec.RULES_HO3_BATCH, ec.RULES_DP_BATCH,
         ec.RULES_SPLIT) = saved


def test_in_the_live_configuration_no_empty_main_call_is_made():
    res, calls = _run(LIVE_PD)
    assert calls and all(c["rule"] for c in calls)              # only the rules check
    assert ec.LAST_CALL_USAGE.get("main") is None and res


def test_a_main_call_record_for_a_program_it_was_not_asked_about_is_dropped():
    pd = dict(LIVE_PD, occupancy_type="Tenant Occupied", dwelling_type="Condo")
    _, calls = _run(pd)
    res, _ = _run(pd, extra_main="Allied_Trust_HO3")             # an HO3 program on a tenant check
    assert "Allied_Trust_HO3" not in res


# -- b. citations by row id ---------------------------------------------------------------------
def test_the_rules_check_asks_for_row_ids_only():
    assert "row id only" in ev.PILOT_INSTRUCTION and "never copy a rule's text" in ev.PILOT_INSTRUCTION


def test_a_bare_row_id_still_gets_the_guides_words_from_code():
    outcomes = ev.evaluate_carrier("Allied_Trust_HO3", dict(LIVE_PD, solar_panels="Yes"))
    rec = ev.finish_model_record({"carrier": "Allied_Trust_HO3", "status": "ELIGIBLE", "reasons": ["Mounted panels."],
                                  "citations": ["[ALL-109]"], "missing_info": [], "notes": ""},
                                 "Allied_Trust_HO3", outcomes)
    assert any("ALL-109" in c and "olar" in c for c in rec["citations"])


# -- c. the guard on a rules-check record -------------------------------------------------------
@pytest.mark.parametrize("item", ["Solar panel brand, and whether any Tesla parts are installed",
                                  "Solar panel manufacturer (whether Tesla)",
                                  "Confirm the solar panels are not a Tesla solar roof"])
def test_the_panel_maker_is_a_fact_the_form_never_asks(item):
    assert hold_guard.classify(item)[0] == "c"


def _swy_record(missing):
    # no pool: STANDARD's fenced pool (boxes unticked) would leave SWY-035 open on a blank form field
    outcomes = ev.evaluate_carrier("Swyfft_-_Benchmark_(Admitted)_HO3",
                                   dict(LIVE_PD, solar_panels="Yes", swimming_pool="No Pool"))
    assert [r for r, (o, _) in outcomes.items() if o == "OPEN"] == ["SWY-043"]
    assert outcomes["SWY-043"][1].startswith("ambiguous:")
    rec = {"carrier": "Swyfft_-_Benchmark_(Admitted)_HO3", "status": "INSUFFICIENT_INFORMATION", "flaw_count": 0,
           "reasons": ["Tesla parts cannot be ruled out."], "citations": ["[SWY-043]"], "missing_info": missing,
           "notes": ""}
    return ev.finish_model_record(rec, "Swyfft_-_Benchmark_(Admitted)_HO3", outcomes)


def test_a_rules_check_hold_on_the_panel_maker_becomes_a_confirm_note():
    rec = _swy_record(["Solar panel brand, and whether any Tesla parts are installed"])
    assert rec["status"] == "ELIGIBLE" and not rec["missing_info"] and "Confirm (not asked" in rec["notes"]


def test_a_rules_check_hold_on_a_form_field_stays():
    rec = _swy_record(["Solar panel brand", "Roof type"])
    assert rec["status"] == "INSUFFICIENT_INFORMATION" and rec["missing_info"] == ["Roof type"]


def test_a_pool_box_left_unticked_keeps_the_hold():
    outcomes = ev.evaluate_carrier("Swyfft_-_Benchmark_(Admitted)_HO3", dict(LIVE_PD, solar_panels="Yes"))
    rec = ev.finish_model_record({"carrier": "Swyfft_-_Benchmark_(Admitted)_HO3", "status": "INSUFFICIENT_INFORMATION",
                                  "reasons": ["x"], "citations": [], "missing_info": ["Solar panel brand"], "notes": ""},
                                 "Swyfft_-_Benchmark_(Admitted)_HO3", outcomes)
    assert rec["status"] == "INSUFFICIENT_INFORMATION"            # SWY-035 is open on a blank form field


def test_a_named_hold_is_never_released():
    # an FPC row open (class c by name): the guard does not touch the record
    pd = dict(LIVE_PD, ppc="3", fire_station_miles="7", hydrant_1000ft="No")
    outcomes = ev.evaluate_carrier("Sage_-_Auros_HO3", pd)
    assert any(o == "OPEN" and rid in ev.HOLD_BY_DECISION for rid, (o, _) in outcomes.items())
    rec = ev.finish_model_record({"carrier": "Sage_-_Auros_HO3", "status": "INSUFFICIENT_INFORMATION",
                                  "reasons": ["x"], "citations": [], "missing_info": ["Central station fire alarm",
                                                                                      "Solar panel brand"],
                                  "notes": ""}, "Sage_-_Auros_HO3", outcomes)
    assert rec["status"] == "INSUFFICIENT_INFORMATION" and len(rec["missing_info"]) == 2


# -- d. the split rules check ---------------------------------------------------------------------
@pytest.mark.parametrize("n,sizes", [(1, [7]), (2, [4, 3]), (3, [3, 2, 2]), (9, [1] * 7)])
def test_split_groups(n, sizes):
    assert [len(g) for g in ec._split_groups(list("abcdefg"), n)] == sizes


@pytest.mark.parametrize("pd", [LIVE_PD, dict(LIVE_PD, occupancy_type="Seasonal")])
def test_a_split_rules_check_covers_every_carrier_once_and_answers_the_same(pd):
    one, calls1 = _run(pd, split=1)
    three, calls3 = _run(pd, split=3)
    rule1 = [c["names"] for c in calls1 if c["rule"]]
    rule3 = [c["names"] for c in calls3 if c["rule"]]
    assert len(rule1) == 1 and len(rule3) == min(3, len(rule1[0]))
    assert sorted(n for g in rule3 for n in g) == sorted(rule1[0])
    strip = lambda res: {c: {k: v for k, v in r.items() if k not in ("notes",)} for c, r in res.items()}  # noqa: E731
    assert strip(one) == strip(three)


def test_a_check_records_its_timings():
    _run(LIVE_PD)
    assert {"before_models", "models", "after_models", "total"} <= set(ec.LAST_TIMINGS)
