"""Round 37 step 4 (Liam, 2026-10-10): two optional questions -- "Losses in the last 5 years" (0 / 1 / 2 / 3 or
more / Unknown; if 1 or more: types, most recent year, how many in the last 3 years) and "Electrical" (breakers /
fuses / Federal Pacific or Zinsco / knob-and-tube / aluminum branch wiring / Unknown, any that apply) -- and the
loss-history and electrical rows of all four tables decided from them (rules_data/loss_electrical_lines.py).
Blank or Unknown is a "Confirm:" note, never a hold. Every option is tried against every line that reads it.
Zero API."""
import csv
import itertools
import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rules_data"))
import eligibility_check as ec  # noqa: E402
import intake_fields  # noqa: E402
import loss_electrical_lines as le  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
TODAY_YEAR = 2026


def _maps():
    out = {}
    for b in rv.BATCHES.values():
        with open(b["map"], encoding="utf-8-sig") as fh:
            out.update({m["row_id"]: m for m in csv.DictReader(l for l in fh if not l.startswith("#"))})
    return out


MAPS = _maps()


def outcome(rid, **answers):
    m = MAPS[rid]
    import datetime
    f = rv.facts(dict(answers), today=datetime.date(TODAY_YEAR, 10, 10))
    return rv.evaluate_row(m, f)[0]


# ---------------------------------------------------------------- the maps carry the lines

def test_every_line_is_in_its_map_and_every_undecided_row_stays_none():
    for rid, (field, test, gate, _, _) in le.LINES.items():
        assert (MAPS[rid]["field"], MAPS[rid]["test"], MAPS[rid]["gate"]) == (field, test, gate), rid
    undecided = " ".join(le.UNDECIDED.values()).split()
    assert all(MAPS[rid]["field"] == "NONE" for rid in undecided if rid in MAPS)
    assert not set(undecided) & set(le.LINES)


def test_how_many_rows_each_table_decides():
    per = {name: sum(1 for rid in le.LINES if rid in {m["row_id"] for m in csv.DictReader(
        l for l in open(b["map"], encoding="utf-8-sig") if not l.startswith("#"))}) for name, b in rv.BATCHES.items()}
    assert sum(per.values()) == len(le.LINES) == 179
    assert per == {"pilot": 34, "sage": 27, "ho3": 60, "dp": 58}


# ---------------------------------------------------------------- every option against every line

LOSS_ROWS = sorted(le.LOSS)
ELEC_ROWS = sorted(le.ELECTRICAL)
COUNTS = ["", "0", "1", "2", "3 or more", "Unknown"]
TYPE_SETS = [[]] + [[t] for t in intake_fields.LOSS_TYPES] + [["Water", "Fire"], ["Wind or hail", "Other"],
                                                              list(intake_fields.LOSS_TYPES)]
IN3 = ["", "0", "1", "2", "3 or more"]


def _loss_answers():
    for n in COUNTS:
        if n in ("", "0", "Unknown"):
            yield {"losses_5yr": n}
            continue
        for types, in3 in itertools.product(TYPE_SETS, IN3):
            yield {"losses_5yr": n, "loss_types": types, "losses_3yr": in3}


@pytest.mark.parametrize("rid", LOSS_ROWS)
def test_every_loss_answer_on_every_loss_line_is_pass_fail_or_a_confirm_never_a_hold(rid):
    seen = set()
    for a in _loss_answers():
        o = outcome(rid, **a)
        assert o in ("PASS", "FAIL", "NOTE"), (rid, a, o)
        seen.add(o)
        if a["losses_5yr"] in ("", "Unknown"):
            assert o == "NOTE", (rid, a, o)                    # blank / Unknown: a confirm
        if a.get("loss_types") == ["Other"] and "loss_types" in le.LOSS[rid]:
            assert o != "FAIL" or rid in OTHER_CAN_FAIL, (rid, a)   # "Other" never proves a named type
    # no losses in 5 years passes every 5- and 3-year rule; a rule over a longer window (ever()) stays a confirm
    zero = outcome(rid, losses_5yr="0")
    # CHANGED 2026-10-11 (round 38 step 3, Liam: a loss row decides from count, type and years only where the guide's condition is just those): a row that is a bare
    # confirm (the Sage 6-year rows: "non-zero" losses the form cannot count) is a confirm at 0 losses too.
    longer = bool(re.fullmatch(r"\(.*\) and FACT\([^()]*\)", le.LOSS[rid])) or le.LOSS[rid].startswith("FACT(")
    assert zero == ("NOTE" if longer else "PASS"), (rid, zero)


