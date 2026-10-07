"""Round 26 step 7 (Liam's live check, 2026-10-05): his copy of the page showed
the Insufficient, Not Eligible and Could Not Be Checked sections two or three
times. These tests count what the app actually renders. Zero API: the check
is answered by a fake."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402

pytestmark = pytest.mark.retrieval

APP = os.path.join(os.path.dirname(__file__), "..", "app.py")
HEADERS = ("### Eligible", "### Refer to Underwriting", "### Insufficient Information",
           "### Not Eligible", "### Could Not Be Checked")


def _records():
    def rec(c, status, **kw):
        base = {"carrier": c, "status": status, "flaw_count": 1 if status == "INELIGIBLE" else 0,
                "reasons": ["a reason"], "citations": [], "missing_info": [], "notes": ""}
        base.update(kw)
        return base
    return [rec("Travelers_HO3_-_06.12.2026", "ELIGIBLE"),
            rec("CHUBB_HO_-_05.22.2026", "REFER"),
            rec("TWICO_HO3", "INSUFFICIENT_INFORMATION", missing_info=["Distance to fire station"]),
            rec("Sage_-_Auros_HO3", "INELIGIBLE"),
            rec("Centauri_-_HO3_-_05.01.2026", ec.GUIDE_UNAVAILABLE, reasons=["The guide on file has no readable text."],
                notes=""),
            rec("Foremost_DP3_and_HO3_-_07.01.2026", ec.NOT_EVALUATED,
                reasons=["No answer came back for this carrier in this check -- run the check again."],
                notes="This carrier was in the check, but the model's answer left it out.")]


@pytest.fixture
def app(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: [dict(r) for r in _records()])
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    at.selectbox(key="dwelling_type").select("House").run()
    return at


def _counts(at):
    values = [m.value for m in at.markdown]
    return {h: values.count(h) for h in HEADERS}


def test_each_section_header_renders_once_per_check(app):
    app.button(key="submit").click().run()
    assert not app.exception
    assert _counts(app) == {h: 1 for h in HEADERS}


def test_a_second_check_in_the_same_session_still_renders_each_header_once(app):
    app.button(key="submit").click().run()
    app.button(key="submit").click().run()
    assert not app.exception
    assert _counts(app) == {h: 1 for h in HEADERS}


def test_a_widget_change_without_a_new_check_does_not_repeat_a_section(app):
    app.button(key="submit").click().run()
    app.number_input(key="year").set_value(1990).run()
    assert not app.exception
    # The results belong to the check that produced them; a changed input
    # clears them rather than showing stale ones. Never more than one.
    assert all(n <= 1 for n in _counts(app).values())


def test_could_not_be_checked_has_no_empty_bullet_and_no_empty_details(app):
    app.button(key="submit").click().run()
    warnings = [w.value for w in app.warning]
    assert any(w.startswith("**Centauri_-_HO3_-_05.01.2026** — The guide on file has no readable text.")
               for w in warnings)
    md = [m.value for m in app.markdown]
    # Centauri has nothing beyond its warning line: no Details toggle for it;
    # Foremost's note is the only Details among these rows.
    details = [m for m in md if m.startswith("<details>")]
    assert not any("Centauri" in m for m in details)
    assert any("left it out" in m for m in details)
    assert not any("<li></li>" in m or "<li> </li>" in m for m in md)
    assert not any(m.strip() in ("-", "- ", "*") for m in md)


# Round 26 step 11 (Liam, 2026-10-05)
def test_the_form_says_once_what_is_and_is_not_checked(app):
    caption = "Only checked items are considered. Inspections and the condition of the home are not checked."
    assert [c.value for c in app.caption].count(caption) == 1


# Round 27 step 3 (Liam, 2026-10-06): the Fingerprint panel says whether the
# rules pilot is on, so Liam can confirm the Railway variable took effect.
@pytest.mark.parametrize("on,line", [(True, "**Rules pilot: ON (6 carriers)**"), (False, "**Rules pilot: OFF**")])
def test_the_fingerprint_panel_shows_the_rules_pilot_state(monkeypatch, on, line):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(ec, "RULES_PILOT", on)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    assert not at.exception
    shown = [m for m in at.markdown if m.value.startswith("**Rules pilot:")]
    assert [m.value for m in shown] == [line]
    assert 'exactly "1"' in (shown[0].help or "")


@pytest.mark.parametrize("value,on", [("1", True), ("true", False), ("yes", False), ("0", False), ("", False),
                                      (" 1", False)])
def test_only_exactly_1_turns_the_pilot_on(value, on):
    import subprocess
    env = dict(os.environ, ELIGIBILITY_RULES_PILOT=value, ANTHROPIC_API_KEY="x", OPENAI_API_KEY="x")
    out = subprocess.run([sys.executable, "-c", "import eligibility_check as e; print(e.RULES_PILOT)"],
                         cwd=os.path.join(os.path.dirname(__file__), ".."), env=env,
                         capture_output=True, text=True, timeout=300)
    assert out.stdout.strip().splitlines()[-1] == str(on), out.stderr[-500:]


# Round 27 step 6 (Liam's decision 4, 2026-10-06): the Sage batch has its own
# switch, exactly "1", effective only with the pilot on; the panel says so.
def test_the_fingerprint_panel_shows_the_sage_batch_state(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(ec, "RULES_PILOT", True)
    monkeypatch.setattr(ec, "RULES_SAGE_BATCH", True)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    assert not at.exception
    shown = [m.value for m in at.markdown if m.value.startswith("**Rules pilot:")]
    assert shown == ["**Rules pilot: ON (6 carriers) + Sage batch ON (6 more)**"]


@pytest.mark.parametrize("pilot,batch,on", [("1", "1", True), ("1", "true", False), ("1", " 1", False),
                                            ("1", "", False), ("0", "1", False), ("", "1", False)])
def test_the_sage_batch_needs_exactly_1_and_the_pilot(pilot, batch, on):
    import subprocess
    env = dict(os.environ, ELIGIBILITY_RULES_PILOT=pilot, ELIGIBILITY_RULES_SAGE_BATCH=batch,
               ANTHROPIC_API_KEY="x", OPENAI_API_KEY="x")
    out = subprocess.run([sys.executable, "-c", "import eligibility_check as e; print(e.RULES_SAGE_BATCH); "
                                                "print(e.rules_pilot_status_line())"],
                         cwd=os.path.join(os.path.dirname(__file__), ".."), env=env,
                         capture_output=True, text=True, timeout=300)
    flag, line = out.stdout.strip().splitlines()[-2:]
    assert flag == str(on), out.stderr[-500:]
    assert ("Sage batch" in line) == on
