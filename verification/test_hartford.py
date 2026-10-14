"""Round 39 step 1 (Liam's decisions, 2026-10-12): The Hartford HO3 rules table, zero API.

CFIG writes the Hartford HO3 and its tenant-occupied HO3, Rental Property Protection Plus (RPP+): a rental the
owner does not live in, covered only when the owner's own home is with The Hartford. Pools: allowed, but no diving
boards (CFIG experience, Jonathan -- rules_data/cfig_knowledge.csv). The guide: verification/fixtures/
The_Hartford_HO3_-_07.09.2026.pdf (effective 07/09/2026). Cases a-k are Liam's, each through check_eligibility with
a fake model; each names its deciding row."""
import collections
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "rules_data"))
sys.path.insert(0, HERE)
import build_hartford_map as builder  # noqa: E402
import display_names  # noqa: E402
import eligibility_check as ec  # noqa: E402
import hold_guard  # noqa: E402
import intake_fields  # noqa: E402
import measure_rules_pilot as M  # noqa: E402
import pdf_extraction as pe  # noqa: E402
import quotes  # noqa: E402
import rules_evaluator as rv  # noqa: E402
from test_held_reasons import HOME, LANDLORD  # noqa: E402

pytestmark = pytest.mark.retrieval
H = "The_Hartford_HO3_-_07.09.2026"
RULES = rv._load("rules", rv.HARTFORD_RULES_CSV)
FMAP = rv._load("map", rv.HARTFORD_MAP_CSV)
PDF = os.path.join(HERE, "fixtures", H + ".pdf")
USAGE = {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
CFIG_TEXT = "CFIG experience: The Hartford does not accept diving boards (Jonathan, 2026-10-12)"
RPP_NAME = "The Hartford (HO3 rental: Rental Property Protection Plus)"

OWN = dict(HOME, county="Harris")                                   # Harris: Tier II (2% wind/hail deductible)
RENT = dict(LANDLORD, ownership_type="Individual Owner", losses_5yr="0", primary_home_carrier="The Hartford")
POOL_A = dict(swimming_pool="In Ground - Fenced", pool_accessories="None", pool_fence_4ft=True, pool_gate_locking=True)


@pytest.fixture
def check(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))
    prompts = []

    def fake(system, user, max_tokens):
        prompts.append(user)
        names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)) | set(re.findall(r"--- (.+?) \(rule check\) ---", user)))
        return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
                                         "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(USAGE)
    monkeypatch.setattr(ec, "_complete", fake)

    def run(pd):
        res = {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}
        run.prompts = list(prompts)
        return res.get(H)
    return run


def _rows(rec, rid):
    return [x for x in rec.get("reasons") or [] if f"[{rid}]" in x]


def _confirms(rec, rid):
    return [x for x in rec.get("confirm_items") or [] if x.get("row") == rid]


def _decides(rec, status, rid):
    assert rec is not None, "The Hartford was not checked"
    assert rec["status"] == status and _rows(rec, rid), (rec["status"], rec["reasons"])


# ==================================================================== Liam's cases a-k
# a. Harris, fenced in-ground pool, both boxes ticked: Eligible + the Tier II 2% note
def test_a_fenced_pool_in_harris_is_eligible_with_the_2_percent_note(check):
    r = check(dict(OWN, **POOL_A))
    assert r["status"] == "ELIGIBLE", r["reasons"]
    assert "HAR-054" in r["notes"] and "2% windstorm or hail deductible" in r["notes"]
    assert not _rows(r, "HAR-076")                       # the RPP+ pool row never reads an owner's home


def test_a_the_boxes_are_not_needed_the_guide_declines_only_an_unfenced_pool(check):
    r = check(dict(OWN, **dict(POOL_A, pool_fence_4ft=False, pool_gate_locking=False)))
    assert r["status"] == "ELIGIBLE", r["reasons"]


# b. the same with a diving board: Not eligible (CFIG)
@pytest.mark.parametrize("acc", ["Diving board only", "Both slide and diving board"])
def test_b_a_diving_board_is_not_eligible_cfig(check, acc):
    r = check(dict(OWN, **dict(POOL_A, pool_accessories=acc)))
    _decides(r, "INELIGIBLE", "CFG-001")
    assert CFIG_TEXT in r["reasons"][0]
    assert any("CFIG knowledge base" in c and CFIG_TEXT in c for c in r["citations"])


