"""Round 28 step 6 (2026-10-07): a galvanized-plumbing home (round 24's OLD
profile) and the carriers whose guides decline galvanized plumbing. Found while
measuring Haiku 5.5 against Luna: neither model declined these carriers on OLD,
because the rule never reached the prompt. A retrieval miss, so the same for
every model. Zero API: the main call is answered by a fake and its prompt read.

The carriers whose galvanized rule is missing are strict xfails, so the gap shows
on every run until retrieval is fixed (CLAUDE.md: a backlog item must stay visible)."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import eligibility_check as ec  # noqa: E402
import measure_rules_pilot as M  # noqa: E402

pytestmark = pytest.mark.retrieval

USAGE = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}
# carrier -> the guide's own words (checked in guides.guide_text, 2026-10-07)
GALVANIZED_DECLINES = {
    "ARI_(HOA+)": "Galvanized, mixed-galvanized or lead plumbing are not acceptable.",
    "ARI_(HOB)": "Galvanized, mixed-galvanized or lead plumbing are not acceptable.",
    "Swyfft_-_Benchmark_(Surplus)_HO3": "Galvanized and polybutylene plumbing (PLUMBING, ineligible list)",
    "Swyfft_-_Topa_(Surplus)_HO3": "Galvanized and polybutylene plumbing (PLUMBING, ineligible list)",
    "Swyfft_-_Lloyds_(Surplus)_HO3": "Galvanized, steel and polybutylene plumbing (ineligible list)",
    "TWICO_HO3": "Homes with galvanized plumbing are ineligible.",
    "Travelers_HO3_-_06.12.2026": "A dwelling or condo with lead, galvanized or polybutylene plumbing.",
}
# Round 28 (2026-10-07): all seven missing. Round 29 step 7 (2026-10-08): the guaranteed plumbing
# lookup (guarantee:plumbing) brings each one's galvanized rule into the prompt; with the HO3 batch
# on, code decides them from their rows (test_ho3_batch_rules). No strict xfail remains.
MISSING_2026_10_07 = set()


def _main_prompt(pd):
    cap = {}

    def fake(system, user, max_tokens):
        cap.setdefault("main", user)
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)

    real = ec._complete
    ec._complete = fake
    try:
        ec.check_eligibility(dict(pd))
    finally:
        ec._complete = real
    return cap["main"]


@pytest.fixture(scope="module")
def old_prompt():
    return _main_prompt(M.PROFILES["OLD"])


def _section(prompt, carrier):
    parts = re.split(r"\n(?=--- .+? \(page)", prompt)
    return "\n".join(p for p in parts if p.startswith(f"--- {carrier} (page"))


@pytest.mark.parametrize("carrier", [
    pytest.param(c, marks=pytest.mark.xfail(strict=True, reason="round 28: the galvanized decline is not retrieved "
                                                                  "for a galvanized-plumbing home (OLD), so no model "
                                                                  "can apply it"))
    if c in MISSING_2026_10_07 else c for c in GALVANIZED_DECLINES])
def test_a_galvanized_home_gets_the_carriers_galvanized_rule(old_prompt, carrier):
    assert "galvaniz" in _section(old_prompt, carrier).lower()


def test_the_old_profile_is_galvanized_and_the_carriers_are_in_the_prompt(old_prompt):
    assert M.PROFILES["OLD"]["plumbing_type"] == "Galvanized"
    assert all(_section(old_prompt, c) for c in GALVANIZED_DECLINES)


def test_the_plumbing_lookup_adds_nothing_for_copper_plumbing():
    """Round 29 step 7: the lookup is keyed on the form's answer; any other answer's prompt is unchanged."""
    copper = _main_prompt(dict(M.PROFILES["OLD"], plumbing_type="Copper"))
    assert "galvaniz" not in _section(copper, "TWICO_HO3").lower()
