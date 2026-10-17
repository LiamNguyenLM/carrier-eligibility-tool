"""Build rules_data/occidental_field_map.csv -- one line per deciding row (Tool handling EVALUATE /
EVALUATE_CURE_IS_INSPECTION) of rules_data/carrier_rules_occidental_ho3_v1.csv, SageSure Occidental HO3 (Texas
Occidental Homeowners Program, "REVISED 12/2/2025"; round 40 step 2, Liam 2026-10-16).

Every deciding row has a line (Liam, 2026-10-14): a form field decides it where the form asks the fact; otherwise it is
a FACT(...) confirm; a row restating another's fact reads "decided by". The guide is a SageSure HO3 guide like SURE /
SafePort / Wilshire: the shared lines are build_sage_batch_map.sister()'s, so a rule worded the same is decided the
same way.
- Address (OCC-001, either/or with OCC-002): a county entirely south of 31 N except Nueces, or one of the eight East
  Texas counties (rules_data/occidental_counties.csv lists the result per county). A blank county holds the carrier
  through the Sage county hold, as for every Sage program.
- FPC table (OCC-093..096): Liam's Sage FPC hold decisions (2026-10-06 / 2026-10-08) apply
  (rules_evaluator.FPC_TABLE_HOLDS).
- Extreme Hazard (OCC-006..012): the other Sage HO3 tables' lines for the same wording (round 35: SAG-089, SUR-163,
  SFP-172); each confirm names the HO 04 70 + TWIA override (OCC-017 / OCC-018), which makes such a home eligible.
- Tenant-occupied: only other units of a 2-4 family home the owner lives in; a home occupied only by tenants is not
  eligible (OCC-020).
- Steel roof gauge (OCC-055): 29 gauge or heavier passes, aluminum or tin declines -- the form does not say the metal
  or the gauge, so a confirm.

usage: python rules_data/build_occidental_map.py
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_rule_field_map import METAL, NONE_NOTE, SEASONAL, TLOCK, _roofs  # noqa: E402
from build_sage_batch_map import EAST_TEXAS, KINDS, kind, sister  # noqa: E402
from loss_electrical_lines import LINES as LE  # noqa: E402

RULES = os.path.join(HERE, "carrier_rules_occidental_ho3_v1.csv")
OUT = os.path.join(HERE, "occidental_field_map.csv")

TIER1 = "coastal_tier == Tier 1"
TIER123 = "coastal_tier in {Tier 1, Tier 2, Tier 3}"
POOL = "swimming_pool != No Pool"
ABOVE = "swimming_pool in {Above Ground - Fenced, Above Ground - Unfenced}"
OWNER_PRIMARY = "occupancy_type == Owner Occupied"
MULTI = "dwelling_type == House and units_in_building in {2, 3-4}"
LOSSES = "losses_5yr;losses_3yr;loss_types"
TWIA = ", or wind/hail excluded on the HO 04 70 and placed with TWIA"


def confirm(fact, label, gate="always", field="occupancy_type", note=""):
    """A fact the form never asks: a Confirm note when the gate holds (occupancy_type is always on)."""
    return (field, f"FACT({fact})", gate, label, note)


def same(rid, field="occupancy_type"):
    return (field, "always", "always", "", f"decided by {rid} (the same rule); never a second flaw")


MAP = sister("OCC", {
    "owner": "OCC-020", "unoccupied_3mo": "OCC-022", "vacant": "OCC-028", "seasonal_checks": "OCC-025",
    "trust_one": "OCC-043", "llc": "OCC-041", "mobile": "OCC-046", "pool_gate": "OCC-080", "pool_fence": "OCC-081",
    "pool_above": "OCC-082", "fpc_b13": "OCC-093", "fpc_c13": "OCC-094", "fpc_b410": "OCC-095", "fpc_c48": "OCC-096",
    "fpc_9": "OCC-097", "poly": "OCC-072", "roof_flat": "OCC-054", "cov_min_refer": "OCC-128",
    "east_texas": None})
MAP.update({
    # ---- Address (p.2): one row says both halves
    "OCC-001": ("county", "(south_of_31 == True and county != Nueces) or county in {" + EAST_TEXAS + "}", "always",
                "", "rules_data/occidental_counties.csv: a county entirely south of 31 N except Nueces, or East Texas"),
    "OCC-003": confirm("no part of the main residence is built over water or reached only by water", "over water"),
    "OCC-004": confirm("not in a condemned area or one scheduled to be condemned", "condemned area"),
    "OCC-005": confirm("not a wildfire score over 80 within 250 feet of wildland", "wildfire score"),
    # ---- Coastal Extreme Hazard (pp.14-15): the other Sage HO3 tables' lines; the TWIA override in each confirm
    "OCC-006": ("coastal_tier", "FACT(not an extreme hazard location" + TWIA + ")", TIER1, "distance to shoreline",
                "the form's tiers are not the guide's tiers (as SUR-161)"),
    "OCC-007": ("coastal_tier", "FACT(not on a barrier island" + TWIA + ")", TIER1, "barrier island", "as SFP-170"),
    "OCC-008": ("coastal_tier", "FACT(not on Bolivar, Matagorda or a similar peninsula" + TWIA + ")", TIER1,
                "peninsula", "as SFP-171"),
    "OCC-009": ("coastal_tier", "FACT(not within 3 miles of the primary shoreline in a tier 1 county" + TWIA + ")",
                TIER123, "distance to shoreline", "as SAG-089 / SUR-163 / SFP-172 (round 35)"),
    "OCC-010": ("coastal_tier", "FACT(not within 0.1 miles of the primary shoreline in a tier 2 county" + TWIA + ")",
                TIER1, "distance to shoreline", "as SFP-173"),
    "OCC-011": ("coastal_tier", "FACT(not within 0.04 miles of an inner shoreline" + TWIA + ")", TIER1,
                "distance to inner shoreline", "as SFP-174"),
    "OCC-012": ("coastal_tier", "FACT(not in the front or first row of dwellings" + TWIA + ")", TIER1, "first row",
                "as SFP-175"),
    "OCC-017": same("OCC-006"),
    "OCC-018": same("OCC-006"),
    "OCC-019": ("coastal_tier", "FACT(if subject to wave wash, a flood policy at Coverage A up to the NFIP maximum)",
                TIER1, "flood policy", ""),
    # ---- Occupancy (pp.2-4)
    "OCC-021": confirm("the primary residence is not rented for more than 2 weeks", "rented 2+ weeks", OWNER_PRIMARY),
    # round 39 step 4: "single family" read from "Units in the building" (a townhome is one unit)
    "OCC-023": ("occupancy_type;dwelling_type;units_in_building",
                "dwelling_type in {House, Townhome} and (dwelling_type == Townhome or units_in_building in {1})",
                SEASONAL, "", "single family = a Townhome or a 1-unit House; a blank unit count is a confirm"),
    "OCC-024": confirm("no rental occupancies", "rentals", SEASONAL),
    "OCC-026": confirm("the mailing address is the residence premises", "mailing address", OWNER_PRIMARY),
    "OCC-027": confirm("a newly bought home is occupied within 30 days of purchase", "occupied within 30 days"),
    "OCC-031": confirm("no more than 3 full-time rentals in all", "rentals", MULTI, "dwelling_type;units_in_building"),
    "OCC-034": confirm("no short-term tenants, roomers or boarders", "short-term rentals"),
    "OCC-035": confirm("not rented to full-time students", "student tenants", MULTI, "dwelling_type;units_in_building"),
    "OCC-036": confirm("no more than 2 unrelated tenants per unit", "tenants per unit", MULTI,
                       "dwelling_type;units_in_building"),
    "OCC-037": confirm("no lease under 6 months on a rented unit with a pool", "short-term rental with a pool",
                       POOL + " and " + MULTI, "swimming_pool;dwelling_type;units_in_building"),
    "OCC-038": confirm("every rental unit has a full-time renter", "full-time renters",
                       "dwelling_type == House and units_in_building in {3-4}", "dwelling_type;units_in_building"),
    "OCC-039": confirm("each rented unit is rented for 6 months or more", "long-term renters", MULTI,
                       "dwelling_type;units_in_building"),
    # ---- Ownership (pp.2-3)
    "OCC-040": confirm("owned by one individual, or by two with one living there", "owners",
                       "ownership_type == Individual Owner", "ownership_type"),
    "OCC-042": ("ownership_type;trust_type;occupancy_type",
                "occupancy_type != Tenant Occupied and trust_type not in {Land trust, Corporate or business trust} "
                "and (trust_type in {Family trust} or FACT(family held trust)) and FACT(occupied by the trustee, "
                "grantor or beneficiary)", "ownership_type == Trust", "who lives there; family held trust",
                "SUR-019 + SUR-020 in one row; a land or corporate trust fails, an unknown type holds"),
    # ---- Dwelling (pp.2-4): round 39 step 4, "Units in the building"
    "OCC-044": ("dwelling_type;units_in_building", "units_in_building not in {5 or more}", "dwelling_type == House",
                "", "one to four family; a blank unit count is a confirm"),
    "OCC-045": confirm("originally built as a private residence", "original use"),
    "OCC-047": same("OCC-046", "construction_type"),
    # ---- Roof (p.12)
    "OCC-055": ("roof_type", "FACT(steel of 29 gauge or heavier, not aluminum or tin)", "roof_type in " + METAL,
                "metal and gauge", "29 gauge or heavier (gauge number 29 or lower) passes; aluminum or tin fails -- "
                "the form names neither"),
    "OCC-057": confirm("no more than 2 layers of roofing", "roof layers", field="roof_type"),
    "OCC-058": ("roof_type", "roof_type not in " + _roofs(TLOCK), "always", "", "'T-Lock or inter-locking shingles'"),
    # ---- Construction (pp.4-5)
    "OCC-060": confirm("the primary dwelling is not a metal building", "metal building", field="construction_type"),
    "OCC-061": confirm("no metal other structure over 750 square feet", "large metal structures",
                       field="construction_type"),
    "OCC-062": confirm("no EIFS, DEFS or Dryvit beyond trim or a minimal part of the siding", "EIFS",
                       field="construction_type"),
    "OCC-064": confirm("not log, earth, underground, do-it-yourself, dome, A-frame or other unconventional "
                       "construction", "unconventional construction", field="construction_type"),
    "OCC-065": same("OCC-064", "construction_type"),
    "OCC-066": confirm("not under construction", "under construction"),
    "OCC-069": confirm("on a permanent foundation", "foundation"),
    "OCC-070": confirm("no prior slab or sinkhole damage, settling cracks or nearby sinkhole activity", "sinkhole"),
    # ---- Systems (pp.11-12)
    "OCC-073": confirm("the electrical service is at least 100 amps", "service amps", field="electrical"),
    "OCC-074": ("electrical", "electrical none_of {Federal Pacific or Zinsco panel} and FACT(no Magnetrip or "
                "Challenger or Sylvania panel)", "always", "panel maker", "as SUR-137"),
    "OCC-075": ("electrical", "electrical none_of {Aluminum branch wiring, Knob-and-tube wiring, Fuses}", "always", "",
                "as SUR-138; multi-strand aluminum service cable and appliance wiring are allowed"),
    "OCC-076": confirm("a thermostatically controlled central heating system", "central heat"),
    "OCC-077": confirm("the furnace or burner was replaced within 30 years, or an HVAC contractor attests to it",
                       "furnace age"),
    "OCC-078": confirm("no wood, wood pellet or coal stove", "wood stove"),
    # ---- Pools and hazards (pp.5-6)
    "OCC-083": ("swimming_pool;pool_accessories", "pool_accessories == None", POOL, "",
                "'Pools with slides or diving boards' are ineligible (no acknowledgement path)"),
    "OCC-084": confirm("no immovable ladder on an above-ground pool 4 feet or higher", "pool ladder", ABOVE,
                       "swimming_pool"),
    "OCC-085": confirm("a pool attached to decking has a locked gate", "decking gate", POOL, "swimming_pool"),
    "OCC-086": confirm("the pool is filled, or completely and securely covered", "unfilled pool", POOL,
                       "swimming_pool"),
    "OCC-088": confirm("no skateboard ramp, bicycle jump, treehouse, batting cage, zip line or other attractive "
                       "nuisance", "attractive nuisance"),
    # ---- Acreage, business, people (pp.4, 7)
    "OCC-098": confirm("5 acres or less, or no third party pays to use the property", "acreage"),
    "OCC-099": confirm("no farming or ranching beyond a family garden", "farming"),
    "OCC-100": confirm("no business with employees, client traffic or products on the premises", "business"),
    "OCC-101": confirm("no child care or day care on the premises", "day care"),
    "OCC-102": confirm("no applicant convicted in the past 6 years of a felony of insurance fraud, arson, bribery, "
                       "theft, embezzlement or harm to others", "felony"),
    "OCC-103": confirm("no diseased or dead tree that could fall on a structure", "dead trees"),
    "OCC-114": confirm("no major renovation under way or planned", "renovation"),
    "OCC-115": same("OCC-114"),
    # ---- Prior insurance (p.11)
    "OCC-116": confirm("prior insurance with no lapse, or a lapse of 30 days or less with no losses during it",
                       "prior insurance"),
    "OCC-117": same("OCC-116"),
    "OCC-118": same("OCC-116"),
    # ---- Losses (pp.7-8)
    "OCC-119": (LOSSES, "(" + LE["SUR-083"][1] + ") and (" + LE["SUR-084"][1] + ")", "always", "",
                "SUR-083 and SUR-084 in one row (2 in 3 years, 3 in 6 years)"),
    "OCC-120": (LOSSES, "losses_5yr in {0} or loss_types none_of {Water, Other} or FACT(appliance water claims are "
                "certified on TDI form WDR-1)", "always", "", "a cure by inspection: a note, never a hold"),
    "OCC-121": (LOSSES, "losses_5yr in {0} or loss_types none_of {Water, Other} or FACT(no mold claim, or the home is "
                "certified mold free on TDI form MDR-1)", "always", "", "a cure by inspection: a note"),
    "OCC-123": (LOSSES, "losses_5yr in {0, 1} or FACT(the losses are from different perils, or repaired and "
                "unrelated)", "always", "", "2 or more losses from the same peril refer"),
    "OCC-125": confirm("no homeowners policy ever cancelled or non-renewed for material misrepresentation",
                       "misrepresentation"),
    # ---- Coverage A (pp.8-9)
    "OCC-126": ("dwelling_amount", "dwelling_amount <= 2000000", "always", "", ""),
    "OCC-129": confirm("insured to 100% of replacement cost", "insurance to value", field="dwelling_amount"),
})


# Round 40 step 3b (the second reader, 2026-10-16): where Occidental's own words say more than the shared Sage line.
# (OCC-095 / OCC-096's "No prior fire losses" -- a fire loss on the form fails it -- is in the shared line since round
# 41 A6, for every Sage guide.)
SEASONAL_OR_SECOND = "occupancy_type in {Seasonal, Secondary Home}"
MAP.update({
    # p.2: "Residence not continuously unoccupied 3 or more consecutive months" -- under the seasonal / secondary
    # home too, where the form's Vacant (OCC-028) does not reach it
    "OCC-022": confirm("not unoccupied 3 or more consecutive months", "unoccupied 3 months", SEASONAL_OR_SECOND),
    "OCC-025": ("occupancy_type", "FACT(property checked at least once a month while the owner is away)",
                SEASONAL_OR_SECOND, "checks while away", ""),
    # p.4: "(primary home or other structures)" -- the form asks only about the main dwelling
    "OCC-046": ("construction_type", "construction_type != Manufactured/Mobile and FACT(no mobile, manufactured or "
                "motor home used as a residence elsewhere on the premises)", "always", "mobile home on the premises",
                "modular / motor homes are not form options; the guide covers other structures too"),
    # p.5: "The main dwelling is always ineligible. Other structures can be referred to the underwriter"
    "OCC-064": confirm("the main dwelling and its additions are not log, earth, underground, do-it-yourself, dome, "
                       "A-frame or other unconventional construction -- such an other structure is referred or "
                       "excluded", "unconventional construction", field="construction_type"),
    # p.4: "Over 5 acres is eligible as long as no remuneration is received ... A pre-bind underwriting referral is
    # required."
    "OCC-098": confirm("5 acres or less -- over 5 acres needs a pre-bind underwriting referral, and no one may pay "
                       "to use the property", "acreage"),
    # p.11: "Underwriters will consider referrals for situations where the insured will occupy the house during the
    # renovations or the renovations will be complete within 30 days."
    "OCC-114": confirm("no major renovation under way or planned -- underwriting considers a referral if the insured "
                       "lives there during it or it is done within 30 days", "renovation"),
    # p.11: the three tiers of a lapse
    "OCC-116": confirm("prior insurance with no lapse, or a lapse of 30 days or less with no losses during it -- 31 "
                       "to 120 days refers with a No Loss Letter; over 120 days is not eligible", "prior insurance"),
})
OCC_NONE_NOTE = dict(NONE_NOTE)


def coverage(ev):
    out = dict.fromkeys(KINDS, 0)
    for r in ev:
        out[kind(MAP.get(r["Rule ID"], ("NONE", "", "", "", "")))] += 1
    return out


def main():
    rows = list(csv.DictReader(l for l in open(RULES, encoding="utf-8-sig") if not l.startswith("#")))
    ev = [r for r in rows if r["Tool handling"] in ("EVALUATE", "EVALUATE_CURE_IS_INSPECTION")]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write("# source: rules_data/build_occidental_map.py over rules_data/carrier_rules_occidental_ho3_v1.csv "
                 "(SageSure Occidental HO3 version 1, reviewed); built 2026-10-16 (round 40 step 2). "
                 "Grammar: rules_data/RULE_FIELD_MAP.md.\n")
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["row_id", "field", "test", "gate", "outcome_if_fail", "open_fact", "map_note"])
        for r in ev:
            rid = r["Rule ID"]
            cure = r["Tool handling"] == "EVALUATE_CURE_IS_INSPECTION"
            field, test, gate, open_fact, note = MAP.get(rid, ("NONE", "", "", "", OCC_NONE_NOTE.get(
                r["Topic"], "the form has no field for this")))
            w.writerow([rid, field, test, gate, "NOTE" if cure else (r["Effect"] or "UNKNOWN"), open_fact, note])
    unknown = sorted(set(MAP) - {r["Rule ID"] for r in ev})
    print(f"wrote {OUT}: {len(ev)} lines, {sum(1 for r in ev if r['Rule ID'] in MAP)} mapped; "
          f"map ids not deciding rows: {unknown}")
    print(coverage(ev))
    print("NONE:", [r["Rule ID"] for r in ev if r["Rule ID"] not in MAP])


if __name__ == "__main__":
    main()