def test_b_a_slide_is_not_a_diving_board(check):
    assert check(dict(OWN, **dict(POOL_A, pool_accessories="Slide only")))["status"] == "ELIGIBLE"


# c. unfenced in-ground: HAR-060
def test_c_an_unfenced_in_ground_pool_is_declined(check):
    _decides(check(dict(OWN, swimming_pool="In Ground - Unfenced", pool_accessories="None")), "INELIGIBLE", "HAR-060")


@pytest.mark.parametrize("pool", ["Above Ground - Unfenced"])
def test_c_an_unfenced_above_ground_pool_refers_on_the_condition_of_property(check, pool):
    """CHANGED DELIBERATELY (step 5d, second reader, 2026-10-14): p.8 Condition of Property lists unfenced pools
    among the conditions that refer; HAR-060 declines only an unfenced IN-ground pool. Was Eligible."""
    r = check(dict(OWN, swimming_pool=pool, pool_accessories="None"))
    _decides(r, "REFER", "HAR-058")
    assert not _rows(r, "HAR-060")


# d. an LLC: Not eligible; a family trust with the grantor in residence: Eligible
@pytest.mark.parametrize("owner", ["LLC", "Corporation / partnership"])
def test_d_a_business_owner_is_declined(check, owner):
    _decides(check(dict(OWN, ownership_type=owner)), "INELIGIBLE", "HAR-023")


@pytest.mark.parametrize("trust", ["Family trust", "Revocable living trust"])
def test_d_a_family_trust_is_eligible_with_the_grantor_confirm(check, trust):
    r = check(dict(OWN, ownership_type="Trust", trust_type=trust))
    assert r["status"] == "ELIGIBLE", r["reasons"]
    assert _confirms(r, "HAR-026")                       # "the grantor of the trust lives in the home"


def test_d_a_corporate_trust_is_declined(check):
    _decides(check(dict(OWN, ownership_type="Trust", trust_type="Corporate or business trust")), "INELIGIBLE",
             "HAR-025")


def test_d_an_estate_is_a_confirm_on_the_guides_exception(check):
    r = check(dict(OWN, ownership_type="Estate"))
    assert r["status"] == "ELIGIBLE" and _confirms(r, "HAR-022"), r["reasons"]


# e. RPP+ (a tenant-occupied home)
def test_e_rpp_with_the_owners_home_at_the_hartford_is_eligible(check):
    r = check(RENT)
    assert r["status"] == "ELIGIBLE", r["reasons"]
    assert r["display_name"] == RPP_NAME and display_names.record_name(r) == RPP_NAME


@pytest.mark.parametrize("elsewhere", ["Travelers", "Other carrier"])
def test_e_rpp_with_the_owners_home_elsewhere_is_declined(check, elsewhere):
    _decides(check(dict(RENT, primary_home_carrier=elsewhere)), "INELIGIBLE", "HAR-070")


@pytest.mark.parametrize("blank", ["", "Unknown"])
def test_e_rpp_with_the_owners_home_blank_is_held(check, blank):
    r = check(dict(RENT, primary_home_carrier=blank))
    assert r["status"] == "INSUFFICIENT_INFORMATION", r["reasons"]
    assert any("HAR-070" in x for x in r["missing_info"] + r["reasons"])


@pytest.mark.parametrize("pool", ["In Ground - Fenced", "Above Ground - Fenced"])
def test_e_rpp_any_pool_is_declined(check, pool):
    _decides(check(dict(RENT, swimming_pool=pool, pool_accessories="None", pool_fence_4ft=True,
                        pool_gate_locking=True)), "INELIGIBLE", "HAR-076")


def test_e_rpp_more_than_4_rental_units_is_declined(check):
    _decides(check(dict(RENT, rental_units_total="5 or more")), "INELIGIBLE", "HAR-077")


@pytest.mark.parametrize("units,confirm", [("1-4", False), ("", True), ("Unknown", True)])
def test_e_rpp_rental_units_1_to_4_pass_and_blank_is_a_confirm(check, units, confirm):
    r = check(dict(RENT, rental_units_total=units))
    assert r["status"] == "ELIGIBLE" and bool(_confirms(r, "HAR-077")) == confirm, r["reasons"]


