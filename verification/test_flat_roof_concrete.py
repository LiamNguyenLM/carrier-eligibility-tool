"""Round 38 step 7, finding F10 (self-audit, 2026-10-11): Centauri DP3 (CDP-023) and Progressive DP3 (PDP-099) say
"Flat roofs are ineligible unless poured concrete". Their map lines asked to "confirm poured concrete" for every
covering but built-up, membrane and rolled -- so a flat roof covered in shingles, tile, slate or metal was a confirm,
while Centauri's own code check (structured_rules.centauri_dp3_flat_roof, round 14) declined it: a discrete covering
is not a poured deck. Only "Other" can be poured concrete. Zero API."""
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import intake_fields  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
ROWS = {"CDP-023": "Centauri_-_DP3_-_11.16.2022", "PDP-099": "Progressive_DP3_-_10.01.2024"}
BASE = {"occupancy_type": "Tenant Occupied", "ownership_type": "Individual Owner", "year_built": 2005, "roof_age": 5,
        "roof_shape": "Flat", "dwelling_type": "House"}


@pytest.mark.parametrize("row", ROWS)
@pytest.mark.parametrize("roof_type", intake_fields.ROOF_TYPES)
def test_a_flat_roof_passes_only_as_a_confirmed_poured_deck(row, roof_type):
    got = rv.evaluate_carrier(ROWS[row], dict(BASE, roof_type=roof_type))[row][0]
    assert got == ("NOTE" if roof_type == "Other" else "FAIL"), (roof_type, got)


@pytest.mark.parametrize("row", ROWS)
@pytest.mark.parametrize("roof_type", ["Composition Shingle", "Tile", "Other"])
def test_a_pitched_roof_is_not_this_rule(row, roof_type):
    assert rv.evaluate_carrier(ROWS[row], dict(BASE, roof_shape="Gable", roof_type=roof_type))[row][0] == "N/A"


def test_the_map_agrees_with_centauris_code_check():
    import structured_rules as sr
    for roof_type in intake_fields.ROOF_TYPES:
        code, _ = sr.centauri_dp3_flat_roof("Flat", roof_type)
        table = rv.evaluate_carrier(ROWS["CDP-023"], dict(BASE, roof_type=roof_type))["CDP-023"][0]
        assert (code == "INELIGIBLE") == (table == "FAIL"), (roof_type, code, table)
