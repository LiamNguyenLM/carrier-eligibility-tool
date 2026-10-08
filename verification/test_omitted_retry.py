"""Round 29 step 2 (2026-10-08): a carrier the reply leaves out gets one more
call, for just the missing carriers (same schema, smaller enum). Still missing
-> its card says "No answer came back ... run the check again" (never silently
dropped). Zero API."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import eligibility_check as ec  # noqa: E402
from profiles import STANDARD_PROFILE  # noqa: E402

pytestmark = pytest.mark.retrieval

USAGE = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}
PD = dict(STANDARD_PROFILE, dwelling_type="House", county="Bexar", dwelling_amount=450000)
LIB = "Liberty_Mutual_HO3_-_02.21.2026"


def _run(omit_first=(), omit_retry=(), pilot_on=False, omit_pilot_first=()):
    calls = []

    def fake(system, user, max_tokens):
        enum = list(getattr(ec._CALL, "carriers", None) or [])
        pilot = "RULE CHECK:" in user
        retry = "ANSWER ONLY FOR THESE CARRIERS" in user
        calls.append({"pilot": pilot, "retry": retry, "enum": enum})
        names = (re.findall(r"--- (.+?) \(rule check\) ---", user) if pilot
                 else sorted(set(re.findall(r"\n--- (.+?) \(page", user))))
        if retry:
            names = [n for n in enum if n not in omit_retry]
        elif pilot:
            names = [n for n in names if n not in omit_pilot_first]
        else:
            names = [n for n in names if n not in omit_first]
        status = "INSUFFICIENT_INFORMATION" if pilot else "ELIGIBLE"
        return json.dumps({"carriers": [{"carrier": n, "status": status, "flaw_count": 0, "reasons": ["fixture"],
                                         "citations": [], "missing_info": ["an open fact"] if pilot else [],
                                         "notes": ""} for n in names]}), dict(USAGE)

    saved = ec._complete, ec.RULES_PILOT
    ec._complete, ec.RULES_PILOT = fake, pilot_on
    try:
        res = {r["carrier"]: r for r in ec.check_eligibility(dict(PD))}
    finally:
        ec._complete, ec.RULES_PILOT = saved
    return res, calls


def test_nothing_omitted_means_no_retry():
    res, calls = _run()
    assert [c for c in calls if c["retry"]] == []
    assert res[LIB]["status"] == "ELIGIBLE"


def test_an_omitted_carrier_is_retried_once_with_only_its_name_in_the_enum():
    res, calls = _run(omit_first=(LIB,))
    retries = [c for c in calls if c["retry"]]
    assert len(retries) == 1 and retries[0]["enum"] == [LIB]
    assert res[LIB]["status"] == "ELIGIBLE"
    assert "main_retry" in ec.LAST_CALL_USAGE


def test_still_missing_after_the_retry_is_not_evaluated_never_dropped():
    res, calls = _run(omit_first=(LIB,), omit_retry=(LIB,))
    assert len([c for c in calls if c["retry"]]) == 1               # once, never twice
    assert res[LIB]["status"] == ec.NOT_EVALUATED
    assert "run the check again" in " ".join(res[LIB]["reasons"]).lower()


def test_a_pilot_carrier_left_out_of_the_pilot_reply_is_retried_too():
    allied = "Allied_Trust_HO3"
    res, calls = _run(pilot_on=True, omit_pilot_first=(allied,))
    retries = [c for c in calls if c["retry"]]
    if not any(c["pilot"] for c in calls if allied in c["enum"]):
        pytest.skip("Allied was decided by code on this profile; no pilot call carried it")
    assert any(r["enum"] == [allied] for r in retries)
    assert res[allied]["status"] != ec.NOT_EVALUATED


# -- round 30 step 5 (2026-10-08): an empty / unparseable reply gets the same one retry ---------------
def _run_empty(empties):
    """The main call answers "" `empties` times, then a full answer."""
    calls = []

    def fake(system, user, max_tokens):
        pilot = "RULE CHECK:" in user
        calls.append(pilot)
        if not pilot and calls.count(False) <= empties:
            return "", dict(USAGE)
        names = (re.findall(r"--- (.+?) \(rule check\) ---", user) if pilot
                 else sorted(set(re.findall(r"\n--- (.+?) \(page", user))))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    saved = ec._complete
    ec._complete = fake
    try:
        return {r["carrier"]: r for r in ec.check_eligibility(dict(PD))}, calls
    finally:
        ec._complete = saved


def test_an_empty_reply_is_retried_once_and_the_check_completes():
    res, calls = _run_empty(1)
    assert calls.count(False) == 2 and "Parse Error" not in res and LIB in res


def test_two_empty_replies_still_show_the_parse_error_card():
    res, calls = _run_empty(2)
    assert calls.count(False) == 2 and "Parse Error" in res