def test_e_rpp_a_short_term_rental_is_declined(check):
    _decides(check(dict(RENT, rental_term="Short-term")), "INELIGIBLE", "HAR-046")


def test_e_rpp_a_long_term_tenant_passes(check):
    r = check(dict(RENT, rental_term="Long-term"))
    assert r["status"] == "ELIGIBLE" and not _confirms(r, "HAR-046"), r["reasons"]


def test_e_rpp_class_10_is_declined_by_the_rpp_row(check):
    r = check(dict(RENT, ppc="10", fire_station_miles=9.0))
    _decides(r, "INELIGIBLE", "HAR-074")


def test_e_rpp_a_general_row_applies_to_a_rental(check):
    """HAR-009 (fuses) is a general row: it declines a rental too (GENERAL_ROWS_ON_A_RENTAL)."""
    _decides(check(dict(RENT, electrical=["Fuses"])), "INELIGIBLE", "HAR-009")


def test_e_rpp_a_trust_needs_no_grantor_in_residence(check):
    r = check(dict(RENT, ownership_type="Trust", trust_type="Family trust"))
    assert r["status"] == "ELIGIBLE" and not _confirms(r, "HAR-026"), r["reasons"]


def test_e_a_rented_condo_unit_and_a_vacant_home_are_not_routed(check):
    assert check(dict(RENT, dwelling_type="Condo")) is None
    assert check(dict(RENT, occupancy_type="Vacant")) is None


def test_e_an_owners_home_keeps_the_plain_name(check):
    r = check(OWN)
    assert "display_name" not in r and display_names.record_name(r) == "The Hartford (HO3)"


# f. a seasonal home: the primary with The Hartford -> Eligible; with another carrier -> Not eligible
@pytest.mark.parametrize("occ", ["Seasonal", "Secondary Home"])
def test_f_a_seasonal_home_with_the_primary_at_the_hartford_is_eligible(check, occ):
    r = check(dict(OWN, occupancy_type=occ, primary_home_carrier="The Hartford"))
    assert r["status"] == "ELIGIBLE", r["reasons"]


@pytest.mark.parametrize("occ,other", [("Seasonal", "Travelers"), ("Secondary Home", "Other carrier")])
def test_f_a_seasonal_home_with_the_primary_elsewhere_is_declined(check, occ, other):
    _decides(check(dict(OWN, occupancy_type=occ, primary_home_carrier=other)), "INELIGIBLE", "HAR-059")


# g. Dallas + fuses -> Not eligible; Dallas + breakers -> Eligible with the hail confirm
@pytest.mark.parametrize("county", ["Dallas", "Tarrant"])
def test_g_fuses_are_declined(check, county):
    _decides(check(dict(OWN, county=county, zip="", harris_east_146=None, electrical=["Fuses"])), "INELIGIBLE",
             "HAR-009")


@pytest.mark.parametrize("county", ["Dallas", "Tarrant"])
def test_g_breakers_in_dfw_are_eligible_with_the_hail_confirm(check, county):
    r = check(dict(OWN, county=county, zip="", harris_east_146=None, electrical=["Circuit breakers"]))
    assert r["status"] == "ELIGIBLE" and _confirms(r, "HAR-056"), r["reasons"]


def test_g_outside_dfw_there_is_no_hail_confirm(check):
    assert not _confirms(check(dict(OWN, electrical=["Circuit breakers"])), "HAR-056")


@pytest.mark.parametrize("wiring", [["Knob-and-tube wiring"], ["Circuit breakers", "Aluminum branch wiring"]])
def test_g_knob_and_tube_or_aluminum_wiring_is_declined(check, wiring):
    _decides(check(dict(OWN, electrical=wiring)), "INELIGIBLE", "HAR-008")


# h. a flat roof, or a built-up roof -> Not eligible
def test_h_a_flat_roof_is_declined(check):
    _decides(check(dict(OWN, roof_shape="Flat")), "INELIGIBLE", "HAR-016")


