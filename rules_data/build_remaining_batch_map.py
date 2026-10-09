"""Build rules_data/remaining_batch_field_map.csv -- one line per deciding row (Tool
handling EVALUATE / EVALUATE_CURE_IS_INSPECTION) of
rules_data/carrier_rules_remaining_v1.csv, the remaining-guides batch (round 29
step 8, 2026-10-08): Centauri DP3 (CDP), Centauri HO3 (CHO, OCR text), HOAIC
Texas Dwelling (HDP), Liberty / Safeco Landlord DP3 (LDP), NatGen Custom360
Landlord (NCD), NatGen Premier Dwelling Fire (NPD, closed), Progressive DP3
(PDP), Progressive HO6 (PH6), Sage Markel / Occidental / SURE / SafePort / Vave
DP3 (MDP / ODP / SDP / FDP / VDP), Steadily DP3 (STD), Foremost Dwelling Fire
(FOD).

Same grammar and conventions as build_ho3_batch_map.py (rules_data/RULE_FIELD_MAP.md).
Readings added here, listed in RULE_FIELD_MAP.md:
- Dwelling fire is a landlord's policy: Tenant Occupied is the normal case and
  passes every occupancy line unless the guide's own row says otherwise. The
  form's Seasonal / Secondary Home are the OWNER's homes (Liam's decision 2,
  2026-10-08), so a landlord-only guide fails Seasonal and Secondary Home
  (a seasonal rental is a tenant-occupied home).
- "Ineligible for liability coverage" lists (pools, dogs, stairs, trampolines)
  never decline the home: they are NONE (coverage only) here.
- A condition that applies to the program's base case and that the form never
  asks (a 12-month lease on every rental, the deed, the replacement-cost
  estimate) is NONE -- an "Also confirm" note, never a hold (decision 1,
  2026-10-08). A gated FACT is used only behind a specific exposure the form
  does show (a pool, dogs, a trust or LLC, a flat roof, PPC 9-10, an old home).
- The SURE (SDP-078..083) and SafePort (FDP-103..111) FPC tables: the merged
  cell covers FPC 4-10 "B" (station <= 5 miles, hydrant over 1,000 ft or none)
  and FPC 4-8 "C" (station > 5 miles). A tenant home in those bands fails "no
  rental exposures"; a blank distance or hydrant holds (decision 2026-10-07).
  Occidental's cell (ODP-112..115) says "primary occupancy dwellings only"
  without the rental line: ODP-115 reads primary vs secondary / seasonal.

usage: python rules_data/build_remaining_batch_map.py
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_rule_field_map import DOGS, FLAT, NONE_NOTE, POOL_OK, SEASONAL, breed_line  # noqa: E402
from build_rule_field_map import PEX_2011, PEX_ANY  # noqa: E402
from build_rule_field_map import (ASBESTOS, BUILT_UP, METAL, MEMBRANE, NOT_WOOD, PANEL, PROG_ROOF, PROG_ROOF_NOTE,  # noqa: E402
                                  ROLLED_ROOF, SEAM, MSHINGLE, TLOCK, WOOD, _roofs)
from build_sage_batch_map import (BATCH_NONE_NOTE, EAST_TEXAS, FPC_7ROWS, FPC_B13, FPC_B410, FPC_BC,  # noqa: E402
                                  FPC_C13, FPC_C48, OPEN_B, OPEN_C, ROW_FACT_3, kind)

RULES = os.path.join(HERE, "carrier_rules_remaining_v1.csv")
OUT = os.path.join(HERE, "remaining_batch_field_map.csv")

NOT_VACANT = "occupancy_type != Vacant"
NOT_TENANT = "occupancy_type != Tenant Occupied"
TENANT = "occupancy_type == Tenant Occupied"
TRUST = "ownership_type == Trust"
LLC = "ownership_type == LLC"
ENTITY = "ownership_type in {Trust, LLC}"
POOL = "swimming_pool != No Pool"
FENCED = "swimming_pool not in {In Ground - Unfenced, Above Ground - Unfenced}"
NO_ACCESSORIES = "pool_accessories == None"
MOBILE = "construction_type != Manufactured/Mobile"
GALV = "plumbing_type != Galvanized"
POLY = "plumbing_type != Polybutylene"
GALV_POLY = "plumbing_type not in {Galvanized, Polybutylene}"
TIER1 = "coastal_tier == Tier 1"
TWIA_TIER1 = ("{Aransas, Brazoria, Calhoun, Cameron, Chambers, Galveston, Jefferson, Kenedy, Kleberg, Matagorda, "
              "Nueces, Refugio, San Patricio, Willacy}")
FOREMOST_COASTAL = ("{Aransas, Bee, Brazoria, Brooks, Calhoun, Cameron, Chambers, Fort Bend, Galveston, Goliad, "
                    "Hardin, Harris, Hidalgo, Jackson, Jefferson, Jim Wells, Kenedy, Kleberg, Liberty, Matagorda, "
                    "Montgomery, Nueces, Orange, Refugio, San Patricio, Victoria, Wharton, Willacy}")
# A landlord-only guide: the owner's own homes (Owner Occupied, Secondary Home) fail; Seasonal may be a
# seasonal rental (AMBIGUOUS); Vacant is decided by the guide's own vacancy row.
LANDLORD_ONLY = ("occupancy_type", "occupancy_type in {Tenant Occupied, Vacant}", "always", "",
                 "the form's Seasonal and Secondary Home are the owner's own homes (decision 2, 2026-10-08); a "
                 "seasonal rental is a tenant-occupied home. Vacant is decided by the guide's own vacancy row")
PPC_1_8 = ("ppc", "ppc_num <= 8", "always", "", "")
NO_BITES = ("has_dogs", "FACT(no dog with a bite history)", DOGS, "bite history", "")
POOL_4FT = ("swimming_pool;pool_fence_4ft;pool_gate_locking", FENCED + " and " + POOL_OK, POOL,
            "fence 4 ft; locking gate", "an approved alternative enclosure also qualifies (not a form option)")
WOOD_ROOF = ("roof_type", NOT_WOOD, "always", "", "")
ROLLED = ("roof_type", "roof_type not in " + _roofs(ROLLED_ROOF), "always", "", "rolled roofing (round 35)")
CORRUGATED = ("roof_type", "roof_type not in " + _roofs(PANEL), "always", "", "corrugated metal (round 35)")


def same_as(rid, field="occupancy_type"):
    return (field, "always", "always", "", f"decided by {rid} (the same rule); never a second flaw")


def money(test):
    return ("dwelling_amount", test, "always", "", "")


def none(note):
    """NONE with a reason other than the topic's default note."""
    return ("NONE", "", "", "", note)


