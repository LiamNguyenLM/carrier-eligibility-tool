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


# ---- 5. bundled answers: a confirm naming the half the guide names
PROGRESSIVE_HO3 = "Progressive_HO3_-_04.01.2026"
PANEL = "Metal: corrugated / exposed-fastener / tin / aluminum panels"


def test_mercury_does_not_decline_corporation_or_partnership_unconfirmed(check):
    r = check(dict(HOME, ownership_type="Corporation / partnership"))[MERCURY]
    assert not _rows(r, "MER-005") and _confirms(r, "MER-005")
    assert check(dict(HOME, ownership_type="LLC"))[MERCURY]["status"] == "INELIGIBLE"      # LLC is named


@pytest.mark.parametrize("canon,rid,base", [(PROGRESSIVE_HO3, "PRO-024", HOME), (PROGRESSIVE_DP3, "PDP-098", LANDLORD)])
def test_progressive_confirms_the_metal_panel_answer(check, canon, rid, base):
    r = check(dict(base, roof_type=PANEL))[canon]
    assert not _rows(r, rid) and _confirms(r, rid), r["reasons"]
    assert _rows(check(dict(base, roof_type="Rolled roofing"))[canon], rid)                # rolled is named


# ---- 6. estate and business trust follow each guide's quote
LIBERTY_HO3, WILSHIRE = "Liberty_Mutual_HO3_-_02.21.2026", "Sage_-_Wilshire_HO3_-_12.02.2025"
BUSINESS_TRUST = dict(ownership_type="Trust", trust_type="Corporate or business trust")


@pytest.mark.parametrize("canon,decline,refer,base", [(PROGRESSIVE_HO3, "PRO-012", "PRO-013", HOME),
                                                      (PROGRESSIVE_DP3, "PDP-049", "PDP-048", LANDLORD)])
def test_a_business_trust_refers_progressive_because_its_guide_refers_trusts(check, canon, decline, refer, base):
    r = check(dict(base, **BUSINESS_TRUST))[canon]
    assert not _rows(r, decline) and r["status"] == "REFER" and _rows(r, refer), r["reasons"]
    land = check(dict(base, ownership_type="Trust", trust_type="Land trust"))[canon]
    assert land["status"] == "INELIGIBLE" and _rows(land, decline)                       # "land trust" is named


@pytest.mark.parametrize("owner", [dict(ownership_type="Estate"), BUSINESS_TRUST])
def test_liberty_confirms_an_estate_or_trust_owner(check, owner):
    r = check(dict(HOME, **owner))[LIBERTY_HO3]
    assert not _rows(r, "LIB-048") and _confirms(r, "LIB-048")


def test_sage_wilshire_still_declines_an_estate_on_its_own_words(check):
    # p.2: "Corporate / Business, LLC, association, partnership or other non-individual owned properties are ineligible."
    r = check(dict(HOME, ownership_type="Estate", county="Bexar", zip=""))[WILSHIRE]
    assert r["status"] == "INELIGIBLE"


# ---- 7. confirm unless the guide is clear
import rules_evaluator as rv  # noqa: E402

FOREMOST, ARI_HOA, VAVE = "Foremost_DP3_and_HO3_-_07.01.2026", "ARI_(HOA+)", "Sage_-_Vave_HO3_-_07.01.2026"


@pytest.mark.parametrize("types", [["Water"], ["Wind or hail"]])
def test_any_3_year_loss_refers_chubb(check, types):
    # p.9 "Risks or applicants with a loss history will require underwriter approval" (clear)
    r = check(dict(CHUBB_HOME, dwelling_amount=1500000, losses_5yr="1", loss_types=types, loss_year=2025,
                   losses_3yr="1"))[CHUBB]
    assert r["status"] == "REFER" and _rows(r, "CHU-073"), r["reasons"]


def row(canon, rid, **pd):
    return rv.evaluate_carrier(canon, dict(HOME, loss_year=2025, **pd))[rid][0]


def test_foremost_multiple_losses_may_require_approval_so_a_confirm():
    # p.18 "... loss severity or multiple loss activity in the past five years may require approval"
    assert row(FOREMOST, "FOR-121", losses_5yr="2", loss_types=["Theft"], losses_3yr="1") == "NOTE"
    assert row(FOREMOST, "FOR-121", losses_5yr="3 or more", loss_types=["Fire"], losses_3yr="2") == "NOTE"


@pytest.mark.parametrize("rid", ["ARA-066", "ARA-067"])
def test_ari_wind_or_hail_against_all_other_losses_is_a_confirm(rid):
    # "*All Other Losses are losses other than water, fire, theft or liability" -- and Act of Nature claims are their
    # own line ("Two or more Act of Nature claims"): unclear whether wind/hail counts here
    assert row(ARI_HOA, rid, losses_5yr="2", loss_types=["Wind or hail"], losses_3yr="2") == "NOTE"


def test_liberty_wind_hazard_area_is_a_confirm_on_the_card(check):
    r = check(dict(HOME, coastal_tier="Tier 1", county="Jefferson", zip=""))[LIBERTY_HO3]
    assert _confirms(r, "LIB-050")          # "Dwelling located in a brush or wind hazard area" -- never defined


@pytest.mark.parametrize("types,want", [(["Wind or hail"], "PASS"), (["Theft"], "FAIL")])
def test_vave_counts_wind_and_hail_as_cat(types, want):
    # "two or more losses from any non-Cat causes or liability claims, in the last three years"
    assert row(VAVE, "VAV-090", losses_5yr="2", loss_types=types, losses_3yr="2") == want


# ---- 8. a decline / referral names the answer that fails the rule (F12)
import cards  # noqa: E402

AUROS, TWICO = "Sage_-_Auros_HO3", "TWICO_HO3"


@pytest.mark.parametrize("canon,pd,named", [
    (AUROS, dict(HOME, county="Wheeler", zip=""), "County: Wheeler"),                      # second reader, seed 1594
    (TWICO, dict(HOME, roof_type="Slate"), "Roof: Slate"),
    (MERCURY, dict(HOME, ownership_type="LLC"), "Owner: LLC"),
    (CHUBB, dict(CHUBB_HOME, dwelling_amount=1500000, losses_5yr="1", loss_types=["Water"], loss_year=2025,
                 losses_3yr="1"), "Losses: 1 in 5 yrs (water), 1 in 3 yrs"),
])
def test_a_card_names_the_failing_answer(check, canon, pd, named):
    r = check(pd)[canon]
    assert r["status"] in ("INELIGIBLE", "REFER")
    assert any(cards.agent_text(x).startswith(named + " — ") for x in r["reasons"]), r["reasons"]


def test_without_the_form_the_reason_is_the_rule_alone():
    out = rv.evaluate_carrier(TWICO, dict(HOME, roof_type="Slate"))
    assert rv.code_record(TWICO, out)[0]["reasons"][0].startswith("[TWI-037] declines: Wood")