@pytest.mark.parametrize("roof", [intake_fields.ROOF_BUILT_UP, intake_fields.ROOF_MEMBRANE, intake_fields.ROOF_ROLLED,
                                  intake_fields.ROOF_WOOD])
def test_h_a_built_up_membrane_rolled_or_wood_roof_is_declined(check, roof):
    _decides(check(dict(OWN, roof_type=roof)), "INELIGIBLE", "HAR-017")


# i. Coverage A
def test_i_2m_is_referred(check):
    _decides(check(dict(OWN, dwelling_amount=2000000)), "REFER", "HAR-003")


@pytest.mark.parametrize("ppc", ["9", "10"])
def test_i_2m_in_class_9_or_10_is_declined(check, ppc):
    _decides(check(dict(OWN, dwelling_amount=2000000, ppc=ppc)), "INELIGIBLE", "HAR-005")


def test_i_3m_is_declined(check):
    _decides(check(dict(OWN, dwelling_amount=3000000)), "INELIGIBLE", "HAR-002")


def test_i_the_alarm_is_asked_only_at_1_5m(check):
    """Liam's run asked the central alarm item on every home; it is a High Value Homes ($1,500,000+) row."""
    assert _confirms(check(dict(OWN, dwelling_amount=1500000)), "HAR-006")
    assert not _confirms(check(dict(OWN, dwelling_amount=400000)), "HAR-006")


# j. Galveston Tier 1: Eligible with the exclusion note and the 2,000-ft / barrier-island confirm
@pytest.mark.parametrize("county,tier", [("Galveston", "Tier 1"), ("Nueces", "Not Coastal")])
def test_j_a_tier_i_county_is_eligible_with_the_exclusion_and_the_coast_confirm(check, county, tier):
    r = check(dict(OWN, county=county, coastal_tier=tier, zip="", harris_east_146=None))
    assert r["status"] == "ELIGIBLE", r["reasons"]
    assert "HAR-053" in r["notes"] and "windstorm or hail exclusion" in r["notes"]
    assert _confirms(r, "HAR-052")


def test_j_inland_has_neither(check):
    r = check(dict(OWN, county="Travis", coastal_tier="Not Coastal", zip="", harris_east_146=None))
    assert "HAR-053" not in (r["notes"] or "") and not _confirms(r, "HAR-052")


# k. losses (the 3 years before the effective date)
L2 = dict(losses_5yr="2", losses_3yr="2", loss_year=2025)


@pytest.mark.parametrize("types", [["Theft", "Wind or hail"], ["Fire"]])
def test_k_2_losses_in_3_years_are_declined(check, types):
    _decides(check(dict(OWN, loss_types=types, **L2)), "INELIGIBLE", "HAR-027")


def test_k_2_water_losses_are_a_confirm_on_the_appliance_and_mold_exception(check):
    """Remediated appliance-related and mold claims are acceptable (p.3, forms PC-327 / PC-326): water losses the form
    cannot tell apart -- a confirm, not a decline (for Liam: his case k said "2 losses -> Not eligible")."""
    r = check(dict(OWN, loss_types=["Water"], **L2))
    assert r["status"] == "ELIGIBLE" and _confirms(r, "HAR-027"), r["reasons"]
    # Liam's wording (2026-10-14), on the card word for word
    import confirm_topics
    say = ("2 water losses: only acceptable if both were appliance-related and remediated, with Hartford form PC-327; "
           "otherwise Not eligible.")
    assert any(it["text"] == say for it in confirm_topics.card_items(r, dict(OWN, loss_types=["Water"], **L2)))


@pytest.mark.parametrize("types", [["Water", "Other"], ["Other"]])
def test_k_2_losses_that_may_be_mold_are_the_general_exception_confirm(check, types):
    """Not exactly 2 water losses: the exception (appliance or mold claims) is a confirm in the guide's terms, not
    Liam's 2-water sentence."""
    r = check(dict(OWN, loss_types=types, **L2))
    assert r["status"] == "ELIGIBLE" and _confirms(r, "HAR-027"), r["reasons"]
    assert not any(x.get("say") for x in r["confirm_items"])


