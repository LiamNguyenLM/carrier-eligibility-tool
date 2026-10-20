"""Round 41 B5 (Liam, 2026-10-17): the "all roof types" coverage rows show as notes on the cards they apply to --
SageSure's cosmetic hail marring exclusion (HO3 and DP3, Occidental HO3), HOAIC TDP3's cosmetic hail cap, Vave's and
TWICO's "underwriting may change roof settlement regardless of roof age or material" -- on every card of that carrier;
Markel's Roof Exclusion form only when the roof's material and age meet its rows (MKL-094 / 095, MDP-052 / 053), with
what the form excludes (MKL-092 / 093); inspection-only rows (deterioration, an inspection concern) never; Foremost's
marring row after a paid hail loss. Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import intake_fields as I  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
R = rv._rules()
EVERY = ["SAG-036", "SUR-152", "SFP-158", "WIL-156", "TRI-044", "OCC-059", "ODP-080", "SDP-117", "FDP-141", "HDP-011",
         "VAV-040", "VDP-088", "TWI-058"]
ROOFS = [("Composition Shingle", 3), ("Architectural Shingle", 30), ("Tile", 12), (I.ROOF_METAL_SEAM, 45),
         (I.ROOF_WOOD, 20), ("", None)]


def applies(rid, **pd):
    return rv._coverage_note_applies(R[rid], pd)


@pytest.mark.parametrize("rid", EVERY)
@pytest.mark.parametrize("roof,age", ROOFS)
def test_an_every_roof_row_is_a_note_on_every_card(rid, roof, age):
    assert applies(rid, roof_type=roof, roof_age=age)


@pytest.mark.parametrize("roof,age,want", [("Composition Shingle", 26, True), ("Architectural Shingle", 30, True),
                                           ("Composition Shingle", 25, False), ("Tile", 45, False),
                                           (I.ROOF_METAL_SEAM, 30, False), ("Composition Shingle", None, False)])
@pytest.mark.parametrize("rid", ["MKL-094", "MDP-052"])
def test_markels_exclusion_for_other_roofs_over_25_years(rid, roof, age, want):
    assert applies(rid, roof_type=roof, roof_age=age) is want


@pytest.mark.parametrize("roof,age,want", [("Tile", 41, True), (I.ROOF_METAL_SEAM, 45, True), ("Slate", 40, False),
                                           (I.ROOF_METAL_SEAM, 5, False), ("Composition Shingle", 45, False)])
@pytest.mark.parametrize("rid", ["MKL-095", "MDP-053"])
def test_markels_exclusion_for_slate_tile_metal_over_40_years(rid, roof, age, want):
    assert applies(rid, roof_type=roof, roof_age=age) is want


@pytest.mark.parametrize("roof,age,want", [("Composition Shingle", 30, True), ("Tile", 41, True),
                                           ("Composition Shingle", 10, False), ("Tile", 30, False)])
@pytest.mark.parametrize("rid", ["MKL-092", "MKL-093"])
def test_what_markels_roof_exclusion_form_excludes_shows_with_its_age_rows(rid, roof, age, want):
    assert applies(rid, roof_type=roof, roof_age=age) is want


@pytest.mark.parametrize("rid", ["MKL-096", "MKL-097", "MDP-054", "MDP-055"])
def test_an_inspection_only_row_is_never_a_note(rid):
    assert not applies(rid, roof_type="Composition Shingle", roof_age=30)


@pytest.mark.parametrize("pd,want", [(dict(losses_5yr="1", loss_types=["Wind or hail"]), True),
                                     (dict(losses_5yr="2", loss_types=["Water", "Wind or hail"]), True),
                                     (dict(losses_5yr="1", loss_types=["Water"]), False), (dict(losses_5yr="0"), False)])
def test_foremosts_marring_row_after_a_paid_hail_loss(pd, want):
    assert applies("FOR-034", roof_type="Composition Shingle", roof_age=10, **pd) is want


def test_the_card_carries_the_cosmetic_hail_note():
    pd = {"roof_type": "Tile", "roof_age": 12, "county": "Bexar", "occupancy_type": "Owner Occupied"}
    notes = rv.coverage_notes("Sage_-_SURE_HO-3_-_01.31.2026", {}, pd)
    assert any("cosmetic marring due to hail on all roof types" in n for n in notes)
