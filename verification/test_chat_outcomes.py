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