@pytest.mark.parametrize("five,three,types,status", [("2", "2", ["Water", "Theft"], "INELIGIBLE"),
                                                     ("3 or more", "2", ["Water", "Theft"], "ELIGIBLE"),
                                                     ("3 or more", "3 or more", ["Water", "Theft"], "INELIGIBLE")])
def test_k_a_decline_type_loss_declines_unless_it_may_be_older_than_3_years(check, five, three, types, status):
    r = check(dict(OWN, losses_5yr=five, losses_3yr=three, loss_types=types, loss_year=2025))
    assert r["status"] == status, r["reasons"]
    assert (_rows(r, "HAR-027") if status == "INELIGIBLE" else _confirms(r, "HAR-027"))


def test_k_1_water_loss_passes_every_loss_row(check):
    r = check(dict(OWN, losses_5yr="1", losses_3yr="1", loss_types=["Water"], loss_year=2025))
    assert r["status"] == "ELIGIBLE", r["reasons"]
    assert not any(_rows(r, rid) or _confirms(r, rid) for rid in ("HAR-027", "HAR-028", "HAR-029", "HAR-030"))


def test_k_1_fire_loss_is_declined(check):
    _decides(check(dict(OWN, losses_5yr="1", losses_3yr="1", loss_types=["Fire"], loss_year=2025)), "INELIGIBLE",
             "HAR-028")


def test_k_1_liability_loss_is_referred(check):
    _decides(check(dict(OWN, losses_5yr="1", losses_3yr="1", loss_types=["Liability"], loss_year=2025)), "REFER",
             "HAR-030")


def test_k_class_10_with_any_loss_is_declined(check):
    _decides(check(dict(OWN, ppc="10", fire_station_miles=9.0, losses_5yr="1", losses_3yr="1", loss_types=["Theft"],
                        loss_year=2025)), "INELIGIBLE", "HAR-029")


# ==================================================================== the model's part
def test_the_model_never_reads_the_hartfords_guide_and_judges_only_open_rows(check):
    check(dict(OWN, **POOL_A))
    assert not any(f"--- {H} (page" in p for p in check.prompts)
    assert not any(f"--- {H} (rule check) ---" in p for p in check.prompts)     # nothing open: no model at all
    check(dict(RENT, primary_home_carrier=""))
    rule_check = [p for p in check.prompts if f"--- {H} (rule check) ---" in p]
    assert rule_check and "[HAR-070]" in rule_check[-1]
    section = rule_check[-1].split(f"--- {H} (rule check) ---")[1].split("\n--- ")[0]
    assert set(re.findall(r"\[(HAR-\d{3}|CFG-\d{3})\]", section.split("Not decided by code")[-1])) == {"HAR-070"}


# ==================================================================== the data
def test_data_files_carry_their_source_header():
    for path in (rv.HARTFORD_RULES_CSV, rv.HARTFORD_MAP_CSV, rv.CFIG_KNOWLEDGE_CSV):
        assert open(path, encoding="utf-8-sig").readline().startswith("# source:"), path


def test_every_deciding_row_has_exactly_one_map_line_and_the_file_is_the_builders():
    deciding = {rid for rid, r in RULES.items() if r["Tool handling"] in rv.DECIDING}
    # CHANGED DELIBERATELY (step 5d, 2026-10-14): HAR-058 (Condition of Property) decides an unfenced pool. Was 60.
    assert len(RULES) == 85 and len(deciding) == 61 and set(FMAP) == deciding
    assert {r["Carrier"] for r in RULES.values()} == {"The Hartford HO3"}
    assert not set(RULES) & (set(rv._rules()) - set(RULES))           # ids never collide with another batch
    for rid, m in FMAP.items():
        want = builder.MAP.get(rid)
        if want is None:
            assert m["field"] == "NONE"
        else:
            assert (m["field"], m["test"], m["gate"], m["open_fact"], m["map_note"]) == want


@pytest.mark.parametrize("prof", ["OLD", "CLEAN", "STRESS", "ALT"])
def test_every_expression_parses(prof):
    f = rv.facts(M.PROFILES[prof])
    for m in list(FMAP.values()) + [rv._map()["CFG-001"]]:
        if m["field"] != "NONE":
            rv.evaluate_expr(m["gate"] or "always", f)
            for t in m["test"].split("||"):
                rv.evaluate_expr(t, f)