MAP = {
    # ================= Centauri DP3
    "CDP-021": CORRUGATED, "CDP-022": WOOD_ROOF,
    "CDP-023": ("roof_shape;roof_type", "roof_type not in " + _roofs(BUILT_UP, MEMBRANE, ROLLED_ROOF)
                + " and FACT(poured concrete flat roof)", FLAT, "poured concrete roof",
                "built-up, membrane and rolled are not poured concrete"),
    "CDP-027": ROLLED,
    "CDP-032": ("plumbing_type", POLY, "always", "", ""),
    "CDP-038": ("construction_type", MOBILE, "always", "", "modular / pre-fabricated are not form options"),
    "CDP-048": PPC_1_8,
    "CDP-051": ("coastal_tier", "FACT(more than 2,500 ft from tidal water, or a TWIA policy written excluding wind)",
                TIER1, "distance to tidal water", "the form's tiers are not distances"),
    "CDP-053": POOL_4FT,
    "CDP-057": breed_line("centauri_dp", "open", "'vicious dogs including ...'"),
    "CDP-058": NO_BITES,
    "CDP-066": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "CDP-068": none("lease length is not asked; every rental needs a 12-month lease (confirm)"),
    "CDP-069": ("ownership_type", "FACT(a family member living trust as an Additional Named Insured)", TRUST,
                "family living trust",
                "LLCs are decided by CDP-071 / CDP-072"),
    "CDP-070": same_as("CDP-069", "ownership_type"),
    "CDP-071": ("ownership_type", "ownership_type != LLC", "always", "",
                "every LLC needs underwriting approval before binding"),
    "CDP-072": ("ownership_type;occupancy_type", TENANT, LLC, "", ""),
    # round 35 step 2: $750,001-$2,000,000 is for single-family dwellings (House, Townhome: decision 3)
    "CDP-094": ("dwelling_amount;dwelling_type",
                "dwelling_amount <= 750000 or (dwelling_amount <= 2000000 and dwelling_type in {House, Townhome})",
                "always", "", "single family = House or Townhome (Liam, 2026-10-09)"),
    "CDP-096": money("dwelling_amount <= 1000000"),
    "CDP-014": same_as("CDP-096", "dwelling_amount"),
    # ================= Centauri HO3 (OCR text)
    "CHO-007": ("ownership_type", "ownership_type == Individual Owner || ownership_type != LLC", "always", "",
                "a trust-owned home may still have an individual named insured"),
    "CHO-009": money("dwelling_amount <= 1250000"),
    # round 35 step 4 (Liam, 2026-10-09, decision 2): "One or two -family, owner-occupied dwellings only" -- an
    # owner's seasonal or secondary home counts as owner-occupied (Centauri bars "risks that are not primary
    # residences" only from Scheduled Personal Property, p8): it passes with a confirm note
    "CHO-013": ("occupancy_type", "occupancy_type != Tenant Occupied and (occupancy_type not in {Seasonal, Secondary Home} "
                "or FACT(the owner lives there when the home is used))", "always", "the owner's own use",
                "Vacant is decided by CHO-049"),
    "CHO-017": ("swimming_pool;pool_accessories", NO_ACCESSORIES, POOL, "", ""),
    # "Flat roofs, rock or tar roofs, gravel roofs or roofs with asbestos shingles, wood, rolled roofs, sheet tin,
    # aluminum (including galvanized)" (round 35 step 3b)
    "CHO-024": ("roof_type;roof_shape", "roof_type not in " + _roofs(WOOD, BUILT_UP, ROLLED_ROOF, ASBESTOS, MEMBRANE)
                + " and roof_shape != Flat and (roof_type not in " + METAL
                + " or FACT(the metal is not sheet tin or aluminum))", "always", "metal kind",
                "membrane is a flat-roof covering"),
    "CHO-056": same_as("CHO-024", "roof_type;roof_shape"),
    "CHO-045": ("plumbing_type", "plumbing_type not in {Galvanized, Polybutylene, Cast iron}", "always", "",
                "'polybutylene, cast-iron or galvanized' (round 35)"),
    "CHO-049": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "CHO-051": ("construction_type", MOBILE, "always", "", ""),
    "CHO-059": PPC_1_8,
    "CHO-064": ("swimming_pool;pool_gate_locking", FENCED + " and pool_gate_locking == True and FACT(fence at least "
                                                            "5 ft, or a screened enclosure)",
                POOL, "5 ft fence or screened enclosure", "the form's fence box is 4 ft"),
    "CHO-067": NO_BITES,
    # ================= HOAIC Texas Dwelling (TDP3)
    "HDP-001": ("year_built", "home_age <= 100", "always", "", ""),
    "HDP-002": ("year_built", "home_age <= 50 or FACT(proof of updates)", "always", "proof of updates", ""),
    "HDP-003": ("ppc;dwelling_amount", "dwelling_amount <= 500000", "ppc_num <= 7", "", ""),
    "HDP-004": ("ppc;dwelling_amount", "dwelling_amount <= 300000", "ppc_num >= 8", "", ""),
    # ================= Liberty Mutual / Safeco Landlord DP3
    "LDP-001": LANDLORD_ONLY,
    "LDP-002": same_as("LDP-001"), "LDP-005": same_as("LDP-001"), "LDP-008": same_as("LDP-001"),
    "LDP-009": same_as("LDP-001"),
    "LDP-010": same_as("LDP-013"),
    "LDP-013": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "LDP-018": same_as("LDP-019", "ownership_type"),
    "LDP-019": ("ownership_type", "FACT(owns it for the benefit of an individual owner who is the named insured)",
                ENTITY, "who the trust / LLC benefits", ""),
    "LDP-024": ("construction_type", MOBILE, "always", "", ""),
    "LDP-035": WOOD_ROOF,
    "LDP-049": ("plumbing_type", "plumbing_type in {Copper, PVC, " + PEX_ANY[1:], "always", "", ""),
    "LDP-050": NO_BITES,
    "LDP-069": money("dwelling_amount <= 1500000"),
    # ================= NatGen Custom360 Landlord
    "NCD-001": same_as("NCD-006 / NCD-004", "ownership_type"),
    "NCD-002": same_as("NCD-006 / NCD-004", "ownership_type"),
    "NCD-004": ("ownership_type", "FACT(no commercial activities; owned only by the insured and relatives)", LLC,
                "the LLC's activities and owners", ""),
    "NCD-003": same_as("NCD-004", "ownership_type"),
    "NCD-006": ("ownership_type", "FACT(guarantor, trustee and named insured are the same person)", TRUST,
                "who the trust's guarantor and trustee are", "a trust may only be an additional insured"),
    "NCD-027": ("ppc;dwelling_amount", "dwelling_amount <= 1500000", "ppc_num <= 8", "", ""),
    "NCD-030": ("ppc;dwelling_amount", "dwelling_amount <= 1000000 or dwelling_amount > 1500000", "ppc_num <= 8", "",
                "over $1,500,000 is NCD-027"),
    "NCD-028": ("ppc;dwelling_amount", "dwelling_amount <= 750000", "ppc_num == 9", "",
                "1X-8X split classes are not form options"),
    "NCD-029": ("ppc;dwelling_amount", "dwelling_amount <= 500000", "ppc_num == 10", "", ""),
    "NCD-042": ("ppc;dwelling_amount", "FACT(central station fire alarm)", "ppc_num <= 8 and dwelling_amount > 1000000",
                "alarm", ""),
    "NCD-043": ("ppc;dwelling_amount", "FACT(central station fire alarm)", "ppc_num == 9 and dwelling_amount > 750000",
                "alarm", ""),
    "NCD-044": ("ppc;dwelling_amount", "FACT(central station fire alarm)", "ppc_num == 10 and dwelling_amount > 500000",
                "alarm", ""),
    "NCD-047": LANDLORD_ONLY,
    "NCD-051": ("occupancy_type", "FACT(occupied within 60 days of the effective date)", "occupancy_type == Vacant",
                "when it will be occupied", ""),
    "NCD-052": same_as("NCD-051"),
    "NCD-057": ("construction_type", MOBILE, "always", "", ""),
    "NCD-058": ("dwelling_type", "FACT(8 or fewer family units in the fire division)", "dwelling_type == Townhome",
                "units per fire division", ""),
    "NCD-059": ("dwelling_type;construction_type;year_built", "FACT(4 or fewer units)",
                "dwelling_type == Townhome and construction_type == Frame and year_built < 1980", "number of units", ""),
    "NCD-060": ("dwelling_type", "FACT(firewall goes through the roof)", "dwelling_type == Townhome", "firewall", ""),
    "NCD-066": ("dwelling_type", "dwelling_type != Condo", "always", "", ""),
    # "Tar paper, T-lock, Thermoplastic Polyolefin (TPO), rolled, wood, Ludowici tile, stapled, and flat roofs"
    "NCD-097": ("roof_type;roof_shape", "roof_type not in " + _roofs(TLOCK, ROLLED_ROOF, WOOD, BUILT_UP)
                + " and roof_shape != Flat and (roof_type not in " + _roofs(MEMBRANE)
                + " or FACT(the membrane is not TPO)) and (roof_type not in {Tile} or FACT(not Ludowici tile))",
                "always", "membrane kind; tile maker", "round 35"),
    "NCD-100": same_as("NCD-097", "roof_type"),
    "NCD-104": ("swimming_pool;pool_gate_locking", FENCED + " and pool_gate_locking == True", POOL,
                "self-locking gate", ""),
    "NCD-105": ("pool_accessories", "FACT(diving board under 18 inches above the water)",
                "pool_accessories in {Diving board only, Both slide and diving board}", "diving board height", ""),
    "NCD-106": ("swimming_pool", "FACT(pull-up ladder)",
                "swimming_pool in {Above Ground - Fenced, Above Ground - Unfenced}", "ladder", ""),
    "NCD-111": ("has_dogs", "FACT(no vicious or dangerous dog)", DOGS, "vicious or dangerous dog",
                "NatGen names no breed list (round 35): a confirm note"),
    "NCD-112": NO_BITES,
    "NCD-113": same_as("NCD-112", "has_dogs"), "NCD-114": same_as("NCD-112", "has_dogs"),
    "NCD-115": same_as("NCD-112", "has_dogs"),
    "NCD-116": ("ppc;fire_station_miles", "fire_station_miles <= 10", "ppc_num >= 9", "station distance", ""),
    # ================= Progressive DP3
    "PDP-006": money("dwelling_amount <= 500000 or (dwelling_amount <= 750000 and home_age == 0)"),
    "PDP-008": same_as("PDP-006", "dwelling_amount"),
    "PDP-007": money("dwelling_amount <= 5000000"),
    "PDP-013": ("county", "county not in {Hidalgo, Webb}", "always", "", ""),
    "PDP-014": ("coastal_tier", "FACT(more than 1,000 ft from the Gulf of Mexico)", TIER1, "distance to the Gulf",
                "the form's tiers are not distances"),
    "PDP-030": ("occupancy_type", NOT_VACANT, "always", "", "under construction / renovation is not asked"),
    "PDP-048": ("ownership_type", "ownership_type != Trust", "always", "", "trust or IRA: prior approval"),
    "PDP-120": ("ownership_type", "ownership_type != LLC", "always", "", ""),
    "PDP-049": same_as("PDP-048 / PDP-120", "ownership_type"),
    "PDP-063": ("dwelling_type", "FACT(4 or fewer family units in the fire division)", "dwelling_type == Townhome",
                "units per fire division", ""),
    "PDP-064": ("construction_type", MOBILE, "always", "", ""),
    "PDP-088": ("plumbing_type", "plumbing_type not in {Galvanized, Polybutylene, " + PEX_ANY[1:], "always", "",
                "any PEX (round 35)"),
    "PDP-096": ("roof_age", "FACT(5+ years of useful life left)", "roof_age >= 15", "remaining roof life",
                "as ARA-059"),
    "PDP-098": ("roof_type", PROG_ROOF, "always", "membrane kind", PROG_ROOF_NOTE),
    "PDP-099": ("roof_shape;roof_type", "roof_type not in " + _roofs(BUILT_UP, MEMBRANE, ROLLED_ROOF)
                + " and FACT(poured concrete flat roof)", FLAT,
                "poured concrete roof", ""),
    "PDP-103": POOL_4FT,
    "PDP-104": ("swimming_pool;pool_accessories", NO_ACCESSORIES, POOL, "", ""),
    "PDP-109": breed_line("progressive", "open", "'includes, but is not limited to'"),
    "PDP-116": ("ppc", "FACT(visible to neighbors)", "ppc_num >= 9", "visibility", ""),
    # ================= Progressive HO6 (condo unit-owners)
    "PH6-001": ("county", "county not in {Hidalgo, Webb}", "always", "", ""),
    "PH6-012": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "PH6-017": ("occupancy_type", "FACT(occupied at least 3 months a year)", SEASONAL, "months occupied", ""),
    "PH6-027": ("ownership_type", "ownership_type != Trust", "always", "", "trust or IRA: prior approval"),
    "PH6-029": ("ownership_type", "ownership_type != LLC", "always", "", ""),
    "PH6-028": same_as("PH6-027 / PH6-029", "ownership_type"),
    "PH6-044": ("coastal_tier", "FACT(more than 1,000 ft from the Gulf of Mexico)", TIER1, "distance to the Gulf",
                "the form's tiers are not distances"),
    "PH6-050": ("ppc", "FACT(visible to neighbors)", "ppc_num >= 9", "visibility", ""),
    "PH6-069": ("year_built", "home_age <= 100", "always", "", ""),
    # round 35 step 3c (Claude's audit): the install year decides, not year built
    "PH6-074": ("plumbing_type;year_built", PEX_2011, "always", "", "PEX installed before 2011: the form's install year"),
    "PH6-077": ("roof_type", PROG_ROOF, "always", "membrane kind", PROG_ROOF_NOTE),
    "PH6-086": breed_line("progressive", "open", "'includes, but is not limited to'"),
    "PH6-092": money("dwelling_amount <= 500000"),
    "PH6-094": money("dwelling_amount >= 20000 and dwelling_amount <= 1000000"),
    # ================= Sage Markel DP3
    "MDP-006": ("occupancy_type", NOT_VACANT, "always", "", "vacant is eligible on referral"),
    "MDP-007": none("MDP-006 refers every vacant home; demolition and heat are not asked"),
    "MDP-015": ("ownership_type;occupancy_type", "FACT(the occupant is the entity's principal)",
                "ownership_type == LLC and occupancy_type in {Owner Occupied, Seasonal, Secondary Home}",
                "who occupies the home", ""),
    "MDP-028": ("construction_type", MOBILE, "always", "", ""),
    "MDP-081": money("dwelling_amount >= 100000"),
    # ================= Sage Occidental DP3
    "ODP-003": ("county", "county != Nueces", "always", "", "this guide's Nueces exclusion; ODP-004 decides the rest"),
    "ODP-004": ("county", "county in {" + EAST_TEXAS + "}", "south_of_31 == False", "",
                "a county not entirely south of 31 N (as the Sage batch v2)"),
    "ODP-031": ("occupancy_type", NOT_VACANT, "always", "", "eligible on underwriter approval with a signed lease"),
    "ODP-032": same_as("ODP-031"),
    "ODP-041": ("construction_type", MOBILE, "always", "", ""),
    "ODP-075": ("roof_shape;roof_type", "FACT(no prior roof wind/water loss, or fully renovated)", FLAT,
                "prior roof loss; renovation", ""),
    "ODP-077": ("roof_type", "FACT(steel, 29 gauge or heavier)", "roof_type in " + METAL, "metal roof gauge", ""),
    "ODP-078": same_as("ODP-077", "roof_type"),
    "ODP-082": ("plumbing_type", POLY, "always", "", ""),
    "ODP-110": ("ppc;fire_station_miles;hydrant_1000ft", ROW_FACT_3, FPC_B13, OPEN_B + "; visibility, alarm, access",
                ""),
    "ODP-111": ("ppc;fire_station_miles", ROW_FACT_3, FPC_C13, OPEN_C + "; visibility, alarm, access", ""),
    # round 35 step 2: with no hydrant at FPC 4-8 the home is in this band or ODP-113's (same conditions)
    # whatever the distance, so a blank distance does not leave the gate unknown
    "ODP-112": ("ppc;fire_station_miles;hydrant_1000ft", ROW_FACT_3,
                "ppc_num between 4 and 10 and hydrant_1000ft == No and (fire_station_miles <= 5 or ppc_num <= 8)",
                OPEN_B + "; visibility, alarm, access", ""),
    "ODP-113": ("ppc;fire_station_miles;hydrant_1000ft", ROW_FACT_3,
                "ppc_num between 4 and 8 and (fire_station_miles > 5 or hydrant_1000ft == No)",
                OPEN_C + "; visibility, alarm, access", "round 35: as ODP-112"),
    "ODP-114": ("year_built;ppc;fire_station_miles;hydrant_1000ft", "home_age < 25", FPC_7ROWS, OPEN_B, ""),
    "ODP-115": ("occupancy_type;ppc;fire_station_miles;hydrant_1000ft",
                "occupancy_type in {Owner Occupied, Tenant Occupied} and FACT(no prior fire loss)", FPC_7ROWS,
                OPEN_B + "; fire losses", "primary vs secondary / seasonal, not owner vs tenant: this cell has no "
                                          "rental line"),
    "ODP-116": ("ppc;fire_station_miles", "fire_station_miles <= 5", "ppc_num >= 9", "station distance", ""),
    "ODP-117": money("dwelling_amount <= 2000000"),
    "ODP-118": money("dwelling_amount <= 1250000"),
    "ODP-119": money("dwelling_amount >= 85000"),
    # ================= Sage SURE DP3
    "SDP-002": ("county", "county != Nueces", "always", "", "this guide's Nueces exclusion; SDP-003 decides the rest"),
    "SDP-003": ("county", "county in {" + EAST_TEXAS + "}", "south_of_31 == False", "",
                "a county not entirely south of 31 N (as the Sage batch v2)"),
    "SDP-008": ("ownership_type", "FACT(family held trust)", TRUST, "family held trust", ""),
    "SDP-009": ("ownership_type", "FACT(only one trust on the property)", TRUST, "number of trusts", ""),
    "SDP-012": same_as("SDP-015"), "SDP-013": same_as("SDP-015"),
    "SDP-015": ("occupancy_type", NOT_VACANT, "always", "", "eligible on underwriter approval with a signed lease"),
    "SDP-016": same_as("SDP-015"),
    "SDP-028": ("construction_type", MOBILE, "always", "", ""),
    "SDP-069": money("dwelling_amount <= 4000000"),
    "SDP-070": ("dwelling_amount;occupancy_type;fire_station_miles;hydrant_1000ft", "dwelling_amount <= 2000000",
                "occupancy_type == Vacant or hydrant_1000ft == No or fire_station_miles > 5", OPEN_B,
                "vacant, or FPC B or C (no hydrant is B or C at any distance, round 35); TIV is not asked"),
    "SDP-071": money("dwelling_amount <= 2000000"),
    "SDP-072": money("dwelling_amount >= 85000"),
    "SDP-078": ("ppc;fire_station_miles;hydrant_1000ft", ROW_FACT_3,
                "ppc_num between 1 and 3 and (hydrant_1000ft == No or fire_station_miles > 5)",   # round 35
                OPEN_B + "; visibility, alarm, access", ""),
    "SDP-079": ("ppc;fire_station_miles;hydrant_1000ft", ROW_FACT_3, FPC_7ROWS, OPEN_B + "; visibility, alarm, access",
                "the merged cell: FPC 4-10 B and FPC 4-8 C"),
    "SDP-080": ("year_built;ppc;fire_station_miles;hydrant_1000ft", "home_age < 25", FPC_7ROWS, OPEN_B, ""),
    "SDP-081": ("occupancy_type;ppc;fire_station_miles;hydrant_1000ft", "occupancy_type == Owner Occupied", FPC_7ROWS,
                OPEN_B, "no rental exposures: a tenant home in these bands is ineligible"),
    "SDP-082": ("ppc;fire_station_miles;hydrant_1000ft", "FACT(no prior fire loss)", FPC_7ROWS,
                OPEN_B + "; fire losses", ""),
    "SDP-083": ("ppc;fire_station_miles", "fire_station_miles <= 5", "ppc_num >= 9", "station distance", ""),
    "SDP-100": ("plumbing_type", POLY, "always", "", ""),
    "SDP-112": ("roof_shape;roof_type", "FACT(no prior roof wind/water loss, or fully renovated)", FLAT,
                "prior roof loss; renovation", ""),
    "SDP-114": ("roof_type", "FACT(steel, 29 gauge or heavier)", "roof_type in " + METAL, "metal roof gauge", ""),
    "SDP-115": same_as("SDP-114", "roof_type"),
    # ================= Sage SafePort DP3
    "FDP-001": ("county", "county != Nueces", "always", "", "this guide's Nueces exclusion; FDP-002 decides the rest"),
    "FDP-002": ("county", "county in {" + EAST_TEXAS + "}", "south_of_31 == False", "",
                "a county not entirely south of 31 N (as the Sage batch v2)"),
    "FDP-025": ("ownership_type", "FACT(family held trust)", TRUST, "family held trust", ""),
    "FDP-026": ("ownership_type", "FACT(only one trust on the property)", TRUST, "number of trusts", ""),
    "FDP-032": ("occupancy_type", NOT_VACANT, "always", "", "eligible on underwriter approval with a signed lease"),
    "FDP-033": same_as("FDP-032"), "FDP-034": same_as("FDP-032"),
    "FDP-050": ("construction_type", MOBILE, "always", "", ""),
    "FDP-093": money("dwelling_amount <= 5000000"),
    "FDP-094": ("dwelling_amount;occupancy_type;fire_station_miles;hydrant_1000ft", "dwelling_amount <= 2000000",
                "occupancy_type == Vacant or hydrant_1000ft == No or fire_station_miles > 5", OPEN_B,
                "vacant, or FPC B or C (no hydrant is B or C at any distance, round 35); TIV is not asked"),
    "FDP-095": money("dwelling_amount <= 2000000"),
    "FDP-097": money("dwelling_amount >= 85000"),
    "FDP-104": ("ppc;fire_station_miles", "fire_station_miles <= 5", "ppc_num >= 9", "station distance", ""),
    "FDP-105": ("ppc;fire_station_miles;hydrant_1000ft", ROW_FACT_3,
                "(" + FPC_B13 + ") or (" + FPC_C13 + ") or (" + FPC_7ROWS + ")",
                OPEN_B + "; visibility, alarm, access", "FPC 1-3 B or C, FPC 4-10 B, FPC 4-8 C"),
    "FDP-106": same_as("FDP-105", "ppc"), "FDP-107": same_as("FDP-105", "ppc"),
    "FDP-108": ("year_built;ppc;fire_station_miles;hydrant_1000ft", "home_age < 25", FPC_7ROWS, OPEN_B, ""),
    "FDP-109": ("occupancy_type;ppc;fire_station_miles;hydrant_1000ft",
                "occupancy_type in {Owner Occupied, Tenant Occupied}", FPC_7ROWS, OPEN_B,
                "primary occupancy: secondary, seasonal and vacant homes fail; rentals are FDP-110"),
    "FDP-110": ("occupancy_type;ppc;fire_station_miles;hydrant_1000ft", NOT_TENANT, FPC_7ROWS, OPEN_B,
                "no rental exposures: a tenant home in these bands is ineligible"),
    "FDP-111": ("ppc;fire_station_miles;hydrant_1000ft", "FACT(no prior fire loss)", FPC_7ROWS,
                OPEN_B + "; fire losses", ""),
    "FDP-125": ("plumbing_type", POLY, "always", "", ""),
    "FDP-137": ("roof_shape;roof_type", "FACT(no prior roof wind/water loss, or fully renovated)", FLAT,
                "prior roof loss; renovation", ""),
    "FDP-139": ("roof_type", "FACT(steel, 29 gauge or heavier)", "roof_type in " + METAL, "metal roof gauge", ""),
    # ================= Sage Vave DP3
    "VDP-005": money("dwelling_amount >= 100000"),
    "VDP-006": money("dwelling_amount <= 2000000"),
    "VDP-026": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "VDP-031": ("year_built", "year_built >= 1900", "always", "", ""),
    "VDP-042": ("year_built", "year_built >= 1930 or FACT(full gut rehab in 1930 or later)", "year_built >= 1900",
                "gut rehab", "pre-1900 is VDP-031"),
    "VDP-057": ("construction_type", MOBILE, "always", "", ""),
    "VDP-062": ("ownership_type;occupancy_type", "occupancy_type in {Owner Occupied, Seasonal, Secondary Home} and "
                                                 "FACT(the trustee, grantor or beneficiary lives there)", TRUST,
                "who lives there", "a tenant-occupied or vacant trust home fails"),
    "VDP-063": ("ownership_type", "FACT(set up only for tax or real estate holding; 6 or fewer unrelated principals; "
                                  "10 or fewer properties; no other business; no timeshares)", LLC,
                "the entity's purpose, principals and holdings", ""),
    "VDP-064": same_as("VDP-063", "ownership_type"), "VDP-065": same_as("VDP-063", "ownership_type"),
    "VDP-066": same_as("VDP-063", "ownership_type"), "VDP-067": same_as("VDP-063", "ownership_type"),
    "VDP-069": ("plumbing_type", "plumbing_type not in {Galvanized, Polybutylene, Cast iron}", "always", "",
                "'galvanized, steel, iron or polybutylene': iron includes cast iron (round 35); steel is not a form option"),
    # ================= Steadily DP3
    "STD-024": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "STD-041": ("construction_type", MOBILE, "always", "", ""),
    "STD-042": same_as("STD-041", "construction_type"),
    "STD-045": ("year_built", "home_age <= 100", "always", "", ""),
    "STD-052": same_as("STD-067", "roof_shape;roof_type"),
    "STD-064": ("roof_type", "roof_type not in " + METAL + " or FACT(the metal is not aluminum)", "always",
                "metal kind", "'Aluminum' (round 35)"),
    "STD-065": ("roof_type", "roof_type not in " + _roofs(PANEL) + " or FACT(the panels are not tin)", "always",
                "tin", "'Tin' (round 35)"),
    "STD-067": ("roof_shape;roof_type", "FACT(proper drainage, no pooling)", FLAT, "flat roof drainage", ""),
    "STD-069": WOOD_ROOF,
    "STD-073": ("plumbing_type", GALV, "always", "",
                "'older homes' is not defined; a home with galvanized pipes is an older home (galvanized "
                "supply lines went out of use in the 1960s)"),
    "STD-092": ("solar_panels", "FACT(panels cover 50% of the roof or less)", "solar_panels == Yes", "share of roof",
                ""),
    "STD-095": PPC_1_8,
    "STD-102": money("dwelling_amount <= 1500000"),
    "STD-104": ("dwelling_type;dwelling_amount", "dwelling_amount < 350000", "dwelling_type == Condo", "", ""),
    # ================= Foremost Dwelling Fire (TDP-3): the registry applies FOD only to Tenant / Vacant checks
    # FOD-004/005/006/009/012: INFO_ONLY since round 30 step 3 (decision 3) -- not deciding rows; a Vacant
    # Foremost DP check gets rules_evaluator.PROGRAM_NOTES' "quote TDP-1" note instead.
    "FOD-018": ("ownership_type", "FACT(no business conducted from the premises)", LLC, "business on premises", ""),
    # "Manufactured homes ... unless vacant/unoccupied." (p.16): a vacant one is written on TDP-1 (round 30 step 3)
    "FOD-020": ("construction_type;occupancy_type", MOBILE + " or occupancy_type == Vacant", "always", "",
                "vacant manufactured homes are acceptable on TDP-1"),
    "FOD-031": money("dwelling_amount >= 100000"),
    "FOD-033": money("dwelling_amount <= 1000000"),
    "FOD-055": ("county", "county not in " + FOREMOST_COASTAL, "always", "", ""),
    "FOD-053": same_as("FOD-055", "county"),
}

