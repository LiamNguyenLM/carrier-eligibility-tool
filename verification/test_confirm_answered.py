"""Round 38 step 2 (Liam, 2026-10-11): confirm items must not contradict the form. On LANDLORD the top box asked
"Owned by individuals (not an LLC, corporation, trust or estate)?" (6 of 7 carriers) though he entered LLC, and cards
asked "Any losses or claims in the last 5 years? (how many, what type, when)" though he had answered all of it. Each
topic now records the form fields it covers; answered, the item asks only what is still open, worded from the
answer, and it is dropped when nothing is left. Every topic x every answer for ownership, occupancy, losses,
electrical, pool, dogs, roof, plumbing and solar is checked here. Zero API."""
import itertools
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import cards  # noqa: E402
import confirm_topics as ct  # noqa: E402
import eligibility_check as ec  # noqa: E402
import intake_fields  # noqa: E402
from test_held_reasons import LANDLORD  # noqa: E402

pytestmark = pytest.mark.retrieval

# one card's confirm rows: a real-looking rule per topic (amperage, spa and "updated" wording included, so the parts
# that can stay open are reachable)
RULES = {
    "ownership": "Properties owned by an LLC, corporation or trust are ineligible unless titled to the applicant.",
    "occupancy": "Short-term rentals, roomers and boarders are ineligible.",
    "losses": "2 or more losses in the last 3 years are ineligible.",
    "electrical": "Homes with fuses, knob-and-tube or aluminum wiring are ineligible; 100 amp service minimum "
                  "unless updated.",
    "pool": "Pools must have a 4 ft fence with a self-latching, locking gate; diving boards, slides and hot tubs "
            "are ineligible.",
    "animals": "Dogs with a bite history, livestock and exotic animals are ineligible.",
    "roof": "Roofs must be in good condition with one layer and at least 5 years of life left.",
    "plumbing": "Polybutylene plumbing is ineligible; leaking pipes must be repaired.",
    "solar": "Solar panels must be professionally installed and permitted.",
}


def rec(keys=RULES, status="ELIGIBLE"):
    return {"carrier": "X", "status": status, "confirm_items": [
        {"row": f"XX-{i:03d}", "category": "", "effect": "DECLINES", "rule": RULES[k], "kind": "not_asked"}
        for i, k in enumerate(keys)]}


def test_every_sample_rule_lands_in_its_topic():
    assert {k: ct.topic_of(r) for k, r in RULES.items()} == {k: k for k in RULES}


def asks(pd, checked=None, keys=RULES):
    """{topic: the question (without the guide's rule)} the card prints, and the top box's lines."""
    items = {it["key"]: it["ask"] for it in ct.card_items(rec(keys), pd, checked)}
    box = [text for text, _, _ in ct.top_box([rec(keys), rec(keys, "REFER")], pd, checked)]
    return items, box


# ---------------------------------------------------------------- the answers

OWNERSHIP = [dict(ownership_type=o) for o in intake_fields.OWNERSHIP_TYPES if o != "Trust"] + \
            [dict(ownership_type="Trust", trust_type=t) for t in intake_fields.TRUST_TYPES]
OCCUPANCY = [dict(occupancy_type=o) for o in ("Owner Occupied", "Tenant Occupied", "Seasonal", "Vacant",
                                              "Secondary Home")]
LOSSES = [dict(losses_5yr="0")] + [
    {k: v for k, v in dict(losses_5yr=n, loss_types=t, loss_year=y, losses_3yr=n3).items() if v not in (None, [])}
    for n, t, y, n3 in itertools.product(("1", "2", "3 or more"), ([], ["Theft"], ["Water", "Wind or hail"]),
                                         (None, 2022, 2025), ("", "0", "1"))]
ELECTRICAL = [dict(electrical=list(c)) for n in (1, 2) for c in itertools.combinations(
    [x for x in intake_fields.ELECTRICAL_CHOICES if x != "Unknown"], n)]
