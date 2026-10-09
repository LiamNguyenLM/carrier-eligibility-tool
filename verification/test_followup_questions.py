"""Round 35 steps 3d-f (Liam, 2026-10-09, decision 1): the solar type and Tesla equipment; the trust type,
Corporation / partnership and Estate; Harris County east of Highway 146. Every new answer against every line
that reads it. Zero API."""
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import eligibility_check as ec  # noqa: E402
import intake_fields as I  # noqa: E402
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval
M = ev._map()


def row(rid, **pd):
    return ev.evaluate_row(M[rid], ev.facts(pd))[0]


def test_no_ambiguous_line_is_left():
    assert not [rid for rid, m in M.items() if "||" in (m["test"] or "")]


# -- 3d solar -----------------------------------------------------------------------------------------------
RM, SR, GM = "Roof-mounted panels", "Solar roof (shingles or tiles)", "Ground-mounted"
TESLA_ROOF = {(RM, "No"): "PASS", (RM, "Yes"): "NOTE", (RM, "Unknown"): "OPEN",
              (GM, "No"): "PASS", (GM, "Yes"): "NOTE", (GM, "Unknown"): "OPEN",
              (SR, "No"): "PASS", (SR, "Yes"): "FAIL", (SR, "Unknown"): "OPEN",
              ("", "No"): "PASS", ("", "Yes"): "OPEN", ("", "Unknown"): "OPEN"}


@pytest.mark.parametrize("rid", ["SWY-043", "SLL-058", "STO-043"])
@pytest.mark.parametrize("kind,tesla", list(TESLA_ROOF))
def test_swyfft_tesla_solar_roofs(rid, kind, tesla):
    # "No Tesla Solar Roofs including solar roofs that include Tesla batteries and/or any Tesla parts"
    assert row(rid, solar_panels="Yes", solar_type=kind, solar_tesla=tesla) == TESLA_ROOF[(kind, tesla)]


@pytest.mark.parametrize("kind,tesla,want", [(RM, "No", "PASS"), (RM, "Yes", "NOTE"), (RM, "Unknown", "OPEN"),
                                             (SR, "No", "FAIL"), (SR, "Yes", "FAIL"), (GM, "No", "PASS")])
def test_swyfft_benchmark_surplus_declines_any_solar_roof(kind, tesla, want):
    assert row("SBS-040", solar_panels="Yes", solar_type=kind, solar_tesla=tesla) == want


@pytest.mark.parametrize("rid,want", [
    ("ALL-109", {RM: "PASS", SR: "FAIL", GM: "PASS", "": "OPEN"}),     # "solar roof system"
    ("FOR-066", {RM: "PASS", SR: "FAIL", GM: "PASS", "": "OPEN"}),     # "Solar shingles"
    ("TRV-023", {RM: "PASS", SR: "PASS", GM: "NOTE", "": "OPEN"}),     # "unprotected ground mounted solar panels"
    ("STD-093", {RM: "PASS", SR: "PASS", GM: "NOTE", "": "OPEN"}),     # "more than 10 ground mounted"
    ("STD-092", {RM: "NOTE", SR: "NOTE", GM: "N/A"})])                 # 50% of the roof: not for ground panels
def test_the_solar_type(rid, want):
    for kind, out in want.items():
        assert row(rid, solar_panels="Yes", solar_type=kind, solar_tesla="No") == out, (rid, kind)


def test_no_solar_no_row():
    for rid in ("ALL-109", "SWY-043", "SBS-040", "FOR-066", "TRV-023"):
        assert row(rid, solar_panels="No") == "N/A"


def test_an_old_profile_with_solar_yes_and_no_type_holds():
    assert row("ALL-109", solar_panels="Yes") == "OPEN"


def test_allied_solar_tiles_are_its_solar_roof_row():
    assert M["ALL-110"]["test"] == "always"


