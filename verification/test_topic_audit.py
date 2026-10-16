"""Round 37 follow-up (Liam, 2026-10-11): confirm items quoted rules from the wrong topic -- TWICO "Electrical"
showed the unconventional-construction rule, Progressive "business" the 2-horse limit, Travelers "Site and access"
the FireLine score, Liberty "Coverage A" the under-construction rule. A rule's topic is now the one whose words come
first (its subject), with a few deciding phrases; across the 4,443 rows of the four tables 689 moved topic. An item
quotes the rule that decides most often (a count before a dollar amount). Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import confirm_topics as ct  # noqa: E402
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval
RULES = ev._rules()


def topic(rid):
    r = RULES[rid]
    return ct.topic_of(r["Plain rule"], r["Topic"])


@pytest.mark.parametrize("rid,want", [
    # Liam's four
    ("TWI-032", "construction"),        # "Homes of unconventional construction ... Solar panels are handled ..."
    ("PRO-064", "animals"),             # "Saddle, hoofed or other farm animals are limited to 2 horses ..."
    ("TRV-098", "wildfire"),            # "... a Maximum FireLine score other than 0-30 must be referred ..."
    ("LIB-040", "under_construction"),  # "For a building under construction ..., Coverage A over $1 million ..."
    # the same mistakes, other phrasings
    ("TRV-095", "wildfire"), ("PRO-032", "construction"), ("NPD-060", "solar"), ("ORI-022", "solar"),
    ("SAG-033", "roof"), ("FDP-139", "roof"),                     # metal roofs "aluminum or tin" are roofs
    ("SUR-113", "fire_protection"), ("WIL-120", "fire_protection"), ("ARA-085", "fire_protection"),
    ("PRO-012", "ownership"), ("PDP-049", "ownership"),          # "in the name of a business, LLC ..."
    ("MER-089", "losses"), ("CHO-036", "losses"),                # "water damage claims" are losses
])
def test_a_rules_topic_is_its_subject(rid, want):
    assert topic(rid) == want


def test_the_topic_table():
    # CHANGED 2026-10-11 (round 37 follow-up): + "fire_protection" (the protection-class rows). Was: 33 topics.
    assert len(ct.TOPICS) == 34
    other = sum(1 for r in RULES.values() if ct.topic_of(r["Plain rule"], r["Topic"]) == "other")
    # CHANGED DELIBERATELY (round 39 step 1, 2026-10-14; Liam's decision 1, 2026-10-12): + HAR-044 (golf carts, NOT_ELIGIBILITY), HAR-069 (inspections, IGNORE_INSPECTION) and HAR-080 (SILENT):
    # never on a card. Was 256 (312 with the first-in-table rule, round 37).
    # CHANGED DELIBERATELY (round 40 step 2, 2026-10-16; Liam: the right NatGen Custom360 HO3 and Occidental HO3 guides, each with its table): + 6 rows of the two new tables that never decide (NC3-154 / 155 and
    # OCC-132 inspections, OCC-134 / 135 / 136 product notes); the applicant's age, a high-profile resident, structures
    # away and farm public activities got their topics (NCD-019 moves from other to applicant with NC3-015). Was 259.
    assert other == 264
    deciding = [r for r in RULES.values() if r["Carrier"] in ("The Hartford HO3", "NatGen Custom360 HO3",
                                                             "Sage Occidental HO3") and r["Tool handling"] in ev.DECIDING]
    assert deciding and not [r["Rule ID"] for r in deciding if ct.topic_of(r["Plain rule"], r["Topic"]) == "other"]


def _row(rid, rule, effect="DECLINES"):
    return {"row": rid, "category": "LOSS_HISTORY", "effect": effect, "rule": rule, "kind": "not_asked"}


@pytest.mark.parametrize("rows,quoted", [
    ([_row("X-1", "1 or more losses paying $15,000 or more within 5 years is ineligible."),
      _row("X-2", "3 or more claims within 5 years are ineligible.")], "3 or more claims within 5 years are ineligible"),
    ([_row("X-3", "A water loss over $25,000 in the last 3 years is ineligible.", "DECLINES"),
      _row("X-4", "2 or more losses in 5 years must be referred to underwriting.", "REFERS_TO_UW")],
     "2 or more losses in 5 years must be referred to underwriting"),
])
def test_an_item_quotes_the_rule_that_decides_most_often(rows, quoted):
    item = ct.card_items({"status": "ELIGIBLE", "confirm_items": rows})[0]
    assert item["text"].endswith("guide: " + quoted)
