"""Round 37 follow-up 2 (Liam, 2026-10-11): reason lines lost words when row IDs were hidden -- SageSure Auros "…is
unknown; and apply only if it is.", SURE / SafePort "the FPC C limit in and the to criteria apply only if…", Chubb "the
Coastal Areas decline in and pre-approval in do not apply." Now a held rules-table card leads with code's own reason
(held_reason), a model reason that cites rows becomes those rows' rules, and an ID left inside a sentence reads "the
guide's rule". Chubb on Harris says the guide restricts all of Harris County; the internal "Rules table: the pilot
answer said ..." note is gone; the prompt says the form asks about losses and electrical. Zero API."""
import json
import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import cards  # noqa: E402
import confirm_topics as ct  # noqa: E402
import eligibility_check as ec  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
APP = os.path.join(ROOT, "app.py")
DANGLING = re.compile(r"\bin and\b|\bthe to\b|; and\b|\s{2,}|\bin (do|apply|are|is)\b|\bthe (criteria|rules?) (apply|do)\b")

# Liam's three, as the model wrote them (IDs inline)
GARBLED = [
    ("The station distance is unknown; [SAG-077] and [SAG-078] apply only if it is.",
     "The station distance is unknown; the guide's rules apply only if it is."),
    ("Unknown station distance: the FPC C limit in [SUR-091] and the [SUR-114] to [SUR-117] criteria apply only if the "
     "station is over 5 miles.",
     "Unknown station distance: the FPC C limit in the guide's rule and the guide's criteria apply only if the "
     "station is over 5 miles."),
    ("Not Coastal, so the Coastal Areas decline in [CHU-043] and pre-approval in [CHU-044] do not apply.",
     "Not Coastal, so the Coastal Areas decline in the guide's rule and pre-approval in the guide's rule do not apply."),
]


@pytest.mark.parametrize("raw,shown", GARBLED)
def test_an_id_inside_a_sentence_becomes_the_guides_rule_never_a_hole(raw, shown):
    assert cards.agent_text(raw) == shown
    assert not DANGLING.search(shown)


@pytest.mark.parametrize("raw,shown", [
    ("[FOR-078] declines: Foremost is not written in Harris.", "Foremost is not written in Harris."),
    ("Coverage (not eligibility): [ALL-045] Shingles need 3/4 life left.", "Coverage (not eligibility): Shingles need 3/4 life left."),
    ("ALL-064 applies.", "The guide's rule applies."),
])
def test_an_id_used_as_a_label_still_goes(raw, shown):
    assert cards.agent_text(raw) == shown


def test_a_model_reason_citing_rows_becomes_their_rules():
    rec = {"reasons": ["Not Coastal, so the decline in [CHU-043] does not apply.", "PPC 5 is fine."]}
    rv.readable_reasons(rec)
    assert rec["reasons"] == ["This guide: " + rv._rules()["CHU-043"]["Plain rule"], "PPC 5 is fine."]


def test_held_reasons():
    harris = {"CHU-043": ("OPEN", "Chubb territory"), "CHU-044": ("OPEN", "Chubb territory")}
    assert rv.held_reason(harris, ["CHU-043", "CHU-044"]) == (
        "Chubb restricts all of Harris County (unacceptable in 1A, pre-approval in 1B/1C/1E); the form can't tell "
        "which area.")
    fpc = {"SAG-076": ("OPEN", "station distance if not given; visibility, alarm, access, fire losses"),
           "SAG-078": ("OPEN", "station / hydrant distance if not given")}
    assert rv.held_reason(fpc, ["SAG-076", "SAG-078"]) == (
        "Held: if the fire station is more than 5 miles away, this guide's higher-risk fire protection rules apply "
        "(for example, the home must be under 25 years old). Confirm the distance.")
    other = {"ALL-030": ("OPEN", "pool fence height if not given")}
    text = rv.held_reason(other, ["ALL-030"])
    assert text.startswith("Held: the form does not give pool fence height. This guide: ") and text.endswith(" Confirm it.")
    assert not DANGLING.search(text) and "[" not in text


