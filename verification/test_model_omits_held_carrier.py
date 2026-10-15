"""Round 39 step 5e: live (Haiku 5.5 low, 300 profiles), the model left The Hartford out of 4 of its 10 held rule
checks -- each a tenant-occupied home held on the blank owner's-home answer (HAR-070) -- and the card said "No answer
came back for this carrier in this check -- run the check again." A rules-table carrier the model leaves out whose
open rows are all holds on a blank form field is held by code instead (the verdict the model's answer would have
reached); any other omission keeps its NOT_EVALUATED row. Zero API: the fake model omits the carrier."""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import eligibility_check as ec  # noqa: E402
import rules_evaluator as rv  # noqa: E402
from test_held_reasons import HOME, LANDLORD  # noqa: E402

pytestmark = pytest.mark.retrieval
H = "The_Hartford_HO3_-_07.09.2026"
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
RENT = dict(LANDLORD, ownership_type="Individual Owner", losses_5yr="0", primary_home_carrier="")


def _check(monkeypatch, tmp_path, pd, omit, reply=None):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---",
                                                                                  user)))
        if reply is not None and "(rule check) ---" in user:
            return reply, dict(USAGE)
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                                         "citations": [], "missing_info": [], "notes": ""}
                                        for n in names if n not in omit]}), dict(USAGE)
    monkeypatch.setattr(ec, "_complete", fake)
    return {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}


# two phrasings of the live case: a rental held on the owner's home (HAR-070), a seasonal home held on its primary
@pytest.mark.parametrize("pd,row", [(RENT, "HAR-070"),
                                    (dict(HOME, occupancy_type="Seasonal", primary_home_carrier=""), "HAR-059")])
def test_a_held_carrier_the_model_leaves_out_is_held_by_code(monkeypatch, tmp_path, pd, row):
    r = _check(monkeypatch, tmp_path, pd, omit={H})[H]
    assert r["status"] == "INSUFFICIENT_INFORMATION", r["reasons"]
    assert any(f"[{row}]" in m for m in r["missing_info"]) and "run the check again" not in " ".join(r["reasons"])
    assert r.get("diagnostics", {}).get("model_omitted")


def test_an_unparseable_rule_check_answer_still_holds_it(monkeypatch, tmp_path):
    r = _check(monkeypatch, tmp_path, RENT, omit=set(), reply="not json at all")[H]
    assert r["status"] == "INSUFFICIENT_INFORMATION" and any("[HAR-070]" in m for m in r["missing_info"])


def test_when_the_model_answers_nothing_changes(monkeypatch, tmp_path):
    r = _check(monkeypatch, tmp_path, RENT, omit=set())[H]
    assert r["status"] == "INSUFFICIENT_INFORMATION" and not r.get("diagnostics", {}).get("model_omitted")


@pytest.mark.parametrize("outcomes,want", [
    ({"A": ("OPEN", "Primary home insured with"), "B": ("PASS", "")}, True),
    ({"A": ("OPEN", "Trust type"), "B": ("OPEN", "PPC Number")}, True),
    ({"A": ("OPEN", "ambiguous: the readings disagree"), "B": ("OPEN", "Trust type")}, False),   # the model decides
    ({"A": ("OPEN", "the row's effect is UNKNOWN")}, False),
    ({"A": ("PASS", ""), "B": ("NOTE", "confirm: x")}, False),                                     # nothing held
])
def test_only_blank_holds(outcomes, want):
    assert rv.only_blank_holds(outcomes) == want
