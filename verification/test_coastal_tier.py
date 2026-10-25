"""Round 35 step 1 (Claude's map audit, 2026-10-09): every coastal tier value the form can send reaches
the map lines that name it. app.py sends the "Tier N" prefix; facts() now reduces the full label to it
too, so a caller that passes "Tier 1 - Closest to coast" is never N/A on wording. Zero API."""
import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval
LABELS = {"Tier 1 - Closest to coast": "Tier 1", "Tier 2 - Moderate coastal area": "Tier 2",
          "Tier 3 - Outer coastal zone": "Tier 3", "Not Coastal": None}
BASE = {"year_built": 1990, "dwelling_amount": 2000000, "occupancy_type": "Owner Occupied", "dwelling_type": "House"}
COASTAL = sorted(rid for rid, m in ev._map().items() if "coastal_tier" in m["field"])


def test_the_form_labels_are_the_app_s_options():
    # CHANGED (round 43 step 2, Liam 2026-10-24: one form for app.py and the web page -- the choices live in
    # engine/form.py and app.py reads them from there). Was: each label written in app.py's source.
    from engine import form
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    assert "list(engine_form.COASTAL_CHOICES)" in src
    assert set(LABELS) == set(form.COASTAL_CHOICES)
    assert {c.split(" - ")[0] for c in form.COASTAL_CHOICES} == {v or "Not Coastal" for v in LABELS.values()}


def test_the_28_coastal_lines():
    # CHANGED DELIBERATELY (round 39 step 1, 2026-10-14; Liam's decision 1, 2026-10-12): + HAR-052, The Hartford's 2,000-ft / barrier-island confirm. Was 27.
    # CHANGED DELIBERATELY (round 40 step 2, 2026-10-16; Liam: the right NatGen Custom360 HO3 and Occidental HO3 guides, each with its table): + OCC-006..012 (the Extreme Hazard rows, the TWIA override in each) and OCC-019
    # (wave wash). Was 28.
    # CHANGED DELIBERATELY (round 41 A8, 2026-10-17; Liam: the seventh Extreme Hazard bullet, OCC-138). Was 36.
    assert len(COASTAL) == 37 and "HAR-052" in COASTAL and "OCC-138" in COASTAL
    assert {"OCC-006", "OCC-007", "OCC-008", "OCC-009", "OCC-010", "OCC-011", "OCC-012", "OCC-019"} <= set(COASTAL)
    assert {"ARA-024", "TWI-044", "TRV-080", "TRV-083", "CDP-051", "PDP-014", "PH6-044", "SAG-088", "SAG-089",
            "MER-061", "PRO-073", "PRO-087", "SUR-161", "SUR-165", "SFP-169", "SFP-175", "TRI-100"} <= set(COASTAL)


@pytest.mark.parametrize("label", list(LABELS))
@pytest.mark.parametrize("prefix_only", [False, True])
def test_every_form_value_hits_the_lines_that_name_its_tier(label, prefix_only):
    tier = LABELS[label]
    value = tier if (prefix_only and tier) else label
    for rid in COASTAL:
        m = ev._map()[rid]
        # round 39: a line that also reads the county (HAR-052: the form's Tier 1 OR the guide's Tier I counties) is
        # checked on an inland county, so only its tier decides
        f = ev.facts(dict(BASE, coastal_tier=value, **({"county": "Travis"} if "county in" in m["gate"] else {})))
        # CHANGED 2026-10-17 (round 41 B2, Liam: HAR-052 also for Jackson and Orange in a coastal tier): a tier named
        # only inside "(county in {...} and ...)" is that county's, not every home's. Was: every tier in the gate.
        named = set(re.findall(r"Tier \d", re.sub(r"\(county in \{[^}]*\} and [^)]*\)", "", m["gate"])))
        out = ev.evaluate_row(m, f)[0]
        assert (out != "N/A") == (tier in named), (rid, value, m["gate"], out)


@pytest.mark.parametrize("rid", ["SAG-089", "SUR-163", "SFP-172"])
def test_the_tier_1_county_three_mile_band_reaches_the_form_s_tier_3(rid):
    # "Within 3 miles of the designated primary shoreline in a tier 1 county": the guide's tier is the
    # county's, so a home 2-3 miles out can be the form's Tier 3 (round 35 step 1)
    m = ev._map()[rid]
    assert ev.evaluate_row(m, ev.facts(dict(BASE, coastal_tier="Tier 3 - Outer coastal zone")))[0] != "N/A"


@pytest.mark.parametrize("yb,want", [(1999, "NOTE"), (2000, "PASS")])   # 1999: a confirm note (round 30)
def test_trv_082_decides_on_year_built_from_the_full_label(yb, want):
    f = ev.facts(dict(BASE, coastal_tier="Tier 2 - Moderate coastal area", year_built=yb))
    assert ev.evaluate_row(ev._map()["TRV-082"], f)[0] == want
