"""Round 38d step 2 (Liam's decisions, 2026-10-13), end to end through check_eligibility with a fake model (zero API):
1. Foremost FOR-121: 2+ losses refer ("may require approval" names an underwriting path, round 31 rule).
2. CDP-021 / ORI-059 / TWI-037: the bundled "Metal: corrugated / exposed-fastener / tin / aluminum panels" answer is a
   confirm naming "corrugated", not a decline.
3. PDP-103 / PRO-051 stay Refer ("approved alternate enclosure" is an underwriting path); Centauri DP3 (CDP-053) has
   no such path and declines."""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import eligibility_check as ec  # noqa: E402
from test_held_reasons import HOME, LANDLORD  # noqa: E402

pytestmark = pytest.mark.retrieval
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
PANEL = "Metal: corrugated / exposed-fastener / tin / aluminum panels"
FOREMOST = "Foremost_DP3_and_HO3_-_07.01.2026"
TRAVIS = dict(HOME, county="Travis", zip="", harris_east_146=None)     # Foremost Choice does not write Harris (FOR-078)


@pytest.fixture
def check(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    monkeypatch.setattr(ec, "_complete", fake)
    return lambda pd: {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}


def _rows(rec, rid):
    return [x for x in rec.get("reasons") or [] if f"[{rid}]" in x]


def _confirms(rec, rid):
    return [x for x in rec.get("confirm_items") or [] if x.get("row") == rid]


# ---- 1. Foremost: 2+ losses refer; one loss is a confirm on its severity
@pytest.mark.parametrize("n,types", [("2", ["Theft"]), ("3 or more", ["Water", "Fire"])])
def test_foremost_refers_multiple_losses(check, n, types):
    r = check(dict(TRAVIS, losses_5yr=n, loss_types=types, loss_year=2025, losses_3yr="1"))[FOREMOST]
    assert r["status"] == "REFER" and _rows(r, "FOR-121"), r["reasons"]


def test_foremost_one_loss_is_a_confirm_not_a_referral(check):
    r = check(dict(TRAVIS, losses_5yr="1", loss_types=["Theft"], loss_year=2025, losses_3yr="1"))[FOREMOST]
    assert not _rows(r, "FOR-121") and _confirms(r, "FOR-121")


# ---- 2. the bundled panel answer is a confirm naming "corrugated"
@pytest.mark.parametrize("canon,rid,base", [("TWICO_HO3", "TWI-037", HOME),
                                            ("Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3", "ORI-059", HOME),
                                            ("Centauri_-_DP3_-_11.16.2022", "CDP-021", LANDLORD)])
def test_the_panel_answer_is_a_corrugated_confirm(check, canon, rid, base):
    r = check(dict(base, roof_type=PANEL))[canon]
    assert not _rows(r, rid) and _confirms(r, rid), r["reasons"]
    assert not any("ineligible roof material regardless of age" in x for x in r["reasons"])    # TWICO's code check


def test_twicos_code_check_confirms_the_panel_answer_but_still_declines_named_corrugated():
    from structured_rules import twico_roof_settlement
    assert twico_roof_settlement(PANEL, 5)[0] == "CONFIRM"
    assert twico_roof_settlement("Corrugated Metal", 5)[0] == "INELIGIBLE"


# ---- 3. "approved alternate enclosure" is an underwriting path (Progressive refers); Centauri DP3 has none (declines)
@pytest.mark.parametrize("canon,rid,base", [("Progressive_DP3_-_10.01.2024", "PDP-103", LANDLORD),
                                            ("Progressive_HO3_-_04.01.2026", "PRO-051", HOME)])
def test_progressive_refers_an_unfenced_pool(check, canon, rid, base):
    r = check(dict(base, swimming_pool="In Ground - Unfenced", pool_accessories="None"))[canon]
    assert r["status"] == "REFER" and _rows(r, rid), r["reasons"]


def test_centauri_dp3_declines_an_unfenced_pool(check):
    r = check(dict(LANDLORD, swimming_pool="In Ground - Unfenced", pool_accessories="None"))["Centauri_-_DP3_-_11.16.2022"]
    assert r["status"] == "INELIGIBLE" and _rows(r, "CDP-053")
