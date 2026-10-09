"""Round 35 step 3c (Liam, 2026-10-09, decision 1): PEX by install year, and Cast iron. Every option against
every line that reads the plumbing. Zero API."""
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import intake_fields as I  # noqa: E402
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval
M = ev._map()
NEW, OLD, UNK = I.PEX_2011_ON, I.PEX_PRE_2011, I.PEX_YEAR_UNKNOWN
LINES = sorted(rid for rid, m in M.items() if "plumbing_type" in m["field"])
OPTIONS = [o for o in I.PLUMBING_TYPES if o not in ("Unknown", "Other")]


def out(rid, plumbing, year=1990):
    return ev.evaluate_row(M[rid], ev.facts({"plumbing_type": plumbing, "year_built": year}))[0]


PRE_2011 = ("ALL-057", "PRO-039", "PH6-074")           # "Pre-2011 PEX" / "PEX installed before 2011"


@pytest.mark.parametrize("rid", PRE_2011)
@pytest.mark.parametrize("plumbing,year,want", [
    (NEW, 1990, "PASS"), (OLD, 1990, "FAIL"), (UNK, 1990, "OPEN"),     # unknown install year holds
    (UNK, 2011, "PASS"), (UNK, 2015, "PASS"),                          # a home built 2011+ has no pre-2011 PEX
    (OLD, 2015, "FAIL"),                                               # the answer, not the year built, decides
    ("Galvanized", 2015, "FAIL"), ("Polybutylene", 1990, "FAIL"), ("Copper", 1990, "PASS")])
def test_the_pre_2011_pex_rules(rid, plumbing, year, want):
    assert out(rid, plumbing, year) == want


@pytest.mark.parametrize("rid,home_age_year", [("ALL-058", 1960), ("ALL-060", 1940)])
@pytest.mark.parametrize("plumbing,want", [(OLD, "NOTE"), ("Cast iron", "NOTE"), (NEW, "PASS"), ("Copper", "PASS")])
def test_allied_older_homes_list_cast_iron_too(rid, home_age_year, plumbing, want):
    # NOTE: the cure is a service inspection (round 24)
    assert out(rid, plumbing, home_age_year) == want


@pytest.mark.parametrize("rid", ["MER-030", "CHO-045", "VAV-047", "VDP-069"])
def test_cast_iron_fails_where_the_guide_names_iron(rid):
    assert out(rid, "Cast iron") == "FAIL" and out(rid, "Copper") == "PASS"


@pytest.mark.parametrize("rid", ["MER-029", "LDP-049"])
@pytest.mark.parametrize("plumbing", [NEW, OLD, UNK])
def test_any_pex_is_on_a_copper_pvc_pex_list(rid, plumbing):
    assert out(rid, plumbing) == "PASS"


@pytest.mark.parametrize("plumbing", [NEW, OLD, UNK, "PEX"])
def test_progressive_dp3_declines_any_pex(plumbing):
    assert out("PDP-088", plumbing) == "FAIL"


@pytest.mark.parametrize("rid", LINES)
def test_an_old_saved_pex_is_pex_of_unknown_install_year(rid):
    for year in (1990, 2015):
        assert out(rid, "PEX", year) == out(rid, UNK, year), rid


@pytest.mark.parametrize("rid", LINES)
@pytest.mark.parametrize("plumbing", OPTIONS)
def test_every_option_gives_an_outcome_on_every_line(rid, plumbing):
    # no option is a string a line cannot read (it would fall through as an unknown)
    assert out(rid, plumbing) in {"PASS", "FAIL", "NOTE", "OPEN", "N/A"}
    if plumbing in ("Copper", "PVC", NEW) and out(rid, plumbing) not in ("N/A", "NOTE") and rid != "PDP-088":
        # (Progressive DP3 declines any PEX: "polybutylene, PEX, or galvanized")
        assert out(rid, plumbing) == "PASS", (rid, plumbing, M[rid]["test"])


def test_no_plumbing_line_is_ambiguous_and_no_bare_pex_is_left():
    import re
    assert not [r for r in LINES if "||" in M[r]["test"]]
    assert not [r for r in LINES if re.search(r"\bPEX\b(?!:)", M[r]["test"] + " " + M[r]["gate"])]


def test_the_form():
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    assert 'st.selectbox("Plumbing Type", list(intake_fields.PLUMBING_TYPES)' in src
    assert I.PLUMBING_LABELS[NEW] == "PEX, installed 2011 or later" and "Cast iron" in I.PLUMBING_TYPES
    assert "PEX" not in I.PLUMBING_TYPES and not any("," in o for o in I.PLUMBING_TYPES)
