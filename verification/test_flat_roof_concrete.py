"""Round 38 step 7, finding F10 -- decided by Liam 2026-10-12 (round 38b). Centauri DP3 (CDP-023) and Progressive DP3
(PDP-099): "Flat roofs are ineligible unless poured concrete". Round 14's code check
(structured_rules.centauri_dp3_flat_roof) declined a flat roof with any discrete covering; round 35's map line made it
a confirm. Liam: a flat roof with shingle, tile or metal is a CONFIRM for now; the code check is aligned with the map
line (built-up, membrane and rolled coverings still decline). This file held a strict xfail until then. Zero API."""
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import intake_fields  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
BASE = {"occupancy_type": "Tenant Occupied", "ownership_type": "Individual Owner", "year_built": 2005, "roof_age": 5,
        "roof_shape": "Flat", "dwelling_type": "House"}
LOW_SLOPE = (intake_fields.ROOF_BUILT_UP, intake_fields.ROOF_MEMBRANE, intake_fields.ROOF_ROLLED)
DISCRETE = [r for r in intake_fields.ROOF_TYPES if r not in ("Other",) + LOW_SLOPE]


def test_the_map_agrees_with_centauris_code_check():
    import structured_rules as sr
    bad = []
    for roof_type in intake_fields.ROOF_TYPES:
        code, _ = sr.centauri_dp3_flat_roof("Flat", roof_type)
        table = rv.evaluate_carrier("Centauri_-_DP3_-_11.16.2022", dict(BASE, roof_type=roof_type))["CDP-023"][0]
        if (code == "INELIGIBLE") != (table == "FAIL"):
            bad.append((roof_type, code, table))
    assert bad == []


@pytest.mark.parametrize("roof_type", DISCRETE)
def test_both_flat_roof_lines_confirm_a_discrete_covering(roof_type):
    for canon, rid in (("Centauri_-_DP3_-_11.16.2022", "CDP-023"), ("Progressive_DP3_-_10.01.2024", "PDP-099")):
        assert rv.evaluate_carrier(canon, dict(BASE, roof_type=roof_type))[rid][0] == "NOTE", (rid, roof_type)


@pytest.mark.parametrize("roof_type", LOW_SLOPE)
def test_both_flat_roof_lines_decline_low_slope_roofing(roof_type):
    for canon, rid in (("Centauri_-_DP3_-_11.16.2022", "CDP-023"), ("Progressive_DP3_-_10.01.2024", "PDP-099")):
        assert rv.evaluate_carrier(canon, dict(BASE, roof_type=roof_type))[rid][0] == "FAIL", (rid, roof_type)
