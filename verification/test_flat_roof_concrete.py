"""Round 38 step 7, finding F10 (self-audit, 2026-10-11) -- FOR LIAM, not fixed. Centauri DP3 (CDP-023) and Progressive
DP3 (PDP-099): "Flat roofs are ineligible unless poured concrete". Two deliberate decisions disagree:
  - round 14: Centauri's code check (structured_rules.centauri_dp3_flat_roof) declines a flat roof with any discrete
    covering (shingle, tile, slate, metal) -- it is not a poured deck;
  - round 35 step 2 (map audit): CDP-023 / PDP-099 confirm "poured concrete" for every covering but built-up, membrane
    and rolled (test_roof_types.test_a_flat_roof_that_is_not_poured_concrete).
So Centauri declines through the code check with no row and no quote on the card, and Progressive DP3 (no code check)
gives a confirm for the same answers. A fix was tried (237dfe4) and reverted: it changed Progressive DP3's verdict
against round 35's expectation. These xfails stay until Liam picks one reading. Zero API."""
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
DISCRETE = [r for r in intake_fields.ROOF_TYPES if r not in ("Other", intake_fields.ROOF_BUILT_UP,
                                                                intake_fields.ROOF_MEMBRANE, intake_fields.ROOF_ROLLED)]


@pytest.mark.xfail(strict=True, reason="for Liam (F10): round-14 code check declines a flat roof with a discrete covering; "
                                       "round-35 CDP-023 line confirms it")
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
def test_today_the_two_flat_roof_lines_confirm_a_discrete_covering(roof_type):
    # what ships today (round 35), so a change to either line is deliberate
    for canon, rid in (("Centauri_-_DP3_-_11.16.2022", "CDP-023"), ("Progressive_DP3_-_10.01.2024", "PDP-099")):
        assert rv.evaluate_carrier(canon, dict(BASE, roof_type=roof_type))[rid][0] == "NOTE", (rid, roof_type)
