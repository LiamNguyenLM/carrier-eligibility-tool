"""Round 35 step 3b (Liam, 2026-10-09, decision 1): the roof covering in detail. Every new option against
every line that reads it, from each row's own words. Zero API."""
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import intake_fields as I  # noqa: E402
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval
M = ev._map()
COMP, ARCH, SEAM, PANEL, MSH = ("Composition Shingle", "Architectural Shingle", I.ROOF_METAL_SEAM, I.ROOF_METAL_PANEL,
                                I.ROOF_METAL_SHINGLE)
TILE, SLATE, WOOD, BUILT, ROLLED, MEMB = "Tile", "Slate", I.ROOF_WOOD, I.ROOF_BUILT_UP, I.ROOF_ROLLED, I.ROOF_MEMBRANE
ASB, TLOCK, SOLAR, OTHER = I.ROOF_ASBESTOS, I.ROOF_TLOCK, I.ROOF_SOLAR, "Other"
ALL = I.ROOF_TYPES
METALS = (SEAM, PANEL, MSH)
BASE = {"roof_shape": "Gable", "roof_age": 5, "county": "Travis", "occupancy_type": "Owner Occupied",
        "dwelling_type": "House", "dwelling_amount": 450000, "year_built": 2010}


def out(rid, roof, **pd):
    return ev.evaluate_row(M[rid], ev.facts(dict(BASE, roof_type=roof, **pd)))[0]


def expect(fail=(), note=(), rest="PASS"):
    return {r: "FAIL" if r in fail else "NOTE" if r in note else rest for r in ALL}


WOOD_ONLY = expect(fail=(WOOD,))
PROGRESSIVE = expect(fail=(WOOD, BUILT, ROLLED, PANEL), note=(MEMB,))
ARI = dict(fail=(WOOD, ASB, BUILT, PANEL), note=(SEAM, MSH))
GAUGE = expect(note=METALS, rest="N/A")
CASES = {
    # "T-lock shingles, slate, corrugated metal, copper, tin, rubber membrane, rolled tar paper, built up tar and
    # gravel, solar roof system and roofs with any type of wood shingles or shakes"
    "ALL-037": expect(fail=(TLOCK, SLATE, PANEL, BUILT, ROLLED, SOLAR, WOOD), note=(MEMB, SEAM, MSH)),
    "ALL-042": expect(fail=(SLATE, SOLAR), note=(OTHER,)),            # "Solar panel tiles, slate, unique/uncommon"
    "MER-012": expect(fail=(ASB, TLOCK, WOOD), note=(PANEL,)),        # "Asbestos shingles, tin, T-lock, wood ..."
    "PRO-024": PROGRESSIVE, "PDP-098": PROGRESSIVE, "PH6-077": PROGRESSIVE,
    "ARA-007": expect(**ARI), "ARB-006": expect(fail=ARI["fail"] + (SLATE,), note=ARI["note"]),
    "ARA-056": expect(fail=METALS), "ARB-055": expect(fail=METALS),   # "Metal roofs must be pre-approved"
    "ORI-012": expect(fail=(WOOD, BUILT, ROLLED, MEMB, ASB, TLOCK, SOLAR), note=(OTHER,)),
    "ORI-059": expect(fail=(PANEL, TLOCK)),                            # "corrugated metal, T-lock shingles"
    "TWI-037": expect(fail=(WOOD, ASB, SLATE, MSH, PANEL)),           # standing seam is eligible
    "TRV-041": expect(fail=(ASB, TLOCK, WOOD, ROLLED)),
    "CDP-021": expect(fail=(PANEL,)), "CDP-027": expect(fail=(ROLLED,)),
    "CHO-024": expect(fail=(WOOD, BUILT, ROLLED, ASB, MEMB), note=METALS),
    "NCD-097": expect(fail=(TLOCK, ROLLED, WOOD, BUILT), note=(MEMB, TILE)),
    "STD-064": expect(note=METALS), "STD-065": expect(note=(PANEL,)),  # "Aluminum", "Tin"
    "LIB-034": WOOD_ONLY, "LDP-035": WOOD_ONLY, "STD-069": WOOD_ONLY, "CDP-022": WOOD_ONLY, "CHU-020": WOOD_ONLY,
    **{rid: GAUGE for rid in ("SAG-033", "SUR-149", "SFP-155", "WIL-153", "TRI-041", "ODP-077", "SDP-114", "FDP-139")},
    # flat-roof rows on a gabled roof: only the low-slope coverings make the roof flat
    "ALL-038": expect(note=(BUILT, MEMB), rest="N/A"),
    "CHU-012": expect(fail=(BUILT, MEMB)), "MER-016": expect(fail=(BUILT, MEMB)),
    "CDP-023": expect(fail=(BUILT, MEMB), rest="N/A"), "PDP-099": expect(fail=(BUILT, MEMB), rest="N/A"),
}


