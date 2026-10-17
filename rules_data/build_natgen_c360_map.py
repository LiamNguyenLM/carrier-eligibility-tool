"""Build rules_data/natgen_c360_field_map.csv -- one line per deciding row (Tool handling EVALUATE /
EVALUATE_CURE_IS_INSPECTION) of rules_data/carrier_rules_natgen_c360_ho3_v1.csv, NatGen Custom360 HO3 (Texas
Homeowners -- Custom360, Imperial Fire and Casualty, 09/02/2026; round 40 step 2, Liam 2026-10-16). Rows cite PDF
pages (the guide's own page numbers run 2 behind).

Every deciding row has a line (Liam, 2026-10-14): a form field decides where the form asks the fact; otherwise a
FACT(...) confirm; a row that restates another's fact, or one item of a requirement list another row confirms as a
whole (the 18 solid-fuel-stove conditions, the brush inspection, true farming, Course of Construction), reads
"decided by" that row -- one confirm, never one per bullet.
Liam's decisions (2026-10-16):
- Coverage A (p.5): the tables (NC3-017..021) are BINDING AUTHORITY. Below $150,000 declines (NC3-192). Above "Under-
  writing approval is required" (Non-Premier: PC 1-8 over $1,500,000; PC 9-10 over $750,000; secondary / seasonal over
  $750,000) refers -- never a decline. The form does not say Premier Client: read as Non-Premier, with a confirm.
- Losses (p.12): NC3-115 is non-remediated damage only (a condition note, CONDITION_STANDARD). The 3-year rules:
  package policies at most two paid losses, at most one theft / vandalism / water loss; monoline at most one loss
  (NC3-111's Insurance Score 1-30: a confirm). Two remediated, certified appliance water losses are accepted (WDR-1).
  Package or monoline is not asked: confirm, and decide only what both readings agree on.
- Wood roofs: NC3-100 (p.11 wildfire list) conflicts with p.7's Wood Roofs section -- refer, unless a p.7 requirement
  clearly fails (a wood roof older than 25 years declines, NC3-062).
- Coastal (p.9): the zones are notes (rules_evaluator.PROGRAM_NOTES); "acceptable CAT score" (NC3-092 / NC3-094) has
  no threshold -- a note, never a decline.

usage: python rules_data/build_natgen_c360_map.py
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_rule_field_map import NONE_NOTE, ROLLED_ROOF, SEASONAL, TLOCK, WOOD, _roofs  # noqa: E402
from build_sage_batch_map import KINDS, kind  # noqa: E402

RULES = os.path.join(HERE, "carrier_rules_natgen_c360_ho3_v1.csv")
OUT = os.path.join(HERE, "natgen_c360_field_map.csv")

PRIMARY = "occupancy_type == Owner Occupied"
POOL = "swimming_pool != No Pool"
ABOVE = "swimming_pool in {Above Ground - Fenced, Above Ground - Unfenced}"
IS_WOOD = "roof_type in " + _roofs(WOOD)
LOSSES = "losses_5yr;losses_3yr;loss_types"
NON_PREMIER = "read as a Non-Premier client (the form does not say Premier Client): a confirm"
LOSS_NOTE = "decided only where the package and monoline readings agree; blank or Unknown is a confirm"
STOVE = ("no solid fuel burning stove, or one UL-certified stove in an owner-occupied home, the only stove on its "
         "chimney, professionally installed and cleaned yearly, its legs not on wood blocks, used only as supplemental "
         "heat, on a 4-inch mat 18 inches out, with a lined chimney 3 feet above the roof, heat "
         "shields, a clear area and an approved stovepipe -- none in a PC 10 home")
FARM = ("no true farming exposure: farm income of $5,000 a year or less -- $10,000 with the Incidental Farming "
        "Endorsement -- 5 head of livestock or horses or fewer -- 10 with it -- no "
        "racing, show or boarded animals, one tractor at most, no farm employees, processing or public activities")
BRUSH = ("a Cotality Wildfire Risk Score of 50 or less, or a passed Brush Inspection: no wood siding or exposed areas, a "
         "16-foot street, woodpiles and LPG tanks 30 feet from structures")
COC = ("not under construction or significant renovation, or approved by underwriting -- and not eligible unless in "
       "PC 1-8, with a completed value of $1,000,000 or less and a licensed general contractor, completed in 180 days if $500,000 or less, otherwise 1 year")


def confirm(fact, label, gate="always", field="occupancy_type", note=""):
    return (field, f"FACT({fact})", gate, label, note)


def same(rid, field="occupancy_type"):
    return (field, "always", "always", "", f"decided by {rid} (the same rule); never a second flaw")


MAP = {
    # ---- Named insured and ownership (pp.3-4)
    "NC3-002": same("NC3-004 (LLC, corporation), NC3-007 (trust) and NC3-008 (estate)", "ownership_type"),
    "NC3-003": confirm("owned by the named insured, alone or with another resident of the household", "owners",
                       "ownership_type == Individual Owner", "ownership_type"),
    "NC3-004": ("ownership_type", "ownership_type not in {LLC, Corporation / partnership} or FACT(an LLC or LLP is only an "
                "additional insured, with no commercial activities, owned by the insured and relatives -- a "
                "corporation only as an additional interest, chartered as a family trust whose trustee lives "
                "there)", "always", "LLC / corporation terms",
                "'except as listed': an LLC or a family-trust corporation can be added (NC3-005, NC3-006) -- a confirm"),
    "NC3-005": same("NC3-004", "ownership_type"),
    "NC3-006": same("NC3-004", "ownership_type"),
    "NC3-007": confirm("the trust is an additional insured, with the grantor, trustee and occupant the same person",
                       "trust terms", "ownership_type == Trust", "ownership_type"),
    "NC3-008": ("ownership_type", "ownership_type != Estate", "always", "", "'Estate of' is not a named insured at new "
                "business"),
    "NC3-009": confirm("any life estate, life tenancy or joint tenancy is written in the individual's name", "life "
                       "estate", "ownership_type == Individual Owner", "ownership_type"),
    "NC3-010": same("NC3-004", "ownership_type"),
    "NC3-011": same("NC3-004", "ownership_type"),
    "NC3-012": same("NC3-004", "ownership_type"),
    "NC3-013": confirm("only one LLC on the property", "number of LLCs", "ownership_type == LLC", "ownership_type"),
    "NC3-014": confirm("not owned by a trust and an LLC together", "trust and LLC",
                       "ownership_type in {Trust, LLC}", "ownership_type"),
    "NC3-015": confirm("the applicant is 18 or older", "applicant's age"),
    "NC3-016": confirm("no lapse in coverage in the past 12 months, unless prior insurance was not required -- "
                       "prior renters business excluded",
                       "prior insurance"),
    # ---- Coverage A (p.5): the binding authority tables refer; the minimum declines
    # Round 41 A5 (Liam, 2026-10-17): the form asks the split class (1X-8X), and NatGen counts it as PC 9 (p.5
    # footnote; rules_evaluator.SPLIT_CLASS_AS), so NC3-017 is NC3-022's rule again. (Round 40: a confirm between
    # $750,000 and $1,500,000 while the form had no X classes.)
    "NC3-017": same("NC3-022", "dwelling_amount"),
    "NC3-018": same("NC3-023", "dwelling_amount"),
    "NC3-019": same("NC3-023", "dwelling_amount"),
    "NC3-020": same("NC3-026", "dwelling_amount"),
    "NC3-021": same("NC3-026", "dwelling_amount"),
    "NC3-022": ("dwelling_amount;occupancy_type;ppc", "dwelling_amount <= 1500000", PRIMARY + " and ppc_num <= 8", "",
                NON_PREMIER + "; a 1X-8X split class reads PC 9 (rules_evaluator.SPLIT_CLASS_AS)"),
    "NC3-023": ("dwelling_amount;occupancy_type;ppc", "dwelling_amount <= 750000", PRIMARY + " and ppc_num >= 9", "",
                NON_PREMIER),
    "NC3-024": ("dwelling_amount;occupancy_type;ppc", "FACT(not a Premier Client)", PRIMARY + " and ppc_num <= 8 and "
                "dwelling_amount > 2000000", "Premier Client", NON_PREMIER),
    "NC3-025": ("occupancy_type;ppc", "FACT(not a Premier Client)", PRIMARY + " and ppc_num >= 9", "Premier Client",
                NON_PREMIER),
    "NC3-026": ("dwelling_amount;occupancy_type", "dwelling_amount <= 750000", SEASONAL, "", NON_PREMIER),
    "NC3-027": ("occupancy_type", "FACT(not a Premier Client)", SEASONAL, "Premier Client", NON_PREMIER),
    "NC3-192": ("dwelling_amount", "dwelling_amount >= 150000", "always", "", "the minimum of every binding table"),
    "NC3-028": confirm("written at 100% of the estimated replacement cost", "insurance to value",
                       field="dwelling_amount"),
    "NC3-032": confirm("Coverage A is no more than 150% of the estimated replacement cost", "insurance to value",
                       field="dwelling_amount"),
    # ---- Families, locations, occupancy (p.6); round 39 step 4: "Units in the building"
    "NC3-033": ("dwelling_type;units_in_building", "units_in_building not in {5 or more}", "dwelling_type == House",
                "", "Non-Premier 1-4 family; a blank unit count is a confirm"),
    "NC3-034": ("dwelling_type;units_in_building", "units_in_building in {1, 2} or FACT(not a Premier Client)",
                "dwelling_type == House", "Premier Client", "Premier: 1-2 family"),
    "NC3-035": confirm("no more than 6 locations or 16 units insured in all", "locations"),
    "NC3-036": ("occupancy_type;primary_home_carrier", "primary_home_carrier in {National General} or (primary_home_carrier in {Other carrier} and "
                "FACT(the primary home is with a National General affiliate -- Allstate or Encompass))", SEASONAL,
                "primary home with National General", "the form's 'Primary home insured with'"),
    "NC3-037": confirm("not a Premier Client, or the primary home is written as Premier", "Premier Client", SEASONAL),
    "NC3-038": ("ppc;fire_station_miles", "fire_station_miles <= 10", "ppc_num >= 9", "station distance",
                "PC 9-10 within 10 road miles of the first responding fire department"),
    "NC3-039": confirm("a fire truck can reach the structure", "fire truck access", "ppc_num >= 9", "ppc"),
    "NC3-041": ("occupancy_type", "occupancy_type != Vacant and FACT(not abandoned, for sale, condemned or "
                "foreclosed)", "always", "for sale / condemned", ""),
    "NC3-042": same("NC3-179"),
    "NC3-043": confirm("working smoke detectors on each floor and a fire extinguisher", "smoke detectors"),
    "NC3-044": ("occupancy_type", "occupancy_type != Tenant Occupied", "always", "",
                "a rental goes to the landlord program (NatGen Custom360 DP3)"),
    "NC3-045": confirm("no outbuilding worth more than 50% of Coverage A", "outbuildings", field="dwelling_amount"),
    "NC3-046": confirm("no open claim at application", "open claims"),
    "NC3-047": confirm("no structure away from the premises over $100,000", "structures away"),
    "NC3-048": confirm("no more than 2 structures away from the premises", "structures away"),
    "NC3-050": confirm("not a split or whole log home", "log home", field="construction_type"),
    "NC3-051": ("dwelling_amount;occupancy_type;ppc", "FACT(a central station burglar and fire alarm)",
                PRIMARY + " and ppc_num <= 8 and dwelling_amount > 1500000", "central alarm", ""),
    "NC3-052": ("dwelling_amount;occupancy_type;ppc", "FACT(a central station burglar and fire alarm)",
                PRIMARY + " and ppc_num >= 9 and dwelling_amount > 750000", "central alarm", ""),
    "NC3-053": ("dwelling_amount;occupancy_type", "FACT(a central station burglar and fire alarm)",
                SEASONAL + " and dwelling_amount > 750000", "central alarm", ""),
    # ---- Roof (p.7)
    "NC3-054": ("roof_type", "roof_type not in " + _roofs(TLOCK, ROLLED_ROOF) + " and (roof_type not in {Tile} or "
                "FACT(not Ludowici tile)) and (roof_type not in {Other} or FACT(not tar paper or stapled))", "always",
                "Ludowici tile; tar paper / stapled", "'not all-inclusive'"),
    "NC3-055": confirm("one layer of shingles", "roof layers", "roof_type in {Composition Shingle, Architectural "
                       "Shingle}", "roof_type"),
    "NC3-058": confirm("a Betterview Aerial roof index score of 70 or higher", "Betterview score", IS_WOOD, "roof_type"),
    "NC3-059": confirm("a Cotality Wildfire Score of 10 or less", "wildfire score", IS_WOOD, "roof_type"),
    "NC3-062": ("roof_type;roof_age", "roof_age <= 25", IS_WOOD, "", "a p.7 requirement that clearly fails (Liam)"),
    "NC3-100": ("roof_type", "roof_type not in " + _roofs(WOOD), "always", "",
                "Liam 2026-10-16: the p.11 wildfire list conflicts with p.7's Wood Roofs -- refer"),
    # ---- Solid fuel stoves (p.8, p.16): one confirm
    "NC3-065": same("NC3-066"),
    "NC3-066": confirm(STOVE, "solid fuel stove", note="the Solid Fuel Burning Stove Requirements as one confirm"),
    **{f"NC3-0{n}": same("NC3-066") for n in (68, 69, 70, 71, 73, 74, 75, 76, 78, 79, 80, 81, 82, 83)},
    "NC3-149": confirm("no coal or kerosene secondary heater", "secondary heater"),
    "NC3-151": confirm("no solid fuel burning stove -- a PC 10 home with one is not eligible", "solid fuel stove",
                       "ppc_num >= 10", "ppc"),
    "NC3-152": same("NC3-066"),
    # ---- Pools, trampolines (p.8)
    "NC3-084": ("swimming_pool;pool_gate_locking", "swimming_pool not in {In Ground - Unfenced, Above Ground - "
                "Unfenced} and pool_gate_locking == True", POOL, "gate",
                "a rural home without a fence may be approved by underwriting (NC3-087): a referral"),
    "NC3-085": confirm("the diving board is under 18 inches above the water", "diving board height",
                       "pool_accessories in {Diving board only, Both slide and diving board}",
                       "swimming_pool;pool_accessories"),
    "NC3-086": confirm("a pull-up ladder on the above-ground pool", "pool ladder", ABOVE, "swimming_pool"),
    "NC3-087": same("NC3-084", "swimming_pool"),
    "NC3-089": confirm("no trampoline, or one with safety netting on flat ground", "trampoline"),
    # ---- Wildfire (p.11): one confirm on the score and the brush inspection
    "NC3-097": confirm("a Cotality Wildfire Risk Score under 61, or under 41 in PC 10", "wildfire score"),
    "NC3-098": same("NC3-097"),
    "NC3-099": confirm(BRUSH, "brush inspection", note="the Brush Inspection items as one confirm"),
    **{f"NC3-{n}": same("NC3-099") for n in (101, 102, 103, 105)},
    # ---- Losses (p.12), Liam 2026-10-16
    "NC3-106": (LOSSES, "losses_5yr in {0} or FACT(the loss history needs no underwriting review)", "always", "",
                LOSS_NOTE),
    "NC3-107": (LOSSES, "losses_5yr in {0} or FACT(no disputed loss)", "always", "", LOSS_NOTE),
    "NC3-109": (LOSSES, "losses_3yr in {0, 1, 2} or (not (loss_types none_of {Water, Other}) and FACT(the losses "
                "beyond two are remediated, certified appliance water losses))", "always", "",
                "package: at most 2 paid losses in 3 years; monoline allows fewer, so 3+ fails both readings"),
    "NC3-110": (LOSSES, "losses_3yr in {0, 1} or (not (loss_types none_of {Water, Fire, Liability, Wind or hail, "
                "Other}) and FACT(no more than one theft, one vandalism or one non-appliance water loss in the 3 "
                "years))", "always", "", "2+ losses in 3 years that are all theft fail both readings"),
    "NC3-111": (LOSSES, "losses_3yr in {0} or FACT(a package policy, or an Insurance Score of 1 to 30)", "always", "",
                "the Insurance Score is not asked (UNCLEAR in the guide)"),
    "NC3-112": (LOSSES, "losses_3yr in {0, 1} or FACT(a package policy, or the second loss is a remediated, certified "
                "appliance water loss)", "always", "", "monoline: one loss; package allows two -- a confirm"),
    "NC3-113": (LOSSES, "FACT(no non-remediated mold loss, at any time)", "always", "mold loss",
                "no time limit in the guide: a confirm even with no losses in 5 years"),
    "NC3-114": same("NC3-113", "losses_5yr"),
    "NC3-116": (LOSSES, "losses_5yr in {0} or FACT(no loss caused by negligence or an intentional act)", "always", "",
                LOSS_NOTE),
    "NC3-117": same("NC3-110", "losses_5yr"),
    "NC3-118": (LOSSES, "losses_3yr in {0, 1, 2} or loss_types none_of {Water, Other} or FACT(fewer than 3 paid "
                "appliance claims in the 3 years)", "always", "", LOSS_NOTE),
    # ---- Ineligible exposures (pp.15-16)
    "NC3-119": confirm("no resident in a high-profile profession exposed to libel or slander claims", "profession"),
    "NC3-120": confirm("no vicious or dangerous dog -- a bite claim or medical report, an agency finding, unlawful to "
                       "keep -- and no wild or exotic animal", "dangerous animals"),
    **{f"NC3-{n}": same("NC3-120", "has_dogs") for n in (121, 122, 123, 124)},
    "NC3-125": confirm("no property or casualty policy cancelled, declined or non-renewed for underwriting reasons in "
                       "the past 5 years", "prior cancellation"),
    "NC3-126": ("construction_type", "construction_type != Manufactured/Mobile", "always", "", ""),
    "NC3-127": confirm("no more than 8 units in the fire division", "units per fire division",
                       "dwelling_type == Townhome", "dwelling_type"),
    "NC3-128": ("dwelling_type;construction_type;year_built", "FACT(4 or fewer units)",
                "dwelling_type == Townhome and construction_type == Frame and year_built < 1980", "units",
                "as NCD-059"),
    "NC3-129": confirm("the firewall goes through the roof", "firewall", "dwelling_type == Townhome", "dwelling_type"),
    "NC3-130": confirm("not a yurt, earth or basement home", "unusual home", field="construction_type"),
    "NC3-131": confirm("not a boat house", "boat house"),
    "NC3-132": confirm("no skateboard or bicycle ramp, unless excluded", "ramps"),
    "NC3-133": confirm("no treehouse over 12 feet, unless excluded", "treehouse"),
    "NC3-134": confirm("not on a historic registry", "historic registry"),
    "NC3-135": confirm("not on an open foundation", "foundation"),
    "NC3-136": confirm("not an island exposure", "island"),
    "NC3-137": confirm("not on piers, stilts, wharves, jetties or pilings", "foundation"),
    "NC3-138": ("electrical", "electrical none_of {Knob-and-tube wiring, Aluminum branch wiring}", "always", "",
                "round 37 step 4: blank or Unknown is a confirm"),
    "NC3-139": ("electrical", "electrical none_of {Federal Pacific or Zinsco panel}", "always", "",
                "Stab-Lok is the Federal Pacific panel"),
    "NC3-140": confirm("on a permanent slab or foundation", "foundation"),
    "NC3-142": confirm("not of obsolete, uncommon, unconventional or irreplaceable construction", "construction",
                       field="construction_type"),
    "NC3-143": confirm("built, renovated and remodeled by licensed contractors", "contractor"),
    "NC3-144": confirm("not a home converted from shipping containers", "container home", field="construction_type"),
    "NC3-145": confirm("not converted to a dwelling from another use; a barndominium is allowed", "converted use"),
    "NC3-146": confirm("4 stories or fewer", "stories"),
    "NC3-147": confirm("not a relocated dwelling", "relocated"),
    "NC3-148": confirm("primary heat is not from a portable source", "portable heat"),
    "NC3-150": confirm("central heating, unless in a warm climate or a winterized seasonal home", "central heat"),
    "NC3-153": confirm("no underground oil tank", "oil tank"),
    "NC3-156": confirm("on a paved road passable in all seasons", "road"),
    "NC3-157": confirm("not in a known wave wash, sinkhole, pollution, landslide or cave-in area", "hazard area"),
    "NC3-158": confirm("not in flood zone A or V without an active flood policy -- not eligible otherwise", "flood zone"),
    "NC3-159": confirm("market value at least 70% of the current replacement cost", "market value",
                       field="dwelling_amount"),
    "NC3-160": ("dwelling_amount;year_built", "FACT(the Functional Replacement Cost endorsement, or Premier Client "
                "coverage)", "dwelling_amount > 1500000 and year_built < 1930", "endorsement", ""),
    "NC3-161": ("dwelling_amount", "FACT(the Extended Replacement Cost endorsement)", "dwelling_amount > 1500000",
                "endorsement", "also over 5,000 square feet (not asked)"),
    "NC3-162": confirm("inside a legal fire protection jurisdiction", "fire district"),
    "NC3-163": confirm("no commercial exposure or non-incidental business on the premises", "business"),
    "NC3-164": confirm("not within 100 feet of a commercial or industrial property", "neighbours"),
    "NC3-165": confirm("the primary residence is not rented, or a short-term rental of up to 3 months approved by "
                       "underwriting", "rented primary", PRIMARY),
    "NC3-166": same("NC3-165"),
    "NC3-167": confirm("rented no more than 12 weeks a year", "rented seasonal home", SEASONAL),
    "NC3-168": confirm("Home Sharing coverage if rented to tenants", "Home Sharing coverage", SEASONAL),
    "NC3-169": confirm("only one primary residence on the policy", "primary residences"),
    "NC3-170": confirm("no more than 2 mortgages", "mortgages"),
    "NC3-171": confirm(FARM, "farming", note="the True Farming Exposures as one confirm"),
    **{f"NC3-{n}": same("NC3-171") for n in (172, 173, 174, 175, 176, 177, 178)},
    # ---- Course of Construction (p.25): one confirm
    "NC3-179": confirm(COC, "under construction", note="the Course of Construction Endorsement as one confirm"),
    "NC3-180": confirm("not under construction or significant renovation -- in PC 9-10 such a home is not "
                       "eligible", "under construction", "ppc_num >= 9", "ppc"),
    **{f"NC3-{n}": same("NC3-179") for n in (181, 182, 183, 184)},
    # ---- Secondary / seasonal homes (p.38)
    "NC3-187": confirm("the secondary home is furnished, with heat and utilities all year",
                       "heat and utilities", "occupancy_type == Secondary Home"),
    "NC3-188": confirm("heat and utilities on, or drained and winterized if unused in winter", "winterized",
                       "occupancy_type == Seasonal"),
}


def coverage(ev):
    out = dict.fromkeys(KINDS, 0)
    for r in ev:
        out[kind(MAP.get(r["Rule ID"], ("NONE", "", "", "", "")))] += 1
    return out


def main():
    rows = list(csv.DictReader(l for l in open(RULES, encoding="utf-8-sig") if not l.startswith("#")))
    ev = [r for r in rows if r["Tool handling"] in ("EVALUATE", "EVALUATE_CURE_IS_INSPECTION")]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write("# source: rules_data/build_natgen_c360_map.py over rules_data/carrier_rules_natgen_c360_ho3_v1.csv "
                 "(NatGen Custom360 HO3 version 1, reviewed); built 2026-10-16 (round 40 step 2). "
                 "Grammar: rules_data/RULE_FIELD_MAP.md.\n")
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["row_id", "field", "test", "gate", "outcome_if_fail", "open_fact", "map_note"])
        for r in ev:
            rid = r["Rule ID"]
            cure = r["Tool handling"] == "EVALUATE_CURE_IS_INSPECTION"
            field, test, gate, open_fact, note = MAP.get(rid, ("NONE", "", "", "", NONE_NOTE.get(
                r["Topic"], "the form has no field for this")))
            w.writerow([rid, field, test, gate, "NOTE" if cure else (r["Effect"] or "UNKNOWN"), open_fact, note])
    unknown = sorted(set(MAP) - {r["Rule ID"] for r in ev})
    print(f"wrote {OUT}: {len(ev)} lines, {sum(1 for r in ev if r['Rule ID'] in MAP)} mapped; "
          f"map ids not deciding rows: {unknown}")
    print(coverage(ev))
    print("NONE:", [r["Rule ID"] for r in ev if r["Rule ID"] not in MAP])


if __name__ == "__main__":
    main()