# rules where "Other" is itself the named kind ("All Other Losses", Stillwater's "other losses")
OTHER_CAN_FAIL = {"ARA-066", "ARA-067", "ARB-069", "ARB-070", "STD-146"}

ELEC_ANSWERS = [[], ["Unknown"]] + [[x] for x in intake_fields.ELECTRICAL_CHOICES[:5]] + \
    [["Circuit breakers", x] for x in intake_fields.ELECTRICAL_CHOICES[1:5]] + [["Circuit breakers", "Unknown"]]


def _named(rid):
    """The options a line's none_of sets name."""
    import re
    return {x.strip() for grp in re.findall(r"electrical none_of \{([^}]*)\}", le.ELECTRICAL[rid])
            for x in grp.split(",")} - {"Circuit breakers"}


@pytest.mark.parametrize("rid", ELEC_ROWS)
def test_every_electrical_answer_on_every_electrical_line(rid):
    for a in ELEC_ANSWERS:
        o = outcome(rid, electrical=a, year_built=1970)
        assert o in ("PASS", "FAIL", "NOTE", "N/A"), (rid, a, o)
        if not a or "Unknown" in a:
            assert o in ("NOTE", "N/A"), (rid, a, o)          # blank / Unknown: a confirm
        elif set(a) & _named(rid) and "FACT(aluminum wiring retrofitted" not in le.ELECTRICAL[rid] \
                and "FACT(the panel is Zinsco" not in le.ELECTRICAL[rid]:
            assert o == "FAIL", (rid, a, o)                   # a named option declines
        elif a == ["Circuit breakers"]:
            assert o in ("PASS", "NOTE"), (rid, a, o)         # breakers alone never decline


# ---------------------------------------------------------------- the exact answers Liam named

@pytest.mark.parametrize("rid,answers,want", [
    # one water loss
    ("ARA-071", dict(losses_5yr="1", loss_types=["Water"]), "FAIL"),        # refer: any water/fire/theft/liability
    ("ARB-065", dict(losses_5yr="1", loss_types=["Water"], losses_3yr="1"), "PASS"),   # 2+ water in 3 years
    # CHANGED 2026-10-11 (round 38 step 3, Liam: a loss row decides from count, type and years only where the guide's condition is just those): Mercury's footnote --
    # a single non-weather water loss is never by itself a reason to reject. Was: FAIL.
    ("MER-087", dict(losses_5yr="1", loss_types=["Water"]), "PASS"),
    ("MER-087", dict(losses_5yr="1", loss_types=["Fire"]), "NOTE"),         # paid? a loss to the home?
    ("MER-088", dict(losses_5yr="1", loss_types=["Water"]), "PASS"),        # 2+ total losses
    ("PRO-097", dict(losses_5yr="1", loss_types=["Water"]), "PASS"),        # liability only
    # CHANGED 2026-10-11 (round 38 step 3, Liam: a loss row decides from count, type and years only where the guide's condition is just those): a Water loss may be a
    # catastrophe or appliance loss, which this rule does not count. Was: FAIL (refer).
    ("TRV-066", dict(losses_5yr="1", loss_types=["Water"]), "NOTE"),
    # a wind or hail loss is weather
    ("MER-087", dict(losses_5yr="1", loss_types=["Wind or hail"]), "PASS"),
    ("ARA-065", dict(losses_5yr="2", loss_types=["Wind or hail"]), "FAIL"),  # 2 Act of Nature claims
    ("ARA-065", dict(losses_5yr="2", loss_types=["Wind or hail", "Water"]), "NOTE"),  # 1 or 2 of them weather
    # counts and windows
    ("ALL-144", dict(losses_5yr="3 or more", losses_3yr="3 or more"), "FAIL"),
    ("ALL-144", dict(losses_5yr="3 or more", losses_3yr="1"), "PASS"),
    ("ALL-144", dict(losses_5yr="3 or more"), "NOTE"),                         # 3-year count not given
    ("ALL-144", dict(losses_5yr="2", loss_year=2021), "PASS"),                 # most recent over 3 years back
    ("MKL-106", dict(losses_5yr="3 or more"), "NOTE"),                         # 4+ declines: 3 or more is a confirm
    ("SAG-113", dict(losses_5yr="3 or more", loss_types=["Water"]), "NOTE"),   # 6 years: never passed on 5
    ("CHO-034", dict(losses_5yr="1", loss_types=["Liability"]), "FAIL"),       # "any" liability claim, ever
    ("CHO-034", dict(losses_5yr="0"), "NOTE"),
    # a dollar amount is never asked
    ("MKL-105", dict(losses_5yr="0"), "PASS"),
    ("MKL-105", dict(losses_5yr="1", loss_types=["Fire"]), "NOTE"),
])
def test_the_common_loss_answers(rid, answers, want):
    assert outcome(rid, **answers) == want


