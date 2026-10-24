"""Round 42 step 0a (Liam, 2026-10-24): WIL-123 (Wilshire HO3, "No prior fire losses" in the fire-protection table)
stays a decline -- Round 31's rule: a requirement the form shows unmet declines unless the row's own guide text names an
underwriting, referral or approval path. The guide (Sage_-_Wilshire_HO3_-_12.02.2025, p.10, its FPC 4-10 / FPC 4-8
cell): "Risk is eligible only if all of the following criteria are met: ... Age of Home must be less than 25 years,
and Primary occupancy dwellings only, and No rental exposures allowed, and No prior fire losses." No path is named in
the cell (the page's "This list is not all inclusive. If any questions, please check with your underwriter." is the
table's general footer, as in SURE's and Occidental's, whose same cells decline). Zero API: the stored guide text."""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import guides  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
CELL_START = "Risk is eligible only if all of the following"
CELL_END = "Risk is ineligible."


def _cell(carrier):
    """The FPC 4-10 / 4-8 cell: from its "eligible only if all of the following" to the next row's "ineligible"."""
    t = " ".join(guides.guide_text(carrier).split())
    end = t.find("No prior fire losses")
    start = t.rfind(CELL_START, 0, end)
    stop = t.find(CELL_END, end)
    assert -1 not in (end, start, stop), carrier
    return t[start:stop]


@pytest.mark.parametrize("carrier", ["Sage_-_Wilshire_HO3_-_12.02.2025", "Sage_-_SURE_HO-3_-_01.31.2026",
                                     "Sage_-_Occidental_HO3_-_12.02.2025"])
def test_the_fire_loss_cell_names_no_underwriting_path(carrier):
    cell = _cell(carrier)
    assert "No prior fire losses" in cell and "Age of Home must be less than 25" in cell
    assert not re.search(r"(?i)\brefer|underwrit|approv|exception", cell), cell


def test_wil_123_stays_a_decline_with_its_siblings():
    m = rv._map()
    assert [m[r]["outcome_if_fail"] for r in ("WIL-121", "WIL-122", "WIL-123")] == ["DECLINES"] * 3
    assert "WIL-123" in rv.HOLD_BY_DECISION
