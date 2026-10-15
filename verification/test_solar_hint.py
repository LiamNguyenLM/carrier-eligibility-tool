"""Round 39 step 0b (Liam): with Solar Panels = Yes the form says how many carriers hold until the solar type and the
Tesla answer are given ("Six carriers hold until these are answered." on an owner's home). The number is counted here
from the rules: the carriers held with both answers blank that any answer releases. Zero API (fake model)."""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import eligibility_check as ec  # noqa: E402
import intake_fields  # noqa: E402
from test_held_reasons import HOME, LANDLORD  # noqa: E402

pytestmark = pytest.mark.retrieval
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
WORDS = {"One": 1, "Two": 2, "Five": 5, "Six": 6}
# Travis: no county rule rules a solar-holding carrier out first
TRAVIS = dict(zip="", county="Travis", harris_east_146=None)
OWN = dict(HOME, **TRAVIS)
RENT = dict(LANDLORD, ownership_type="Individual Owner", **TRAVIS)


@pytest.fixture
def statuses(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---",
                                                                                  user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    monkeypatch.setattr(ec, "_complete", fake)
    return lambda pd: {r["carrier"]: r["status"] for r in ec.check_eligibility(dict(pd))}


def held_by_solar(statuses, base):
    blank = statuses(dict(base, solar_panels="Yes", solar_type="", solar_tesla="Unknown"))
    released = set()
    for answer in (dict(solar_type="Roof-mounted panels", solar_tesla="No"),
                   dict(solar_type="Ground-mounted", solar_tesla="Yes")):
        got = statuses(dict(base, solar_panels="Yes", **answer))
        released |= {c for c, s in blank.items() if s == "INSUFFICIENT_INFORMATION" and got.get(c) != s}
    return sorted(released)


@pytest.mark.parametrize("base,occupancy", [(OWN, "Owner Occupied"), (dict(OWN, occupancy_type="Seasonal",
                                                                          primary_home_carrier="Other carrier"),
                                                                     "Seasonal"),
                                            (dict(OWN, occupancy_type="Secondary Home",
                                                  primary_home_carrier="Other carrier"), "Secondary Home"),
                                            (RENT, "Tenant Occupied"), (dict(RENT, occupancy_type="Vacant"), "Vacant")])
def test_the_hint_counts_the_carriers_that_hold(statuses, base, occupancy):
    hint = intake_fields.solar_hold_hint(occupancy)
    want = WORDS[hint.split()[0]]
    held = held_by_solar(statuses, base)
    assert len(held) == want, (hint, held)


def test_the_owners_home_hint_is_liams_wording():
    assert intake_fields.solar_hold_hint("Owner Occupied") == "Six carriers hold until these are answered."
    assert intake_fields.solar_hold_hint("Tenant Occupied") == "Two carriers hold until these are answered."
    assert intake_fields.solar_hold_hint("Vacant") == "One carrier holds until these are answered."
    assert set(intake_fields.SOLAR_HOLD_COUNTS) == {"Owner Occupied", "Seasonal", "Secondary Home", "Tenant Occupied",
                                                    "Vacant"}