# Rows the registry's scope keeps from ever being evaluated (an owner's home never reaches FOD),
# and the closed NatGen Premier Dwelling Fire program (CLOSED_PROGRAMS decides it, as for its HO3).
SCOPE_NONE = {"FOD-054": "owner-occupied: FOD rows apply only to Tenant / Vacant checks"}
CLOSED_NOTE = "closed to new business 11/30/2023: CLOSED_PROGRAMS decides NatGen Premier DP3 (as its HO3)"
LIABILITY_ONLY = "liability coverage only (write without liability): never a decline of the home"
REMAINING_NONE_NOTE = dict(BATCH_NONE_NOTE, SOLAR="solar shingles / roofs are not the form's (mounted) Solar panels",
                           PROTECTION_CLASS="response time, visibility and water source are not asked",
                           LIABILITY_HAZARDS="liability hazards are not asked")


def none_note(r):
    rid = r["Rule ID"]
    if rid.startswith("NPD-"):
        return CLOSED_NOTE
    if rid in SCOPE_NONE:
        return SCOPE_NONE[rid]
    if "liability coverage" in (r["Plain rule"] + " " + r["Applies when"]).lower():
        return LIABILITY_ONLY
    return REMAINING_NONE_NOTE.get(r["Topic"], NONE_NOTE.get(r["Topic"], "the form has no field for this"))


