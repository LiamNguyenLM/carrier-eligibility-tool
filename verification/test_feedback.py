"""Round 36 step 6 (Liam, 2026-10-10): "This looks wrong" on every card -- an optional comment and a choice of
should be Eligible / Ineligible / Refer / not sure -- appended to carrier_docs_db/feedback_log.jsonl with the
usage log's atomic write: time, app version, property details as entered, carrier, verdict, reasons, deciding
rows, model, choice, comment, and the optional "Your name". The Manage Carriers tab downloads it as CSV and
counts this week's reports. Never blocks or slows a check. Zero API."""
import csv
import datetime
import io
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import eligibility_check as ec  # noqa: E402
import feedback  # noqa: E402

pytestmark = pytest.mark.retrieval
APP = os.path.join(ROOT, "app.py")
PD = {"zip": "77248", "county": "Harris", "ppc": "5", "year_built": 1994, "dwelling_type": "House",
      "dog_breeds": [], "solar_panels": "No"}
REC = {"carrier": "Progressive_HO3_-_04.01.2026", "status": "ELIGIBLE", "flaw_count": 0, "rules_table": True,
       "reasons": ["Rules table: 7 rule(s) decided from the form pass; none fails."], "citations": [],
       "missing_info": [], "notes": "See [PRO-072].",
       "also_confirm": ["[PRO-072] New business is not accepted in Hidalgo or Webb county. (blank County; confirm)",
                        "[PRO-088] Coverage A dwelling limits ... (blank Coverage A; confirm)"]}


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "feedback_log.jsonl"
    monkeypatch.setenv("ELIGIBILITY_FEEDBACK_LOG", str(p))
    return p


def _lines(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")] if p.exists() else []


def test_a_report_holds_everything_needed_to_replay_it(log):
    feedback.append(feedback.record(REC, PD, "Should be Refer", "  Hidalgo rule should refer  ", name="Liam",
                                    model="claude-haiku-5-5", display_name="Progressive (HO3)"))
    (line,) = _lines(log)
    assert set(line) == {"ts", "app_version", "name", "property_details", "carrier", "display_name", "verdict",
                         "reasons", "deciding_rows", "model", "rules_table", "choice", "comment"}
    assert line["property_details"] == PD and line["carrier"] == REC["carrier"] and line["verdict"] == "ELIGIBLE"
    assert line["deciding_rows"] == ["PRO-072", "PRO-088"]
    assert line["choice"] == "Should be Refer" and line["comment"] == "Hidalgo rule should refer"
    assert line["name"] == "Liam" and line["model"] == "claude-haiku-5-5" and line["app_version"]


@pytest.mark.parametrize("choice", ["Should be Eligible", "Should be Ineligible", "Should be Refer", "Not sure"])
def test_every_choice_is_kept(log, choice):
    feedback.append(feedback.record(REC, PD, choice))
    assert _lines(log)[-1]["choice"] == choice


def test_an_unexpected_choice_is_not_sure_and_blank_name_and_comment_are_empty(log):
    feedback.append(feedback.record(REC, PD, None))
    line = _lines(log)[-1]
    assert line["choice"] == "Not sure" and line["name"] == "" and line["comment"] == ""


def test_the_app_version_is_railways_commit_when_set(monkeypatch):
    feedback.app_version.cache_clear()
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "8113499abcdef")
    assert feedback.app_version() == "8113499"
    feedback.app_version.cache_clear()
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA")
    assert feedback.app_version() not in ("", None)
    feedback.app_version.cache_clear()


def test_a_broken_log_never_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("ELIGIBILITY_FEEDBACK_LOG", str(tmp_path))       # a directory: the open() fails
    feedback.append(feedback.record(REC, PD, "Not sure"))


def test_reports_from_many_processes_are_all_whole_lines(log):
    code = ("import sys; sys.path.insert(0, %r); import feedback\n"
            "for i in range(20): feedback.append(feedback.record({'carrier': 'C%%d' %% i, 'status': 'ELIGIBLE'}, "
            "{'note': 'x' * 2000}, 'Not sure', 'comment, with \"quotes\"\\nand a newline'))") % ROOT
    procs = [subprocess.Popen([sys.executable, "-c", code], env=dict(os.environ)) for _ in range(8)]
    assert all(p.wait(timeout=300) == 0 for p in procs)
    lines = _lines(log)
    assert len(lines) == 160 and all(l["property_details"]["note"] == "x" * 2000 for l in lines)


