"""Round 43 step 0b (Liam, 2026-10-24): the rules-table switches (ELIGIBILITY_RULES_PILOT and the Sage, HO3 and DP
batches) and the placement panel (ELIGIBILITY_PLACEMENT) default ON -- no variable means "1", as Railway runs. "0" (or
anything but exactly "1") still turns each one off. Liam's local run was model-only because they defaulted OFF.

Each case runs a fresh interpreter with the variables removed (the suite itself keeps them at "0", conftest.py)."""
import os
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SWITCHES = ("ELIGIBILITY_RULES_PILOT", "ELIGIBILITY_RULES_SAGE_BATCH", "ELIGIBILITY_RULES_HO3_BATCH",
            "ELIGIBILITY_RULES_DP_BATCH", "ELIGIBILITY_PLACEMENT")
PRINT = ("import eligibility_check as e, placement as p; "
         "print(e.RULES_PILOT, e.RULES_SAGE_BATCH, e.RULES_HO3_BATCH, e.RULES_DP_BATCH, p.enabled())")


def _flags(**set_):
    env = {k: v for k, v in os.environ.items() if k not in SWITCHES and k != "ELIGIBILITY_DOTENV"}
    env.update(set_, ANTHROPIC_API_KEY="x", OPENAI_API_KEY="x")
    out = subprocess.run([sys.executable, "-c", PRINT], cwd=ROOT, env=env, capture_output=True, text=True,
                         timeout=300)
    return out.stdout.strip().splitlines()[-1].split(), out.stderr[-500:]


def test_no_variable_turns_every_switch_on():
    flags, err = _flags()
    assert flags == ["True"] * 5, err


@pytest.mark.parametrize("switch,index", [(s, i) for i, s in enumerate(SWITCHES)],
                         ids=[s.split("_", 1)[1].lower() for s in SWITCHES])
def test_0_turns_one_switch_off_and_leaves_the_others_on(switch, index):
    flags, err = _flags(**{switch: "0"})
    expected = ["True"] * 5
    expected[index] = "False"
    if switch == "ELIGIBILITY_RULES_PILOT":         # the batches ride on the pilot
        expected[1:4] = ["False"] * 3
    assert flags == expected, err


@pytest.mark.parametrize("value", ["true", "", " 1"])
def test_only_exactly_1_or_no_variable_is_on(value):
    flags, err = _flags(ELIGIBILITY_RULES_PILOT=value, ELIGIBILITY_PLACEMENT=value)
    assert flags == ["False"] * 5, err
