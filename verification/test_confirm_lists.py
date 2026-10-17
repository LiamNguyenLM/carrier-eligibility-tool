"""Round 37 step 1 (Liam, 2026-10-10): each card's "Also confirm" row-ID dump becomes "Before you quote, confirm:"
-- at most 6 plain items, one per topic, declines first, then refers, then conditions, upkeep last; a number in
the guide's rule is kept; "+N more" and a collapsed "Rule IDs" line -- and the results open with "Things to
confirm with the client": the topics at least half of the Eligible and Refer cards ask (at most 8, with counts).
Zero API."""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cards  # noqa: E402
import confirm_topics as ct  # noqa: E402
import eligibility_check as ec  # noqa: E402

pytestmark = pytest.mark.retrieval
APP = os.path.join(os.path.dirname(__file__), "..", "app.py")


def row(rid, rule, effect="DECLINES", category="OTHER", kind="not_asked"):
    return {"row": rid, "category": category, "effect": effect, "rule": rule, "kind": kind}


ROWS = [
    row("XX-001", "Dwellings with existing damage are ineligible."),                                  # upkeep
    row("XX-002", "At most 1 Act of Nature claim in the past 5 years; 2 or more is ineligible.", category="LOSS_HISTORY"),
    row("XX-003", "Any fire or smoke claim within the previous 5 years needs prior underwriting approval.",
        "REFERS_TO_UW", "LOSS_HISTORY"),
    row("XX-004", "A prior mold loss is acceptable only with evidence of remediation.", "CONDITION", "LOSS_HISTORY"),
    # CHANGED 2026-10-11 (round 37 follow-up: a rule's topic is its subject): "Prior sinkhole claims" is a foundation / ground rule now; a plain loss rule instead
    row("XX-005", "Prior theft claims are ineligible.", category="LOSS_HISTORY"),
    row("XX-006", "Knob and tube wiring is ineligible.", category="ELECTRICAL"),
    row("XX-007", "Federal Pacific or Zinsco panels are ineligible.", category="ELECTRICAL"),
    row("XX-008", "Trampolines are ineligible."),
    row("XX-009", "Homes on more than 10 acres must be referred to underwriting.", "REFERS_TO_UW", "ACREAGE"),
    row("XX-010", "Dwellings with more than 2 mortgages are ineligible."),
    row("XX-011", "Water heaters older than 12 years are ineligible."),                                 # upkeep
    row("XX-012", "Historic Registry properties are ineligible."),
    row("XX-013", "Homes must be well maintained.", "CONDITION", kind="standard"),                     # upkeep
    row("XX-014", "Homes with a business on premises are ineligible."),
    row("XX-015", "Wood stoves as primary heat are ineligible.", category="OTHER_SYSTEMS"),
]


def rec(rows=ROWS, status="ELIGIBLE", notes=""):
    return {"carrier": "Allied_Trust_HO3", "status": status, "reasons": ["x"], "citations": [], "notes": notes,
            "confirm_items": [dict(r) for r in rows], "rules_table": True}


def test_at_most_six_show_and_the_rest_are_under_more():
    shown, more, ids = ct.card_list(rec())
    assert len(shown) == ct.CARD_MAX == 6
    assert len(shown) + len(more) == len({ct.topic_of(r["rule"], r["category"]) for r in ROWS})
    assert ids == sorted(r["row"] for r in ROWS)
    html = cards.confirm_html(rec())
    assert html.startswith("<p><b>Before you quote, confirm:</b></p>")
    assert f"<summary>+{len(more)} more</summary>" in html
    # (round 37 step 2: the row IDs moved to the card's own collapsed line)
    assert "<summary>Rule IDs</summary>" not in html
    assert cards.rule_ids_html(rec()) == ("<details><summary>Rule IDs</summary><small>"
                                         + ", ".join(sorted(r["row"] for r in ROWS)) + "</small></details>")
    assert html.count("<li>") == len(shown) + len(more)


def test_declines_come_first_then_refers_then_conditions_and_upkeep_last():
    items = ct.card_items(rec())
    rank = [ct.EFFECT_RANK.get(i["effect"], 3) for i in items if not ct.TOPICS.get(i["key"], ("", (), False))[2]]
    assert rank == sorted(rank)
    keys = [i["key"] for i in items]
    assert keys.index("acreage") > keys.index("electrical")          # a refer after the declines
    assert keys[-2:] == ["upkeep", "water_heater"] or set(keys[-2:]) == {"upkeep", "water_heater"}
    shown, _, _ = ct.card_list(rec())
    assert not {"upkeep", "water_heater"} & {i["key"] for i in shown}   # upkeep is dropped first


@pytest.mark.parametrize("topic,rows", [
    ("losses", ["XX-002", "XX-003", "XX-004", "XX-005"]),               # four loss rows, one item
    ("electrical", ["XX-006", "XX-007"]),                               # wiring and panels, one item
])
def test_rows_on_one_topic_merge_into_one_item(topic, rows):
    items = [i for i in ct.card_items(rec()) if i["key"] == topic]
    assert len(items) == 1 and items[0]["rows"] == rows and items[0]["count"] == len(rows)
    assert items[0]["effect"] == "DECLINES"                               # the strongest of its rows


@pytest.mark.parametrize("rule,kept", [
    ("At most 1 Act of Nature claim in the past 5 years; 2 or more is ineligible.",
     "guide: At most 1 Act of Nature claim in the past 5 years"),
    ("No more than 2 losses in 3 years are accepted.", "guide: No more than 2 losses in 3 years are accepted"),
])
def test_where_a_number_decides_the_guides_own_rule_is_kept(rule, kept):
    item = ct.card_items(rec([row("XX-100", rule, category="LOSS_HISTORY")]))[0]
    assert item["text"] == ct.TOPICS["losses"][0] + " — " + kept


