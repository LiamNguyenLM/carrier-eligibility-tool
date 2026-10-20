"""Round 41 B7 (Liam, 2026-10-17): on his 2026-10-16 run the Chubb card under Insufficient Information showed only an
empty bullet. agent_text takes the row IDs out of a line, and a line that was only IDs ("(rows CHU-043, CHU-044)") or a
label with an ID ("Chubb territory -- [CHU-043]") read "" or "Chubb territory:"; the Missing list and Details dropped
blank lines only before agent_text. Now no card renders an empty first line, reason or list item (cards.shown_items,
cards.says_something), and the deep checks hold it (verification/fuzz/checks.c8_page, new_guides_deep). Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fuzz"))
import cards  # noqa: E402

pytestmark = pytest.mark.retrieval
HELD = {"carrier": "CHUBB_HO_-_05.22.2026", "status": "INSUFFICIENT_INFORMATION", "flaw_count": 0,
        "reasons": ["Chubb restricts all of Harris County; the form can't tell which area."], "citations": [],
        "notes": ""}


@pytest.mark.parametrize("item", ["(rows CHU-043, CHU-044)", "[CHU-043]", "CHU-043", " -- [CHU-043] ", "", "   "])
def test_a_missing_item_that_is_only_row_ids_is_not_shown(item):
    assert cards.shown_items([item, "Coverage A amount"]) == ["Coverage A amount"]


@pytest.mark.parametrize("item,shown", [("Chubb territory -- [CHU-043] Primary houses in Harris 1A are unacceptable.",
                                         "Chubb territory: Primary houses in Harris 1A are unacceptable."),
                                        ("Distance to fire station", "Distance to fire station")])
def test_a_real_item_is_shown_as_agent_text(item, shown):
    assert cards.shown_items([item]) == [shown]


@pytest.mark.parametrize("missing", [["(rows CHU-043, CHU-044)"], ["Chubb territory -- [CHU-043]", "[CHU-044]"]])
def test_the_held_chubb_card_renders_no_empty_line(missing):
    import checks
    rec = dict(HELD, missing_info=missing)
    assert checks._empty_items(rec, {}, None, rec["carrier"]) == []
    assert "Missing" not in [h for h, _ in cards.details_items(rec)]


@pytest.mark.parametrize("reason", ["[CHU-043]", "(rows CHU-043, CHU-044)"])
def test_a_first_line_that_is_only_ids_reads_the_status(reason):
    line = cards.first_line_markdown(dict(HELD, reasons=[reason], missing_info=[]), {}, None, label=False)
    assert cards.says_something(line) and "CHU-" not in line


def test_the_page_renders_missing_through_shown_items():
    src = open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8").read()
    assert "cards.missing_lines(carrier.get(\"missing_info\"))" in src


# Round 41, the final live check: a code-held card's Missing list in the form's words, not the engine's
@pytest.mark.parametrize("items,want", [
    (["station distance if not given; visibility, alarm, access, fire losses -- [SAG-076] Protection class 4-8 ...",
      "station distance if not given -- [SAG-078] Homes in the higher-risk rows must be less than 25 years old."],
     ["Driving distance to fire station", "Where the guide's table applies: visibility, alarm, access, fire losses"]),
    (["hydrant within 1,000 ft if not given; visibility, alarm, access -- [ODP-112] With FPC 4-10 ...",
      "visibility, alarm, access -- [ODP-113] With FPC 4-8 ...", "hydrant within 1,000 ft if not given; fire losses "
      "-- [ODP-115] For the FPC 4-10 ..."],
     ["Hydrant within 1,000 ft", "Where the guide's table applies: visibility, alarm, access, fire losses"]),
    # a row open only on a fact the form never asks keeps its own words (the fast tier: Chubb's 1A / 1B-1E lines)
    (["Chubb territory -- [CHU-043] Primary houses in Harris County 1A are unacceptable.",
      "Chubb territory -- [CHU-044] Primary houses in Harris County 1B, 1C and 1E must be pre-approved."],
     ["Chubb territory: Primary houses in Harris County 1A are unacceptable.",
      "Chubb territory: Primary houses in Harris County 1B, 1C and 1E must be pre-approved."]),
    (["Distance to fire station", "(rows CHU-043, CHU-044)"], ["Distance to fire station"]),
])
def test_a_code_held_cards_missing_list_is_in_the_forms_words(items, want):
    assert cards.missing_lines(items) == want
