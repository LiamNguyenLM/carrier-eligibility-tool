"""Round 41 B6 (Liam, 2026-10-17): a confirm item's quoted rule
  - never has a condition the form already rules out (The Hartford's "stove in a home in Protection Class 10" on a
    PC 2 home);
  - is the rule that most directly answers the item (a row left open by the blank answer itself, one with no threshold;
    not NatGen's "no single outbuilding over 50% of Coverage A" for the Coverage A item);
  - says when it applies only above a Coverage A the form left blank ("only if Coverage A is $1,500,000+").
Over the Round 38 fuzz set (a sample here; verification/confirm_quotes_fuzz.py runs all 3,409): no quoted rule's
condition is false for the profile. Zero API."""
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "fuzz"))
import confirm_topics as ct  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
H, NG = "The_Hartford_HO3_-_07.09.2026", "NatGen_Custom360_HO3_-_09.02.2026"
# Liam's Harris HO3 profile: Coverage A and the station distance blank
LIAM = {"year_built": 1994, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "dog_breeds": [], "solar_panels": "No", "ppc": "5",
        "fire_station_miles": None, "hydrant_1000ft": "Yes", "zip": "77248", "county": "Harris",
        "dwelling_amount": None, "dwelling_type": "House", "harris_east_146": "Unknown"}


def items(canon, pd):
    o = rv.evaluate_carrier(canon, pd)
    return {it["key"]: it["text"] for it in ct.card_items(rv.code_record(canon, o, pd)[0], pd)}


@pytest.mark.parametrize("ppc", ["2", "6"])
def test_the_hartfords_pc_10_stove_rule_is_not_quoted_on_a_lower_class_home(ppc):
    text = items(H, dict(LIAM, ppc=ppc)).get("heating", "")
    assert "Protection Class 10" not in text


def test_the_hartfords_pc_10_stove_rule_is_quoted_in_pc_10():
    assert "Protection Class 10" in items(H, dict(LIAM, ppc="10", fire_station_miles=3.0)).get("heating", "")


def test_natgens_coverage_a_item_quotes_the_coverage_a_range_not_the_outbuilding_rule():
    text = items(NG, LIAM)["coverage_a"]
    assert "outbuilding" not in text and "$150,000" in text


@pytest.mark.parametrize("amount,shown", [(None, " (only if Coverage A is $1,500,000+)"), (2000000, "")])
def test_a_threshold_left_blank_says_when_the_rule_applies(amount, shown):
    text = items(NG, dict(LIAM, dwelling_amount=amount)).get("alarms", "")
    assert "insured over $1,500,000" in text and text.endswith(shown or "alarm")


@pytest.mark.parametrize("rule,pd,out", [
    ("A wood, coal or pellet stove in a home in Protection Class 10 (including 10W) is declined.", {"ppc": "2"}, True),
    ("Dwellings in PC 10 with a solid fuel burning stove.", {"ppc": "9"}, True),
    ("Dwellings in PC 10 with a solid fuel burning stove.", {"ppc": "10"}, False),
    ("In PC 1-9, a Cotality Wildfire Risk Score of 61 or higher is ineligible.", {"ppc": "4"}, False),
    ("In PC 1-9, a Cotality Wildfire Risk Score of 61 or higher is ineligible.", {"ppc": "10"}, True),
    ("Primary dwellings in PC 1-8 insured over $1,500,000 require a central station alarm.",
     {"ppc": "5", "dwelling_amount": 400000}, True),
    ("For primary dwellings, Coverage A over $1,500,000 requires underwriting approval.", {"dwelling_amount": 900000},
     True),
    ("For primary dwellings, Coverage A over $1,500,000 requires underwriting approval.", {"dwelling_amount": None},
     False),
    ("Wood roofs require a Betterview Aerial roof index score of 70 or higher.", {"roof_type": "Tile"}, True),
    ("Metal roofs other than steel are ineligible.", {"roof_type": "Metal: standing seam"}, False),
    ("A structure away from the premises with a coverage limit over $100,000 must be referred.",
     {"dwelling_amount": 400000}, False),
    ("Any rule at all.", {}, False),
    # a split class rates as each carrier says (NatGen DP3: 1X-8X is PC 9): never ruled out on protection class
    ("Dwellings under construction or significant renovation in PC 1X-8X or PC 9 are ineligible.", {"ppc": "6X"}, False),
    ("Dwellings under construction or significant renovation in PC 1X-8X or PC 9 are ineligible.", {"ppc": "6"}, True),
])
def test_a_rules_own_condition_against_the_form(rule, pd, out):
    assert ct.ruled_out(rule, pd) is out


def _quoted(text):
    return text.split(" — guide: ", 1)[1] if " — guide: " in text else None


def test_over_a_fuzz_sample_no_quoted_rule_is_ruled_out():
    import gen
    bad = []
    on = set(rv.BATCHES) - {"pilot"}
    for seed in range(0, 3409, 23):                       # 149 profiles of the Round 38 set's first batch range
        pd, checked = gen.profile(seed)
        for canon in rv.WB_TO_CANON.values():
            wb = rv.rules_table_wb(canon, on, pd)
            if wb is None:
                continue
            rec = rv.code_record(canon, rv.evaluate_carrier(canon, pd, checked, wb=wb), pd)[0]
            for it in ct.card_items(rec, pd, checked):
                q = _quoted(it["text"])
                if q and ct.ruled_out(q, pd):
                    bad.append((seed, canon, it["key"], q[:80]))
    assert bad == [], bad[:5]