def test_without_a_number_the_item_is_just_the_question():
    item = ct.card_items(rec([row("XX-101", "Trampolines are ineligible.")]))[0]
    assert item["text"] == ct.TOPICS["liability_hazards"][0]


def test_a_blank_field_note_names_its_places():
    r = row("PRO-072", "New business is not accepted in Hidalgo or Webb county.", category="LOCATION", kind="blank")
    item = ct.card_items(rec([r]))[0]
    assert item["key"] == "county" and "Hidalgo or Webb" in item["text"]


def test_the_model_paths_confirm_notes_are_items_too():
    notes = ("FPC 3 is fine. Confirm (not asked by the form; never a hold): Insurance score; Coverage C amount. "
             "Confirm (left blank on the form; for this carrier a blank answer is never a hold): County.")
    keys = {i["key"] for i in ct.card_items({"status": "ELIGIBLE", "notes": notes})}
    assert keys == {"insurance_score", "other_coverages", "county"}


def test_no_confirm_rows_no_list():
    assert ct.card_list({"status": "ELIGIBLE"}) == ([], [], [])
    assert cards.confirm_html({"status": "ELIGIBLE"}) == ""


def test_the_also_confirm_dump_is_gone_from_details():
    r = dict(rec(), also_confirm=["Also confirm (not asked by the form; never a hold): ACREAGE: ALL-157."])
    assert "Also confirm" not in cards.details_html(r, guide=True)


# ---------------------------------------------------------------- the top box

def _card(status, rules):
    return rec([row(f"XX-{i:03d}", t) for i, t in enumerate(rules)], status=status)


LOSS, WIRE, POOL, ACRE = ("2 losses in 3 years are ineligible.", "Knob and tube wiring is ineligible.",
                          "Diving boards are ineligible.", "Homes on over 5 acres are ineligible.")


def test_the_top_box_counts_the_eligible_and_refer_cards_only():
    results = [_card("ELIGIBLE", [LOSS, WIRE, POOL]), _card("ELIGIBLE", [LOSS, WIRE]), _card("REFER", [LOSS, ACRE]),
               _card("ELIGIBLE", [LOSS]), _card("INELIGIBLE", [POOL, ACRE]),
               _card("INSUFFICIENT_INFORMATION", [POOL, ACRE])]
    box = ct.top_box(results)
    # of 4 Eligible / Refer cards: losses 4, wiring 2 (half counts), pool 1 and acreage 1 (under half)
    assert box == [(ct.TOPICS["losses"][0], 4, 4), (ct.TOPICS["electrical"][0], 2, 4)]


def test_the_top_box_keeps_at_most_eight():
    rules = ["2 losses in 3 years are ineligible.", "Knob and tube wiring is ineligible.", "Diving boards are ineligible.",
             "Homes on over 5 acres are ineligible.", "Trampolines are ineligible.", "Historic homes are ineligible.",
             "Wood stoves are ineligible.", "More than 2 mortgages are ineligible.", "Brush fire areas are ineligible.",
             "Homes in a flood zone need a flood policy."]
    box = ct.top_box([_card("ELIGIBLE", rules), _card("REFER", rules)])
    assert len(box) == ct.TOP_MAX == 8 and all(n == 2 and of == 2 for _, n, of in box)


def test_the_topic_table():
    # CHANGED 2026-10-11 (round 37 follow-up: a rule's topic is its subject): + fire_protection. Was: 33.
    # CHANGED DELIBERATELY (round 41 A5, 2026-10-17; Liam: the split classes 1X-8X, a confirm where a guide does not
    # rate them): + "split_class". Was 34.
    assert len(ct.TOPICS) == 35 and all(q.endswith("?") or "?" in q for q, _, _ in ct.TOPICS.values())
    assert set(ct.CATEGORY_TOPIC.values()) <= set(ct.TOPICS)


# ---------------------------------------------------------------- the page

def test_the_page_shows_the_box_and_each_cards_list(monkeypatch):
    from streamlit.testing.v1 import AppTest
    results = [dict(_card("ELIGIBLE", [LOSS, WIRE, POOL]), carrier="Allied_Trust_HO3"),
               dict(_card("REFER", [LOSS, WIRE]), carrier="Progressive_HO3_-_04.01.2026")]
    monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: [dict(r) for r in results])
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    at.selectbox(key="dwelling_type").select("House").run()
    at.button(key="submit").click().run()
    assert not at.exception
    md = [m.value for m in at.markdown]
    box = next(m for m in md if m.startswith("#### Things to confirm with the client"))
    assert f"{ct.TOPICS['losses'][0]} — asked by 2 of 2 carriers" in box
    lists = [m for m in md if "Before you quote, confirm:" in m]
    assert len(lists) == 2 and not any("Also confirm" in m for m in md)
    assert not any(re.search(r"XX-\d{3}", m.split("<summary>Rule IDs</summary>")[0]) for m in lists)


def test_the_warm_up_classifies_every_rule_so_the_first_page_is_fast():
    # round 37 step 5: building the confirm lists took 1-2.5 s per page on Liam's profile; topic_of is cached
    # and the app-start warm-up fills it
    import rules_evaluator
    ct.topic_of.cache_clear()
    ec.warm_up()
    pairs = {(r["Plain rule"], r["Topic"]) for r in rules_evaluator._rules().values()}
    assert ct.topic_of.cache_info().currsize >= len(pairs) > 1000