def test_the_prompts_say_the_form_asks_about_losses_and_electrical():
    for prompt in (ec.SYSTEM_INSTRUCTIONS, rv.PILOT_INSTRUCTION):
        assert "losses in the last 5 years" in prompt and "the electrical system" in prompt
        assert "never say the form does not ask it" in prompt
    assert "the 3-year loss history (the form's optional losses question)" in ec._CHUBB_COVERAGE_A_ITEM


@pytest.mark.parametrize("rid", ["ORI-049", "NCD-135"])
def test_a_commercial_exposure_nearby_is_the_site_not_a_business_on_the_premises(rid):
    r = rv._rules()[rid]
    assert ct.topic_of(r["Plain rule"], r["Topic"]) == "site"


# ---------------------------------------------------------------- Liam's page

SAYS = {
    "Sage_-_Auros_HO3": ("The station distance is unknown; [SAG-076] and [SAG-078] apply only if it is.",
                         ["Driving distance to the fire station"]),
    "Sage_-_SURE_HO-3_-_01.31.2026": (GARBLED[1][0], ["Driving distance to the fire station"]),
    "Sage_-_SafePort_HO-3_-_01.31.2026": (GARBLED[1][0].replace("SUR-", "SFP-"), []),
    "CHUBB_HO_-_05.22.2026": (GARBLED[2][0] + " Losses and electrical are not asked by the form.", []),
}


@pytest.fixture
def page(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_PLACEMENT", "1")
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        recs = [{"carrier": n, "status": "INSUFFICIENT_INFORMATION" if n in SAYS else "ELIGIBLE", "flaw_count": 0,
                 "reasons": [SAYS.get(n, ("Meets [ALL-110] and the [ALL-111] to [ALL-112] rules.", []))[0]],
                 "citations": [], "missing_info": SAYS.get(n, ("", []))[1], "notes": ""} for n in names]
        return json.dumps({"carriers": recs}), {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0,
                                                "cache_creation_input_tokens": 0}
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
    at.button(key="submit").click().run()
    assert not at.exception
    return at


def _texts(at):
    out = []
    for kind in ("markdown", "caption", "warning", "info", "error", "success"):
        for el in getattr(at, kind):
            v = re.sub(r"<details><summary>Rule IDs</summary>.*?</details>", "", str(el.value), flags=re.S)
            out += [re.sub(r"<[^>]+>", " ", line) for line in re.split(r"</li>|\n", v)]
    return [" ".join(t.split()) if "  " not in t.strip() else t.strip() for t in out]


def test_no_agent_facing_sentence_has_a_hole_where_an_id_was(page):
    # ("Fill it in and check again" is English, not a hole)
    bad = [t for t in _texts(page) if re.search(r"(?<!\bit )\bin and\b|\bthe to\b|; and\b|\bin (do|apply|are|is)\b", t)]
    assert bad == []
    shown = [str(el.value) for el in page.markdown]
    assert not any("Rules table: the pilot answer" in v for v in shown)
    assert not any(re.search(r"\b[A-Z]{3}-\d{3}\b", re.sub(r"<details><summary>Rule IDs</summary>.*?</details>", "", v,
                                                          flags=re.S)) for v in shown
                   if not v.startswith("- "))      # (the Manage tab lists program names, which have no row IDs)


def test_the_chubb_and_sage_cards_on_liams_harris_profile(page):
    lines = [m.value for m in page.markdown]
    assert ("**Insufficient information** — Chubb restricts all of Harris County (unacceptable in 1A, pre-approval in "
            "1B/1C/1E); the form can't tell which area. Coverage A is also needed.") in lines
    assert ("**Insufficient information** — Held: if the fire station is more than 5 miles away, this guide's "
            "higher-risk fire protection rules apply (for example, the home must be under 25 years old). Confirm the "
            "distance.") in lines
    chubb_missing = next(m for m in lines if m.startswith("**Missing:**") and "Chubb territory" in m)
    assert "Harris County 1A" in chubb_missing and "Harris County 1B, 1C and 1E" in chubb_missing
    assert not any("not asked by the form" in m and "osses" in m for m in lines)
