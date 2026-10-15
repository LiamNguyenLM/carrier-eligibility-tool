"""Round 39 step 0c (Liam): a 23-year-old roof on a 1995 house, every roof type -- each carrier's roof-age rule is
on the card. Run through the pipeline, two kinds of roof-settlement coverage note never showed:
- an architectural shingle is an asphalt shingle: Vave HO3 (VAV-031..033), Vave DP3 (VDP-077) and Swyfft Lloyd's
  (SLL-025) write their asphalt schedule as "asphalt shingle", so an architectural roof got none of it;
- "all other roofs / roof types": Mercury MER-019 ("... required for all other roof types older than 10 years") and
  NatGen Custom360 DP3 NCD-101 ("Composition and all other roofs (except metal, slate, tile) ...") showed for no
  covering the row does not name itself.
Notes only, never a status (zero API, rules_evaluator)."""
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import intake_fields as I  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
R = rv._rules()


def shows(rid, roof):
    return rv._coverage_note_applies(R[rid], {"roof_type": roof, "roof_age": 23, "year_built": 1995})


@pytest.mark.parametrize("rid", ["VAV-032", "VDP-077", "SLL-025"])
def test_an_architectural_roof_gets_the_asphalt_schedule(rid):
    assert shows(rid, "Architectural Shingle") and shows(rid, "Composition Shingle")


def test_the_3_tab_row_stays_off_an_architectural_roof():
    assert not shows("CHO-028", "Architectural Shingle") and shows("CHO-029", "Architectural Shingle")


@pytest.mark.parametrize("roof", ["Architectural Shingle", I.ROOF_WOOD, I.ROOF_BUILT_UP, I.ROOF_MEMBRANE,
                                  I.ROOF_ROLLED, "Other"])
def test_all_other_roofs_reach_every_covering_not_named_elsewhere(roof):
    assert shows("NCD-101", roof) and shows("MER-019", roof)


@pytest.mark.parametrize("roof", ["Tile", "Slate", I.ROOF_METAL_SEAM])
def test_all_other_roofs_leave_out_the_coverings_named_elsewhere(roof):
    assert not shows("NCD-101", roof) and not shows("MER-019", roof)
    assert shows("NCD-102", roof) and shows("MER-018", roof)


def test_no_settlement_row_naming_one_covering_spreads_to_another():
    assert not shows("NCD-102", "Composition Shingle") and not shows("MER-018", "Architectural Shingle")
