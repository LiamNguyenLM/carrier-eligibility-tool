"""Round 47 (Liam and Jonathan, 2026-11): Ask the Guides' cross-carrier answers name every program, each labelled as
the eligibility check would label it. Zero API.

- rules_data/chat/outcomes.json is the checker's own outcome for every topic value, scope and program
  (cloudflare/scripts/export_chat_outcomes.py runs engine.api.check); it must equal a fresh export, so a change to a
  rules table, a field map, the checker or sweep_topics.json without a re-export fails here.
- every program in a scope gets a label for every value (an agent asking "which carriers take X" needs all of them).
- the guides' own dates reach the chat (rules_data/chat/guide_dates.csv), so a dated guide never shows "not stated".
"""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
CHAT = os.path.join(ROOT, "rules_data", "chat")
pytestmark = pytest.mark.retrieval
LABELS = {"Eligible", "Confirm", "Refer", "Not eligible", "Coverage limited", "Guide silent", "Closed", "Not checked"}


def _outcomes():
    return json.load(open(os.path.join(CHAT, "outcomes.json"), encoding="utf-8"))


def test_the_committed_outcomes_are_a_fresh_export_of_the_checker(tmp_path):
    out = subprocess.run([sys.executable, os.path.join(ROOT, "cloudflare", "scripts", "export_chat_outcomes.py"),
                          "--out", str(tmp_path)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                         timeout=1200)
    assert out.returncode == 0, out.stderr[-3000:]
    fresh = open(tmp_path / "outcomes.json", encoding="utf-8").read()
    committed = open(os.path.join(CHAT, "outcomes.json"), encoding="utf-8").read()
    assert fresh == committed, "outcomes.json is stale: rerun python cloudflare/scripts/export_chat_outcomes.py"


def test_every_program_in_a_scope_gets_a_label_for_every_value():
    d = _outcomes()
    for key, scopes in d["sweeps"].items():
        for scope, per in scopes.items():
            scope_programs = {p["program"] for p in d["scopes"][scope]["programs"]}
            assert scope_programs <= set(per), (key, scope, sorted(scope_programs - set(per)))
            for prog, o in per.items():
                assert o["label"] in LABELS, (key, scope, prog, o["label"])
                assert o["name"], (key, scope, prog)
    assert len(d["scopes"]["HO3"]["programs"]) >= 25 and len(d["scopes"]["DP3"]["programs"]) >= 12


@pytest.mark.parametrize("key,want", [
    # Liam (2026-11): the chat said Ineligible; the checker (round 39, HAR-058 condition of property) says Refer
    ("pool/above_unfenced", ("Refer", "REFER", "HAR-058")),
    # ... while an unfenced IN-GROUND pool is declined (HAR-060, "Unfenced inground swimming pool")
    ("pool/in_unfenced", ("Not eligible", "INELIGIBLE", "HAR-060"))])
def test_the_hartford_on_an_unfenced_pool_is_what_the_checker_says(key, want):
    h = _outcomes()["sweeps"][key]["HO3"]["The_Hartford_HO3_-_07.09.2026"]
    assert (h["label"], h["status"], h["rows"][0]) == want


def test_a_program_the_checker_cannot_check_still_gets_a_line():
    # Liberty Mutual HO6's file is the HO3 guide (a known defect): "Not checked", never left out
    lib = _outcomes()["sweeps"]["diving/diving_board"]["HO6"]["Liberty_Mutual_HO6_-_02.21.2026"]
    assert lib["label"] == "Not checked"


@pytest.mark.parametrize("program", ["Sage_-_Auros_HO3", "Swyfft_-_Benchmark_(Surplus)_HO3", "Sage_-_Occidental_DP3",
                                     "ARI_(HOA+)", "Steadily_Underwriting_Guidelines_DP3"])
def test_a_guide_that_prints_its_date_never_shows_not_stated(program):
    progs = {p["program"]: p for p in json.load(open(os.path.join(CHAT, "programs.json"), encoding="utf-8"))}
    assert progs[program]["date"], program


def test_only_twico_has_no_date_on_file():
    progs = json.load(open(os.path.join(CHAT, "programs.json"), encoding="utf-8"))
    assert [p["program"] for p in progs if not p["date"]] == ["TWICO_HO3"]


# Round 47 step 3 (the graded rerun, 2026-11): the labels the grader found wrong, as the export now reads them.
def _label(key, name_part, scope="HO3"):
    per = _outcomes()["sweeps"][key][scope]
    hits = [o for o in per.values() if name_part in o["name"]]
    assert len(hits) == 1, (key, name_part, [o["name"] for o in hits])
    return hits[0]["label"]


@pytest.mark.parametrize("key,program,want", [
    # a FULL check: Allied Trust's and Progressive's plumbing declines also test the year built, so a check with only
    # plumbing ticked skipped them and the chat said Eligible (Q16, Q20)
    ("plumbing/galvanized", "Allied Trust", "Not eligible"), ("plumbing/galvanized", "Progressive (HO3)", "Not eligible"),
    ("plumbing/polybutylene", "Allied Trust", "Not eligible"), ("plumbing/polybutylene", "Progressive (HO3)", "Not eligible"),
    # a guide silent on the material is Guide silent, even with other plumbing rules (Q16: SageSure said Eligible)
    ("plumbing/galvanized", "SageSure Auros", "Guide silent"), ("plumbing/galvanized", "SageSure Wilshire", "Guide silent"),
    # "attractive nuisances (except trampolines)" is no trampoline decline; a signed acknowledgement is a Confirm (Q17)
    ("trampoline/trampoline", "SageSure Auros", "Confirm"), ("trampoline/trampoline", "SageSure SafePort", "Confirm"),
    # a damaged-structure decline is not a trampoline rule; the trampoline exclusion is (Orion180, ORI-076 vs ORI-114)
    ("trampoline/trampoline", "Orion180", "Coverage limited"),
    # "accepted only with safety netting" / "without a safety net are ineligible": Confirm, not Not eligible
    ("trampoline/trampoline", "The Hartford", "Confirm"), ("trampoline/trampoline", "Mercury", "Confirm"),
    # acreage: a farm-and-ranch rating rule is not an acreage limit; a 5-10 acre referral is a Refer (Q18)
    ("acreage/acreage", "Chubb", "Guide silent"), ("acreage/acreage", "Allied Trust", "Refer"),
    # stoves: declined only as the only heat source / not professionally installed / in PC 10 -> Confirm; a plain
    # decline stays Not eligible (Q19)
    ("wood_stove/wood_stove", "The Hartford", "Confirm"), ("wood_stove/wood_stove", "NatGen Custom360", "Confirm"),
    ("wood_stove/wood_stove", "Orion180", "Confirm"), ("wood_stove/wood_stove", "Liberty Mutual", "Confirm"),
    ("wood_stove/wood_stove", "SageSure Auros", "Not eligible"),
    # the regrade: "declined even if not the primary source of heat" is a plain decline (TWI-040); a decline its cure
    # column lifts ("unless professionally installed", MER-043) is a Confirm; "wood ... as a source of fuel is
    # unacceptable" is a stove rule (ARA-064 / ARB-062); "over 10 acres" is a size limit -> Confirm (VAV-100)
    ("wood_stove/wood_stove", "TWICO", "Not eligible"), ("wood_stove/wood_stove", "Mercury", "Confirm"),
    ("wood_stove/wood_stove", "ARI (HOA+)", "Not eligible"), ("wood_stove/wood_stove", "ARI (HOB)", "Not eligible"),
    ("acreage/acreage", "SageSure Vave", "Confirm"),
])
def test_the_graded_labels(key, program, want):
    assert _label(key, program) == want


def test_reading_a_row_negation_a_condition_and_a_damaged_structure():
    sys.path.insert(0, os.path.join(ROOT, "cloudflare", "scripts"))
    import export_chat_outcomes as E
    row = lambda plain, effect="DECLINES", topic="LIABILITY_HAZARDS": {  # noqa: E731
        "id": "X-001", "topic": topic, "state": "RULE", "effect": effect, "text": plain, "plain": plain, "fields": set()}
    for plain, want in [("Properties with skateboard ramps or other attractive nuisances (except trampolines) are ineligible.", []),
                        ("Attractive nuisances other than trampolines are ineligible.", []),
                        ("Damaged or dilapidated detached structures (sheds, trampolines) are ineligible.", []),
                        ("Trampolines are ineligible.", ["X-001"])]:
        got = [r["id"] for r in E.matching_rows([row(plain)], ["LIABILITY_HAZARDS"], "trampoline", set()) if r["about"]]
        assert got == want, plain
    for plain in ["A trampoline is accepted only with safety netting.", "Trampolines without a safety net are ineligible.",
                  "A wood stove cannot be the primary heat source.", "A home with a solid fuel stove must be owner occupied."]:
        assert E.row_label(row(plain)) == "Confirm", plain
    for plain in ["Dwellings with wood, wood pellet or coal stoves are ineligible.", "Trampolines are ineligible."]:
        assert E.row_label(row(plain)) == "Not eligible", plain
