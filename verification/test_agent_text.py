"""Round 37 step 2 (Liam, 2026-10-10): no internal labels where an agent reads -- no "rules table" badge, "Guide
date: <date>" or "Guide date: not stated" (never a file name), the placement panel names a program once, and no
row IDs (outside the card's collapsed "Rule IDs" line), program / file names or engine words on the results.
Zero API."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import cards  # noqa: E402
import display_names  # noqa: E402
import eligibility_check as ec  # noqa: E402
import placement  # noqa: E402

pytestmark = pytest.mark.retrieval
APP = os.path.join(os.path.dirname(__file__), "..", "app.py")


@pytest.mark.parametrize("raw,shown", [
    ("[FOR-078] declines: Foremost Choice Homeowners is not written in Harris.",
     "Foremost Choice Homeowners is not written in Harris."),
    ("[CHU-056] refers to underwriting: Primary houses need pre-approval.", "Primary houses need pre-approval."),
    ("[SAG-010] condition not met: Fence required.", "Condition not met: Fence required."),
])
def test_a_rules_reason_reads_without_its_row_and_label(raw, shown):
    assert cards.agent_text(raw) == shown


@pytest.mark.parametrize("raw,shown", [
    ("Chubb territory -- [CHU-043] Primary houses in Harris 1A are unacceptable.",
     "Chubb territory: Primary houses in Harris 1A are unacceptable."),
    ("Coverage (not eligibility): [ALL-045] Shingles need 3/4 life left.",
     "Coverage (not eligibility): Shingles need 3/4 life left."),
    ("Sage_-_Auros_HO3 held (rows SAG-076, SAG-078) on distance.", "SageSure Auros (HO3) held on distance."),
    ('Allied_Trust_HO3: [ALL-057] p.12: "Galvanized plumbing"', 'Allied Trust (HO3): p.12: "Galvanized plumbing"'),
])
def test_missing_items_notes_and_citations_lose_ids_and_program_names(raw, shown):
    assert cards.agent_text(raw) == shown


def test_the_rules_tables_own_summary_is_plain():
    assert cards.agent_text("Rules table: 7 rule(s) decided from the form pass; none fails.") == \
        "7 of this guide's rules were checked against the form; none rules it out."


@pytest.mark.parametrize("program,line", [("Progressive_HO3_-_04.01.2026", "Guide date: 04/01/2026"),
                                          ("TWICO_HO3", "Guide date: not stated")])
def test_the_guide_date_never_shows_a_file_name(program, line):
    assert display_names.guide_line(program) == line


def test_the_card_keeps_its_row_ids_on_one_collapsed_line():
    rec = {"carrier": "Allied_Trust_HO3", "status": "INELIGIBLE", "reasons": ["[ALL-057] declines: Galvanized."],
           "citations": ['Allied_Trust_HO3: [ALL-057] p.12: "q"'], "missing_info": [], "notes": "",
           "confirm_items": [{"row": "ALL-157", "category": "ACREAGE", "effect": "DECLINES", "rule": "Over 10 acres.",
                              "kind": "not_asked"}]}
    assert cards.rule_ids(rec) == ["ALL-057", "ALL-157"]
    assert cards.rule_ids_html(rec).startswith("<details><summary>Rule IDs</summary>")
    assert "ALL-057" not in cards.first_line_markdown(rec, {}) + cards.details_html(rec, guide=True)


@pytest.mark.parametrize("market,programs,line", [
    ("SageSure Auros", ["Sage_-_Auros_HO3"], "1. **SageSure Auros (HO3)**"),
    ("Swyfft Benchmark", ["Swyfft_-_Benchmark_(Admitted)_HO3", "Swyfft_-_Benchmark_(Surplus)_HO3"],
     "1. **Swyfft Benchmark Admitted (HO3), Swyfft Benchmark Surplus (HO3)**"),
    ("Progressive / ASI", ["Progressive_HO3_-_04.01.2026"], "1. **Progressive (HO3)**"),
    ("National General", ["NatGen_Custom360_HO3_-_09.02.2026"], "1. **National General** — NatGen Custom360 (HO3)"),
])
def test_the_placement_panel_names_a_program_once(market, programs, line):
    p = {"title": "Where we usually place homes like this", "usual": "",
         "picks": [{"market": market, "programs": programs, "held": "Held: confirm Chubb territory -- [CHU-043] x",
                    "reason": None, "fit": None}]}
    md = placement.panel_markdown(p)
    assert line in md.splitlines() and "CHU-043" not in md
    assert f"{market} — {display_names.display_name(programs[0])}" not in md or market == "National General"


# ---------------------------------------------------------------- the page

_ROW = re.compile(r"\b[A-Z]{3}-\d{3}\b")
_WORDS = re.compile(r"\b(map line|OPEN|N/A|FACT|SKIP|NONE|AMBIGUOUS|readings?|rules table|rule\(s\)|not in the file name)\b"
                    r"|\(file: |\.pdf\b")


@pytest.mark.parametrize("cov_a", [None, 500000])
def test_liams_results_page_carries_no_internal_labels(monkeypatch, tmp_path, cov_a):
    from streamlit.testing.v1 import AppTest
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_PLACEMENT", "1")
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "INSUFFICIENT_INFORMATION", "flaw_count": 0,
                                         "reasons": [f"{n} holds on the distance."], "citations": [],
                                         "missing_info": ["Distance to fire station"], "notes": ""} for n in names]}), {
            "input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    monkeypatch.setattr(ec, "_complete", fake)
    at = AppTest.from_file(APP, default_timeout=300)
    at.session_state["authenticated"] = True
    at.run()
    at.button(key="select_all").click().run()
    at.text_input(key="zip").input("77248").run()
    at.selectbox(key="ppc").set_value("5").run()
    at.selectbox(key="hydrant").set_value("Yes").run()
    at.number_input(key="year").set_value(1994).run()
    at.selectbox(key="dwelling_type").set_value("House").run()
    if cov_a:
        at.text_input(key="dwelling_amount").input(str(cov_a)).run()
    at.button(key="submit").click().run()
    assert not at.exception
    programs = re.compile("|".join(re.escape(p) for p in sorted(display_names.DISPLAY, key=len, reverse=True)))
    manage = {f"- {p}" for p in display_names.DISPLAY}            # the Manage tab's admin list keeps file names
    leaks = []
    for kind in ("markdown", "caption", "warning", "info", "error", "success"):
        for el in getattr(at, kind):
            text = str(el.value)
            if text in manage or text.startswith("**Rules pilot"):
                continue
            visible = re.sub(r"<details><summary>Rule IDs</summary>.*?</details>", "", text, flags=re.S)
            # round 40 (2026-10-16): Liam's own sentence on a guide-only card (round 39 step 2e) is agent text,
            # not an internal label; "rules table" anywhere else still is
            visible = visible.replace(display_names.GUIDE_ONLY_LINE, "")
            for rx in (_ROW, programs, _WORDS):
                leaks += [(kind, m.group(0), visible[max(0, m.start() - 60):m.end() + 30]) for m in rx.finditer(visible)]
    leaks += [("title", e.label, "") for e in at.expander if programs.search(e.label)]
    assert leaks == []
    assert "rules table" not in [c.value for c in at.caption]
    assert any("<summary>Rule IDs</summary>" in m.value for m in at.markdown)
