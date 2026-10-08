"""Round 30 step 1 (Liam, 2026-10-08, decision 1): "Primary home insured with" and "Distance to
the primary home (miles)", asked only for a Seasonal / Secondary Home. Zero API.

The rows these answers settle (guide wording in the comment; none of these guides extends its
rule to an affiliate or group, so only the carrier's own choice passes):
  CHU-004 / 045 / 046  "Applicable to residences where Chubb writes the primary residence."
  MER-003              "Secondary/seasonal dwelling ... and Mercury does not insure the primary dwelling."
  ARA-029              "... not eligible ... unless ARI insures the primary home"
  TWI-005              "Secondary must have an associated primary written in Twico."
  TRV-039              "A secondary or seasonal home which is an ISO protection class 9, 10 ... and we do
                        not write the primary dwelling."
  SWY-007 / SBS-027    "Seasonal or secondary homes that are not owner occupied and/or less than 50 miles
                        from the primary residence"
Not settled by them: SLL-043 (country of the primary home), ARB-025 / ARB-039 (both rows refer, so a
non-ARI primary still refers -- the data has no decline row), NPD-010 (closed program)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402
import hold_guard  # noqa: E402
import intake_fields as F  # noqa: E402
import rules_evaluator as ev  # noqa: E402
from data_defects import EXPECTED_PROGRAMS_FILE  # noqa: E402

pytestmark = pytest.mark.retrieval

BASE = {"year_built": 2005, "roof_age": 5, "roof_type": "Architectural Shingle", "roof_shape": "Gable",
        "construction_type": "Masonry", "plumbing_type": "Copper", "occupancy_type": "Seasonal",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "aggressive_breed": "No", "solar_panels": "No",
        "ppc": "3", "dwelling_type": "House", "county": "Harris", "dwelling_amount": 450000}


def _expected_programs():
    return [l.strip() for l in open(EXPECTED_PROGRAMS_FILE, encoding="utf-8") if l.strip() and not l.startswith("#")]


def test_every_program_maps_to_exactly_one_choice_and_the_choices_follow_the_carrier_list():
    labels = [F.primary_home_label(p) for p in _expected_programs()]
    assert None not in labels
    assert set(labels) == set(F.PRIMARY_HOME_CARRIERS)       # no choice without a program on file
    assert F.PRIMARY_HOME_CHOICES[0] == "" and F.PRIMARY_HOME_CHOICES[-2:] == ("Other carrier", "Unknown")
    # in the carrier list's (sorted program name) order
    first_seen = list(dict.fromkeys(F.primary_home_label(p) for p in sorted(_expected_programs())))
    assert list(F.PRIMARY_HOME_CARRIERS) == first_seen


@pytest.mark.parametrize("value,want", [("Chubb", "Chubb"), ("Other carrier", "Other carrier"), ("Unknown", None),
                                        ("", None), (None, None), ("chubb insurance", None)])
def test_unknown_or_blank_is_unknown(value, want):
    assert F.primary_home_carrier(value) == want


# -- each mapped row: its own carrier / another carrier / Other / Unknown / blank ------------------
CARRIER_ROWS = [("CHU-004", "Chubb", {}), ("CHU-045", "Chubb", {}), ("MER-003", "Mercury", {}),
                ("ARA-029", "ARI", {}), ("TWI-005", "TWICO", {}), ("TRV-039", "Travelers", {"ppc": "9"})]


@pytest.mark.parametrize("rid,own,extra", CARRIER_ROWS)
@pytest.mark.parametrize("occupancy", ["Seasonal", "Secondary Home"])
def test_a_same_carrier_rule_passes_only_on_that_carrier(rid, own, extra, occupancy):
    def out(answer):
        pd = dict(BASE, occupancy_type=occupancy, primary_home_carrier=answer, **extra)
        return ev.evaluate_row(ev._map()[rid], ev.facts(pd))[0]
    other = "Progressive" if own != "Progressive" else "Chubb"
    assert out(own) == "PASS"
    assert out(other) == "FAIL" and out("Other carrier") == "FAIL"
    assert out("Unknown") == "OPEN" and out("") == "OPEN"


def test_chubb_coastal_harris_still_needs_the_premium_fact():
    pd = dict(BASE, primary_home_carrier="Chubb")
    # the $25,000 non-CAT premium is never asked: a "Confirm:" note since round 30 step 2
    assert ev.evaluate_row(ev._map()["CHU-046"], ev.facts(pd))[0] == "NOTE"
    pd = dict(BASE, primary_home_carrier="Travelers")
    assert ev.evaluate_row(ev._map()["CHU-046"], ev.facts(pd))[0] == "FAIL"


def test_a_lower_ppc_never_reaches_travelers_row():
    pd = dict(BASE, ppc="8", primary_home_carrier="Chubb")
    assert ev.evaluate_row(ev._map()["TRV-039"], ev.facts(pd))[0] == "N/A"


@pytest.mark.parametrize("rid", ["SWY-007", "SBS-027"])
def test_the_50_mile_rule_at_its_boundary(rid):
    # "less than 50 miles from the primary residence" is ineligible: 50 passes
    got = {m: ev.evaluate_row(ev._map()[rid], ev.facts(dict(BASE, primary_home_miles=m)))[0]
           for m in ("49.9", "50", "50.1", "", None)}
    assert got == {"49.9": "FAIL", "50": "PASS", "50.1": "PASS", "": "OPEN", None: "OPEN"}


def test_the_rows_the_answers_do_not_settle_are_unchanged():
    # Lloyd's "primary residence is outside of the United States": still a fact the form does not ask
    m = ev._map()["SLL-043"]
    assert "primary_home" not in m["field"] and "FACT(" in m["test"]


# -- the prompt: byte-identical unless the question was shown and answered --------------------------
def _text(pd):
    return ec._property_details_text(pd, 20, pd["occupancy_type"], pd["ownership_type"], ec.topics.normalize(None))


@pytest.mark.parametrize("occupancy", ["Owner Occupied", "Tenant Occupied", "Vacant"])
def test_other_occupancies_get_the_same_prompt_even_with_stray_answers(occupancy):
    pd = dict(BASE, occupancy_type=occupancy)
    assert _text(dict(pd, primary_home_carrier="Chubb", primary_home_miles=40)) == _text(pd)


@pytest.mark.parametrize("occupancy", ["Seasonal", "Secondary Home"])
def test_an_answered_question_is_stated_and_a_blank_one_is_not(occupancy):
    pd = dict(BASE, occupancy_type=occupancy)
    assert _text(dict(pd, primary_home_carrier="Unknown", primary_home_miles=None)) == _text(pd)
    t = _text(dict(pd, primary_home_carrier="Chubb", primary_home_miles=40))
    assert "Primary Home Insured With: Chubb" in t and "Distance to the Primary Home: 40 miles" in t


@pytest.mark.parametrize("item", ["Whether Chubb writes the primary residence",
                                  "Whether TWICO also insures the applicant's primary home",
                                  "Distance from the primary residence"])
def test_the_hold_guard_now_treats_them_as_form_fields(item):
    assert hold_guard.classify(item)[0] == "a"