@pytest.mark.parametrize("rid,answers,want", [
    # CHANGED 2026-10-11 (round 38 step 7, F15: Progressive names Federal Pacific only; the form's combined answer
    # alone is a confirm, as FOR-041). Was FAIL.
    ("PRO-040", ["Circuit breakers", "Federal Pacific or Zinsco panel"], "NOTE"),
    ("SWY-029", ["Federal Pacific or Zinsco panel"], "FAIL"),
    ("MER-034", ["Circuit breakers"], "PASS"),                   # 100% circuit breakers
    ("MER-034", ["Circuit breakers", "Fuses"], "FAIL"),
    ("ALL-062", ["Circuit breakers"], "NOTE"),                   # breakers, but 150-amp service is not asked
    ("ALL-063", ["Circuit breakers", "Aluminum branch wiring"], "FAIL"),   # "even if remediated"
    ("SWY-027", ["Circuit breakers", "Aluminum branch wiring"], "NOTE"),   # AlumiConn / COPALUM cure: a confirm
    ("SBS-034", ["Aluminum branch wiring"], "NOTE"),
    ("SAG-046", ["Circuit breakers"], "NOTE"),                   # Challenger / Sylvania are not form options
    ("LDP-048", ["Fuses"], "FAIL"),                              # built before 1976 (1970 here)
])
def test_the_common_electrical_answers(rid, answers, want):
    assert outcome(rid, electrical=answers, year_built=1970) == want


def test_a_home_built_after_1975_is_outside_liberty_dp3s_wiring_rule():
    assert outcome("LDP-048", electrical=["Fuses"], year_built=1994) == "N/A"


# ---------------------------------------------------------------- the answers as the rules read them

@pytest.mark.parametrize("pd,want", [
    ({}, (None, None, None)),
    ({"losses_5yr": "Unknown"}, (None, None, None)),
    ({"losses_5yr": "0"}, ("0", "0", [])),
    ({"losses_5yr": "2", "loss_types": ["Water"], "losses_3yr": "1"}, ("2", "1", ["Water"])),
    ({"losses_5yr": "2", "loss_types": ["Water"], "loss_year": 2022}, ("2", "0", ["Water"])),   # 4 years back
    ({"losses_5yr": "1", "loss_year": 2025}, ("1", "1", None)),                                  # the one loss is recent
    ({"losses_5yr": "1", "loss_year": 2023}, ("1", None, None)),                                 # could be either side
])
def test_loss_answers(pd, want):
    import datetime
    a = intake_fields.loss_answers(pd, today=datetime.date(TODAY_YEAR, 10, 10))
    assert (a["losses_5yr"], a["losses_3yr"], a["loss_types"]) == want


@pytest.mark.parametrize("picked,want", [([], None), (["Unknown"], None), (["Circuit breakers", "Unknown"], None),
                                         (["Circuit breakers", "Aluminum branch wiring"],
                                          ["Circuit breakers", "Aluminum branch wiring"])])
def test_electrical_answer(picked, want):
    assert intake_fields.electrical_answer({"electrical": picked}) == want


def test_the_prompt_states_the_answers_only_when_given():
    base = {"year_built": 1994, "solar_panels": "No"}
    assert ec._followup_lines(base, "Individual Owner") == []
    rows = ec._followup_lines(dict(base, losses_5yr="2", loss_types=["Water", "Fire"], loss_year=2025,
                                   losses_3yr="2", electrical=["Circuit breakers"]), "Individual Owner")
    assert [t for _, t in rows] == ["Losses in the Last 5 Years: 2; Types: Water, Fire; Most Recent: 2025; "
                                    "In the Last 3 Years: 2", "Electrical: Circuit breakers"]


def test_the_form_asks_both_and_sends_only_what_was_answered(monkeypatch):
    from streamlit.testing.v1 import AppTest
    calls = []
    monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: calls.append(pd) or [])
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    at.selectbox(key="dwelling_type").select("House").run()
    at.button(key="submit").click().run()
    assert not {"losses_5yr", "loss_types", "loss_year", "losses_3yr", "electrical"} & set(calls[-1])
    at.selectbox(key="losses_5yr").select("1").run()
    at.multiselect(key="loss_types").select("Water").run()
    at.selectbox(key="losses_3yr").select("1").run()
    at.multiselect(key="electrical").select("Circuit breakers").run()
    at.button(key="submit").click().run()
    assert not at.exception
    pd = calls[-1]
    assert (pd["losses_5yr"], pd["loss_types"], pd["losses_3yr"], pd["electrical"]) == \
        ("1", ["Water"], "1", ["Circuit breakers"])
