"""Round 36 step 7 (Liam, 2026-10-10): a collapsible "About this tool (testing)" box at the top of the form --
5-6 plain lines: what it checks (verdicts come from the carriers' guides), blank means unknown, what Held and
Confirm mean, the placement panel is our own history (not prices), use "This looks wrong". Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytestmark = pytest.mark.retrieval
APP = os.path.join(os.path.dirname(__file__), "..", "app.py")


@pytest.fixture(scope="module")
def at():
    from streamlit.testing.v1 import AppTest
    a = AppTest.from_file(APP, default_timeout=60)
    a.session_state["authenticated"] = True
    a.run()
    return a


def test_the_box_is_the_first_thing_on_the_form_and_starts_closed(at):
    assert not at.exception
    box = at.expander[0]
    assert box.label == "About this tool (testing)"
    assert box.proto.expanded is False


def test_it_says_the_six_things_in_plain_lines(at):
    text = at.expander[0].markdown[0].value
    lines = [l for l in text.splitlines() if l.strip()]
    assert 5 <= len(lines) <= 6
    for words in ("underwriting guide", "Blank means unknown", "Held", "Confirm", "not prices",
                  "This looks wrong"):
        assert words in text, words
