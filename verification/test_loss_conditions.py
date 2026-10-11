"""Round 38 step 3 (Liam, 2026-10-11): NatGen Custom360 DP3 was Not eligible on his LANDLORD profile (1 theft loss,
2022) on "Non-remediated mold, fire, vandalism, theft/burglary or flood losses in the last 5 years are ineligible" --
the form cannot say whether the loss was remediated. A loss row now decides from count, type and years only where the
guide's condition is just those; where it also turns on paid / $0, an amount, remediated or open, negligence, weather
vs non-weather or same-peril / per-location counts, an answer that could fail is a confirm naming the condition, and 0
losses still passes. 55 rows changed (rules_data/loss_electrical_lines.ROUND38_LOSS). Zero API."""
import csv
import itertools
import json
import os
import re
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rules_data"))
import eligibility_check as ec  # noqa: E402
import loss_electrical_lines as le  # noqa: E402
import rules_evaluator as rv  # noqa: E402

pytestmark = pytest.mark.retrieval
COUNTS = ["0", "1", "2", "3 or more"]
TYPES = [[], ["Water"], ["Fire"], ["Liability"], ["Wind or hail"], ["Theft"], ["Other"], ["Water", "Fire"],
         ["Liability", "Theft"], ["Wind or hail", "Water"], ["Fire", "Theft"]]
# rows whose guide condition the form cannot settle (paid, amount, remediated, weather, location...): never a decline
NEVER_FAIL = ["ALL-151", "SAG-112", "CHU-063", "CHU-073", "MER-087", "MER-088", "SUR-083", "SUR-084", "SFP-088", "SFP-089",
              "WIL-089", "WIL-090", "TRI-129", "TRI-130", "MKL-104", "ARA-066", "ARA-067", "ARB-069", "ARB-070",
              "FOR-106", "FOR-107", "TRV-012", "TRV-063", "TRV-066", "ODP-126", "SDP-063", "FDP-084", "FOD-035",
              "FOD-036", "CDP-099", "CDP-100", "CDP-102", "NCD-145", "NCD-146", "NCD-150", "STD-143", "STD-154",
              "STD-155", "STD-156"]
# rows whose condition is weather vs non-weather: they fail only when every loss is surely non-weather
WEATHER_SPLIT = ["ALL-147", "VAV-090", "VDP-052", "SBS-050", "STO-053", "SLL-071", "CHO-031"]


def _maps():
    out = {}
    for b in rv.BATCHES.values():
        with open(b["map"], encoding="utf-8-sig") as fh:
            out.update({m["row_id"]: m for m in csv.DictReader(l for l in fh if not l.startswith("#"))})
    return out


MAPS = _maps()


def _answers():
    for n in COUNTS:
        for types, in3 in itertools.product(TYPES if n != "0" else [[]], COUNTS if n != "0" else ["0"]):
            if COUNTS.index(in3) <= COUNTS.index(n):
                yield {"losses_5yr": n, "losses_3yr": in3, "loss_types": types}


def outcome(rid, a):
    return rv.evaluate_row(MAPS[rid], rv.facts(dict(a)))[0]


def test_the_audit_changed_55_rows_and_every_map_carries_them():
    assert len(le.ROUND38_LOSS) == 55
    for rid, test in le.ROUND38_LOSS.items():
        assert MAPS[rid]["test"] == test, rid


@pytest.mark.parametrize("rid", NEVER_FAIL)
def test_a_condition_the_form_cannot_settle_is_never_a_decline(rid):
    got = {json.dumps(a): outcome(rid, a) for a in _answers()}
    assert "FAIL" not in got.values(), [a for a, o in got.items() if o == "FAIL"][:3]
    assert outcome(rid, {"losses_5yr": "0"}) in ("PASS", "NOTE")


@pytest.mark.parametrize("rid", WEATHER_SPLIT)
def test_a_water_or_wind_loss_that_could_be_weather_never_fails_a_non_weather_rule(rid):
    for a in _answers():
        if set(a["loss_types"]) & {"Water", "Wind or hail", "Other"}:
            assert outcome(rid, a) != "FAIL", (rid, a)


@pytest.mark.parametrize("rid,answers", [
    ("ALL-147", dict(losses_5yr="2", losses_3yr="2", loss_types=["Liability", "Theft"])),   # surely not natural
    ("VDP-052", dict(losses_5yr="2", losses_3yr="2", loss_types=["Fire", "Theft"])),
    ("STD-144", dict(losses_5yr="2", losses_3yr="0", loss_types=["Theft"])),               # Steadily: 5 years exactly
])
def test_a_surely_failing_history_still_fails(rid, answers):
    assert outcome(rid, answers) == "FAIL"


@pytest.mark.parametrize("rid", ["STD-141", "STD-142", "STD-144", "STD-145", "STD-146", "FOD-035", "FOD-036"])
def test_no_losses_is_a_clear_pass_where_the_guide_counts_5_years(rid):
    assert outcome(rid, {"losses_5yr": "0"}) == "PASS"


def test_landlords_natgen_custom360_dp3_is_a_confirm_not_a_decline(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), {
            "input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    monkeypatch.setattr(ec, "_complete", fake)
    sys.path.insert(0, os.path.dirname(__file__))
    from test_held_reasons import LANDLORD
    res = {r["carrier"]: r for r in ec.check_eligibility(dict(LANDLORD))}
    natgen = res["NatGen_Custom360_DP3_-_06.25.2026"]
    assert natgen["status"] != "INELIGIBLE"
    item = next(x for x in natgen["confirm_items"] if x["row"] == "NCD-150")
    assert item["kind"] in ("not_asked", "blank")
    assert rv.evaluate_carrier("NatGen_Custom360_DP3_-_06.25.2026", dict(LANDLORD))["NCD-150"] == \
        ("NOTE", "confirm: any mold fire vandalism theft or flood loss in the last 5 years was fully remediated")
