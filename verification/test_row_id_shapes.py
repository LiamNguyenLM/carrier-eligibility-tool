"""Round 38 step 7, finding F08 (self-audit, 2026-10-11): Progressive HO6's rows are numbered PH6-NNN, and the
patterns that hide row IDs from agents (cards._ROW) and attach a model's named rows' quotes
(rules_evaluator._ROW_ID) only knew three letters. The card's first line read "[PH6-074] declines: Units with
polybutylene ... are ineligible." Every row-ID shape in the rules tables must be hidden from agent text. Zero API."""
import csv
import glob
import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import cards  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval


def _prefixes():
    out = set()
    for f in glob.glob(os.path.join(ROOT, "rules_data", "carrier_rules_*.csv")):
        with open(f, encoding="utf-8-sig") as fh:
            out |= {r["Rule ID"].split("-")[0] for r in csv.DictReader(l for l in fh if not l.startswith("#"))}
    return sorted(out)


PREFIXES = _prefixes()


def test_progressive_ho6_is_among_the_shapes():
    assert "PH6" in PREFIXES and all(re.fullmatch(r"[A-Z][A-Z0-9]{2}", p) for p in PREFIXES)


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("text", [
    "[{id}] declines: Units with polybutylene plumbing are ineligible.",          # a decline's first line
    "[{id}] refers to underwriting: Units older than 100 years must be referred.",
    "Confirm the plumbing -- [{id}] Polybutylene is ineligible.",               # a missing item
    "Not written here (rows {id}, {id2}).",                                      # IDs in a parenthesis
    "This follows {id} for the unit.",                                           # an ID used as a noun
])
def test_no_row_id_reaches_an_agent(prefix, text):
    out = cards.agent_text(text.format(id=f"{prefix}-074", id2=f"{prefix}-075"))
    assert f"{prefix}-07" not in out, out


def test_a_model_record_naming_a_ph6_row_gets_its_quote():
    canon = "Progressive_HO6_-_10.01.2025"
    rec = {"carrier": canon, "status": "INELIGIBLE", "reasons": ["PH6-074 rules out galvanized plumbing."],
           "citations": [], "missing_info": [], "notes": ""}
    rv.finish_model_record(rec, canon, {})
    assert any("[PH6-074] p." in c for c in rec["citations"]), rec["citations"]
