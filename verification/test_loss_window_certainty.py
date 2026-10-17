"""Round 41 B3 (Liam, 2026-10-17): a typed loss row with a 3-year window never declines (or refers) when the form
cannot tell which loss falls in the window -- more losses in 5 years than in 3, and a loss type on the form the rule
does not count (that loss may be one of the recent ones, the counted one the older). It is a confirm naming the
condition, as The Hartford's rows have been since round 39 (build_hartford_map.recent_type).

Found 2026-10-17: every table already does (the shared template's 3-year one-loss rows ARA-066, ARB-069 and CDP-100
were hand-worded confirms since round 37); the rows that fail on such profiles -- HAR-027, SLL-071, VAV-090, VDP-052 --
fail only when every type shown is one they count, so the recent losses are certainly counted. This test keeps it so
for every table. A 5-year row is not windowed: the form's loss types are the 5-year losses. Zero API."""
import itertools
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
TYPES = ("Water", "Fire", "Liability", "Wind or hail", "Theft", "Other")
BASE = {"year_built": 2005, "roof_age": 8, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "PVC", "ownership_type": "Individual Owner",
        "coastal_tier": "Not Coastal", "swimming_pool": "No Pool", "pool_accessories": "None", "has_dogs": "No",
        "dog_breeds": [], "solar_panels": "No", "ppc": "4", "fire_station_miles": 2.0, "hydrant_1000ft": "Yes",
        "county": "Bexar", "zip": "78201", "dwelling_amount": 400000, "dwelling_type": "House",
        "units_in_building": "1", "loss_year": 2025}
# more losses in 5 years than in 3: the form cannot say which of them are the recent ones
UNPLACED = [("2", "1"), ("3 or more", "1"), ("3 or more", "2")]
WINDOWED = sorted(rid for rid, m in rv._map().items() if "losses_3yr" in m["test"] and "loss_types" in m["test"])


def _counted(test):
    out = set()
    for s in re.findall(r"loss_types none_of \{([^}]*)\}", test):
        out |= {x.strip() for x in s.split(",") if x.strip()}
    return out


def test_there_are_windowed_typed_rows_to_check():
    assert len(WINDOWED) >= 20 and {"HAR-027", "SLL-071", "CDP-100", "ARA-066"} <= set(WINDOWED)


@pytest.mark.parametrize("rid", WINDOWED)
def test_an_unplaced_loss_of_a_type_the_rule_does_not_count_never_fails_it(rid):
    m = rv._map()[rid]
    counted = _counted(m["test"])
    wrong = []
    for (n5, n3), k in itertools.product(UNPLACED, (2, 3)):
        for types in itertools.combinations(TYPES, k):
            if set(types) <= counted:
                continue
            for occ in ("Owner Occupied", "Tenant Occupied"):
                pd = dict(BASE, losses_5yr=n5, losses_3yr=n3, loss_types=list(types), occupancy_type=occ)
                if rv.evaluate_row(m, rv.facts(pd))[0] == "FAIL":
                    wrong.append((n5, n3, types, occ))
    assert wrong == [], (rid, wrong[:3])


@pytest.mark.parametrize("rid,types", [("CDP-100", ["Liability", "Wind or hail"]), ("CDP-100", ["Liability", "Water"]),
                                       ("ARA-066", ["Water", "Wind or hail"]), ("ARB-069", ["Theft", "Other"])])
def test_the_shared_templates_3_year_one_loss_rows_are_confirms_naming_the_condition(rid, types):
    pd = dict(BASE, losses_5yr="2", losses_3yr="1", loss_types=types, occupancy_type="Tenant Occupied"
              if rid.startswith("CDP") else "Owner Occupied")
    o, d = rv.evaluate_row(rv._map()[rid], rv.facts(pd))
    assert o == "NOTE" and d.startswith("confirm: ") and "3 years" in d


@pytest.mark.parametrize("rid,types", [("SLL-071", ["Fire", "Liability"]), ("VDP-052", ["Fire", "Theft"])])
def test_two_recent_losses_all_of_counted_types_still_decline(rid, types):
    pd = dict(BASE, losses_5yr="3 or more", losses_3yr="2", loss_types=types,
              occupancy_type="Tenant Occupied" if rid.startswith("VDP") else "Owner Occupied")
    assert rv.evaluate_row(rv._map()[rid], rv.facts(pd))[0] == "FAIL"
