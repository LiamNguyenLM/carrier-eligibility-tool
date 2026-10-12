"""Round 38b (Liam's decisions, 2026-10-12): each verdict change, end to end through check_eligibility with a fake model
(zero API), on Liam's Harris home (test_held_reasons.HOME) and LANDLORD."""
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
TRAVELERS, MERCURY = "Travelers_HO3_-_06.12.2026", "Mercury_HO3_-_01.01.2026"


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


ONE_LOSS = dict(HOME, losses_5yr="1", loss_year=2025, losses_3yr="1")


# ---- 1. Travelers TRV-066: "1 or more water damage claim(s)" refers (round 38 step 3 had made it a confirm)
def test_one_water_loss_refers_travelers(check):
    r = check(dict(ONE_LOSS, loss_types=["Water"]))[TRAVELERS]
    assert r["status"] == "REFER" and _rows(r, "TRV-066"), r["reasons"]


def test_an_other_loss_is_a_travelers_confirm_not_a_referral(check):
    r = check(dict(ONE_LOSS, loss_types=["Other"]))[TRAVELERS]
    assert not _rows(r, "TRV-066") and _confirms(r, "TRV-066")


# ---- Mercury MER-087: theft is non-weather, but the footnote counts only paid losses -> a confirm, not a decline
@pytest.mark.parametrize("types", [["Theft"], ["Fire"]])
def test_one_non_weather_loss_is_a_mercury_confirm_because_only_paid_losses_count(check, types):
    r = check(dict(ONE_LOSS, loss_types=types))[MERCURY]
    assert not _rows(r, "MER-087") and _confirms(r, "MER-087")
    assert "paid" in _confirms(r, "MER-087")[0]["rule"]      # p.4: "*All paid losses (including CAT losses)"


# ---- 2. Centauri DP3 CDP-053: an unprotected pool is Ineligible (p.5 'PROPERTY - Ineligible'; no underwriting path)
CENTAURI_DP3 = "Centauri_-_DP3_-_11.16.2022"


@pytest.mark.parametrize("pool", ["Above Ground - Unfenced", "In Ground - Unfenced"])
def test_an_unfenced_pool_declines_centauri_dp3(check, pool):
    r = check(dict(LANDLORD, swimming_pool=pool, pool_accessories="None"))[CENTAURI_DP3]
    assert r["status"] == "INELIGIBLE" and _rows(r, "CDP-053"), r["reasons"]


def test_a_fenced_pool_with_both_boxes_ticked_passes_cdp_053(check):
    r = check(dict(LANDLORD, swimming_pool="In Ground - Fenced", pool_accessories="None", pool_fence_4ft=True,
                   pool_gate_locking=True))[CENTAURI_DP3]
    assert not _rows(r, "CDP-053")


# ---- 3. Chubb CHU-012: flat roofs are decided on the shape; built-up / membrane on a pitched roof is a confirm
CHUBB = "CHUBB_HO_-_05.22.2026"
CHUBB_HOME = dict(HOME, county="Tom Green", zip="", dwelling_amount=330000)     # second reader hour 4, seed 5583


@pytest.mark.parametrize("shape,cover", [("Hip", "Built-up (tar and gravel)"),
                                         ("Gable", "Membrane (rubber/EPDM / TPO / modified bitumen)")])
def test_a_pitched_roof_with_a_low_slope_covering_is_a_chubb_confirm(check, shape, cover):
    r = check(dict(CHUBB_HOME, roof_shape=shape, roof_type=cover))[CHUBB]
    assert r["status"] != "INELIGIBLE" and not _rows(r, "CHU-012"), r["reasons"]
    assert _confirms(r, "CHU-012")


def test_a_flat_shape_still_declines_chubb(check):
    r = check(dict(CHUBB_HOME, roof_shape="Flat", roof_type="Composition Shingle"))[CHUBB]
    assert r["status"] == "INELIGIBLE" and _rows(r, "CHU-012"), r["reasons"]


# ---- 4. a flat roof with shingle, tile or metal is a confirm (Centauri / Progressive DP3); low-slope roofing declines
PROGRESSIVE_DP3 = "Progressive_DP3_-_10.01.2024"


@pytest.mark.parametrize("cover", ["Composition Shingle", "Tile"])
def test_a_flat_discrete_roof_is_a_confirm_at_centauri_and_progressive_dp3(check, cover):
    res = check(dict(LANDLORD, roof_shape="Flat", roof_type=cover))
    for canon, rid in ((CENTAURI_DP3, "CDP-023"), (PROGRESSIVE_DP3, "PDP-099")):
        assert not _rows(res[canon], rid) and _confirms(res[canon], rid), (canon, res[canon]["reasons"])
    assert not any("poured concrete" in x for x in res[CENTAURI_DP3]["reasons"])     # the code check no longer declines


def test_a_flat_built_up_roof_still_declines_centauri_dp3(check):
    r = check(dict(LANDLORD, roof_shape="Flat", roof_type="Built-up (tar and gravel)"))[CENTAURI_DP3]
    assert r["status"] == "INELIGIBLE"
