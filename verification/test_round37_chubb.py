"""Round 37 step 3 (Liam's Railway run, 2026-10-10): Chubb came back Eligible on his profile -- ZIP 77248 (Harris
pre-filled), PPC 5, Not Coastal, hydrant Yes, Owner Occupied, Individual Owner, built 1994, House, Coverage A blank,
East of Highway 146 = Unknown.

What the guide says (Chubb HO, 05.22.2026, the coastal-areas table; rows CHU-043/044/048/049): a primary house in
Harris County is unacceptable in Territory 1A (east and west of Hwy 146, CHU-043), "subject to pre-approval" in
1B, 1C and 1E (CHU-044), and outside the coastal areas in 01D (CHU-049). The form does not ask the sub-territory,
and "East of 146" does not settle it for a primary house (1A covers both sides). So with County = Harris the
result depends on an unknown fact on Liam's named hold rows (CHU-043/044, HOLD_BY_DECISION, 2026-10-06/08):
Chubb must be held, never Eligible. Coverage A $500,000 fails CHU-056 (Standard tier pre-approval below
$1,000,000): Refer.

Found: through the real app, Chubb is never Eligible while the County box is ticked -- typed and pre-filled
Harris give the same verdict for every carrier. It is Eligible only when BOTH the County and the Coverage A
boxes are unticked (Round 21: an unticked topic is ignored), e.g. "Clear" after entering the ZIP. That is the
only way this code reproduces Liam's result, so no rule is changed; a "This looks wrong" report now records the
ticked topics so the next such report can be replayed. Zero API (the model is a fake that says Eligible to
anything it is asked, so a hold that survives it is code's)."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402

pytestmark = pytest.mark.retrieval
APP = os.path.join(os.path.dirname(__file__), "..", "app.py")
CHUBB = "CHUBB_HO_-_05.22.2026"
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def _fake(system, user, max_tokens):
    names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
    return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                                     "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)


@pytest.fixture
def live(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_PLACEMENT", "1")
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "usage.jsonl"))
    monkeypatch.setattr(ec, "_complete", _fake)
    calls = []
    real = ec.check_eligibility
    monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: calls.append((pd, kw, real(pd, **kw))) or calls[-1][2])
    return calls


def run(calls, county, cov_a=None, e146=None, untick=()):
    """Liam's form through the app: Select All, then his inputs, then the check."""
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=300)
    at.session_state["authenticated"] = True
    at.run()
    at.button(key="select_all").click().run()
    if county == "prefilled":
        at.text_input(key="zip").input("77248").run()
    elif county == "typed":
        at.selectbox(key="county").select("Harris").run()
    at.selectbox(key="ppc").set_value("5").run()
    at.selectbox(key="hydrant").set_value("Yes").run()
    at.number_input(key="year").set_value(1994).run()
    at.selectbox(key="dwelling_type").set_value("House").run()
    if cov_a:
        at.text_input(key="dwelling_amount").input(str(cov_a)).run()
    if e146:
        at.selectbox(key="harris_east_146").set_value(e146).run()
    for topic in untick:
        at.checkbox(key=f"chk_{topic}").uncheck().run()
    at.button(key="submit").click().run()
    assert not at.exception, at.exception
    pd, kw, res = calls[-1]
    return pd, kw, {r["carrier"]: r for r in res}


def _rows(rec):
    return sorted(set(re.findall(r"CHU-\d{3}", " ".join((rec.get("missing_info") or []) + (rec.get("reasons") or [])))))


CASES = [  # (county, Coverage A, East of 146) -> (Chubb, deciding rows)
    ("blank", None, None, "INSUFFICIENT_INFORMATION", []),           # held on Coverage A (Chubb's named hold)
    ("blank", 500000, None, "REFER", ["CHU-056"]),
] + [(c, None, e, "INSUFFICIENT_INFORMATION", ["CHU-043", "CHU-044"])
     for c in ("typed", "prefilled") for e in ("Yes", "No", "Unknown")] \
  + [(c, 500000, e, "REFER", ["CHU-043", "CHU-044", "CHU-056"])
     for c in ("typed", "prefilled") for e in ("Yes", "No", "Unknown")]


@pytest.mark.parametrize("county,cov_a,e146,status,rows", CASES)
def test_chubb_on_liams_profile(live, county, cov_a, e146, status, rows):
    pd, kw, res = run(live, county, cov_a, e146)
    assert pd["county"] == ("" if county == "blank" else "Harris")
    rec = res[CHUBB]
    assert (rec["status"], _rows(rec)) == (status, rows), rec.get("missing_info")
    if county == "blank" and not cov_a:
        assert any(m.startswith("Dwelling amount (Coverage A)") for m in rec["missing_info"])


@pytest.mark.parametrize("cov_a,e146", [(None, "Unknown"), (500000, "Yes"), (None, "No")])
def test_a_prefilled_county_and_a_typed_one_give_every_carrier_the_same_verdict(live, cov_a, e146):
    _, _, typed = run(live, "typed", cov_a, e146)
    _, _, pre = run(live, "prefilled", cov_a, e146)
    assert {c: r["status"] for c, r in typed.items()} == {c: r["status"] for c, r in pre.items()}
    assert len(typed) >= 25 and sum(1 for r in typed.values() if r.get("rules_table")) >= 20


@pytest.mark.parametrize("untick,status", [(("county",), "INSUFFICIENT_INFORMATION"),
                                           (("dwelling_amount",), "INSUFFICIENT_INFORMATION"),
                                           (("county", "dwelling_amount"), "ELIGIBLE")])
def test_the_only_way_to_liams_eligible_is_both_boxes_unticked(live, untick, status):
    pd, kw, res = run(live, "prefilled", None, "Unknown", untick=untick)
    assert pd["county"] == "Harris" and not set(untick) & set(kw["checked_topics"])
    assert res[CHUBB]["status"] == status
