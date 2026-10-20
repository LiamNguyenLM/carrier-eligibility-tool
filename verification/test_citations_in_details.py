"""Round 41 A9 (Liam, 2026-10-17: "The Occidental card shows a 'Citations' section; other cards keep the citation in
Details. Make it match."). Checked 2026-10-17 on the rendered page (app.py through Streamlit's AppTest, and the card
helpers app.py calls): every card's citations are inside the collapsed Details block, under the same "Citations"
heading -- the Occidental HO3 held card, a NatGen code decline, a model-path card -- and never in the first line, the
Missing list or the confirm list. The round 40 report's pasted cards had dropped the "Details" line, so the
Occidental card's "Citations:" read as its own section. This keeps every card the same. Zero API."""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cards  # noqa: E402

pytestmark = pytest.mark.retrieval
QUOTE = 'p.10: "FPC is 4 – 8, and"'
RECS = [
    {"carrier": "Sage_-_Occidental_HO3_-_12.02.2025", "status": "INSUFFICIENT_INFORMATION", "flaw_count": 0,
     "reasons": ["Held: if the fire station is more than 5 miles away ... Confirm the distance."],
     "citations": [f"Sage_-_Occidental_HO3_-_12.02.2025: [OCC-096] {QUOTE}"],
     "missing_info": ["Driving distance to fire station"], "notes": ""},
    {"carrier": "NatGen_Custom360_HO3_-_09.02.2026", "status": "INELIGIBLE", "flaw_count": 1,
     "reasons": ['[NC3-008] declines: Owner: Estate — At new business, an "Estate of" may not be the named insured.'],
     "citations": ['NatGen_Custom360_HO3_-_09.02.2026: [NC3-008] p.3: "is a legal term and should not be listed"'],
     "missing_info": [], "notes": "", "decided_by_code": True},
]


@pytest.mark.parametrize("rec", RECS, ids=["Occidental held", "NatGen decline"])
def test_a_cards_citations_are_inside_details_under_one_heading(rec):
    details = cards.details_html(rec, guide=True)
    assert details.startswith("<details><summary>Details</summary>")
    body = details.split("<summary>Details</summary>", 1)[1]
    assert "<p><b>Citations</b></p>" in body
    shown_outside = cards.first_line_markdown(rec, {}, None, label=False) + " ".join(cards.shown_items(
        rec.get("missing_info"))) + cards.confirm_html(rec, {}, None)
    assert "Citations" not in shown_outside and not re.search(r'p\.\d+: "', shown_outside)


def test_the_citations_heading_is_the_same_on_every_card():
    heads = [[h for h, _ in cards.details_items(r, guide=True)] for r in RECS]
    assert all("Citations" in h and h.index("Citations") <= 1 for h in heads)
