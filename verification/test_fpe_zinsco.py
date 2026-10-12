"""Round 38 step 7, finding F15 (second reader, 2026-10-11): the form's electrical answer is "Federal Pacific or
Zinsco panel". Progressive HO3 / DP3 / HO6 (PRO-040, PDP-087, PH6-073) name Federal Pacific only, yet declined on that
answer -- a Zinsco panel would not meet their rule, so the form cannot settle it. Like Foremost's FOR-041 (which names
Stab-Lok), that answer alone is now a confirm. A guide that names both brands still declines. Zero API."""
import csv
import glob
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rules_data"))
import loss_electrical_lines as le  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
PANEL = "Federal Pacific or Zinsco panel"


def _rules():
    out = {}
    for f in glob.glob(os.path.join(ROOT, "rules_data", "carrier_rules_*.csv")):
        with open(f, encoding="utf-8-sig") as fh:
            out.update({r["Rule ID"]: r for r in csv.DictReader(l for l in fh if not l.startswith("#"))})
    return out


def _maps():
    out = {}
    for b in rv.BATCHES.values():
        with open(b["map"], encoding="utf-8-sig") as fh:
            out.update({m["row_id"]: m for m in csv.DictReader(l for l in fh if not l.startswith("#"))})
    return out


RULES, MAPS = _rules(), _maps()
PANEL_ROWS = sorted(r for r, t in le.ELECTRICAL.items() if PANEL in t)


def _names_zinsco(rid):
    return "zinsco" in (RULES[rid]["Plain rule"] + " " + RULES[rid]["Verbatim quote from guide"]).lower()


def outcome(rid, picked):
    return rv.evaluate_row(MAPS[rid], rv.facts({"electrical": picked}))[0]


@pytest.mark.parametrize("rid", PANEL_ROWS)
def test_the_combined_panel_answer_declines_only_where_the_guide_names_zinsco(rid):
    got = outcome(rid, [PANEL])
    if _names_zinsco(rid):
        assert got in ("FAIL", "OPEN", "NOTE"), got        # named: fails, or holds on another brand the form lacks
    else:
        assert got in ("NOTE", "OPEN"), (rid, got)          # Federal Pacific only: never a decline on this answer


@pytest.mark.parametrize("rid", ["PRO-040", "PDP-087", "PH6-073"])
@pytest.mark.parametrize("picked,expected", [([PANEL], "NOTE"), ([PANEL, "Fuses"], "FAIL"),
                                             (["Circuit breakers"], "PASS"), (["Knob-and-tube wiring"], "FAIL")])
def test_progressive_names_federal_pacific_only(rid, picked, expected):
    assert outcome(rid, picked) == expected


def test_the_three_rows_name_federal_pacific_but_not_zinsco():
    for rid in ("PRO-040", "PDP-087", "PH6-073", "FOR-041"):
        text = (RULES[rid]["Plain rule"] + " " + RULES[rid]["Verbatim quote from guide"]).lower()
        assert ("federal pacific" in text or "stab" in text) and "zinsco" not in text, rid
