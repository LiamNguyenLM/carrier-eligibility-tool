"""Round 41 A5 (Liam, 2026-10-17): the PPC field offers the split classes 1X-8X. Where a guide names them, it decides
how they rate (NatGen Custom360 HO3 and its landlord DP3: "*Includes all PC 9 or 1X - 8X variations", so PC 9);
where a guide does not mention split classes, its rules read the number and the card adds the confirm "Split class
(X): check how this carrier rates it." Zero API."""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import confirm_topics as ct  # noqa: E402
import eligibility_check as ec  # noqa: E402
import intake_fields  # noqa: E402
import rules_evaluator as rv  # noqa: E402
import structured_rules  # noqa: E402

pytestmark = pytest.mark.retrieval
NG, NGD = "NatGen_Custom360_HO3_-_09.02.2026", "NatGen_Custom360_DP3_-_06.25.2026"
HOME = {"year_built": 2005, "roof_age": 8, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "PVC", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "dog_breeds": [], "solar_panels": "No", "ppc": "6X",
        "fire_station_miles": 4.0, "hydrant_1000ft": "Yes", "county": "Bexar", "zip": "78201",
        "dwelling_amount": 400000, "dwelling_type": "House", "units_in_building": "1", "losses_5yr": "0",
        "electrical": ["Circuit breakers"]}
LANDLORD = dict(HOME, occupancy_type="Tenant Occupied", ownership_type="Individual Owner")
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def test_the_form_offers_1x_to_8x_and_the_page_reads_the_list():
    assert [c for c in intake_fields.PPC_CHOICES if c.endswith("X")] == [f"{n}X" for n in range(1, 9)]
    assert {"N/A", "8A", "8B", "9", "10"} <= set(intake_fields.PPC_CHOICES)
    assert "intake_fields.PPC_CHOICES" in open(os.path.join(HERE, "..", "app.py"), encoding="utf-8").read()


@pytest.mark.parametrize("value,n", [("6X", 6), ("6x", 6), (" 1X ", 1), ("8X", 8), ("6", None), ("8B", None),
                                     ("10", None), ("N/A", None), ("", None), (None, None), ("9X", None)])
def test_a_split_class_is_read_as_its_number(value, n):
    assert intake_fields.ppc_split_class(value) == n


@pytest.mark.parametrize("ppc", ["6X", "3X"])
def test_natgen_reads_a_split_class_as_pc_9(ppc):
    o = rv.evaluate_carrier(NG, dict(HOME, ppc=ppc, fire_station_miles=12.0))
    assert o["NC3-038"][0] == "FAIL"                       # PC 9-10 more than 10 road miles from the station
    assert rv.evaluate_carrier(NG, dict(HOME, ppc=ppc[0], fire_station_miles=12.0))["NC3-038"][0] == "N/A"


@pytest.mark.parametrize("ppc", ["6X", "8X"])
def test_natgens_landlord_guide_reads_a_split_class_as_pc_9(ppc):
    o = rv.evaluate_carrier(NGD, dict(LANDLORD, ppc=ppc, dwelling_amount=800000))
    assert o["NCD-028"][0] == "FAIL" and o["NCD-027"][0] == "N/A"   # the PC 9 table, not PC 1-8


@pytest.mark.parametrize("wb", ["Sage SURE HO-3", "Allied Trust HO3", "The Hartford HO3"])
def test_a_guide_without_split_classes_reads_the_number_with_a_confirm(wb):
    item = rv.split_class_item(wb, dict(HOME, ppc="6X"))
    assert item["say"] == "Split class (6X): check how this carrier rates it."
    assert ct.topic_of(item["rule"], item["category"]) == "split_class"
    assert rv.split_class_item(wb, dict(HOME, ppc="6")) is None


@pytest.mark.parametrize("wb", list(rv.SPLIT_CLASS_AS))
def test_a_guide_that_rates_split_classes_gets_no_confirm(wb):
    assert rv.split_class_item(wb, dict(HOME, ppc="6X")) is None


def test_the_sage_fpc_table_reads_a_split_class_as_its_number():
    assert structured_rules.sage_family_fpc_eligibility("6X", 3.0, 1000) == \
        structured_rules.sage_family_fpc_eligibility("6", 3.0, 1000)


@pytest.fixture
def run(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))

    def fake(system, user, max_tokens):
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    monkeypatch.setattr(ec, "_complete", fake)
    return lambda pd: {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}


def test_on_the_page_every_rules_table_card_but_natgens_asks_about_the_split_class(run):
    res = run(HOME)
    says = {c: [i for i in r.get("confirm_items") or [] if i.get("say", "").startswith("Split class (6X)")]
            for c, r in res.items() if r.get("rules_table")}
    assert says and not says.get(NG)
    without = [c for c, s in says.items() if not s and c != NG]
    assert without == [], without
    items = ct.card_items(res["Allied_Trust_HO3"], HOME)
    assert "Split class (6X): check how this carrier rates it." in [i["text"] for i in items]


def test_no_split_class_no_confirm(run):
    res = run(dict(HOME, ppc="6"))
    assert not [c for c, r in res.items() for i in r.get("confirm_items") or [] if i.get("say", "").startswith("Split")]
