"""Round 39 step 4 (Liam): "Units in the building" (asked for a House: 1 / 2 / 3-4 / 5 or more / Unknown) decides the
family / unit-count rows of every table (rules_data/units_lines.py: 21 rows); blank or Unknown is a confirm, never a
hold; a Townhome or Condo is not asked. Plus the help line under Dwelling type. Zero API (rules_evaluator)."""
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "rules_data"))
import intake_fields  # noqa: E402
import rules_evaluator as rv  # noqa: E402
from units_lines import LINES  # noqa: E402

pytestmark = pytest.mark.retrieval
HOUSE = {"dwelling_type": "House", "occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner"}
M = rv._map()


def out(rid, **pd):
    return rv.evaluate_row(M[rid], rv.facts(dict(HOUSE, **pd)))[0]


def test_21_rows_read_the_units_answer():
    assert len(LINES) == 21 and all("units_in_building" in M[rid]["field"] for rid in LINES)


# (rows, the answers that pass, the answers that fail) -- two carriers or more per kind of rule
KINDS = [
    (["SUR-005", "LIB-008", "LDP-023", "STD-036"], ["1", "2", "3-4"], ["5 or more"]),        # one-to-four family
    (["MER-008", "SLL-040", "CHO-014", "HAR-033"], ["1", "2"], ["3-4", "5 or more"]),        # one- or two-family
    (["ALL-020"], ["1"], ["2", "3-4", "5 or more"]),                                          # single-family / townhome
]


@pytest.mark.parametrize("rows,ok,bad", KINDS)
def test_each_answer(rows, ok, bad):
    for rid in rows:
        for units in ok:
            assert out(rid, units_in_building=units) == "PASS", (rid, units)
        for units in bad:
            assert out(rid, units_in_building=units) == "FAIL", (rid, units)


@pytest.mark.parametrize("rid", sorted(LINES))
@pytest.mark.parametrize("units", ["", "Unknown", None])
def test_blank_or_unknown_is_a_confirm_never_a_hold(rid, units):
    pd = {"occupancy_type": "Seasonal"} if rid in ("SAG-003", "SUR-016", "SFP-016", "WIL-016", "TRI-004") else \
        {"occupancy_type": "Tenant Occupied"} if rid == "HAR-071" else {}
    pd = dict(pd, **({"units_in_building": units} if units is not None else {}))
    assert out(rid, **pd) in ("NOTE", "N/A", "PASS")


@pytest.mark.parametrize("rid", ["SUR-005", "MER-008", "ALL-020", "HAR-033", "CHO-014"])
def test_a_townhome_is_not_asked(rid):
    got = rv.evaluate_row(M[rid], rv.facts(dict(HOUSE, dwelling_type="Townhome", units_in_building="5 or more")))[0]
    assert got in ("N/A", "PASS")


@pytest.mark.parametrize("rid", ["SAG-003", "TRI-004"])
def test_a_seasonal_home_must_be_single_family(rid):
    assert out(rid, occupancy_type="Seasonal", units_in_building="1") == "PASS"
    assert out(rid, occupancy_type="Seasonal", units_in_building="2") == "FAIL"
    assert out(rid, units_in_building="2") == "N/A"                       # an owner's primary home: not this row


@pytest.mark.parametrize("rid", ["ARA-011", "ARB-009"])
def test_ari_reads_a_two_unit_house_as_a_duplex(rid):
    assert out(rid, units_in_building="2") == "NOTE"                      # the Single Building confirm
    assert out(rid, units_in_building="1") == "N/A"


def test_the_hartford_rental_row():
    assert out("HAR-071", occupancy_type="Tenant Occupied", units_in_building="3-4") == "FAIL"
    assert out("HAR-071", occupancy_type="Tenant Occupied", units_in_building="2") == "PASS"
    assert out("HAR-071", units_in_building="3-4") == "N/A"                # an owner's home: HAR-033


def test_the_label_and_the_help_line():
    assert rv.FIELD_LABELS["units_in_building"] == "Units in the building"
    assert intake_fields.UNITS_CHOICES == ("", "1", "2", "3-4", "5 or more", "Unknown")
    assert intake_fields.DWELLING_TYPE_HELP == ("Renting an apartment? That's a renters (HO4) policy, not covered "
                                                "here. An owned apartment unit: choose Condo. A building with 5+ units "
                                                "is commercial.")
    src = open(os.path.join(HERE, "..", "app.py"), encoding="utf-8").read()
    assert "intake_fields.DWELLING_TYPE_HELP" in src and '"Units in the building"' in src