def test_twico_s_mounted_panel_decision_is_untouched():
    # Liam, 2026-10-06: standard code-compliant mounted panels are eligible (TWI-033 is not a deciding row)
    assert ev._rules()["TWI-033"]["Tool handling"] == "CONDITION_STANDARD" and "TWI-033" not in M


# -- 3e ownership -------------------------------------------------------------------------------------------
OWNERS = ["Individual Owner", "LLC", "Corporation / partnership", "Estate"]
TRUSTS = ["Family trust", "Revocable living trust", "Land trust", "Corporate or business trust", "Unknown"]


def own(rid, owner, trust=None):
    pd = {"ownership_type": owner, "occupancy_type": "Owner Occupied"}
    if trust:
        pd["trust_type"] = trust
    return row(rid, **pd)


ENTITY_LINES = {   # owner -> outcome, then trust type -> outcome
    "ALL-017": ("PASS FAIL FAIL FAIL", "PASS PASS FAIL FAIL OPEN"),
    "PRO-012": ("PASS FAIL FAIL FAIL", "PASS PASS FAIL FAIL OPEN"),
    "SAG-017": ("PASS FAIL FAIL FAIL", "PASS PASS PASS FAIL OPEN"),
    "SUR-007": ("PASS FAIL FAIL FAIL", "PASS PASS PASS FAIL OPEN"),
    "TRI-021": ("PASS FAIL FAIL FAIL", "PASS PASS PASS FAIL OPEN"),
    "ORI-048": ("PASS FAIL FAIL FAIL", "PASS PASS PASS FAIL OPEN"),
    "MER-005": ("PASS FAIL FAIL PASS", "PASS PASS PASS FAIL OPEN"),   # "LLC, Corporation, and/or Corporate Trust"
    "LIB-048": ("PASS FAIL FAIL PASS", "PASS PASS PASS PASS PASS"),
    "SLL-074": ("PASS FAIL FAIL PASS", "PASS PASS PASS PASS PASS"),
    "FOR-093": ("PASS PASS FAIL PASS", "PASS PASS FAIL FAIL OPEN"),   # an LLC is FOR-094's
    "PDP-049": ("PASS PASS FAIL FAIL", "PASS PASS FAIL FAIL OPEN"),   # an LLC is PDP-120's
    "PH6-028": ("PASS PASS FAIL FAIL", "PASS PASS FAIL FAIL OPEN"),
    "CHO-007": ("PASS FAIL FAIL FAIL", "NOTE NOTE NOTE NOTE NOTE"),   # a trust may still name an individual
    "CDP-069": ("PASS PASS FAIL FAIL", "NOTE NOTE FAIL FAIL OPEN"),   # family member living trust as an ANI
    "NCD-003": ("PASS PASS FAIL PASS", "PASS PASS PASS PASS PASS"),
    "LDP-018": ("PASS PASS NOTE PASS", "PASS PASS PASS PASS PASS"),   # an LLP / LP holding it for an individual
}


@pytest.mark.parametrize("rid", sorted(ENTITY_LINES))
def test_every_owner_and_trust_type_against_the_entity_lines(rid):
    by_owner, by_trust = (x.split() for x in ENTITY_LINES[rid])
    assert [own(rid, o) for o in OWNERS] == by_owner, rid
    assert [own(rid, "Trust", t) for t in TRUSTS] == by_trust, rid


@pytest.mark.parametrize("rid", ["SUR-020", "SFP-020", "WIL-020", "TRI-024", "SDP-008", "FDP-025"])
def test_a_family_held_trust(rid):
    # a family trust passes, a revocable living trust is a confirm note, a land or corporate trust fails
    assert [own(rid, "Trust", t) for t in TRUSTS] == ["PASS", "NOTE", "FAIL", "FAIL", "OPEN"]
    assert own(rid, "LLC") == "N/A"


