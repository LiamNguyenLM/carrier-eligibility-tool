"""Round 39 steps 2e / 2f (Liam): a carrier with no rules table yet (a new upload), zero API (fake model; Travelers with
its table taken away stands in for one).

2e  a guide-only card says "No rules table yet: verdict read from the guide by the model. Check before quoting." and
    has the same sections as any other card (the citation in Details).
2f  the model alone never makes a guide-only carrier Not eligible: its decline is "Refer: check with underwriting" with
    the guide's quote; a decline code decided stands."""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import cards  # noqa: E402
import display_names  # noqa: E402
import eligibility_check as ec  # noqa: E402
import pdf_extraction as pe  # noqa: E402
import rules_evaluator as rv  # noqa: E402
import store_cache  # noqa: E402
import upload_carrier  # noqa: E402
from test_held_reasons import HOME, LANDLORD  # noqa: E402

pytestmark = pytest.mark.retrieval
PDF = os.path.join(HERE, "fixtures", "The_Hartford_HO3_-_07.09.2026.pdf")
RAILWAY_NAME = "The Hartford HO3 10.12.2026"
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


# ---- 2e / 2f: the guide-only card, through the pipeline (Travelers with its table taken away)
@pytest.fixture
def guide_only(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setattr(ec, "RULES_HO3_BATCH", False)
    tabled = {wb: c for wb, c in rv.WB_TO_CANON.items() if c != "Travelers_HO3_-_06.12.2026"}
    monkeypatch.setattr(rv, "WB_TO_CANON", tabled)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def run(pd, status, quote):
        def fake(system, user, max_tokens):
            names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) |
                           set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
            recs = [{"carrier": n, "status": status if n.startswith("Travelers") else "ELIGIBLE",
                     "flaw_count": 1 if status == "INELIGIBLE" and n.startswith("Travelers") else 0,
                     "reasons": ["The guide lists this as ineligible."],
                     "citations": [f'{n} (page 7): "{quote}"'] if n.startswith("Travelers") else [],
                     "missing_info": [], "notes": ""} for n in names]
            return json.dumps({"carriers": recs}), dict(USAGE)
        monkeypatch.setattr(ec, "_complete", fake)
        return {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}["Travelers_HO3_-_06.12.2026"]
    return run


# two phrasings: an owner's home and a different decline quote
@pytest.mark.parametrize("pd,quote", [(HOME, "Dwellings with polybutylene plumbing are ineligible"),
                                      (dict(HOME, county="Travis", zip="", harris_east_146=None),
                                       "Homes with unfenced swimming pools are unacceptable")])
def test_a_guide_only_decline_is_a_referral_with_the_quote(guide_only, pd, quote):
    r = guide_only(pd, "INELIGIBLE", quote)
    assert r["status"] == "REFER" and r["reasons"][0].startswith("Refer: check with underwriting")
    assert quote in r["reasons"][0] and any(quote in c for c in r["citations"])
    assert r["diagnostics"]["model_status"] == "INELIGIBLE"
    html = cards.confirm_html(r, pd)
    assert display_names.GUIDE_ONLY_LINE in html
    assert [h for h, _ in cards.details_items(r, guide=True)][-1] == "Guide"
    assert any(quote in x for h, xs in cards.details_items(r, guide=True) if h == "Citations" for x in xs)


def test_a_guide_only_eligible_card_says_it_too(guide_only):
    r = guide_only(HOME, "ELIGIBLE", "x")
    assert r["status"] == "ELIGIBLE" and r["guide_only"]
    assert display_names.GUIDE_ONLY_LINE in cards.confirm_html(r, HOME)


def test_a_carrier_with_a_table_is_never_guide_only(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))
    sys.path.insert(0, os.path.join(HERE, "fuzz"))
    import checks
    monkeypatch.setattr(ec, "_complete", checks._fake)
    for pd in (HOME, LANDLORD):
        res = ec.check_eligibility(dict(pd))
        assert res and not any(r.get("guide_only") for r in res)