def test_the_csv_has_one_row_per_report_whatever_the_comment_holds(log):
    feedback.append(feedback.record(REC, PD, "Should be Refer", 'a, "quoted"\ncomment', name="Ann"))
    feedback.append(feedback.record(dict(REC, status="INELIGIBLE"), PD, "Should be Eligible"))
    rows = list(csv.DictReader(io.StringIO(feedback.to_csv())))
    assert len(rows) == 2 and tuple(rows[0]) == feedback.CSV_COLUMNS
    assert rows[0]["comment"] == 'a, "quoted"\ncomment' and rows[0]["deciding_rows"] == "PRO-072 | PRO-088"
    assert json.loads(rows[0]["property_details"]) == PD and rows[1]["verdict"] == "INELIGIBLE"


def test_this_weeks_count_starts_on_monday_utc():
    now = datetime.datetime(2026, 10, 10, 12, tzinfo=datetime.timezone.utc)        # a Saturday
    lines = [{"ts": "2026-10-04T23:59:59+00:00"}, {"ts": "2026-10-05T00:00:00+00:00"},
             {"ts": "2026-10-10T11:00:00+00:00"}, {}]
    assert feedback.week_start(now).isoformat() == "2026-10-05T00:00:00+00:00"
    assert feedback.count_this_week(lines, now) == 2


# ---------------------------------------------------------------- the app

def _records():
    return [dict(REC), {"carrier": "Sage_-_Auros_HO3", "status": "INSUFFICIENT_INFORMATION", "flaw_count": 0,
                        "reasons": ["County hold"], "citations": [], "missing_info": ["County -- x"], "notes": ""},
            {"carrier": "Centauri_-_HO3_-_05.01.2026", "status": ec.GUIDE_UNAVAILABLE,
             "reasons": ["The guide on file has no readable text."], "citations": [], "missing_info": [], "notes": ""}]


@pytest.fixture
def app(monkeypatch, log):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: [dict(r) for r in _records()])
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    at.selectbox(key="dwelling_type").select("House").run()
    return at


def test_every_card_has_the_control_and_the_check_writes_nothing(app, log):
    app.button(key="submit").click().run()
    assert not app.exception
    seq = app.session_state["check_seq"]
    for c in _records():
        assert app.radio(key=f"fb_choice_{seq}_{c['carrier']}").options == list(feedback.CHOICES)
    assert _lines(log) == []


def test_sending_writes_one_line_with_the_name_choice_and_comment(app, log):
    app.text_input(key="tester_name").input("Liam").run()
    app.button(key="submit").click().run()
    key = f"{app.session_state['check_seq']}_Progressive_HO3_-_04.01.2026"
    app.radio(key=f"fb_choice_{key}").set_value("Should be Refer")
    app.text_area(key=f"fb_comment_{key}").input("Hidalgo is a referral")
    app.button(key=f"FormSubmitter:fb_form_{key}-Send").click().run()
    assert not app.exception
    (line,) = _lines(log)
    assert line["name"] == "Liam" and line["choice"] == "Should be Refer" and line["comment"] == "Hidalgo is a referral"
    assert line["carrier"] == "Progressive_HO3_-_04.01.2026" and line["verdict"] == "ELIGIBLE"
    assert line["property_details"]["dwelling_type"] == "House" and line["deciding_rows"][0] == "PRO-072"
    # the name is remembered for the session
    assert app.text_input(key="tester_name").value == "Liam"


def test_the_manage_tab_counts_this_week_and_offers_the_csv(app, log):
    app.run()
    assert any("0** \"This looks wrong\" reports this week" in m.value for m in app.markdown)
    feedback.append(feedback.record(REC, {}, "Not sure"))
    app.run()
    assert any("1** \"This looks wrong\" reports this week" in m.value and "1 in all" in m.value for m in app.markdown)