POOLS = ("No Pool", "Above Ground - Fenced", "Above Ground - Unfenced", "In Ground - Fenced", "In Ground - Unfenced")
POOL = [dict(swimming_pool="No Pool", pool_accessories="None")] + [
    dict(swimming_pool=p, pool_accessories=a, pool_fence_4ft=f, pool_gate_locking=g)
    for p, a, f, g in itertools.product(POOLS[1:], ("None", "Slide only", "Diving board only",
                                                    "Both slide and diving board"), (False, True), (False, True))
    if p in intake_fields.FENCED_POOL_VALUES or not (f or g)]
DOGS = [dict(has_dogs="No", dog_breeds=[])] + [dict(has_dogs="Yes", dog_breeds=b) for b in
                                                ([], ["Pit Bull"], [intake_fields.DOG_NONE], [intake_fields.DOG_UNSURE],
                                                 ["Pit Bull", "Rottweiler"])]
ROOF = [dict(roof_age=a) for a in (0, 9, 17, 30)]
PLUMBING = [dict(plumbing_type=p) for p in intake_fields.PLUMBING_TYPES if p != "Unknown"]
SOLAR = [dict(solar_panels="No")] + [dict(solar_panels="Yes", solar_type=t, solar_tesla=s)
                                     for t in intake_fields.SOLAR_TYPES[1:] for s in intake_fields.TESLA_CHOICES]
GRID = [("ownership", a) for a in OWNERSHIP] + [("occupancy", a) for a in OCCUPANCY] + \
       [("losses", a) for a in LOSSES] + [("electrical", a) for a in ELECTRICAL] + [("pool", a) for a in POOL] + \
       [("animals", a) for a in DOGS] + [("roof", a) for a in ROOF] + [("plumbing", a) for a in PLUMBING] + \
       [("solar", a) for a in SOLAR]
# what an answered field must never be asked again by (lower-case, in the question, never in the guide's rule)
REASKED = {
    "ownership": [r"owned by individuals", r"not an llc"],
    "occupancy": [r"^occupancy: no short-term rental, roomers, students or vacancy\?$"],
    "losses": [r"any losses or claims", r"how many, what type, when"],
    "electrical": [r"breakers \(no fuses\)", r"no federal pacific", r"no knob-and-tube", r"aluminum wiring\?"],
    "pool": [r"pool or spa details", r"diving board", r"\bslide\b"],
    "animals": [r"a dog with a bite history"],
    "roof": [r"enough life left"],
    "plumbing": [r"material and condition", r"no polybutylene"],
    "solar": [r"how and where installed"],
}


def _id(case):
    key, a = case
    return key + ":" + json.dumps(a, sort_keys=True)


@pytest.mark.parametrize("case", GRID, ids=[_id(c) for c in GRID])
def test_no_item_or_box_line_reasks_an_answered_field(case):
    key, answer = case
    items, box = asks(answer)
    for text in [items.get(key, "")] + box:
        low = re.sub(r"\([^()]*\bentered\)", "", text).lower()     # "(..., slide only entered)" states the answer
        for rx in REASKED[key]:
            assert not re.search(rx, low), (text, rx)
        assert text != ct.label(key)
    # the parts the answer settles, by topic
    q = items.get(key, "").lower()
    if key == "losses":
        a = intake_fields.loss_answers(answer)
        assert ("what type" in q) == (a["losses_5yr"] != "0" and not a["loss_types"])
        assert ("when" in q) == (a["losses_5yr"] != "0" and not a["loss_year"])
    if key == "occupancy" and answer["occupancy_type"] == "Owner Occupied":
        assert "vacan" not in q
    if key == "pool":
        assert ("fence at least 4 ft" in q) == (answer["swimming_pool"] in intake_fields.FENCED_POOL_VALUES
                                                 and not answer.get("pool_fence_4ft"))
        assert ("gate" in q) == (answer["swimming_pool"] in intake_fields.FENCED_POOL_VALUES
                                 and not answer.get("pool_gate_locking"))
    if key == "animals" and answer["has_dogs"] == "No":
        assert q == "no dogs entered. any livestock or exotic animals?"
    if key == "solar" and answer["solar_panels"] == "No":
        assert key not in items


@pytest.mark.parametrize("topic,key,answer", [("pool", "pool", POOL[3]), ("dogs", "animals", DOGS[1]),
                                              ("roof_age", "roof", ROOF[2]), ("plumbing", "plumbing", PLUMBING[0]),
                                              ("solar", "solar", SOLAR[0])])
