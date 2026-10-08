"""Round 29 step 9 (2026-10-08): a rules-table card keeps the notes a model card had.

Tier 2 (round 28, three models): with the pilot on, Progressive HO3's solar wind/hail
exclusion (Liam, decision C, 2026-10-05), Allied Trust's replacement-cost limit for a
composite roof (round 26) and Allied's [Solar check] note no longer reached the card -- the
rules table never evaluates COVERAGE_ONLY rows, and the solar classification only ran for
retrieved carriers. Verdicts were right; the notes were lost. Zero API."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import eligibility_check as ec  # noqa: E402
import rules_evaluator as ev  # noqa: E402
from profiles import ALT_PROFILE, AUDIT_R13_PROFILE  # noqa: E402

pytestmark = pytest.mark.retrieval
PROGRESSIVE, ALLIED = "Progressive_HO3_-_04.01.2026", "Allied_Trust_HO3"
USAGE = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}


def _run(pd):
    def fake(system, user, max_tokens):
        names = (re.findall(r"--- (.+?) \(rule check\) ---", user) if "RULE CHECK:" in user
                 else sorted(set(re.findall(r"\n--- (.+?) \(page", user))))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    saved = ec._complete, ec.RULES_PILOT
    ec._complete, ec.RULES_PILOT = fake, True
    try:
        return {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}
    finally:
        ec._complete, ec.RULES_PILOT = saved


@pytest.fixture(scope="module")
def alt():
    return _run(ALT_PROFILE)


# -- the general rule, two phrasings each ---------------------------------------------------
@pytest.mark.parametrize("canon,row", [(PROGRESSIVE, "PRO-067"), (ALLIED, None)])
def test_a_solar_coverage_row_is_a_note_only_when_the_home_has_panels(canon, row):
    outcomes = ev.evaluate_carrier(canon, dict(ALT_PROFILE))
    with_panels = ev.coverage_notes(canon, outcomes, dict(ALT_PROFILE, solar_panels="Yes"))
    without = ev.coverage_notes(canon, outcomes, dict(ALT_PROFILE, solar_panels="No"))
    assert not any("solar" in n.lower() for n in without)
    if row:
        assert any(n.startswith(f"[{row}]") for n in with_panels)
    else:   # Allied's solar rows are eligibility rows (ALL-109/110), not coverage rows
        assert not any("solar" in n.lower() for n in with_panels)


@pytest.mark.parametrize("roof_type,row,other", [("Composition Shingle", "ALL-045", "ALL-047"),
                                                 ("Tile", "ALL-047", "ALL-045"),
                                                 ("Metal", "ALL-047", "ALL-045")])
def test_a_roof_settlement_row_is_a_note_only_for_the_roof_material_it_names(roof_type, row, other):
    pd = dict(ALT_PROFILE, roof_type=roof_type)
    notes = ev.coverage_notes(ALLIED, ev.evaluate_carrier(ALLIED, pd), pd)
    assert any(n.startswith(f"[{row}]") for n in notes) and not any(n.startswith(f"[{other}]") for n in notes)


# -- the Tier 2 scenarios, through the pipeline -----------------------------------------------
def test_progressive_ho3_card_carries_its_solar_wind_hail_exclusion(alt):
    r = alt[PROGRESSIVE]
    assert r.get("rules_table") and r["status"] != "INELIGIBLE"
    assert "[PRO-067]" in r["notes"] and "solar" in r["notes"].lower()


def test_allied_card_carries_the_replacement_cost_limit_for_a_14_year_composite_roof(alt):
    r = alt[ALLIED]
    assert r.get("rules_table") and r["status"] != "INELIGIBLE"
    assert "[ALL-045]" in r["notes"] and "replacement" in r["notes"].lower()


@pytest.mark.parametrize("profile", ["ALT", "AUDIT_R13"])
def test_a_rules_table_card_still_gets_the_solar_check_note(profile, alt):
    res = alt if profile == "ALT" else _run(AUDIT_R13_PROFILE)
    assert "[solar check]" in res[ALLIED]["notes"].lower()


def test_coverage_notes_never_change_a_status(alt, monkeypatch):
    monkeypatch.setattr(ev, "coverage_notes", lambda *a: [])
    without = _run(ALT_PROFILE)
    assert {c: r["status"] for c, r in without.items()} == {c: r["status"] for c, r in alt.items()}
    assert "Coverage (not eligibility)" not in without[PROGRESSIVE]["notes"]
