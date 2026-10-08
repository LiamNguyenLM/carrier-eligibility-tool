"""Round 25 (Liam, 2026-10-03/04): the rules-table pilot switch and its
wiring. Zero API: the model call is answered by a fake."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402
import rules_evaluator as rv  # noqa: E402
from profiles import STANDARD_PROFILE  # noqa: E402

pytestmark = pytest.mark.retrieval

SIX = list(rv.PILOT_CARRIERS.values())
LIAM = {"year_built": 2000, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "aggressive_breed": "No", "solar_panels": "No",
        "ppc": "3", "dwelling_type": "House"}
OLD = dict(LIAM, year_built=1970, roof_age=22, plumbing_type="Galvanized", ppc="6", county="Bexar",
           dwelling_amount=350000)
USAGE = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}


def _run(pd, pilot_status="INSUFFICIENT_INFORMATION", pilot_on=True, **kw):
    """check_eligibility with both calls answered by a fake. Returns
    (results, main prompt, pilot prompt or None)."""
    calls = {}

    def fake(system, user, max_tokens):
        if "RULE CHECK:" in user:
            calls["pilot"] = user
            names = re.findall(r"--- (.+?) \(rule check\) ---", user)
            recs = [{"carrier": n, "status": pilot_status, "flaw_count": 0, "reasons": ["open rows"],
                     "citations": [], "missing_info": ["an open fact"], "notes": ""} for n in names]
        else:
            calls["main"] = user
            names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)))
            recs = [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                     "citations": [], "missing_info": [], "notes": ""} for n in names]
        return json.dumps({"carriers": recs}), dict(USAGE)

    real, real_flag = ec._complete, ec.RULES_PILOT
    ec._complete, ec.RULES_PILOT = fake, pilot_on
    try:
        results = ec.check_eligibility(dict(pd), **kw)
    finally:
        ec._complete, ec.RULES_PILOT = real, real_flag
    return {r["carrier"]: r for r in results}, calls.get("main"), calls.get("pilot")


def test_the_switch_is_off_by_default():
    assert os.environ.get("ELIGIBILITY_RULES_PILOT") is None and ec.RULES_PILOT is False


def test_off_keeps_the_six_in_the_main_prompt_and_makes_no_pilot_call():
    res, main, pilot = _run(STANDARD_PROFILE, pilot_on=False)
    assert pilot is None
    assert all(f"--- {c} (page" in main for c in SIX)
    assert not any(r.get("rules_table") for r in res.values())


def test_on_routes_exactly_the_six():
    res, main, pilot = _run(dict(STANDARD_PROFILE, dwelling_type="House"))
    assert not any(f"--- {c} (page" in main for c in SIX)
    # a closed program's fixed row (round 26 step 9, Liam 2026-10-05) is never in a prompt either
    others = [c for c in res if c not in SIX and res[c]["status"] not in (ec.GUIDE_UNAVAILABLE,)
              and not res[c].get("fixed_row")]
    assert others and all(f"--- {c} (page" in main for c in others)
    assert set(re.findall(r"--- (.+?) \(rule check\) ---", pilot)) <= set(SIX)
    assert all(res[c].get("rules_table") for c in SIX)
    assert not any(res[c].get("rules_table") for c in others)


def test_no_pilot_call_when_code_decides_all_six():
    res, main, pilot = _run(dict(LIAM, county="Travis", dwelling_amount=450000, ppc="2"))
    assert pilot is None or "Sage_-_Auros_HO3" in pilot          # Sage's FPC rows may stay open
    assert res["Allied_Trust_HO3"]["status"] == "ELIGIBLE" and res["Allied_Trust_HO3"]["rules_table"]


def test_a_code_decline_carries_row_page_and_quote():
    res, _, _ = _run(OLD)
    allied = res["Allied_Trust_HO3"]
    assert allied["status"] == "INELIGIBLE"
    assert allied["citations"][0].startswith('Allied_Trust_HO3: [ALL-057] p.')
    assert "galvanized" in allied["citations"][0].lower()
    assert not any("Attribution check" in (r.get("notes") or "") for r in res.values())   # guard keeps them


def test_notes_never_change_a_status():
    res, _, _ = _run(dict(LIAM, county="Travis"))              # Coverage A blank
    allied = res["Allied_Trust_HO3"]
    assert allied["status"] == "ELIGIBLE"
    assert any("ALL-133" in n for n in allied["also_confirm"])
    assert not any("ALL-133" in m for m in allied["missing_info"])


def test_unchecked_topic_skips_in_the_evaluator():
    out = rv.evaluate_carrier("Allied_Trust_HO3", dict(LIAM, dwelling_amount=150000),
                              checked=["ppc", "roof_age"])
    assert out["ALL-133"][0] == "SKIP"
    res, _, _ = _run(dict(LIAM, dwelling_amount=150000), checked_topics=["ppc", "roof_age"])
    assert res["Allied_Trust_HO3"]["status"] == "ELIGIBLE"     # the $200,000 minimum is not considered
    res2, _, _ = _run(dict(LIAM, dwelling_amount=150000))
    assert res2["Allied_Trust_HO3"]["status"] == "INELIGIBLE"


def test_the_sage_county_hold_and_chubb_hold_still_fire():
    res, _, _ = _run(LIAM)                                      # County and Coverage A blank
    sage, chubb = res["Sage_-_Auros_HO3"], res["CHUBB_HO_-_05.22.2026"]
    assert sage["status"] == "INSUFFICIENT_INFORMATION" and sage["missing_info"][0].startswith("County")
    assert chubb["status"] == "INSUFFICIENT_INFORMATION"
    assert any(m.startswith("Dwelling amount (Coverage A)") for m in chubb["missing_info"])
    res2, _, _ = _run(dict(LIAM, county="Travis", dwelling_amount=450000))
    assert res2["CHUBB_HO_-_05.22.2026"]["status"] == "REFER"
    res3, _, _ = _run(dict(LIAM, county="Dallas"), pilot_status="ELIGIBLE")
    assert res3["Sage_-_Auros_HO3"]["status"] == "INELIGIBLE"  # out of territory, as round 19


# Round 28 step 1 (Liam, 2026-10-07): one reason per rule on the Auros card. An
# out-of-territory county was 2 flaws from SAG-081 + SAG-083 and a third from the
# round 19 county hold; the territory row now decides, once.
@pytest.mark.parametrize("county,row", [("Dallas", "SAG-081"), ("Nueces", "SAG-082")])
def test_an_auros_county_outside_the_territory_is_one_flaw_and_one_reason_on_the_card(county, row):
    res, _, _ = _run(dict(LIAM, county=county, dwelling_amount=450000), pilot_status="ELIGIBLE")
    sage = res["Sage_-_Auros_HO3"]
    assert sage["status"] == "INELIGIBLE" and sage["flaw_count"] == 1
    assert len(sage["reasons"]) == 1 and sage["reasons"][0].startswith(f"[{row}]")
    assert not any("outside this carrier's territory" in x for x in sage["reasons"] + sage.get("citations", []))


def test_a_blank_county_holds_auros_once():
    res, _, _ = _run(dict(LIAM, dwelling_amount=450000), pilot_status="ELIGIBLE")
    sage = res["Sage_-_Auros_HO3"]
    assert sage["status"] == "INSUFFICIENT_INFORMATION"
    assert sum(1 for m in sage["missing_info"] if m.startswith("County")) == 1
    assert not any(n.startswith(("[SAG-081]", "[SAG-083]")) for n in sage.get("also_confirm", []))


def test_auros_owner_occupied_vacancy_rows_never_fail_twice():
    # Vacant never reaches an HO3 card (occupancy routing, below); the evaluator
    # test covers its one flaw. Owner Occupied passes SAG-001 / SAG-002 / SAG-005.
    res, _, _ = _run(dict(LIAM, county="Bexar", dwelling_amount=450000), pilot_status="ELIGIBLE")
    assert not any(x.startswith(("[SAG-001]", "[SAG-002]", "[SAG-005]")) for x in res["Sage_-_Auros_HO3"]["reasons"])


# Round 28 found the routing gap (strict xfail); round 29 step 4 (Liam's decision 2, 2026-10-08)
# routes an owner's Seasonal / Secondary home to HO3 programs too, so this passes now.
@pytest.mark.parametrize("occupancy", ["Seasonal", "Secondary Home"])
def test_an_owners_seasonal_or_secondary_home_reaches_sage_auros(occupancy):
    res, _, _ = _run(dict(LIAM, county="Bexar", dwelling_amount=450000, occupancy_type=occupancy),
                     pilot_status="ELIGIBLE")
    assert "Sage_-_Auros_HO3" in res
    sage = res["Sage_-_Auros_HO3"]
    assert sage["status"] != "INELIGIBLE"                       # SAG-001 (v4) accepts the owner's seasonal home
    assert not any(x.startswith("[SAG-001]") for x in sage["reasons"])


@pytest.mark.parametrize("occupancy", ["Tenant Occupied", "Vacant"])
def test_a_tenant_or_vacant_home_never_reaches_an_ho3_card(occupancy):
    res, _, _ = _run(dict(LIAM, county="Bexar", dwelling_amount=450000, occupancy_type=occupancy))
    assert "Sage_-_Auros_HO3" not in res


def test_sage_auros_fpc_upgrade_is_off_with_the_pilot_and_on_for_other_sage():
    res, _, pilot = _run(dict(LIAM, county="Travis", dwelling_amount=450000))
    assert "Structured FPC check" not in (res["Sage_-_Auros_HO3"].get("notes") or "")
    assert "[SAG-073]" in pilot or "[SAG-074]" in pilot
    off, _, _ = _run(dict(LIAM, county="Travis", dwelling_amount=450000), pilot_on=False)
    # the other Sage carriers are unaffected: same treatment ON and OFF
    for c in ("Sage_-_SURE_HO-3_-_01.31.2026", "Sage_-_SafePort_HO-3_-_01.31.2026"):
        assert (res[c]["status"], res[c].get("notes")) == (off[c]["status"], off[c].get("notes"))


def test_a_pilot_answer_that_omits_a_carrier_gets_not_evaluated():
    calls = {}

    def fake(system, user, max_tokens):
        if "RULE CHECK:" in user:
            return json.dumps({"carriers": []}), dict(USAGE)
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": [],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    real, flag = ec._complete, ec.RULES_PILOT
    ec._complete, ec.RULES_PILOT = fake, True
    try:
        res = {r["carrier"]: r for r in ec.check_eligibility(dict(STANDARD_PROFILE, dwelling_type="House"))}
    finally:
        ec._complete, ec.RULES_PILOT = real, flag
    assert res["Swyfft_-_Benchmark_(Admitted)_HO3"]["status"] == ec.NOT_EVALUATED


# -- the card -----------------------------------------------------------------
def test_a_pilot_card_shows_the_label_the_quote_and_the_notes(monkeypatch):
    from streamlit.testing.v1 import AppTest
    res, _, _ = _run(OLD)
    allied = res["Allied_Trust_HO3"]
    monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: [allied])
    at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "..", "app.py"), default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    at.selectbox(key="dwelling_type").select("House").run()
    at.button(key="submit").click().run()
    assert not at.exception
    assert "rules table" in [c.value for c in at.caption]
    md = " ".join(m.value for m in at.markdown)
    assert "[ALL-057] p." in md and "galvanized" in md.lower()
    assert "Also confirm" in md


def test_other_cards_are_unchanged(monkeypatch):
    from streamlit.testing.v1 import AppTest
    rec = {"carrier": "Travelers_HO3_-_06.12.2026", "status": "ELIGIBLE", "flaw_count": 0,
           "reasons": ["fine"], "citations": [], "missing_info": [], "notes": ""}
    monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: [rec])
    at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "..", "app.py"), default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    at.selectbox(key="dwelling_type").select("House").run()
    at.button(key="submit").click().run()
    assert "rules table" not in [c.value for c in at.caption]
    assert "Also confirm" not in " ".join(m.value for m in at.markdown)


# Round 25 step 4: on STANDARD (fenced pool, no fence boxes ticked) Luna said
# ELIGIBLE for Allied and Swyfft, and the pool-spec guard -- which knows only
# retrieved carriers -- read "not retrieved" as "no fence spec" and upgraded
# them. Both carriers' guides state a 4 ft fence and a gate.
@pytest.mark.parametrize("carrier,row", [("Allied_Trust_HO3", "ALL-093"),
                                         ("Swyfft_-_Benchmark_(Admitted)_HO3", "SWY-035")])
def test_a_fenced_pool_with_no_boxes_stays_insufficient_for_a_pilot_carrier(carrier, row):
    res, _, pilot = _run(dict(STANDARD_PROFILE, dwelling_type="House"), pilot_status="ELIGIBLE")
    assert carrier in pilot
    r = res[carrier]
    assert r["status"] == "INSUFFICIENT_INFORMATION"
    assert any(row in m and "fence" in m for m in r["missing_info"])
    assert "[Pool spec check]" not in (r.get("notes") or "")