def test_foremost_land_trust():
    assert [own("FOR-097", "Trust", t) for t in TRUSTS] == ["PASS", "PASS", "FAIL", "PASS", "OPEN"]


@pytest.mark.parametrize("rid", ["MKL-016", "VAV-016", "SLL-075", "VDP-063", "FOD-018", "MDP-015"])
def test_a_corporation_reaches_the_llc_or_corporation_conditions(rid):
    assert own(rid, "Corporation / partnership") == "NOTE" and own(rid, "Estate") == "N/A"


def test_travelers_non_personal_entity_includes_corporations_and_estates():
    for o in ("Corporation / partnership", "Estate", "LLC"):
        assert own("TRV-017", o) == "NOTE"


@pytest.mark.parametrize("rid", ["MER-005", "PRO-012", "ALL-017", "SUR-020"])
def test_an_old_trust_profile_without_a_type_holds(rid):
    assert row(rid, ownership_type="Trust", occupancy_type="Owner Occupied") == "OPEN"


# -- 3f Harris east of Highway 146 --------------------------------------------------------------------------
# Round 35 step 6: an unknown answer -- like a blank county (decision 1) -- is a confirm note, not a hold.
@pytest.mark.parametrize("county,east,want", [("Galveston", None, "FAIL"), ("Travis", None, "PASS"),
                                              ("Harris", "Yes", "FAIL"), ("Harris", "No", "PASS"),
                                              ("Harris", "Unknown", "NOTE"), ("Harris", None, "NOTE"),
                                              ("", None, "NOTE")])
def test_ari_hob_twia_area(county, east, want):
    pd = {"county": county}
    if east:
        pd["harris_east_146"] = east
    assert row("ARB-005", **pd) == want


@pytest.mark.parametrize("county,east,want", [("Harris", "No", "PASS"), ("Harris", "Yes", "OPEN"),
                                              ("Harris", "Unknown", "OPEN"), ("Galveston", "No", "OPEN")])
def test_chubb_harris_1a_east(county, east, want):
    assert row("CHU-047", county=county, harris_east_146=east, occupancy_type="Seasonal") == want


def test_the_answer_is_read_only_for_harris():
    assert ev.facts({"county": "Travis", "harris_east_146": "Yes"})["harris_east_146"] is None


# -- the prompt and the form ------------------------------------------------------------------------------
def test_unanswered_follow_ups_add_no_prompt_line():
    assert ec._followup_lines({"solar_panels": "No", "ownership_type": "Individual Owner"}, "Individual Owner") == []
    assert ec._followup_lines({"solar_panels": "Yes"}, "Trust") == []                # old saved values


def test_answered_follow_ups_are_stated():
    lines = [x for _, x in ec._followup_lines({"solar_panels": "Yes", "solar_type": SR, "solar_tesla": "Yes",
                                               "trust_type": "Land trust"}, "Trust")]
    assert lines == ["Trust Type: Land trust", f"Solar Type: {SR}",
                     "Tesla Equipment (Solar Roof, Powerwall or other Tesla parts): Yes"]


def test_the_form_asks_the_follow_ups_only_when_needed():
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    for needle in ('options=list(intake_fields.OWNERSHIP_TYPES)', 'if ownership_type == "Trust":',
                   '"Trust type", list(intake_fields.TRUST_TYPES)', 'if solar_panels:',
                   '"Solar type", list(intake_fields.SOLAR_TYPES)', 'if county == "Harris":',
                   '"East of Highway 146 (TWIA designated area)?"'):
        assert needle in src, needle
    assert I.OWNERSHIP_TYPES == ("Individual Owner", "Trust", "LLC", "Corporation / partnership", "Estate")


def test_new_owners_get_the_entity_ownership_retrieval():
    assert {"Corporation / partnership", "Estate"} <= ec._OWNERSHIP_STRUCTURES_WITH_ENTITY_RULES
    assert ec._OWNERSHIP_TERMS["Estate"].search("owned by an estate")
