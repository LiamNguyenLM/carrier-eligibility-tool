"""Round 26 (Liam, 2026-10-05): Liam's live check on Railway (27870a0) as a
fixed profile. Zero API: the model call is answered by a fake that returns
what the live run returned, so these tests pin the pipeline's handling of it.

LIVE: PPC 3; Owner Occupied; Individual; Year Built 2007; No Pool; PVC;
Solar Yes; ZIP 75094 -> Collin; House. Everything else unchecked."""
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402
from profiles import LIVE_PROFILE, LIVE_CHECKED  # noqa: E402

pytestmark = pytest.mark.retrieval

USAGE = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}
SAGE_FIVE = ["Sage_-_Auros_HO3", "Sage_-_SURE_HO-3_-_01.31.2026", "Sage_-_SafePort_HO-3_-_01.31.2026",
             "Sage_-_Wilshire_HO3_-_12.02.2025", "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026"]


def run_live(answer, profile=None, checked=None):
    """check_eligibility on LIVE with every carrier in the main prompt answered
    by answer(carrier) -> record fields. Returns ({carrier: record}, prompt)."""
    seen = {}

    def fake(system, user, max_tokens):
        seen["user"] = user
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)))
        recs = []
        for n in names:
            rec = {"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                   "citations": [], "missing_info": [], "notes": ""}
            rec.update(answer(n))
            recs.append(rec)
        return json.dumps({"carriers": recs}), dict(USAGE)

    real = ec._complete
    ec._complete = fake
    try:
        results = ec.check_eligibility(dict(profile or LIVE_PROFILE),
                                       checked_topics=list(checked or LIVE_CHECKED))
    finally:
        ec._complete = real
    return {r["carrier"]: r for r in results}, seen.get("user")


# What the live run returned for the Sage family: an INELIGIBLE on the
# territory for Trium, and Insufficient on fire-station items for the rest.
def live_sage_answer(name):
    if name.startswith("Sage_-_Trium"):
        return {"status": "INELIGIBLE", "flaw_count": 1,
                "reasons": ["Collin County is outside the stated territory."],
                "citations": [], "missing_info": []}
    if name in SAGE_FIVE:
        return {"status": "INSUFFICIENT_INFORMATION", "flaw_count": 0,
                "reasons": ["None states a flat ineligible outcome for PPC 3."],
                "missing_info": ["Driving distance to the responding fire station",
                                 "Distance to the nearest hydrant"]}
    return {}


# -- Step 1: buckets (Liam, 2026-10-05, decision A) --------------------------------
def test_the_five_sage_carriers_on_live_all_land_in_not_eligible():
    res, _ = run_live(live_sage_answer)
    buckets = ec.assign_buckets(list(res.values()))
    not_eligible = {r["carrier"] for r in buckets["not_eligible"]}
    assert set(SAGE_FIVE) <= not_eligible
    # Trium carries two flaws, the others one -- the split that put four of
    # them under "One Issue" on Liam's screen. It no longer matters.
    assert res[SAGE_FIVE[4]]["flaw_count"] == 2 and res[SAGE_FIVE[0]]["flaw_count"] == 1
    assert not any(r["carrier"] in SAGE_FIVE for r in buckets["refer"])


# -- Step 2: a code-decided verdict owns the card ----------------------------------
def test_sage_auros_on_live_shows_one_territory_reason_with_the_quote_and_no_missing_info():
    res, _ = run_live(live_sage_answer)
    r = res["Sage_-_Auros_HO3"]
    assert r["status"] == "INELIGIBLE"
    assert len(r["reasons"]) == 1
    assert r["reasons"][0].startswith("Collin County is outside this carrier's territory. The guide says:")
    assert '"' in r["reasons"][0]                            # the guide's own sentence, quoted
    assert r["missing_info"] == []
    assert not any("flat ineligible" in x for x in r["reasons"])
    # the model's own words are kept, off the card
    assert "None states a flat ineligible outcome for PPC 3." in r["diagnostics"]["model_reasons"]
    assert "Distance to the nearest hydrant" in r["diagnostics"]["model_missing_info"]


@pytest.mark.parametrize("carrier", SAGE_FIVE)
def test_every_sage_carrier_on_live_is_owned_by_the_territory_rule(carrier):
    res, _ = run_live(live_sage_answer)
    r = res[carrier]
    assert r["decided_by_code"] and r["missing_info"] == []
    assert [x for x in r["reasons"] if "outside this carrier's territory" in x] == r["reasons"]


def test_a_code_hold_keeps_its_missing_info_and_leads_with_the_code_reason():
    # County blank: the Sage county hold. A hold can still change, so the open
    # items stay; the code's reason is the first (and only) line.
    profile = dict(LIVE_PROFILE, county="", zip="")
    res, _ = run_live(lambda n: {"status": "ELIGIBLE", "reasons": ["PPC 3 is fine."],
                                 "missing_info": ["Distance to fire station"]}
                      if n == "Sage_-_Auros_HO3" else {}, profile=profile)
    r = res["Sage_-_Auros_HO3"]
    assert r["status"] == "INSUFFICIENT_INFORMATION"
    assert r["reasons"][0].startswith("No County given")
    assert any(m.startswith("County") for m in r["missing_info"])
    assert "Distance to fire station" in r["missing_info"]


def test_a_model_decided_record_is_untouched():
    res, _ = run_live(lambda n: {"status": "INSUFFICIENT_INFORMATION", "reasons": ["own reason"],
                                 "missing_info": ["own item"]} if n.startswith("Travelers") else {})
    t = [r for c, r in res.items() if c.startswith("Travelers")][0]
    assert t["reasons"] == ["own reason"] and t["missing_info"] == ["own item"]
    assert "diagnostics" not in t and not t.get("decided_by_code")


# -- Step 4: a citation must be a quote, from the carrier's own guide --------------
# Liam's message describes the live ARI_(HOA+) citation (commentary, not a
# quote, carrying ARI_(HOB)'s "Homes 0-20 years old") but does not quote it;
# these are built to that description, two phrasings of each failure.
HOB_SENTENCE = "Homes 0-20 years old are eligible for this program."
HOA_OWN = 'ARI_(HOA+): "Kerosene, coal, wood or solar as a source of fuel is unacceptable."'


def _ari(citations, status="ELIGIBLE"):
    return lambda n: ({"status": status, "flaw_count": 1 if status == "INELIGIBLE" else 0,
                       "reasons": ["The home is 19 years old."], "citations": citations}
                      if n == "ARI_(HOA+)" else {})


@pytest.mark.parametrize("bad", [
    "ARI_(HOA+): The program accepts homes 0-20 years old, so this 19-year-old home qualifies.",   # no quote
    'ARI_(HOA+): "Homes 0-20 years old" -- the home is 19, inside that range.',                    # commentary after
])
def test_a_citation_that_is_commentary_is_removed(bad):
    res, _ = run_live(_ari([bad, HOA_OWN]))
    r = res["ARI_(HOA+)"]
    assert r["citations"] == [HOA_OWN]
    assert "[Citation check] Removed 1 citation(s) that were not a quote" in r["notes"]
    assert r["status"] == "ELIGIBLE"                         # a note, never a status change


@pytest.mark.parametrize("hob", [f'ARI_(HOA+): "{HOB_SENTENCE}"', 'ARI_(HOA+): \u201cHomes 0-20 years old\u201d'])
def test_hobs_quote_under_hoas_label_is_removed_as_hobs(hob):
    res, _ = run_live(_ari([hob, HOA_OWN]))
    r = res["ARI_(HOA+)"]
    assert r["citations"] == [HOA_OWN]
    assert "belonging to another carrier (ARI_(HOB))" in r["notes"]


def test_an_adverse_verdict_resting_only_on_hobs_quote_is_downgraded():
    res, _ = run_live(_ari([f'ARI_(HOA+): "{HOB_SENTENCE}"'], status="INELIGIBLE"))
    r = res["ARI_(HOA+)"]
    assert r["status"] == "INSUFFICIENT_INFORMATION" and r["citations"] == []


def test_hobs_own_citation_of_the_same_sentence_stays():
    res, _ = run_live(lambda n: {"citations": [f'ARI_(HOB): "{HOB_SENTENCE}"']} if n == "ARI_(HOB)" else {})
    assert res["ARI_(HOB)"]["citations"] == [f'ARI_(HOB): "{HOB_SENTENCE}"']
    assert "[Citation check]" not in (res["ARI_(HOB)"].get("notes") or "")


# -- Step 5: stitch chunks that start mid-sentence; never hold on guide text -------
TWICO_FULL = ("Homes of unconventional construction including log, do-it-yourself, dome, shell, or homes "
              "using unconventional parts or not meeting building codes. This includes solar panels.")


def test_twicos_chunk_reaches_the_prompt_as_the_whole_sentence():
    _, prompt = run_live(lambda n: {})
    assert "meeting building codes. This includes solar panels." in prompt
    assert TWICO_FULL in ec.normalize_chunk_text(prompt) or TWICO_FULL in prompt


@pytest.mark.parametrize("text,stitched", [
    ("meeting building codes. This includes solar panels.", True),     # lowercase start
    (", or homes that are vacant.", True),                             # continuation mark
    ("Homes of unconventional construction including log.", False),    # a sentence start
    ("\u2022 Mobile homes and prefabricated homes.", False),           # a bullet
])
def test_only_a_chunk_that_starts_mid_sentence_is_stitched(text, stitched):
    assert ec.starts_mid_sentence(text) is stitched


def test_the_stitched_start_stops_at_the_sentence_break_and_is_capped():
    prev = "Earlier sentence. \u2022 Homes of unconventional construction including log, or not"
    assert ec.sentence_start_from(prev) == "Homes of unconventional construction including log, or not"
    long_prev = "word " * 200
    assert len(ec.sentence_start_from(long_prev)) <= ec._STITCH_CAP


def test_a_table_chunk_is_never_stitched():
    assert ec.stitched_text("TWICO_HO3", "meeting building codes.", is_table=True) == "meeting building codes."


@pytest.mark.parametrize("item", [
    "The complete sentence of the construction rule, which starts mid-sentence in the excerpt.",   # Liam's TWICO
    "The rest of the rule about unconventional construction.",
    "Applicable eligibility criteria not included in the retrieved excerpts.",                     # recorded
    "The complete roof-material table, including the row for architectural shingles.",            # recorded
])
def test_a_request_for_guide_text_never_holds_a_carrier(item):
    res, _ = run_live(lambda n: {"status": "INSUFFICIENT_INFORMATION", "missing_info": [item]}
                      if n == "TWICO_HO3" else {})
    r = res["TWICO_HO3"]
    assert r["status"] == "ELIGIBLE" and r["missing_info"] == []
    assert "[Excerpt check] Removed 1 request(s) for guide text" in r["notes"]


@pytest.mark.parametrize("item", [
    "For PPC 6, driving distance to the responding fire station and hydrant distance; its table is incomplete.",
    "Whether the roof is in good condition",          # not about guide text at all
])
def test_a_real_open_fact_is_not_mistaken_for_a_guide_text_request(item):
    assert not ec._is_guide_text_request(item)


# -- Step 6: condition standards are notes everywhere (Liam, 2026-10-05, D) --------
ORION = "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3"
ORION_LIVE_ITEM = ("Whether the plumbing system is in proper working condition and meets state "
                   "building codes")


def test_the_condition_sentence_is_in_the_prompt():
    s = ec.SYSTEM_INSTRUCTIONS
    assert "THE CONDITION OF THE HOME IS NOT CHECKED BY THIS TOOL." in s
    for kept in ("galvanized plumbing", "a roof older than 20 years", "no central heat", "unrepaired damage"):
        assert kept in s.split("THE CONDITION OF THE HOME")[1]


def test_orion_on_live_no_longer_holds_on_plumbing_condition():
    res, _ = run_live(lambda n: {"status": "INSUFFICIENT_INFORMATION", "missing_info": [ORION_LIVE_ITEM]}
                      if n == ORION else {})
    r = res[ORION]
    assert r["status"] == "ELIGIBLE" and r["missing_info"] == []
    assert "(condition of the home is not checked)" in r["notes"]


@pytest.mark.parametrize("item", [
    ORION_LIVE_ITEM,
    "Whether the roof is in good condition.",
    "Whether swimming pool is built to code",
    "Whether the property is well maintained and not unduly exposed to loss",
    "Confirm the mounted solar panels meet applicable building codes.",
    "Whether the yard is free of debris",
])
def test_a_condition_standard_is_stripped(item):
    assert ec._is_condition_request(item)


@pytest.mark.parametrize("item", [
    "Plumbing type (galvanized plumbing is ineligible)",
    "Whether the roof is older than 20 years",
    "Whether the home has central heat",
    "Whether the roof is in good condition and whether it has more than one overlay",
    "Roof condition and remaining life expectancy (must have at least 5 years)",
    "Driving distance to the responding fire station, to determine which PPC 3 conditions apply",
    "Homes with significant unrepaired damage",
])
def test_a_rule_about_a_material_or_a_fact_is_kept(item):
    assert not ec._is_condition_request(item)


def test_a_held_carrier_with_another_open_item_stays_held():
    res, _ = run_live(lambda n: {"status": "INSUFFICIENT_INFORMATION",
                                 "missing_info": [ORION_LIVE_ITEM, "Distance to fire station"]}
                      if n == ORION else {})
    r = res[ORION]
    assert r["status"] == "INSUFFICIENT_INFORMATION" and r["missing_info"] == ["Distance to fire station"]


# -- Step 8: the carrier enum -------------------------------------------------------
def test_the_schema_limits_carrier_to_the_programs_of_the_call():
    schema = ec._results_schema(["TWICO_HO3", "ARI_(HOB)"])
    carrier = schema["properties"]["carriers"]["items"]["properties"]["carrier"]
    assert carrier == {"type": "string", "enum": ["ARI_(HOB)", "TWICO_HO3"]}
    # the shared constant is not mutated
    assert "enum" not in ec.CARRIER_RESULTS_SCHEMA["properties"]["carriers"]["items"]["properties"]["carrier"]
    assert ec._results_schema(None) is ec.CARRIER_RESULTS_SCHEMA


def test_the_main_call_enum_is_exactly_the_carriers_in_its_prompt(monkeypatch):
    seen = {}

    def fake(system, user, max_tokens):
        seen["enum"] = list(getattr(ec._CALL, "carriers", None) or [])
        seen["prompt"] = set(re.findall(r"\n--- (.+?) \(page", user))
        return json.dumps({"carriers": []}), dict(USAGE)

    monkeypatch.setattr(ec, "_complete", fake)
    ec.check_eligibility(dict(LIVE_PROFILE), checked_topics=list(LIVE_CHECKED))
    assert seen["prompt"] and seen["prompt"] <= set(seen["enum"])
    assert not any("Occidental_HO3" in c or "Centauri_-_HO3" in c for c in seen["enum"])   # wrong guides
    assert ec._CALL.carriers is None                                                       # reset after


def test_the_enum_can_be_turned_off_for_measurement(monkeypatch):
    monkeypatch.setattr(ec, "CARRIER_ENUM", False)
    seen = {}
    monkeypatch.setattr(ec, "_complete", lambda s, u, m: (seen.setdefault("enum", getattr(ec._CALL, "carriers", None)),
                                                           (json.dumps({"carriers": []}), dict(USAGE)))[1])
    ec.check_eligibility(dict(LIVE_PROFILE), checked_topics=list(LIVE_CHECKED))
    assert seen["enum"] is None
