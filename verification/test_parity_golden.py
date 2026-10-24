"""Round 42 step 4 (Liam, 2026-10-24): the parity golden file (verification/parity/golden.json.xz) is today's engine
output on the Round 38 fuzz set and the named profiles. These tests keep it honest: it holds every profile, the
native engine still matches it on named and fuzz profiles, and the check catches a changed status, held field, row
or text in a full card and in a hashed one, while whitespace alone is not a difference. A deliberate change to a
rules table or a card fails the match test: re-export the golden (see export_golden.py) and commit it with the
change. Zero API: the model is a stub that raises."""
import copy
import datetime
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "parity"))
import export_golden as eg  # noqa: E402

pytestmark = pytest.mark.retrieval
SAMPLE = ["LIVE", "LANDLORD", "HARRIS", "HARTFORD_e_rpp", "HARTFORD_k_1_fire", "R40_BASE", "fuzz_0", "fuzz_1000",
          "fuzz_5003", "fuzz_12681"]


@pytest.fixture(scope="module")
def golden():
    return eg.load(eg.GOLDEN)


@pytest.fixture(scope="module")
def native():
    prof = {pid: (pd, ch) for pid, pd, ch in eg.all_profiles()}
    return eg.build([(pid, *prof[pid]) for pid in SAMPLE])


def test_the_golden_holds_every_named_and_fuzz_profile(golden):
    ids = [pid for pid, _, _ in eg.all_profiles()]
    assert sorted(golden["profiles"]) == sorted(ids)
    assert sum(pid.startswith("fuzz_") for pid in ids) == 3409
    assert {"LIVE", "LANDLORD", "HARRIS", "HARTFORD_a_fenced_pool", "HARTFORD_k_class_10_theft", "R40_BASE"} <= set(ids)
    assert all(c["full"] == (not pid.startswith("fuzz_")) for pid, p in golden["profiles"].items() for c in p["cards"])


def test_the_golden_was_made_this_year(golden):
    """Ages are counted from today: a new year changes cards on purpose. Re-export the golden in January."""
    assert golden["meta"]["year"] == datetime.date.today().year


def test_the_native_engine_matches_the_golden_on_named_and_fuzz_profiles(golden, native):
    assert eg.compare(golden, native, partial=True) == []


def _diff_fields(golden, doc):
    return {(pid, k) for pid, _, k, _, _ in eg.compare(golden, doc, partial=True)}


def test_the_check_catches_a_changed_status_row_and_held_field(golden, native):
    doc = copy.deepcopy(native)
    full, hashed = doc["profiles"]["LANDLORD"]["cards"][0], doc["profiles"]["fuzz_1000"]["cards"][0]
    full["status"] = "ELIGIBLE" if full["status"] != "ELIGIBLE" else "INELIGIBLE"
    doc["lists"].append(doc["lists"][hashed["rows"]] + ["ZZZ-999"])
    hashed["rows"] = len(doc["lists"]) - 1
    doc["lists"].append(doc["lists"][full["held"]] + ["a field nobody asked"])
    full["held"] = len(doc["lists"]) - 1
    assert {("LANDLORD", "status"), ("fuzz_1000", "rows"), ("LANDLORD", "held")} <= _diff_fields(golden, doc)


def test_the_check_catches_a_changed_text_in_a_full_card_and_in_a_hashed_card(golden, native):
    doc = copy.deepcopy(native)
    doc["strings"].append("Held: a different first line")
    doc["profiles"]["HARRIS"]["cards"][0]["first"] = len(doc["strings"]) - 1
    doc["hashes"].append(eg.digest(eg.canonical("notes", "a different note")))
    doc["profiles"]["fuzz_0"]["cards"][0]["notes"] = len(doc["hashes"]) - 1
    assert {("HARRIS", "first"), ("fuzz_0", "notes")} <= _diff_fields(golden, doc)


@pytest.mark.parametrize("k,a,b", [("first", "Held:  the hydrant\n is blank", "Held: the hydrant is blank"),
                                   ("confirm", "<ul><li>Roof  ok?</li>\n<li>Pool?</li></ul>",
                                    "<ul><li>Roof ok?</li> <li>Pool?</li></ul>")])
def test_whitespace_alone_is_not_a_difference(k, a, b):
    assert eg.digest(eg.canonical(k, a)) == eg.digest(eg.canonical(k, b))
