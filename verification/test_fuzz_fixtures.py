"""Round 38 step 7e (Liam, 2026-10-11): every failure the randomized self-audit found, shrunk and saved in
verification/fuzz/fixtures/, is replayed here with the check that caught it. A fixed one must pass; one left for
Liam is an xfail naming why, so it shows on every run until someone removes it deliberately. Zero API."""
import glob
import json
import os
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "fuzz"))
FIXTURES = sorted(glob.glob(os.path.join(HERE, "fuzz", "fixtures", "*.json")))
pytestmark = pytest.mark.retrieval


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _param(path):
    f = _load(path)
    marks = [pytest.mark.xfail(reason=f"for Liam: {f['note']}", strict=True)] if f["status"] == "for_liam" else []
    return pytest.param(path, id=f["name"], marks=marks)


@pytest.mark.parametrize("path", [_param(p) for p in FIXTURES])
def test_fuzz_fixture(path):
    import checks
    f = _load(path)
    got, _, _ = checks.check_profile(f["pd"], f["checked"], f["seed"], only={f["check"]})
    mine = [x for x in got if x["check"] == f["check"] and x["carrier"] == f["carrier"]]
    assert mine == [], mine


# ---------------------------------------------------------------- the checks themselves can fail
# (a self-audit whose checks never fire proves nothing: each one is shown a page it must reject)

def _rec(carrier, status, **kw):
    return dict({"carrier": carrier, "status": status, "reasons": ["x"], "citations": [], "missing_info": [],
                 "notes": ""}, **kw)


def test_the_page_checks_reject_a_bad_page(monkeypatch):
    import checks
    import gen
    pd, checked = gen.profile(0)
    pd = dict(pd, occupancy_type="Owner Occupied")
    bad = [_rec("Liberty_Mutual_DP3_-_02.21.2026", "ELIGIBLE"),                       # a DP program on an owner's home
           _rec("TWICO_HO3", "INELIGIBLE", rules_table=True, reasons=["The roof appears to be too old."]),
           _rec("Travelers_HO3_-_06.12.2026", "ELIGIBLE"), _rec("Travelers_HO3_-_06.12.2026", "ELIGIBLE")]
    assert checks.c5_routing(pd, checked, bad)
    assert checks.c6_deciding_row(pd, checked, bad)
    assert any(f["detail"]["why"] == "carrier twice" for f in checks.c8_page(pd, checked, bad))
    monkeypatch.setattr(checks.ct, "asked", lambda *a, **k: None)                     # wording ignores the form
    llc = dict(pd, ownership_type="LLC")
    rows = [{"row": "XX-001", "category": "", "effect": "DECLINES", "kind": "not_asked",
             "rule": "Properties owned by an LLC or trust are ineligible unless titled to the applicant."}]
    assert checks.c7_no_reask(llc, checked, [_rec("A_HO3", "ELIGIBLE", confirm_items=rows)])
    monkeypatch.setattr(checks.placement, "panel", lambda res, pd: {"picks": [
        {"market": "Travelers", "programs": ["TWICO_HO3"]}]})
    assert checks.c9_placement(pd, checked, bad)


def test_the_pipeline_checks_reject_a_changed_answer(monkeypatch):
    import checks
    import gen
    pd, checked = gen.profile(0)
    base = [_rec("TWICO_HO3", "INELIGIBLE"), _rec("Travelers_HO3_-_06.12.2026", "ELIGIBLE")]
    monkeypatch.setattr(checks, "run", lambda pd, checked: [_rec("TWICO_HO3", "ELIGIBLE"),
                                                            _rec("Travelers_HO3_-_06.12.2026",
                                                                 "INSUFFICIENT_INFORMATION")])
    assert checks.c1_determinism(pd, checked, base)
    import random
    assert checks.c3_monotonic(dict(pd, roof_age=0, year_built=2000), checked, base, random.Random(1))
    monkeypatch.setattr(checks, "answered", lambda pd, rng: ("fire_station_miles", 4.0))
    assert checks.c4_answer_no_hold(dict(pd, fire_station_miles=None), list(checked) + ["ppc"], base,
                                    random.Random(1))
