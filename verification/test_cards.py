"""Round 26 step 3 (Liam, 2026-10-05, decision C): compact cards. Zero API."""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cards  # noqa: E402
import eligibility_check as ec  # noqa: E402
from profiles import LIVE_PROFILE, LIVE_CHECKED  # noqa: E402

pytestmark = pytest.mark.retrieval


def test_an_eligible_card_on_live_is_one_line_of_checked_facts():
    rec = {"status": "ELIGIBLE", "reasons": ["PVC plumbing is not excluded."], "citations": [], "notes": ""}
    line = cards.verdict_line(rec, LIVE_PROFILE, LIVE_CHECKED)
    age = date.today().year - 2007
    assert line == f"No issue on: PPC 3, age {age}, PVC, no pool, solar panels, Collin County"
    # unchecked topics (roof age / type, construction ...) are not claimed
    assert "Composition" not in line and "roof" not in line and "Frame" not in line
    # the model's reason is still there, collapsed
    assert "PVC plumbing is not excluded." in cards.details_html(rec)


def test_with_everything_checked_the_eligible_line_names_every_fact():
    line = cards.verdict_line({"status": "ELIGIBLE"}, LIVE_PROFILE, None)
    assert "roof 10 yrs" in line and "Composition Shingle" in line and "Frame" in line


@pytest.mark.parametrize("status,label", [("INELIGIBLE", "Not eligible"), ("REFER", "Refer to underwriting"),
                                          ("INSUFFICIENT_INFORMATION", "Insufficient information")])
def test_other_cards_lead_with_the_status_and_the_first_reason(status, label):
    rec = {"status": status, "reasons": ["Collin County is outside the territory.", "second"],
           "citations": ['X: "quote"'], "notes": "one sentence."}
    assert cards.first_line_markdown(rec, LIVE_PROFILE, LIVE_CHECKED) == \
        f"**{label}** — Collin County is outside the territory."
    d = cards.details_html(rec)
    assert d.startswith("<details><summary>Details</summary>")
    assert "second" in d and '"quote"' in d and "one sentence." in d
    assert "Collin County is outside" not in d                     # not repeated


def test_no_details_toggle_when_there_is_nothing_more():
    assert cards.details_html({"status": "INELIGIBLE", "reasons": ["only"], "citations": [], "notes": ""}) == ""


def test_details_escape_markup_but_keep_quote_marks():
    d = cards.details_html({"status": "REFER", "reasons": ["a", "<b>x</b>"], "citations": [], "notes": ""})
    assert "&lt;b&gt;x&lt;/b&gt;" in d and "<b>x</b>" not in d


def test_the_schema_caps_reasons_and_citations_at_two():
    items = ec.CARRIER_RESULTS_SCHEMA["properties"]["carriers"]["items"]["properties"]
    assert items["reasons"]["maxItems"] == 2 and items["citations"]["maxItems"] == 2


def test_the_prompt_asks_for_compact_output():
    s = ec.SYSTEM_INSTRUCTIONS
    assert "at most 2 items, each at most 20 words" in s
    assert "Never restate a fact that passes" in s
    assert "short noun phrases" in s
    assert "2 to 4 analysis points" not in s
