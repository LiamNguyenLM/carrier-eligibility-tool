"""Round 37 follow-up (Liam, 2026-10-11): his run showed 18 Eligible and 2 Not Eligible; the 2 carriers whose guide
on file is unusable (NatGen Custom360 HO3, SageSure Occidental HO3) are listed only at the bottom of the page, under
four long columns. The results now name them at the top too. Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402

pytestmark = pytest.mark.retrieval
APP = os.path.join(os.path.dirname(__file__), "..", "app.py")


def _page(monkeypatch, records):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: [dict(r) for r in records])
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    at.selectbox(key="dwelling_type").select("House").run()
    at.button(key="submit").click().run()
    assert not at.exception
    return at


def rec(c, status, reason="x"):
    return {"carrier": c, "status": status, "flaw_count": 0, "reasons": [reason], "citations": [], "missing_info": [],
            "notes": ""}


def test_the_carriers_that_could_not_be_checked_are_named_at_the_top(monkeypatch):
    at = _page(monkeypatch, [rec("Allied_Trust_HO3", "ELIGIBLE"),
                             rec("Liberty_Mutual_HO6_-_02.21.2026", ec.GUIDE_UNAVAILABLE, "The guide on file is wrong."),
                             rec("Centauri_-_DP3_-_11.16.2022", ec.GUIDE_UNAVAILABLE, "The guide on file is wrong.")])
    top = [w.value for w in at.warning if w.value.startswith("Could not check")]
    assert top == ['Could not check 2 carriers: Liberty Mutual (HO6), Centauri (DP3) — see "Could Not Be '
                   'Checked" at the bottom of the results.']
    assert "### Could Not Be Checked" in [m.value for m in at.markdown]


def test_one_carrier_not_evaluated_is_named_too_and_none_means_no_line(monkeypatch):
    at = _page(monkeypatch, [rec("Allied_Trust_HO3", "ELIGIBLE"), rec("TWICO_HO3", ec.NOT_EVALUATED, "no answer")])
    assert [w.value for w in at.warning if w.value.startswith("Could not check")] == [
        'Could not check 1 carrier: TWICO (HO3) — see "Could Not Be Checked" at the bottom of the results.']
    at = _page(monkeypatch, [rec("Allied_Trust_HO3", "ELIGIBLE")])
    assert not [w.value for w in at.warning if w.value.startswith("Could not check")]