def coverage_table(ev):
    kinds = ["decided by a form field", "gated-but-open", "AMBIGUOUS", "same rule as another row", "NONE"]
    counts = {}
    for r in ev:
        counts.setdefault(r["Carrier"], dict.fromkeys(kinds, 0))[kind(MAP.get(r["Rule ID"], ("NONE", "", "", "", "")))] += 1
    out = ["| Carrier | " + " | ".join(kinds) + " | total |", "|---" * (len(kinds) + 2) + "|"]
    total = dict.fromkeys(kinds, 0)
    for carrier, c in counts.items():
        out.append(f"| {carrier} | " + " | ".join(str(c[k]) for k in kinds) + f" | {sum(c.values())} |")
        for k in kinds:
            total[k] += c[k]
    out.append("| **all** | " + " | ".join(f"**{total[k]}**" for k in kinds) + f" | **{sum(total.values())}** |")
    return "\n".join(out)


def main():
    rows = list(csv.DictReader(l for l in open(RULES, encoding="utf-8-sig") if not l.startswith("#")))
    ev = [r for r in rows if r["Tool handling"] in ("EVALUATE", "EVALUATE_CURE_IS_INSPECTION")]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write("# source: rules_data/build_remaining_batch_map.py over rules_data/carrier_rules_remaining_v1.csv "
                 "(remaining batch version 1, reviewed by Claude); built 2026-10-08 (round 29 step 8). "
                 "Grammar: rules_data/RULE_FIELD_MAP.md.\n")
        w = csv.writer(fh)
        w.writerow(["row_id", "field", "test", "gate", "outcome_if_fail", "open_fact", "map_note"])
        for r in ev:
            rid = r["Rule ID"]
            cure = r["Tool handling"] == "EVALUATE_CURE_IS_INSPECTION"
            outcome = "NOTE" if cure else (r["Effect"] or "UNKNOWN")
            line = MAP.get(rid)
            if line and line[0] != "NONE":
                field, test, gate, open_fact, note = line
            else:
                field, test, gate, open_fact = "NONE", "", "", ""
                note = line[4] if line else none_note(r)
            w.writerow([rid, field, test, gate, outcome, open_fact, note])
    unknown = sorted(set(MAP) - {r["Rule ID"] for r in ev})
    print(f"wrote {OUT}: {len(ev)} lines, {sum(1 for v in MAP.values() if v[0] != 'NONE')} mapped; "
          f"map ids not deciding rows: {unknown}")
    print(coverage_table(ev))


if __name__ == "__main__":
    main()
