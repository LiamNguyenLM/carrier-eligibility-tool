"""Round 36 step 5 (Liam, 2026-10-10): agents see display names ("SageSure Auros (HO3)", "Swyfft Benchmark
Admitted (HO3)", "NatGen Custom360 (HO3)", ...) on the cards, the Could Not Be Checked lines, the placement
panel and Ask the Guides, with the guide's date in each card's Details. Prompts, citations and logs keep
program names. Zero API."""
import json
import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import cards  # noqa: E402
import data_defects  # noqa: E402
import display_names  # noqa: E402
import eligibility_check as ec  # noqa: E402
import placement  # noqa: E402

pytestmark = pytest.mark.retrieval
APP = os.path.join(ROOT, "app.py")


@pytest.mark.parametrize("program,name", [("Sage_-_Auros_HO3", "SageSure Auros (HO3)"),
                                          ("Swyfft_-_Benchmark_(Admitted)_HO3", "Swyfft Benchmark Admitted (HO3)"),
                                          ("NatGen_Custom360_HO3_-_06.25.2026", "NatGen Custom360 (HO3)")])
def test_liams_three_examples(program, name):
    assert display_names.display_name(program) == name


def test_every_program_on_file_has_a_name_and_no_two_share_one():
    programs = set(ec.get_all_carriers()) | data_defects.expected_programs()
    assert programs <= set(display_names.DISPLAY), sorted(programs - set(display_names.DISPLAY))
    names = list(display_names.DISPLAY.values())
    assert len(names) == len(set(names))
    for name in names:
        assert "_" not in name and not re.search(r"\d{2}\.\d{2}\.\d{2}", name), name


@pytest.mark.parametrize("program,name", [("Acme_-_Gold_HO6_-_03.01.2027", "Acme Gold (HO6)"),
                                          ("New_Carrier_DP-3", "New Carrier (DP3)"),
                                          ("Plainname", "Plainname")])
def test_a_new_upload_gets_a_name_from_its_file_name(program, name):
    assert display_names.display_name(program) == name


@pytest.mark.parametrize("program,line", [
    ("CHUBB_HO_-_05.22.2026", "Guide dated 05/22/2026 (file: CHUBB_HO_-_05.22.2026)"),
    ("Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3", "Guide dated 07/06/2026 (file: Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3)"),
    ("Allied_Trust_HO3", "Guide date: not in the file name (file: Allied_Trust_HO3)"),
])
def test_the_guide_line(program, line):
    assert display_names.guide_line(program) == line


def test_a_verdict_cards_details_name_the_guide_and_other_details_are_unchanged():
    rec = {"carrier": "Sage_-_Auros_HO3", "status": "INELIGIBLE", "reasons": ["only"], "citations": [], "notes": ""}
    assert cards.details_html(rec) == ""                                   # as before
    d = cards.details_html(rec, guide=True)
    assert "<p><b>Guide</b></p>" in d and "Guide date: not in the file name (file: Sage_-_Auros_HO3)" in d


def test_could_not_be_checked_lines_use_the_display_name():
    assert cards.warning_line({"carrier": "Liberty_Mutual_HO6_-_02.21.2026", "reasons": ["Wrong document."]}) == \
        "**Liberty Mutual (HO6)** — Wrong document."


def test_the_placement_panel_shows_display_names():
    p = {"title": "Where we usually place homes like this", "usual": "",
         "picks": [{"market": "Sage", "programs": ["Sage_-_Auros_HO3", "Sage_-_SURE_HO-3_-_01.31.2026"],
                    "held": None, "reason": None, "fit": None}]}
    assert "1. **Sage** — SageSure Auros (HO3), SageSure SURE (HO3)" in placement.panel_markdown(p)


def test_the_cards_show_display_names_and_the_prompt_and_log_keep_program_names(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    log = tmp_path / "usage.jsonl"
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(log))
    seen = {}

    def fake(system, user, max_tokens):
        seen.setdefault("users", []).append(user)
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), {
            "input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    monkeypatch.setattr(ec, "_complete", fake)
    at = AppTest.from_file(APP, default_timeout=120)
    at.session_state["authenticated"] = True
    at.run()
    at.text_input(key="zip").input("77002").run()
    at.selectbox(key="dwelling_type").select("House").run()
    at.button(key="submit").click().run()
    assert not at.exception
    labels = [e.label for e in at.expander]
    assert "SageSure Auros (HO3)" in labels and "Progressive (HO3)" in labels
    assert not any("_" in l for l in labels), labels
    # the prompt still names programs; the model's answer is matched on them
    assert any("Sage_-_Auros_HO3" in u or "Progressive_HO3_-_04.01.2026" in u for u in seen["users"])
    # (the guides' own text says "SageSure"; the display names themselves never reach the model)
    prompt = " ".join(seen["users"])
    assert "SageSure Auros (HO3)" not in prompt and "Progressive (HO3)" not in prompt