@pytest.mark.parametrize("rid", sorted(CASES))
@pytest.mark.parametrize("roof", ALL)
def test_every_option_against_the_line(rid, roof):
    assert out(rid, roof) == CASES[rid][roof], (rid, roof, M[rid]["test"])


@pytest.mark.parametrize("roof,want", [(SEAM, "PASS"), (TILE, "PASS"), (SLATE, "PASS"), (MSH, "FAIL"), (COMP, "FAIL"),
                                       (PANEL, "FAIL")])
def test_swyfft_lloyds_40_years_for_standing_seam_tile_and_slate(roof, want):
    # the guide's own table: standing seam, tile, slate excluded over 40 years; everything else over 25
    assert out("SLL-015", roof, roof_age=30) == want
    assert out("SLL-015", roof, roof_age=20) == "PASS"


@pytest.mark.parametrize("roof,want", [(BUILT, "FAIL"), (MEMB, "FAIL"), (ROLLED, "FAIL"), (COMP, "NOTE"), (TILE, "NOTE")])
def test_a_flat_roof_that_is_not_poured_concrete(roof, want):
    assert out("CDP-023", roof, roof_shape="Flat") == want


def test_a_flat_shape_fails_centauri_ho3_whatever_the_covering():
    assert {out("CHO-024", r, roof_shape="Flat") for r in ALL} == {"FAIL"}


# -- old saved values ---------------------------------------------------------------------------------------
LINES = sorted(rid for rid, m in M.items() if "roof_type" in m["field"])


@pytest.mark.parametrize("old", ["Metal", "Flat/Built-Up"])
def test_an_old_metal_or_flat_value_never_guesses(old):
    for rid in LINES:
        assert out(rid, old) != "FAIL", rid
    for rid in ("ALL-037", "ARA-056", "LIB-034", "TWI-037", "PRO-024"):
        assert out(rid, old) == "OPEN"                 # the kind is unknown: it holds


def test_an_old_wood_shake_is_the_wood_option():
    for rid in LINES:
        assert out(rid, "Wood Shake") == out(rid, WOOD), rid


def test_no_old_roof_value_is_left_in_a_map_line():
    import re
    old = re.compile(r"Wood Shake|Flat/Built-Up|\bMetal\b(?!:)")
    assert not [rid for rid, m in M.items() if old.search(m["test"] + " " + m["gate"])]


def test_no_roof_line_is_ambiguous_any_more():
    assert not [rid for rid in LINES if "||" in M[rid]["test"]]


# -- the form -----------------------------------------------------------------------------------------------
def test_the_form_offers_the_new_options():
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    assert 'st.selectbox("Roof Type", list(intake_fields.ROOF_TYPES)' in src
    assert not any("," in r for r in ALL)                                     # the grammar splits sets on commas
    assert I.ROOF_LABELS[MSH] == "Metal: shingle, tile or shake (incl. stone-coated)"
    assert I.ROOF_LABELS[MEMB] == "Membrane (rubber/EPDM, TPO, modified bitumen)"
    assert {SEAM, PANEL, MSH, BUILT, ROLLED, MEMB, ASB, TLOCK, SOLAR, WOOD} <= set(ALL)
    assert not {"Metal", "Flat/Built-Up", "Wood Shake"} & set(ALL)