def test_an_unticked_topic_is_blank_so_its_question_stays(topic, key, answer):
    checked = [t for t in ("pool", "dogs", "roof_age", "plumbing", "solar") if t != topic]
    items, _ = asks(answer, checked)
    assert items[key] == ct.label(key)


def test_nothing_answered_keeps_every_question():
    items, _ = asks({})
    assert items == {k: ct.label(k) for k in RULES}


@pytest.mark.parametrize("answer,expected", [
    (dict(losses_5yr="1", loss_types=["Theft"], loss_year=2022, losses_3yr="0"),
     "Loss entered: 1 theft (2022). Confirm it was paid and fully repaired, and there are no open claims."),
    (dict(losses_5yr="0"), "No losses entered. Confirm no open claims and no prior cancellations for losses."),
    (dict(losses_5yr="2", loss_types=["Water", "Theft"], loss_year=2025, losses_3yr="1"),
     "Losses entered: 2 (water, theft; most recent 2025). Confirm they were paid and fully repaired, and there are "
     "no open claims."),
    (dict(losses_5yr="1"), "Loss entered: 1. Confirm what type and when, that it was paid and fully repaired, and "
                           "there are no open claims."),
    (dict(losses_5yr="3 or more", loss_types=["Fire"]),
     "Losses entered: 3 or more (fire). Confirm when and how many in the last 3 years, that they were paid and fully "
     "repaired, and there are no open claims."),
])
def test_the_losses_item_is_worded_from_the_answer(answer, expected):
    assert asks(answer)[0]["losses"] == expected


@pytest.mark.parametrize("answer,expected", [
    (dict(ownership_type="LLC"), "LLC: titled to the LLC, and the LLC only holds rental property (no other business)?"),
    (dict(ownership_type="Trust", trust_type="Land trust"),
     "Trust (land trust): titled to the trust, with trustees and beneficiaries as the guide allows?"),
])
def test_the_ownership_item_is_worded_from_the_answer(answer, expected):
    assert asks(answer)[0]["ownership"] == expected


@pytest.mark.parametrize("picked,expected", [
    (["Circuit breakers"], "Electrical (Circuit breakers entered): service amperage as the guide requires?"),
    (["Fuses"], "Electrical (Fuses entered): service amperage and whether it has been updated or replaced as the "
                "guide requires?"),
])
def test_breakers_keep_only_the_amperage(picked, expected):
    item = next(it for it in ct.card_items(rec(), dict(electrical=picked)) if it["key"] == "electrical")
    assert item["ask"] == expected
    assert "fuses, knob" not in item["text"].lower()        # the guide's rule quoted is the amperage one


def test_breakers_with_no_amperage_rule_drop_the_item():
    r = {"status": "ELIGIBLE", "confirm_items": [{"row": "XX-1", "category": "ELECTRICAL", "effect": "DECLINES",
                                                  "rule": "Knob-and-tube wiring is ineligible.", "kind": "not_asked"}]}
    assert ct.card_items(r, dict(electrical=["Circuit breakers"])) == []
    assert ct.card_items(r, {})[0]["ask"] == ct.label("electrical")


# ---------------------------------------------------------------- Liam's LANDLORD, the exact scenario

@pytest.fixture
def landlord(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), {
            "input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    monkeypatch.setattr(ec, "_complete", fake)
    return ec.check_eligibility(dict(LANDLORD))


def test_liams_landlord_top_box_asks_about_the_llc_not_individual_owners(landlord):
    box = [text for text, _, _ in ct.top_box(landlord, LANDLORD)]
    assert not any("owned by individuals" in t.lower() for t in box), box
    assert not any("any losses or claims" in t.lower() for t in box), box
    assert ct.top_box(landlord) and any("Owned by individuals" in t for t, _, _ in ct.top_box(landlord))   # unchanged without the form


def test_liams_landlord_steadily_card_states_the_loss(landlord):
    steadily = next(r for r in landlord if r["carrier"] == "Steadily_Underwriting_Guidelines_DP3")
    html = cards.confirm_html(steadily, LANDLORD)
    assert "Loss entered: 1 theft (2022). Confirm it was paid and fully repaired, and there are no open claims." in html
    assert "Any losses or claims" not in html and "Owned by individuals" not in html