def test_coverage():
    kinds = collections.Counter(builder.kind(builder.MAP.get(rid, ("NONE", "", "", "", ""))) for rid in FMAP)
    # CHANGED DELIBERATELY (Liam, 2026-10-14): every deciding row has a line, a FACT(...) confirm where the form never
    # asks -- the 21 NONE rows got one (HAR-011 reads HAR-010's: the same fact). Was 18 / 19 / same rule 2 / NONE 21.
    # CHANGED (step 5d, second reader, 2026-10-14): HAR-062 gained a confirm FACT (pit-bull-type breeds). Was 18 / 39.
    # CHANGED (step 5d, second reader, 2026-10-14): HAR-058 (Condition of Property) is new. Was 17 / 40.
    assert kinds == {"decided by a form field": 17, "gated-but-open": 41, "same rule as another row": 3}


def test_no_deciding_row_is_left_to_the_model_or_the_also_confirm_list():
    assert all(m["field"] != "NONE" for m in FMAP.values())
    for rid, m in FMAP.items():
        if m["test"] == "always":                          # a "same rule" line names the row that decides
            assert re.match(r"decided by HAR-\d{3}", m["map_note"]), rid


THE_21 = ("HAR-007", "HAR-010", "HAR-011", "HAR-013", "HAR-014", "HAR-015", "HAR-018", "HAR-021", "HAR-035", "HAR-037",
          "HAR-038", "HAR-040", "HAR-042", "HAR-043", "HAR-050", "HAR-051", "HAR-061", "HAR-065", "HAR-066", "HAR-067",
          "HAR-068")
OWNERS_ONLY = ("HAR-013", "HAR-014", "HAR-015", "HAR-037", "HAR-038", "HAR-042")


def test_the_21_are_confirms_on_an_owners_home(check):
    r = check(dict(OWN, dwelling_amount=400000))
    assert r["status"] == "ELIGIBLE", r["reasons"]
    confirmed = {x["row"] for x in r["confirm_items"] if x["kind"] == "not_asked"}
    assert set(THE_21) - {"HAR-011"} <= confirmed, sorted(set(THE_21) - confirmed)
    assert "HAR-011" not in confirmed                    # HAR-010's confirm covers it


def test_on_a_rental_the_rpp_rows_replace_the_owners_only_confirms(check):
    r = check(RENT)
    confirmed = {x["row"] for x in r["confirm_items"]}
    assert not confirmed & set(OWNERS_ONLY), sorted(confirmed & set(OWNERS_ONLY))
    assert {"HAR-073", "HAR-075"} <= confirmed


@pytest.mark.parametrize("ppc", ["N/A", "7"])
def test_the_stove_confirm_never_holds_on_the_ppc(check, ppc):
    r = check(dict(OWN, ppc=ppc))
    assert r["status"] == "ELIGIBLE" and _confirms(r, "HAR-013"), r["reasons"]


def test_the_general_rows_on_a_rental():
    """Listed for Liam (handoff.md): the general rows a tenant-occupied (RPP+) home is also checked against."""
    rows = list(RULES.values())
    assert builder.general_rows_on_a_rental(rows) == [
        "HAR-002", "HAR-003", "HAR-004", "HAR-005", "HAR-006", "HAR-007", "HAR-008", "HAR-009", "HAR-010", "HAR-011",
        "HAR-016", "HAR-017", "HAR-018", "HAR-021", "HAR-022", "HAR-023", "HAR-024", "HAR-025", "HAR-027", "HAR-028",
        "HAR-030", "HAR-035", "HAR-036", "HAR-040", "HAR-043", "HAR-045", "HAR-046", "HAR-048", "HAR-050", "HAR-051",
        "HAR-052", "HAR-056", "HAR-058", "HAR-061", "HAR-062", "HAR-063", "HAR-064", "HAR-065", "HAR-066", "HAR-067",
        "HAR-068"]
    # the rows an RPP+ row replaces (or that cannot apply to a rental) are gated off a rental
    for rid in ("HAR-013", "HAR-014", "HAR-015", "HAR-026", "HAR-029", "HAR-033", "HAR-034", "HAR-037", "HAR-038",
                "HAR-042", "HAR-060"):
        assert "occupancy_type != Tenant Occupied" in FMAP[rid]["gate"], rid
    for n in range(70, 78):
        m = FMAP[f"HAR-0{n}"]
        assert m["field"] == "NONE" or "occupancy_type == Tenant Occupied" in m["gate"]


