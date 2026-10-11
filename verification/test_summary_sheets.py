"""Round 37 follow-up (Liam, 2026-10-11): cards built from a summary-only guide (HOAIC's rate sheets, TWICO's and
Swyfft's quick-reference guides) showed little or no confirm list; each now says "We have only this carrier's
summary sheet; confirm details with underwriting." Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cards  # noqa: E402
import display_names  # noqa: E402
import eligibility_check as ec  # noqa: E402

pytestmark = pytest.mark.retrieval
LINE = "We have only this carrier's summary sheet; confirm details with underwriting."


def test_the_set_is_every_guide_of_four_pages_or_fewer():
    raw = ec.get_vectorstore()._collection.get(include=["metadatas"])
    pages = {}
    for m in raw["metadatas"]:
        pages.setdefault(m.get("carrier"), set()).add(m.get("page"))
    short = {c for c, p in pages.items() if c and len(p) <= 4}
    assert short == set(display_names.SUMMARY_SHEETS)
    assert display_names.SUMMARY_SHEET_LINE == LINE


@pytest.mark.parametrize("program", ["HOAIC_-_TX-HOMEOWNERS-0326_HO3", "TWICO_HO3"])
def test_a_summary_sheet_card_says_so_with_or_without_a_list(program):
    bare = {"carrier": program, "status": "ELIGIBLE"}
    assert cards.confirm_html(bare) == f"<p><i>{LINE}</i></p>"
    listed = dict(bare, confirm_items=[{"row": "TWI-001", "category": "OTHER", "effect": "DECLINES",
                                        "rule": "Trampolines are ineligible.", "kind": "not_asked"}])
    html = cards.confirm_html(listed)
    assert html.startswith(f"<p><i>{LINE}</i></p><p><b>Before you quote, confirm:</b></p>")


@pytest.mark.parametrize("program", ["Allied_Trust_HO3", "Progressive_HO3_-_04.01.2026"])
def test_a_full_guide_card_does_not(program):
    assert cards.confirm_html({"carrier": program, "status": "ELIGIBLE"}) == ""
