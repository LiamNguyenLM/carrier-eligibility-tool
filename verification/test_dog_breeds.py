"""Round 35 step 3a (Liam, 2026-10-09, decision 1): "Breed(s) on the property" replaces the Aggressive
Breed toggle. Every option against every line that reads it. Zero API."""
import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import eligibility_check as ec  # noqa: E402
import intake_fields  # noqa: E402
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval
M = ev._map()
LINES = sorted(rid for rid, m in M.items() if "dog_breeds none_of" in (m["test"] or ""))
DOGS = {"has_dogs": "Yes", "occupancy_type": "Owner Occupied"}


def kind(rid):
    t = M[rid]["test"]
    if "FACT(Animal Liability" in t:
        return "open_ack"
    if "or FACT(signed acknowledgement" in t:
        return "ack"
    if "and FACT(no other breed" in t:
        return "open"
    return "closed"


def listed(rid):
    return {x.strip() for x in re.search(r"none_of \{([^}]*)\}", M[rid]["test"]).group(1).split(",")}


def row(rid, **pd):
    return ev.evaluate_row(M[rid], ev.facts(dict(DOGS, **pd)))[0]


WHEN_LISTED = {"closed": "FAIL", "open": "FAIL", "ack": "NOTE", "open_ack": "NOTE"}
WHEN_NOT = {"closed": "PASS", "open": "NOTE", "ack": "PASS", "open_ack": "NOTE"}


def test_the_breed_lines():
    assert LINES == sorted(["ALL-106", "SAG-067", "MER-054", "PRO-061", "SWY-040", "SUR-069", "SFP-070", "TRI-081",
                            "ARA-033", "ARB-028", "FOR-062", "STO-018", "TRV-016", "CDP-057", "PDP-109", "PH6-086"])
    assert {kind(r) for r in LINES} == {"closed", "open", "ack", "open_ack"}
    assert all(listed(r) <= set(intake_fields.DOG_BREEDS) for r in LINES)


def test_no_dog_line_is_ambiguous_any_more():
    assert not [rid for rid, m in M.items() if "||" in (m["test"] or "") and ("dog" in m["field"] or "breed" in m["field"])]


@pytest.mark.parametrize("rid", LINES)
@pytest.mark.parametrize("breed", intake_fields.DOG_BREEDS)
def test_every_breed_against_every_line(rid, breed):
    want = (WHEN_LISTED if breed in listed(rid) else WHEN_NOT)[kind(rid)]
    assert row(rid, dog_breeds=[breed]) == want


@pytest.mark.parametrize("rid", LINES)
def test_none_of_these(rid):
    assert row(rid, dog_breeds=[intake_fields.DOG_NONE]) == WHEN_NOT[kind(rid)]


@pytest.mark.parametrize("rid", LINES)
@pytest.mark.parametrize("answer", [[intake_fields.DOG_UNSURE], [], None, ["Akita", intake_fields.DOG_UNSURE]])
def test_not_sure_or_blank_holds(rid, answer):
    assert row(rid, dog_breeds=answer) == "OPEN"


@pytest.mark.parametrize("rid", LINES)
@pytest.mark.parametrize("old", ["Yes", "No"])
def test_an_old_saved_toggle_holds_and_never_guesses(rid, old):
    pd = dict(DOGS, aggressive_breed=old)                 # an old profile: no dog_breeds key at all
    assert ev.evaluate_row(M[rid], ev.facts(pd))[0] == "OPEN"


@pytest.mark.parametrize("rid", LINES)
def test_no_dogs_no_row(rid):
    assert ev.evaluate_row(M[rid], ev.facts({"has_dogs": "No", "dog_breeds": ["Akita"]}))[0] == "N/A"


@pytest.mark.parametrize("rid", ["ALL-107", "MER-057"])
def test_the_mix_rows_are_their_list_s(rid):
    # "Picking a breed means the dog is that breed or a mix of it": the list row decides
    assert M[rid]["test"] == "always"


def test_natgen_names_no_list_so_any_dog_is_a_confirm_note():
    for answer in (["Akita"], [intake_fields.DOG_NONE], [intake_fields.DOG_UNSURE]):
        assert row("NCD-111", dog_breeds=answer) == "NOTE"


@pytest.mark.parametrize("canon,breed,want", [
    ("Allied_Trust_HO3", "Great Dane", "INELIGIBLE"),                 # Allied p7, not on the old form's list
    ("Allied_Trust_HO3", "Boxer", "ELIGIBLE"),
    ("Travelers_HO3_-_06.12.2026", "Bullmastiff", "INELIGIBLE"),     # "Mastiffs"
    ("Mercury_HO3_-_01.01.2026", "American Bully", "INELIGIBLE")])
def test_a_picked_breed_decides_the_card(canon, breed, want):
    base = {"year_built": 2010, "roof_age": 5, "roof_type": "Architectural Shingle", "roof_shape": "Gable",
            "construction_type": "Masonry", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
            "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
            "pool_accessories": "None", "solar_panels": "No", "ppc": "3", "dwelling_type": "House",
            "county": "Bexar", "dwelling_amount": 450000, "fire_station_miles": "2", "hydrant_1000ft": "Yes"}
    rec, _ = ev.code_record(canon, ev.evaluate_carrier(canon, dict(base, has_dogs="Yes", dog_breeds=[breed])))
    assert rec["status"] == want


# -- the prompt and the form ------------------------------------------------------------------------------
@pytest.mark.parametrize("pd,line", [
    ({"has_dogs": "No", "dog_breeds": []}, "Aggressive Breed Dogs: No"),                 # unchanged with no dogs
    ({"has_dogs": "No", "aggressive_breed": "No"}, "Aggressive Breed Dogs: No"),        # an old saved profile
    ({"has_dogs": "Yes", "aggressive_breed": "Yes"}, "Aggressive Breed Dogs: Yes"),
    ({"has_dogs": "Yes", "dog_breeds": ["Rottweiler", "Akita"]},
     "Dog Breed(s) (a mix counts as the breed): Akita, Rottweiler"),
    ({"has_dogs": "Yes", "dog_breeds": ["None of these"]}, "Dog Breed(s) (a mix counts as the breed): none of the listed breeds"),
    ({"has_dogs": "Yes", "dog_breeds": ["Not sure"]}, "Dog Breed(s): not known")])
def test_the_prompt_line(pd, line):
    assert ec._dog_breed_line(pd) == line


def test_the_form_asks_the_breeds():
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    assert '"Breed(s) on the property", list(intake_fields.DOG_CHOICES)' in src
    assert "Aggressive Breed?" not in src and '"aggressive_breed":' not in src
    assert intake_fields.DOG_CHOICES[-2:] == ("None of these", "Not sure")