# ---- quote checks: every row's quote is in the guide's text, as the upload path stores it
@pytest.fixture(scope="module")
def stored_text():
    docs, _ = pe.load_upload_documents(PDF)
    return quotes.compare_key("\n".join(d.page_content for d in docs))


@pytest.mark.parametrize("rid", sorted(r for r in RULES if RULES[r]["Verbatim quote from guide"]))
def test_every_quote_is_in_the_stored_text(stored_text, rid):
    q = quotes.compare_key(RULES[rid]["Verbatim quote from guide"])
    assert quotes.appears_in(q, stored_text), (rid, RULES[rid]["Verbatim quote from guide"])


def _stored_chunks():
    """The Hartford's chunks in the app's store (carrier_docs_db, a copy of the seed): never open the tracked seed
    itself -- opening a Chroma store writes to its sqlite file."""
    return ec.get_vectorstore()._collection.get(where={"carrier": H}, include=["documents"])["documents"]


def test_every_deciding_rows_quote_is_in_the_stored_chunks():
    """The second reader: each deciding row's quote in the app's stored chunks."""
    docs = _stored_chunks()
    text = quotes.compare_key("\n".join(docs))
    assert len(docs) == 47
    missing = [rid for rid in FMAP if RULES[rid]["Verbatim quote from guide"]
               and not quotes.appears_in(quotes.compare_key(RULES[rid]["Verbatim quote from guide"]), text)]
    assert not missing


def test_no_hidden_auto_text_in_the_stored_chunks():
    docs = _stored_chunks()
    assert docs and not any("MAAA" in d or "MVR" in d for d in docs)
    assert all(d.startswith("[") for d in docs)                       # every chunk carries its section


# ---- the CFIG knowledge base
def test_the_cfig_knowledge_base_is_one_file_each_entry_naming_who_and_when():
    rows = [r for r in rv._rules().values() if rv.is_cfig(r)]
    assert [r["Rule ID"] for r in rows] == ["CFG-001"]
    for r in rows:
        assert re.search(r"\b20\d\d-\d\d-\d\d\b", r["Source"]) and r["Carrier"] in rv.WB_TO_CANON
        assert not r["Verbatim quote from guide"] and r["Plain rule"].startswith("CFIG experience:")
    assert rv._rules()["CFG-001"]["Plain rule"] == CFIG_TEXT


def test_the_hold_guard_reads_the_new_row_ids():
    assert hold_guard.ROW_ID.search("[HAR-070]") and hold_guard.ROW_ID.search("[CFG-001]")


def test_the_new_fields_have_topics_and_form_labels():
    for field in ("rental_units_total", "rental_term", "primary_home_carrier"):
        assert field in rv.FIELD_TOPIC and field in intake_fields.FORM_FIELDS


# ---- routing, names, switches
@pytest.mark.parametrize("occ,routed", [("Owner Occupied", True), ("Seasonal", True), ("Secondary Home", True),
                                        ("Tenant Occupied", True), ("Vacant", False)])
def test_routing(occ, routed):
    assert (H in ec.get_carriers_for_occupancy(occ)) == routed


def test_the_hartford_is_on_the_rules_table_with_the_ho3_switch_only():
    pd = {"occupancy_type": "Owner Occupied"}
    assert rv.rules_table_wb(H, set(), pd) is None and rv.rules_table_wb(H, {"ho3"}, pd) is None
    assert rv.rules_table_wb(H, {"hartford"}, pd) == "The Hartford HO3"
    assert ec.RULES_BATCH_SWITCHES["hartford"][0] == "RULES_HO3_BATCH"


def test_names_and_dates():
    assert display_names.display_name(H) == "The Hartford (HO3)"
    assert display_names.guide_date(H) == "07/09/2026"
    assert intake_fields.primary_home_label(H) == "The Hartford"


def test_placement_market():
    import placement
    assert placement.market_of(H) == "The Hartford"
