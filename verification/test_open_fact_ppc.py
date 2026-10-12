"""Round 38 step 7, finding F14 (self-audit check 11, 2026-10-11): Sage Occidental DP3 held a tenant home with PPC
N/A and the fire station 5.9 miles away, saying "needs to know ... and station distance" -- the distance was entered;
what ODP-116 ("FPC 9 or higher with a fire station more than 5 driving miles away is ineligible") lacked was the PPC.
A row's open-fact label is fixed in the map ("station distance"); it now drops once the distance is given, and an
unknown PPC is named. Every row whose label is a bare "station distance" is checked. Zero API."""
import csv
import glob
import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval


def _rows():
    out = {}
    for f in glob.glob(os.path.join(ROOT, "rules_data", "*field_map.csv")):
        with open(f, encoding="utf-8-sig") as fh:
            out.update({m["row_id"]: m for m in csv.DictReader(l for l in fh if not l.startswith("#"))
                        if m["open_fact"] == "station distance"})
    return out


ROWS = _rows()
PROFILE = {"ppc": "N/A", "fire_station_miles": 5.9, "hydrant_1000ft": "Yes", "occupancy_type": "Tenant Occupied",
           "ownership_type": "Individual Owner", "year_built": 2006, "roof_age": 5, "dwelling_type": "House",
           "county": "Madison"}


def test_the_bare_station_distance_rows_are_the_fire_tables():
    assert {"ODP-116", "SDP-083", "SUR-115", "SFP-123", "WIL-120", "TRI-092"} <= set(ROWS)


@pytest.mark.parametrize("rid", sorted(ROWS))
def test_an_entered_distance_is_never_the_open_fact(rid):
    outcome, detail = rv.evaluate_row(ROWS[rid], rv.facts(dict(PROFILE)))
    if outcome in ("OPEN", "NOTE"):
        assert "station distance" not in detail and "protection class (PPC)" in detail, (rid, detail)


@pytest.mark.parametrize("rid", sorted(ROWS))
def test_a_blank_distance_is_still_asked(rid):
    outcome, detail = rv.evaluate_row(ROWS[rid], rv.facts(dict(PROFILE, ppc="10", fire_station_miles=None)))
    if outcome in ("OPEN", "NOTE"):
        assert "station distance" in detail, (rid, detail)


def test_liams_shape_of_the_occidental_card():
    outcomes = rv.evaluate_carrier("Sage_-_Occidental_DP3", dict(PROFILE))
    reason = rv.held_reason(outcomes, [r for r, (o, _) in outcomes.items() if o == "OPEN"])
    assert "station distance" not in reason and "the protection class (PPC)" in reason, reason


@pytest.mark.parametrize("open_fact,unknown,expected", [
    ("station distance", ["ppc_num"], "the protection class (PPC)"),
    ("station distance", ["fire_station_miles", "ppc_num"], "station distance; the protection class (PPC)"),
    ("station distance", ["fire_station_miles"], "station distance"),
    ("station / hydrant distance if not given; visibility, alarm, access", ["hydrant_1000ft"],
     "hydrant within 1,000 ft if not given; visibility, alarm, access"),
    ("protection class; roof", ["ppc_num"], "protection class; roof"),
])
def test_the_open_fact_names_what_is_open(open_fact, unknown, expected):
    assert rv._open_fact_now(open_fact, unknown) == expected
