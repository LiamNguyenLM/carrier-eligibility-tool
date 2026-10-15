"""Build rules_data/hartford_field_map.csv -- one line per deciding row (Tool handling EVALUATE) of
rules_data/carrier_rules_hartford_v1.csv, The Hartford HO3 (Agency Prevail Texas Homeowners, effective 07/09/2026;
round 39 step 1, 2026-10-13).

Same grammar and conventions as build_ho3_batch_map.py (rules_data/RULE_FIELD_MAP.md): every non-NONE line is
written by hand below; a row with no line is NONE (the form has no field that decides it); one failing row per
fact ("decided by" lines).

Liam's decisions (2026-10-12): CFIG writes the HO3 and its tenant-occupied HO3, Rental Property Protection Plus
(RPP+), which covers a rental only when the owner's own home is with The Hartford. The RPP+ rows HAR-070..077 apply
to a tenant-occupied home on top of the general rows; where an RPP+ row and a general row decide the same fact, the
RPP+ row decides a rental and the general row an owner's home (RPP_REPLACES below). The general rows that apply to a
rental are listed by GENERAL_ROWS_ON_A_RENTAL (handoff.md). The CFIG diving-board entry is in
rules_data/cfig_knowledge.csv, not here.

usage: python rules_data/build_hartford_map.py
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_rule_field_map import BUILT_UP, DOGS, MEMBRANE, ROLLED_ROOF, SEASONAL, WOOD, _breeds, _roofs  # noqa: E402
from build_rule_field_map import ASBESTOS, NONE_NOTE  # noqa: E402
from build_sage_batch_map import BATCH_NONE_NOTE, KINDS, kind  # noqa: E402

RULES = os.path.join(HERE, "carrier_rules_hartford_v1.csv")
OUT = os.path.join(HERE, "hartford_field_map.csv")

TENANT = "occupancy_type == Tenant Occupied"
NOT_TENANT = "occupancy_type != Tenant Occupied"
TRUST = "ownership_type == Trust"
HIGH_VALUE = "dwelling_amount >= 1500000"
LOSSES = "losses_5yr;losses_3yr;loss_types"
CONFIRM_NOTE = "round 37 step 4: decided from the losses questions; blank or Unknown is a confirm"
# p.7, Catastrophe Management
TIER_I = ("{Aransas, Brazoria, Calhoun, Cameron, Chambers, Galveston, Jefferson, Kenedy, Kleberg, Matagorda, Nueces, "
          "Refugio, San Patricio, Willacy}")
TIER_II = "{Harris, Fort Bend, Hardin, Jackson, Liberty, Orange, Wharton}"
DFW_HAIL = ("{Collin, Dallas, Denton, Ellis, Grayson, Hood, Hunt, Johnson, Kaufman, Parker, Rockwall, Somervell, "
            "Tarrant, Wise}")
# p.3 losses (Liam, 2026-10-14): exactly 2 losses in 3 years, both water -- the card says this, word for word
# (rules_evaluator.CARD_WORDING)
TWO_WATER = "losses_3yr in {2} and loss_types none_of {Fire, Liability, Wind or hail, Theft, Other}"
TWO_WATER_SAY = ("2 water losses: only acceptable if both were appliance-related and remediated, with Hartford form "
                 "PC-327; otherwise Not eligible")
# Round 39 (Liam, 2026-10-14): every deciding row has a line -- a fact the form never asks is a FACT(...) confirm,
# never left to the model. Facts with no form field read an always-on field (occupancy_type) so no topic skips them.
OWNERS_HOME = ("occupancy_type", NOT_TENANT)            # the RPP+ row decides the same fact on a rental
EVERY_HOME = ("occupancy_type", "always")


def recent_type(kind, fact):
    """A loss of `kind` in the 3 years. Fails when a loss in the 3 years is certainly of `kind`: every loss answered is
    recent (1 of 1, 2 of 2), or every loss answered is of `kind`. A loss of `kind` that may be the older one, or an
    "Other" loss, is a confirm. (The shared loss_electrical_lines.count reads any type among the 5-year losses as
    recent -- step 5d, second reader; "every loss is of kind" -- step 5b, monotonic invariant.)"""
    all_recent = "((losses_5yr in {1} and losses_3yr in {1}) or (losses_5yr in {2} and losses_3yr in {2}))"
    others = ", ".join(t for t in ("Water", "Fire", "Liability", "Wind or hail", "Theft", "Other") if t != kind)
    certain = f"({all_recent} or loss_types none_of {{{others}}})"
    return (f"losses_3yr in {{0}} or (loss_types none_of {{{kind}, Other}}) or (not ({certain} and not (loss_types "
            f"none_of {{{kind}}})) and FACT({fact}))")


# p.8: "Breed is Pit Bull, Staffordshire Terrier, Presa Canario, Rottweiler or [a mix]" -- a closed list
BREEDS = _breeds("Pit Bull (American Pit Bull Terrier)", "American Staffordshire Terrier",
                 "Staffordshire Bull Terrier", "Presa Canario", "Rottweiler")

MAP = {
    # -- Coverage A (p.1)
    "HAR-002": ("dwelling_amount", "dwelling_amount <= 2500000", "always", "", ""),
    "HAR-003": ("dwelling_amount", "dwelling_amount <= 1500000", "always", "",
                "'Coverage A greater than $1,500,000: Refer prior to binding'"),
    # -- High Value Homes ($1,500,000+), p.1 (the heading decides: these apply only at $1.5M+)
    "HAR-004": (LOSSES, "always", "always", "", "decided by HAR-027 (2+ losses in 3 years, every home)"),
    "HAR-005": ("dwelling_amount;ppc", "ppc_num <= 8", HIGH_VALUE, "", "Protection Class 9 or 10 (incl. 10W)"),
    "HAR-006": ("dwelling_amount", "FACT(an active central fire and burglar alarm)", HIGH_VALUE, "central alarm",
                "High Value Homes only; the alarm is not asked"),
    # -- Electrical (p.1)
    "HAR-008": ("electrical", "electrical none_of {Knob-and-tube wiring, Aluminum branch wiring}", "always", "",
                "round 37 step 4: decided from the electrical question; blank or Unknown is a confirm"),
    "HAR-009": ("electrical", "electrical none_of {Fuses}", "always", "",
                "round 37 step 4: decided from the electrical question; blank or Unknown is a confirm"),
    # -- Roof (p.2)
    "HAR-016": ("roof_shape", "roof_shape != Flat", "always", "", "'Flat Roofs: Decline'"),
    "HAR-017": ("roof_type", "roof_type not in " + _roofs(WOOD, ROLLED_ROOF, BUILT_UP, MEMBRANE)
                + " and (roof_type not in {Other} or FACT(the roof is not foam))", "always", "foam roof",
                "built-up / hot mopped and rock or gravel are the Built-up option; rubber/membrane the Membrane one"),
    # -- Ownership and trusts (pp.2-3)
    "HAR-022": ("ownership_type", "FACT(the resident applicant will own the home when the estate is settled)",
                "ownership_type == Estate", "estate settlement", "the guide names the exception"),
    "HAR-023": ("ownership_type", "ownership_type not in {LLC, Corporation / partnership}", "always", "",
                "'A business, LLC or other non-individual'; trusts and estates: their own rows"),
    "HAR-024": ("ownership_type;trust_type", "trust_type in {Family trust, Revocable living trust, Corporate or "
                "business trust} or FACT(the trust is in the name of an individual or family)", TRUST,
                "trust in an individual's or family's name", "a corporate trust is decided by HAR-025"),
    "HAR-025": ("ownership_type;trust_type", "trust_type not in {Corporate or business trust} and FACT(no grantor or "
                "beneficiary of the trust is a business or other non-individual)", TRUST, "grantor / beneficiaries",
                "step 5d (second reader): a family trust can still name a charity or company as a beneficiary"),
    "HAR-026": ("ownership_type;occupancy_type", "FACT(the grantor of the trust lives in the home)",
                TRUST + " and " + NOT_TENANT, "grantor in residence",
                "owner's home only: the tenant-occupied HO3 has no occupancy restriction (HAR-078)"),
    # -- Losses (p.3): "In the THREE (3) years preceding the effective date"
    "HAR-027": (LOSSES, "losses_3yr in {0, 1} or (" + TWO_WATER + " and FACT(" + TWO_WATER_SAY + ")) or (not ("
                + TWO_WATER + ") and loss_types none_of {Fire, Liability, Wind or hail, Theft} and FACT(the losses "
                "beyond one are remediated appliance-related or mold claims, with Hartford form PC-327 or PC-326)) or "
                "(losses_5yr in {3 or more} and losses_3yr in {2} and not (loss_types none_of {Fire, Liability, Wind "
                "or hail, Theft}) and not (loss_types none_of {Water, Other}) and FACT(the fire, liability, wind or "
                "theft losses are more than 3 years old and the 2 recent ones are remediated appliance-related or mold "
                "claims))", "always", "",
                CONFIRM_NOTE + "; appliance and mold claims are water / other losses; exactly 2 water losses: "
                "Liam's wording (2026-10-14)"),
    "HAR-028": (LOSSES, recent_type("Fire", "the fire loss was more than 3 years ago"), "always", "", CONFIRM_NOTE
                + "; fails only when every loss is known to be in the 3 years (step 5d)"),
    "HAR-029": ("ppc;occupancy_type;" + LOSSES, "losses_3yr in {0}", "ppc_num >= 10 and " + NOT_TENANT, "",
                CONFIRM_NOTE + "; a rental in class 10 is declined by HAR-074"),
    "HAR-030": (LOSSES, recent_type("Liability", "the liability loss was more than 3 years ago"), "always", "",
                CONFIRM_NOTE + "; fails only when every loss is known to be in the 3 years (step 5d)"),
    # -- Number of families (p.4): Step 4 decides these from "Units in the building"
    "HAR-033": ("occupancy_type", "FACT(a 1- or 2-family dwelling)", NOT_TENANT, "number of families",
                "owner's home; a rental: HAR-071"),
    "HAR-034": ("occupancy_type", "FACT(no more than 2 boarders or roomers per family)", NOT_TENANT, "boarders",
                "a note under Number of Families (an owner-occupied qualifying dwelling)"),
    # -- Construction (p.4)
    "HAR-036": ("roof_type", "roof_type not in " + _roofs(ASBESTOS) + " and FACT(no other asbestos building "
                "materials)", "always", "asbestos materials", "an asbestos roof decides; other materials are not asked"),
    # -- Occupancy (p.6)
    "HAR-045": ("occupancy_type", "occupancy_type != Vacant", "always", "", ""),
    "HAR-046": ("occupancy_type;rental_term", "rental_term not in {Short-term}", TENANT, "",
                "the rental term is asked for a tenant-occupied home; blank or Unknown is a confirm"),
    "HAR-048": ("construction_type", "construction_type != Manufactured/Mobile", "always", "", ""),
    # -- Catastrophe Management (p.7)
    "HAR-052": ("coastal_tier;county", "FACT(more than 2000 feet from the coastline and not on a barrier island)",
                "coastal_tier == Tier 1 or county in " + TIER_I, "distance to the coastline",
                "the guide's Tier I counties, or the form's Tier 1"),
    "HAR-056": ("county", "FACT(no roof characteristics subject to excessive hail exposure)", "county in " + DFW_HAIL,
                "roof hail exposure", "the guide does not say which roof characteristics: a confirm"),
    # -- Secondary / seasonal (p.8)
    "HAR-059": ("occupancy_type;primary_home_carrier", "primary_home_carrier in {The Hartford}", SEASONAL,
                "primary home with The Hartford", "the form's 'Primary home insured with'"),
    # -- Pool (p.8): the homeowners form declines only an unfenced in-ground pool
    "HAR-060": ("swimming_pool;occupancy_type", "swimming_pool not in {In Ground - Unfenced}", NOT_TENANT, "",
                "owner's home; any pool on a rental: HAR-076"),
    # -- Dogs (p.8)
    "HAR-062": ("has_dogs;dog_breeds", "dog_breeds none_of " + BREEDS + " and (dog_breeds none_of {American Bully, "
                "American Bull Terrier} or FACT(the American Bully or Bull Terrier is not a pit bull type))", DOGS,
                "pit bull type", "'or mix' of the four breeds; pit-bull-type breeds the form names are a confirm "
                "(step 5d)"),
    # -- Condition of Property (p.8): 'unfenced pools, hot tubs, ponds or trampolines' refer (step 5d, second reader);
    # an unfenced in-ground pool on an owner's home is declined by HAR-060, any pool on a rental by HAR-076
    "HAR-058": ("swimming_pool;occupancy_type", "(occupancy_type == Tenant Occupied or swimming_pool not in {Above Ground "
                "- Unfenced}) and FACT(no unrepaired damage, poor upkeep, hot tub, pond or other unusual hazard)",
                "always", "condition of the property", "an unfenced above-ground pool refers; the rest is not asked"),
    "HAR-063": ("has_dogs", "FACT(no dog has bitten anyone or shown undue aggressiveness)", DOGS, "bite history", ""),
    "HAR-064": ("has_dogs;" + LOSSES, "losses_5yr in {0} or loss_types none_of {Liability, Other} or FACT(no liability "
                "loss was caused by a dog the insured still owns)", DOGS, "", CONFIRM_NOTE),
    # -- Rental Property Protection Plus (p.6): a tenant-occupied home only
    "HAR-070": ("occupancy_type;primary_home_carrier", "primary_home_carrier in {The Hartford}", TENANT,
                "owner's home with The Hartford", "the form's 'Where is the owner's own home insured?' (a hold when blank)"),
    "HAR-071": ("occupancy_type", "FACT(a 1- or 2-family dwelling)", TENANT, "number of families", ""),
    "HAR-072": ("occupancy_type;rental_term", "always", TENANT, "", "decided by HAR-046 (the rental term)"),
    "HAR-073": ("occupancy_type", "FACT(no business, day care or farming on the premises)", TENANT,
                "business on the premises", "an owner's home: HAR-037 / HAR-038"),
    "HAR-074": ("occupancy_type;ppc", "ppc_num <= 9", TENANT, "", "Protection Class 10 (incl. 10W)"),
    "HAR-075": ("occupancy_type", "FACT(no wood, coal or pellet stove)", TENANT, "wood stove", ""),
    "HAR-076": ("occupancy_type;swimming_pool", "swimming_pool in {No Pool}", TENANT, "",
                "'Swimming pool on premises (in or above ground)'"),
    "HAR-077": ("occupancy_type;rental_units_total", "rental_units_total not in {5 or more}", TENANT, "",
                "the form's 'Rental units the owner has in total'; blank or Unknown is a confirm"),
}

# Round 39 (Liam, 2026-10-14): the 21 rows that were NONE (left to the "Also confirm" list) -- each a confirm on the
# fact the form never asks. (field, test, gate, open fact, note)
def _confirm(fact, label, note="", where=EVERY_HOME):
    return (where[0], f"FACT({fact})", where[1], label, note)


MAP.update({
    "HAR-007": ("electrical", "FACT(the electrical service is at least 100 amps)", "always", "service amps",
                "service amps are not asked; fuses and wiring: HAR-008 / HAR-009"),
    "HAR-010": _confirm("a thermostatically controlled central heat source heats the whole home", "central heat",
                        "heating is not asked; thermostatic electric baseboard heat in every room counts"),
    "HAR-011": ("occupancy_type", "always", "always", "", "decided by HAR-010 (the same fact: a central heat source)"),
    "HAR-013": _confirm("no wood, coal or pellet stove in a Protection Class 10 home", "wood stove",
                        "stoves are not asked; not gated on PPC, so a blank PPC never holds; a rental: HAR-075",
                        OWNERS_HOME),
    "HAR-014": _confirm("any wood, coal or pellet stove was professionally installed or approved by a Fire Marshal "
                        "or qualified professional", "wood stove installation", "a rental: HAR-075", OWNERS_HOME),
    "HAR-015": _confirm("any wood, coal or pellet stove is professionally cleaned every year, flue and chimney "
                        "included", "wood stove cleaning", "a rental: HAR-075", OWNERS_HOME),
    "HAR-018": ("dwelling_amount", "FACT(Coverage A is at least 100% of the replacement cost)", "always",
                "insurance to value", "the replacement cost is not asked"),
    "HAR-021": ("ownership_type", "FACT(fewer than three unrelated individuals own the home)",
                "ownership_type == Individual Owner", "number of owners", "the number of owners is not asked"),
    "HAR-035": ("construction_type", "FACT(not of unique construction: earth, straw bale, geodesic dome, log, "
                "houseboat or underground)", "always", "unique construction", "'including but not limited to'"),
    "HAR-037": _confirm("no business or farming is conducted from the premises, working from home for an employer "
                        "aside", "business on the premises", "a rental: HAR-073", OWNERS_HOME),
    "HAR-038": _confirm("no day care on the premises", "day care", "a rental: HAR-073", OWNERS_HOME),
    "HAR-040": ("construction_type", "FACT(no mobile home or trailer on the property as an other structure)",
                "always", "mobile home or trailer on the property", ""),
    "HAR-042": _confirm("the home is not under construction, or it is built by a professional contractor, completed "
                        "within 120 days and occupied by the applicant on completion", "under construction",
                        "construction status is not asked; the applicant occupies it: an owner's home",
                        OWNERS_HOME),
    "HAR-043": ("construction_type", "FACT(not elevated on piers or pilings, and no open foundation)", "always",
                "foundation", "the foundation is not asked"),
    "HAR-050": ("construction_type", "FACT(not a modular home that ever had a vehicle registration, axles, I-beams, "
                "steel under-framing or a HUD plate)", "construction_type != Manufactured/Mobile",
                "modular home history", "a manufactured home: HAR-048"),
    "HAR-051": ("county", "FACT(not exposed to brush or forest fire or to wavewash)", "always",
                "brush fire / wavewash", ""),
    "HAR-061": _confirm("no trampoline, or it has safety netting", "trampoline"),
    "HAR-065": _confirm("no prior Hartford policy of the applicant was cancelled for non-payment in the past 12 "
                        "months", "prior Hartford cancellation"),
    "HAR-066": _confirm("the risk was not declined, cancelled or non-renewed by Hartford underwriting in the past 12 "
                        "months", "prior Hartford decline"),
    "HAR-067": _confirm("the risk was not declined for reinstatement in the past 12 months", "reinstatement"),
    "HAR-068": _confirm("the customer owes The Hartford no earned premium", "earned premium"),
})
# Round 39 step 4 (Liam): "Units in the building" decides HAR-033 / HAR-071 (units_lines.py).
from units_lines import LINES as UNITS_LINES  # noqa: E402
MAP.update({rid: line for rid, line in UNITS_LINES.items() if rid.startswith("HAR-")})
# Rows an RPP+ row replaces on a rental (the general row's gate leaves out a tenant-occupied home); None: the row
# cannot apply to a rental.
RPP_REPLACES = {"HAR-026": "HAR-078", "HAR-029": "HAR-074", "HAR-033": "HAR-071", "HAR-034": "HAR-071",
                "HAR-060": "HAR-076", "HAR-059": None, "HAR-013": "HAR-075", "HAR-014": "HAR-075",
                "HAR-015": "HAR-075", "HAR-037": "HAR-073", "HAR-038": "HAR-073", "HAR-042": None}
# The general (non-RPP+) deciding rows that also apply to a tenant-occupied home: every one but RPP_REPLACES and
# the occupancy rows that cannot apply (HAR-059 is a seasonal home's).
HARTFORD_NONE_NOTE = dict(BATCH_NONE_NOTE, OTHER_SYSTEMS="heating and wood stoves are not asked",
                          ELECTRICAL="electrical service amps are not asked",
                          OTHER="business, day care, prior Hartford cancellations and earned premium are not asked")


NONE_BY_ROW = {"HAR-042": "construction status is not asked"}


def coverage(ev):
    """{kind: count} over the deciding rows (the coverage table's columns)."""
    out = dict.fromkeys(KINDS, 0)
    for r in ev:
        out[kind(MAP.get(r["Rule ID"], ("NONE", "", "", "", "")))] += 1
    return out


def general_rows_on_a_rental(rows):
    ev = [r["Rule ID"] for r in rows if r["Tool handling"] == "EVALUATE"]
    rpp = {f"HAR-0{n}" for n in range(70, 80)}
    return [rid for rid in ev if rid not in rpp and rid not in RPP_REPLACES]


def main():
    rows = list(csv.DictReader(l for l in open(RULES, encoding="utf-8-sig") if not l.startswith("#")))
    ev = [r for r in rows if r["Tool handling"] in ("EVALUATE", "EVALUATE_CURE_IS_INSPECTION")]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write("# source: rules_data/build_hartford_map.py over rules_data/carrier_rules_hartford_v1.csv "
                 "(The Hartford HO3 version 1, reviewed by Claude); built 2026-10-13 (round 39 step 1). "
                 "Grammar: rules_data/RULE_FIELD_MAP.md.\n")
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["row_id", "field", "test", "gate", "outcome_if_fail", "open_fact", "map_note"])
        for r in ev:
            rid = r["Rule ID"]
            if rid in MAP:
                field, test, gate, open_fact, note = MAP[rid]
            else:
                field, test, gate, open_fact = "NONE", "", "", ""
                note = NONE_BY_ROW.get(rid) or HARTFORD_NONE_NOTE.get(r["Topic"], NONE_NOTE.get(r["Topic"],
                                                                                  "the form has no field for this"))
            w.writerow([rid, field, test, gate, r["Effect"] or "UNKNOWN", open_fact, note])
    unknown = sorted(set(MAP) - {r["Rule ID"] for r in ev})
    print(f"wrote {OUT}: {len(ev)} lines, {len(MAP)} mapped; map ids not deciding rows: {unknown}")
    print(coverage(ev))
    print("general rows on a rental:", ", ".join(general_rows_on_a_rental(rows)))


if __name__ == "__main__":
    main()
