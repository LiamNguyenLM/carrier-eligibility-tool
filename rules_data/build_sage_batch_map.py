"""Build rules_data/sage_batch_field_map.csv -- one line per deciding row (Tool
handling EVALUATE / EVALUATE_CURE_IS_INSPECTION) of
rules_data/carrier_rules_sage_batch_v2.csv, the Sage batch (round 27 step 5,
Liam's decision 4, 2026-10-06): SURE HO-3, SafePort HO-3, Wilshire HO3,
Trium Lloyd's HO3/HO5, Markel HO3, Vave HO3.

Same grammar and conventions as build_rule_field_map.py (see
rules_data/RULE_FIELD_MAP.md). Every non-NONE line is written by hand below; a
row with no line is NONE (the form has no field that decides it). Where a
reading is unclear the line is AMBIGUOUS ("||") rather than a guess.

Choices that differ from the Auros lines (listed in RULE_FIELD_MAP.md):
- "Dwellings must be owner occupied" covers the guide's primary AND seasonal /
  secondary residences, so the test is "not Tenant Occupied"; Vacant is
  decided by the vacancy row. (SAG-001 tests Owner Occupied only, so it fails
  a seasonal home the guide accepts; listed, not changed.)
- One fact, one failing row: the 3-months-unoccupied rows, the East Texas
  county list and the second mobile-home row restate a rule another row
  already decides; their test is "always" and the note names that row. (In
  Auros, Vacant fails SAG-001, SAG-002 and SAG-005: three flaws for one fact.)
- Territory: the south-of-31 / East Texas row tests "sage_territory == IN or
  county == Nueces", and the guide's own Nueces row decides Nueces. Trium's
  guide has no Nueces exception, so Trium has no Nueces row and Nueces is IN.

usage: python rules_data/build_sage_batch_map.py
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_rule_field_map import BREED, DOGS, FLAT, NONE_NOTE, POOL_OK, SEASONAL  # noqa: E402

RULES = os.path.join(HERE, "carrier_rules_sage_batch_v2.csv")
OUT = os.path.join(HERE, "sage_batch_field_map.csv")

OWNER = "occupancy_type != Tenant Occupied"
NOT_VACANT = "occupancy_type != Vacant"
EAST_TEXAS = "Bell, Falls, Robertson, Leon, Madison, Houston, Trinity, Polk"
TRUST = "ownership_type == Trust"
LLC = "ownership_type == LLC"
IN_GROUND = "swimming_pool in {In Ground - Fenced, In Ground - Unfenced}"
ABOVE = "swimming_pool in {Above Ground - Fenced, Above Ground - Unfenced}"
TIER1 = "coastal_tier == Tier 1"
TIER12 = "coastal_tier in {Tier 1, Tier 2}"
TIER123 = "coastal_tier in {Tier 1, Tier 2, Tier 3}"   # round 35 step 1: a tier-1 county's 3-mile band
# The Sage FPC table (round 26 decision B; the same rows as SAG-073..078).
FPC_B13 = "ppc_num between 1 and 3 and fire_station_miles <= 5 and hydrant_1000ft == No"
FPC_C13 = "ppc_num between 1 and 3 and fire_station_miles > 5"
FPC_B410 = "ppc_num between 4 and 10 and fire_station_miles <= 5 and hydrant_1000ft == No"
FPC_C48 = "ppc_num between 4 and 8 and fire_station_miles > 5"
# Round 28 step 2: the seven-condition rows are FPC 4-10 within 5 miles with no hydrant, and
# FPC 4-8 over 5 miles. FPC 9-10 over 5 miles is row C 9+ (declined), never these rows.
FPC_7ROWS = ("(ppc_num between 4 and 8 and (hydrant_1000ft == No or fire_station_miles > 5)) or (ppc_n"
             "um between 9 and 10 and hydrant_1000ft == No and fire_station_miles <= 5)")
FPC_BC = "(fire_station_miles <= 5 and hydrant_1000ft == No) or fire_station_miles > 5"
ROW_FACT_3 = "FACT(visible from road, central station alarm, 10-ft year-round access)"
ROW_FACT_7 = ("home_age < 25 and occupancy_type == Owner Occupied and "
              "FACT(visible from road, central alarm, 10-ft access, no rentals, no prior fire loss)")
OPEN_B = "station / hydrant distance if not given"
OPEN_C = "station distance if not given"


def same_as(rid, field="occupancy_type"):
    """A row whose rule another row already decides: it never fails twice."""
    return (field, "always", "always", "", f"decided by {rid} (the same rule); never a second flaw")


def sister(p, ids):
    """The lines the four Auros-structured guides share. ids: concept -> row id."""
    m = {}

    def put(concept, line):
        if ids.get(concept):
            m[ids[concept]] = line

    # v2 (2026-10-07): the East Texas list applies only to a county NOT entirely south of 31 N, so it
    # decides that half; Nueces has its own row (not in Trium). The south-of-31 row restates both.
    put("territory", same_as(" and ".join(x for x in (ids["east_texas"], ids.get("nueces")) if x), "county"))
    put("nueces", ("county", "county != Nueces", "always", "", ""))
    put("east_texas", ("county", "county in {" + EAST_TEXAS + "}", "south_of_31 == False", "",
                       "a county not entirely south of 31 N (v2)" + ("" if ids.get("nueces") else
                                                                    "; this guide has no Nueces exception")))
    put("owner", ("occupancy_type", OWNER, "always", "",
                  "owner occupied = primary, seasonal or secondary residence; Vacant is decided by "
                  + ids["vacant"]))
    put("unoccupied_3mo", same_as(ids["vacant"]))
    put("vacant", ("occupancy_type", NOT_VACANT, "always", "", "for sale is not asked"))
    put("seasonal_single", ("occupancy_type;dwelling_type", "dwelling_type == House", SEASONAL, "", ""))
    put("seasonal_checks", ("occupancy_type", "FACT(property checked while the owner is away)", SEASONAL,
                            "checks while away", ""))
    put("trust_occupied", ("ownership_type;occupancy_type", OWNER, TRUST, "", ""))
    put("trust_family", ("ownership_type", "FACT(family held trust)", TRUST, "family held trust", ""))
    put("trust_one", ("ownership_type", "FACT(only one trust on the property)", TRUST, "number of trusts", ""))
    put("llc", ("ownership_type", "ownership_type != LLC", "always", "", ""))
    put("mobile", ("construction_type", "construction_type != Manufactured/Mobile", "always", "",
                   "modular / motor homes are not form options"))
    put("mobile_excl", same_as(ids["mobile"], "construction_type"))
    put("lead", ("year_built;occupancy_type", "FACT(signed lead exclusion acknowledgement)",
                 "occupancy_type == Tenant Occupied and year_built < 1980", "signed acknowledgement", ""))
    put("pool_gate", ("swimming_pool;pool_gate_locking",
                      "swimming_pool != In Ground - Unfenced and pool_gate_locking == True", IN_GROUND, "gate", ""))
    put("pool_fence", ("swimming_pool;pool_fence_4ft", "pool_fence_4ft == True",
                       "swimming_pool == In Ground - Fenced", "fence 4 ft",
                       "an unfenced in-ground pool fails the gate row once, not this row too"))
    put("pool_surround", same_as(ids.get("pool_fence"), "swimming_pool"))
    put("pool_above", ("swimming_pool;pool_fence_4ft;pool_gate_locking", POOL_OK, ABOVE, "fence 4 ft; gate",
                       "the rule is for above-ground pools under 4 ft; pool height is not asked"))
    put("pool_slide", ("pool_accessories", "FACT(signed acknowledgement of the slide/diving board exclusion)",
                       "pool_accessories != None", "signed acknowledgement", ""))
    put("dog_breed", ("has_dogs;aggressive_breed", BREED, DOGS, "", "a signed acknowledgement cures"))
    put("dog_bite", ("has_dogs", "FACT(no bite history)", DOGS, "bite history", ""))
    put("fpc_b13", ("ppc;fire_station_miles;hydrant_1000ft", ROW_FACT_3, FPC_B13,
                    OPEN_B + "; visibility, alarm, access", "the FPC table row is chosen by station distance and hydrant"))
    put("fpc_c13", ("ppc;fire_station_miles", ROW_FACT_3, FPC_C13, OPEN_C + "; visibility, alarm, access", ""))
    put("fpc_b410", ("ppc;year_built;occupancy_type;fire_station_miles;hydrant_1000ft", ROW_FACT_7, FPC_B410,
                     OPEN_B + "; visibility, alarm, access, fire losses", ""))
    put("fpc_c48", ("ppc;year_built;occupancy_type;fire_station_miles", ROW_FACT_7, FPC_C48,
                    OPEN_C + "; visibility, alarm, access, fire losses", ""))
    put("fpc_9", ("ppc;fire_station_miles", "fire_station_miles <= 5", "ppc_num >= 9", "station distance", ""))
    put("fpc_age", ("year_built;ppc;fire_station_miles;hydrant_1000ft", "home_age < 25", FPC_7ROWS, OPEN_B, ""))
    put("fpc_primary", ("occupancy_type;ppc;fire_station_miles;hydrant_1000ft",
                        "occupancy_type == Owner Occupied and FACT(no rental exposures)", FPC_7ROWS,
                        OPEN_B + "; rental exposures", ""))
    put("fpc_primary_only", ("occupancy_type;ppc;fire_station_miles;hydrant_1000ft",
                             "occupancy_type == Owner Occupied", FPC_7ROWS, OPEN_B, ""))
    put("fpc_no_rentals", ("occupancy_type;ppc;fire_station_miles;hydrant_1000ft",
                           "occupancy_type != Tenant Occupied and FACT(no rental exposures)", FPC_7ROWS,
                           OPEN_B + "; rental exposures", ""))
    put("fpc_fire_loss", ("ppc;fire_station_miles;hydrant_1000ft", "FACT(no prior fire loss)", FPC_7ROWS,
                          OPEN_B + "; fire losses", ""))
    put("poly", ("plumbing_type", "plumbing_type != Polybutylene", "always", "", ""))
    put("roof_flat", ("roof_shape;roof_type", "FACT(no prior roof wind/water loss, or fully renovated)", FLAT,
                      "prior roof loss; renovation", ""))
    put("roof_metal", ("roof_type", "FACT(steel, 29 gauge or heavier)", "roof_type == Metal", "metal roof gauge", ""))
    put("cov_min_refer", ("dwelling_amount", "dwelling_amount >= 85000", "always", "", ""))
    return m


MAP = {}
MAP.update(sister("SUR", {
    "territory": "SUR-001", "nueces": "SUR-002", "east_texas": "SUR-003", "owner": "SUR-013",
    "unoccupied_3mo": "SUR-015", "vacant": "SUR-024", "seasonal_single": "SUR-016", "seasonal_checks": "SUR-018",
    "trust_occupied": "SUR-019", "trust_family": "SUR-020", "trust_one": "SUR-021", "llc": "SUR-007",
    "mobile": "SUR-041", "mobile_excl": "SUR-042", "lead": "SUR-028", "pool_gate": "SUR-060",
    "pool_fence": "SUR-061", "pool_above": "SUR-062", "pool_slide": "SUR-066", "dog_breed": "SUR-069",
    "dog_bite": "SUR-070", "fpc_b13": "SUR-111", "fpc_c13": "SUR-112", "fpc_b410": "SUR-113", "fpc_c48": "SUR-114",
    "fpc_9": "SUR-115", "fpc_age": "SUR-116", "fpc_primary": "SUR-117", "poly": "SUR-135", "roof_flat": "SUR-148",
    "roof_metal": "SUR-149", "cov_min_refer": "SUR-100"}))
MAP.update(sister("SFP", {
    "territory": "SFP-001", "nueces": "SFP-002", "east_texas": "SFP-003", "owner": "SFP-013",
    "unoccupied_3mo": "SFP-015", "vacant": "SFP-024", "seasonal_single": "SFP-016", "seasonal_checks": "SFP-018",
    "trust_occupied": "SFP-019", "trust_family": "SFP-020", "trust_one": "SFP-021", "llc": "SFP-007",
    "mobile": "SFP-041", "mobile_excl": "SFP-043", "lead": "SFP-028", "pool_gate": "SFP-059",
    "pool_fence": "SFP-060", "pool_above": "SFP-061", "pool_slide": "SFP-065", "dog_breed": "SFP-070",
    "dog_bite": "SFP-073", "fpc_b13": "SFP-119", "fpc_c13": "SFP-120", "fpc_b410": "SFP-121", "fpc_c48": "SFP-122",
    "fpc_9": "SFP-123", "fpc_age": "SFP-124", "fpc_primary": "SFP-125", "poly": "SFP-142", "roof_flat": "SFP-154",
    "roof_metal": "SFP-155", "cov_min_refer": "SFP-107"}))
MAP.update(sister("WIL", {   # Wilshire: pools and animals are liability exclusions (COVERAGE_ONLY rows)
    "territory": "WIL-001", "nueces": "WIL-002", "east_texas": "WIL-003", "owner": "WIL-013",
    "unoccupied_3mo": "WIL-015", "vacant": "WIL-024", "seasonal_single": "WIL-016", "seasonal_checks": "WIL-018",
    "trust_occupied": "WIL-019", "trust_family": "WIL-020", "trust_one": "WIL-021", "llc": "WIL-007",
    "mobile": "WIL-044", "fpc_b13": "WIL-116", "fpc_c13": "WIL-117", "fpc_b410": "WIL-118", "fpc_c48": "WIL-119",
    "fpc_9": "WIL-120", "fpc_age": "WIL-121", "fpc_primary": "WIL-122", "fpc_fire_loss": "WIL-123",
    "poly": "WIL-140", "roof_flat": "WIL-152", "roof_metal": "WIL-153", "cov_min_refer": "WIL-105"}))
MAP.update(sister("TRI", {   # Trium: no Nueces exception, so no Nueces row
    "territory": "TRI-093", "east_texas": "TRI-094", "owner": "TRI-002",
    "unoccupied_3mo": "TRI-003", "vacant": "TRI-008", "seasonal_single": "TRI-004", "seasonal_checks": "TRI-005",
    "trust_occupied": "TRI-023", "trust_family": "TRI-024", "trust_one": "TRI-025", "llc": "TRI-021",
    "mobile": "TRI-027", "mobile_excl": "TRI-028", "lead": "TRI-033", "pool_gate": "TRI-066",
    "pool_surround": "TRI-067", "pool_fence": "TRI-068", "pool_above": "TRI-069", "pool_slide": "TRI-074",
    "dog_breed": "TRI-081", "dog_bite": "TRI-082", "fpc_b13": "TRI-088", "fpc_c13": "TRI-089",
    "fpc_b410": "TRI-090", "fpc_c48": "TRI-091", "fpc_9": "TRI-092", "fpc_age": "TRI-035",
    "fpc_primary_only": "TRI-019", "fpc_no_rentals": "TRI-020", "poly": "TRI-052", "roof_flat": "TRI-040",
    "roof_metal": "TRI-041", "cov_min_refer": "TRI-114"}))

MAP.update({
    # ---------------- SURE: Coverage A and coastal
    "SUR-090": ("dwelling_amount", "dwelling_amount <= 4000000", "always", "",
                "the $7,000,000 TIV limit is not asked (TIV is not a form field)"),
    "SUR-091": ("dwelling_amount;fire_station_miles;hydrant_1000ft", "dwelling_amount <= 2000000", FPC_BC,
                OPEN_B, "FPC B or C risks; the $3,999,999 TIV limit is not asked"),
    "SUR-092": ("dwelling_amount", "dwelling_amount <= 2000000", "always", "", ""),
    "SUR-161": ("coastal_tier", "FACT(not an extreme hazard location)", TIER1, "distance to shoreline",
                "the form's tiers are not the guide's tiers"),
    "SUR-162": ("coastal_tier", "FACT(not on a barrier island or Bolivar / Matagorda peninsula)", TIER1,
                "barrier island / peninsula", ""),
    "SUR-163": ("coastal_tier", "FACT(not within the primary shoreline distances)", TIER123, "distance to shoreline",
                "as SAG-089"),
    "SUR-164": ("coastal_tier", "FACT(not within 0.04 miles of an inner shoreline)", TIER1,
                "distance to inner shoreline", ""),
    "SUR-165": ("coastal_tier", "FACT(not in the front or first row of dwellings)", TIER1, "first row", ""),
    # ---------------- SafePort: Coverage A and coastal
    "SFP-095": ("dwelling_amount", "dwelling_amount <= 5000000", "always", "",
                "the $8,000,000 TIV limit is not asked (TIV is not a form field)"),
    "SFP-097": ("dwelling_amount;fire_station_miles;hydrant_1000ft", "dwelling_amount <= 2000000", FPC_BC,
                OPEN_B, "FPC B or C risks; the $3,999,999 TIV limit is not asked"),
    "SFP-099": ("dwelling_amount", "dwelling_amount <= 2000000", "always", "", ""),
    "SFP-169": ("coastal_tier", "FACT(not an extreme hazard location)", TIER1, "distance to shoreline",
                "the form's tiers are not the guide's tiers"),
    "SFP-170": ("coastal_tier", "FACT(not on a barrier island)", TIER1, "barrier island", ""),
    "SFP-171": ("coastal_tier", "FACT(not on Bolivar, Matagorda or a similar peninsula)", TIER1, "peninsula", ""),
    "SFP-172": ("coastal_tier", "FACT(not within 3 miles of the primary shoreline in a tier 1 county)", TIER123,
                "distance to shoreline", "as SAG-089"),
    "SFP-173": ("coastal_tier", "FACT(not within 0.1 miles of the primary shoreline in a tier 2 county)", TIER1,
                "distance to shoreline", ""),
    "SFP-174": ("coastal_tier", "FACT(not within 0.04 miles of an inner shoreline)", TIER1,
                "distance to inner shoreline", ""),
    "SFP-175": ("coastal_tier", "FACT(not in the front or first row of dwellings)", TIER1, "first row", ""),
    # ---------------- Wilshire: Coverage A (Extreme Hazard is eligible with a deductible: COVERAGE_ONLY)
    "WIL-096": ("dwelling_amount", "dwelling_amount <= 2000000", "always", "", ""),
    # ---------------- Trium: Coverage A, barrier island
    "TRI-110": ("dwelling_amount", "dwelling_amount <= 2000000", "always", "", ""),
    "TRI-111": ("dwelling_amount", "dwelling_amount <= 1250000", "always", "", ""),
    "TRI-100": ("coastal_tier", "FACT(not on a barrier island without road access to the mainland)", TIER1,
                "barrier island road access", "Extreme Hazard is otherwise eligible with a deductible"),
    # ---------------- Markel
    "MKL-002": ("county", "always", "always", "", "the tool is Texas-only (State: TX)"),
    "MKL-009": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "MKL-007": same_as("MKL-009"),
    "MKL-016": ("ownership_type", "FACT(the occupant is the principal of the corporation / LLC)", LLC,
                "LLC principal occupies", "applies to a primary or seasonal home held by a corporation or LLC"),
    "MKL-022": ("construction_type", "construction_type != Manufactured/Mobile", "always", "", ""),
    "MKL-079": ("dwelling_amount", "dwelling_amount >= 100000", "always", "", ""),
    # ---------------- Vave
    # v2: VAV-001 is the program description (NOT_ELIGIBILITY); the whole home rented long-term
    # (Tenant Occupied) is VAV-007's.
    "VAV-007": ("occupancy_type", OWNER, "always", "",
                "primary, secondary, seasonal and short-term rental homes are accepted; Vacant is decided by "
                "VAV-010"),
    "VAV-010": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "VAV-014": ("ownership_type;occupancy_type", OWNER, TRUST, "", ""),
    "VAV-015": ("ownership_type", "always", LLC, "", "decided by VAV-016..VAV-020, its five criteria"),
    "VAV-016": ("ownership_type", "FACT(formed solely for tax or real estate holding)", LLC, "LLC purpose", ""),
    "VAV-017": ("ownership_type", "FACT(no more than 6 unrelated principals)", LLC, "LLC principals", ""),
    "VAV-018": ("ownership_type", "FACT(owns no more than 10 properties)", LLC, "LLC property count", ""),
    "VAV-019": ("ownership_type", "FACT(no business other than real estate)", LLC, "LLC business", ""),
    "VAV-020": ("ownership_type", "FACT(no fractional ownership or time share properties)", LLC,
                "LLC time shares", ""),
    "VAV-021": ("construction_type", "construction_type != Manufactured/Mobile", "always", "",
                "modular / motor homes are not form options"),
    "VAV-024": ("year_built", "year_built >= 1900", "always", "", ""),
    "VAV-025": ("year_built", "FACT(full gut rehab in 1930 or later)", "year_built between 1900 and 1929",
                "full gut rehab", ""),
    "VAV-026": ("year_built", "FACT(full gut rehab in 1930 or later)", "year_built between 1900 and 1929",
                "full gut rehab", "homes before 1900 are decided by VAV-024"),
    "VAV-047": ("plumbing_type", "plumbing_type not in {Galvanized, Polybutylene}", "always", "",
                "steel / iron are not form options (Unknown / Other stay unknown)"),
    "VAV-072": ("county", "always", "always", "", "the tool is Texas-only (State: TX)"),
    "VAV-078": ("dwelling_amount", "dwelling_amount >= 100000", "always", "", ""),
    "VAV-079": ("dwelling_amount", "dwelling_amount <= 2000000", "always", "", ""),
})

BATCH_NONE_NOTE = dict(NONE_NOTE, ANIMALS="other animals and bite claims are not asked",
                       POOL="pool rentals, ladders, decking and covers are not asked",
                       DWELLING_LIMITS="TIV, Coverage B and the HO5 form are not asked",
                       OCCUPANCY="rentals, mailing address and occupancy dates are not asked",
                       OWNERSHIP="the number of individual owners is not asked",
                       DWELLING_TYPE="unit count, foundation and original use are not asked",
                       HOME_AGE="rehab details are not asked", ROOF_ELIG="roof condition and layers are not asked",
                       LOCATION="location detail beyond county / tier is not asked, or the guide does not say")


def main():
    rows = list(csv.DictReader(l for l in open(RULES, encoding="utf-8-sig") if not l.startswith("#")))
    ev = [r for r in rows if r["Tool handling"] in ("EVALUATE", "EVALUATE_CURE_IS_INSPECTION")]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write("# source: rules_data/build_sage_batch_map.py over rules_data/carrier_rules_sage_batch_v2.csv "
                 "(Sage batch version 2, reviewed by Claude); built 2026-10-07 (round 28 step 3). "
                 "Grammar: rules_data/RULE_FIELD_MAP.md.\n")
        w = csv.writer(fh)
        w.writerow(["row_id", "field", "test", "gate", "outcome_if_fail", "open_fact", "map_note"])
        for r in ev:
            rid = r["Rule ID"]
            cure = r["Tool handling"] == "EVALUATE_CURE_IS_INSPECTION"
            outcome = "NOTE" if cure else (r["Effect"] or "UNKNOWN")
            if rid in MAP:
                field, test, gate, open_fact, note = MAP[rid]
            else:
                field, test, gate, open_fact = "NONE", "", "", ""
                note = BATCH_NONE_NOTE.get(r["Topic"], "the form has no field for this")
            w.writerow([rid, field, test, gate, outcome, open_fact, note])
    unknown = sorted(set(MAP) - {r["Rule ID"] for r in ev})
    print(f"wrote {OUT}: {len(ev)} lines, {len(MAP)} mapped; map ids not deciding rows: {unknown}")
    print(coverage_table(ev))


def kind(line):
    """How a map line decides its row (the coverage table's columns)."""
    field, test, _gate, _open, note = line
    if field == "NONE":
        return "NONE"
    if "||" in test:
        return "AMBIGUOUS"
    if test == "always" and note.startswith("decided by"):
        return "same rule as another row"
    if "FACT(" in test:
        return "gated-but-open"
    return "decided by a form field"


KINDS = ["decided by a form field", "gated-but-open", "AMBIGUOUS", "same rule as another row", "NONE"]


def coverage_table(ev):
    counts = {}
    for r in ev:
        k = kind(MAP.get(r["Rule ID"], ("NONE", "", "", "", "")))
        counts.setdefault(r["Carrier"], dict.fromkeys(KINDS, 0))[k] += 1
    out = ["| Carrier | " + " | ".join(KINDS) + " | total |", "|---" * (len(KINDS) + 2) + "|"]
    total = dict.fromkeys(KINDS, 0)
    for carrier, c in counts.items():
        out.append(f"| {carrier} | " + " | ".join(str(c[k]) for k in KINDS) + f" | {sum(c.values())} |")
        for k in KINDS:
            total[k] += c[k]
    out.append("| **all** | " + " | ".join(f"**{total[k]}**" for k in KINDS) + f" | **{sum(total.values())}** |")
    return "\n".join(out)


if __name__ == "__main__":
    main()
