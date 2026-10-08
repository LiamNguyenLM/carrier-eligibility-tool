"""Build rules_data/ho3_batch_field_map.csv -- one line per deciding row (Tool
handling EVALUATE / EVALUATE_CURE_IS_INSPECTION) of
rules_data/carrier_rules_ho3_batch_v1.csv, the HO3 batch (round 29 step 7,
2026-10-08): ARI HOA+ (ARA), ARI HOB (ARB), Foremost Choice Homeowners (FOR),
HOAIC HO3 (HOA), Liberty Mutual HO3 (LIB), Orion180 (ORI), Swyfft Benchmark /
Lloyd's / Topa Surplus (SBS / SLL / STO), TWICO (TWI), Travelers (TRV).

Same grammar and conventions as build_sage_batch_map.py (rules_data/RULE_FIELD_MAP.md):
every non-NONE line is written by hand below; a row with no line is NONE (the
form has no field that decides it); AMBIGUOUS ("||") rather than a guess; one
failing row per fact ("same rule as" lines).

Readings used here, listed in RULE_FIELD_MAP.md:
- ISO protection classes 1-9 are within 5 road miles of a fire station (class
  10 is beyond), so a known PPC settles the "within 5 / 7 miles" rows; only an
  unknown PPC falls back to the distance field.
- Roof material lists name things the form lumps together: Metal may or may not
  be the "expensive" / corrugated / light metal a guide names, Flat/Built-Up may
  or may not be tar and gravel or rolled roofing -- AMBIGUOUS.
- The FOR rows are Foremost's HOMEOWNERS program only; rules_evaluator applies
  them only to an owner's home (the batch registry's scope), never to a Foremost
  dwelling-fire check.

usage: python rules_data/build_ho3_batch_map.py
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_rule_field_map import BREED, DOGS, FLAT, NONE_NOTE, POOL_OK, SEASONAL  # noqa: E402
from build_sage_batch_map import BATCH_NONE_NOTE, coverage_table as _sage_coverage, kind  # noqa: E402,F401

RULES = os.path.join(HERE, "carrier_rules_ho3_batch_v1.csv")
OUT = os.path.join(HERE, "ho3_batch_field_map.csv")

NOT_VACANT = "occupancy_type != Vacant"
NOT_TENANT = "occupancy_type != Tenant Occupied"
TRUST = "ownership_type == Trust"
LLC = "ownership_type == LLC"
POOL = "swimming_pool != No Pool"
IN_GROUND = "swimming_pool in {In Ground - Fenced, In Ground - Unfenced}"
FENCED = "swimming_pool not in {In Ground - Unfenced, Above Ground - Unfenced}"
NO_ACCESSORIES = "pool_accessories == None"
MOBILE = "construction_type != Manufactured/Mobile"
GALV = "plumbing_type != Galvanized"
GALV_POLY = "plumbing_type not in {Galvanized, Polybutylene}"
TIER1 = "coastal_tier == Tier 1"
TWIA_TIER1 = ("{Aransas, Brazoria, Calhoun, Cameron, Chambers, Galveston, Jefferson, Kenedy, Kleberg, Matagorda, "
              "Nueces, Refugio, San Patricio, Willacy}")
FOREMOST_COASTAL = ("{Aransas, Bee, Brazoria, Brooks, Calhoun, Cameron, Chambers, Fort Bend, Galveston, Goliad, "
                    "Hardin, Harris, Hidalgo, Jackson, Jefferson, Jim Wells, Kenedy, Kleberg, Liberty, Matagorda, "
                    "Montgomery, Nueces, Orange, Refugio, San Patricio, Victoria, Wharton, Willacy}")
# "within 5 road miles of a fire station": ISO classes 1-9 are; class 10 is decided by its own row.
# station_miles_iso (rules_evaluator.facts): the stated distance, else 5 for ISO classes 1-9, else unknown.
WITHIN_5 = ("ppc;fire_station_miles", "station_miles_iso <= 5", "always",
            "station distance if not given", "a stated distance decides; else ISO classes 1-9 are within 5 road "
                                             "miles (PPC 10 with a stated distance over 5 also fails the PPC row)")
PPC_1_9 = ("ppc", "ppc_num <= 9", "always", "", "class 10 is beyond 5 road miles of a fire station")
ROOF_LIFE = ("roof_age", "FACT(5+ years of useful life left)", "roof_age >= 15", "remaining roof life",
             "as ALL-034: no covering on the form ends its life before 20 years")
SEASONAL_REFER = ("occupancy_type", "occupancy_type == Owner Occupied", SEASONAL, "",
                  "a seasonal or secondary home is always referred (ineligible unless ARI insures the primary)")
TOWNHOME = ("dwelling_type", "FACT(meets the Single Building definition)", "dwelling_type == Townhome",
            "Single Building definition", "duplexes are not a form option")
ARI_FLAT = ("roof_shape;roof_type;county", "county == El Paso", FLAT, "", "'in or around El Paso': around is not decided")
ARI_TILE = ("roof_type", "roof_type != Tile or FACT(High Value Home)", "always", "High Value Home", "")
ARI_UNPROTECTED = ("ppc", "FACT(visible from another dwelling or on an all-weather road)", "ppc_num == 10",
                   "visibility / all-weather road", "unprotected = class 10")
ARI_POOL = ("swimming_pool;pool_gate_locking", FENCED + " and pool_gate_locking == True and FACT(fence at least 6 ft)",
            POOL, "6 ft fence; locked or self-locking gate", "the form's fence box is 4 ft")
# Round 30 step 2 (decision 2): whether any water line is exposed is not asked. Copper / PVC pass; any
# other material is a "Confirm: no exposed lines" note, never a hold (round 29: PEX homes were held).
ARI_EXPOSED = ("plumbing_type", "plumbing_type in {Copper, PVC} or FACT(no exposed water lines of another material)",
               "always", "no exposed water lines other than copper / PVC",
               "exposed water lines; PEX is not named; galvanized is decided by its own row")
POOL_4FT = ("swimming_pool;pool_fence_4ft;pool_gate_locking", FENCED + " and " + POOL_OK, POOL,
            "fence 4 ft; self-latching gate", "a pool cage also qualifies (not a form option)")
UNFENCED_IN_GROUND = ("swimming_pool", "swimming_pool != In Ground - Unfenced", IN_GROUND, "", "")
RENOVATED_100 = ("year_built", "home_age <= 100 or FACT(completely renovated)", "always", "renovation",
                 "a completely renovated home may use the renovation year")


def same_as(rid, field="occupancy_type"):
    return (field, "always", "always", "", f"decided by {rid} (the same rule); never a second flaw")


def money(test):
    return ("dwelling_amount", test, "always", "", "")


MAP = {
    # ================= ARI HOA / HOA Plus
    "ARA-007": ("roof_type", "roof_type != Wood Shake || roof_type not in {Wood Shake, Metal, Flat/Built-Up}", "always",
                "", "wood is decided; Metal may not be expensive or corrugated metal, Flat/Built-Up may not be "
                    "tar and gravel"),
    "ARA-008": ARI_FLAT, "ARA-009": ARI_TILE,
    "ARA-010": ("roof_type", "roof_type != Slate", "always", "", ""),
    "ARA-011": TOWNHOME, "ARA-013": ARI_UNPROTECTED, "ARA-014": WITHIN_5,
    "ARA-016": ("construction_type", MOBILE, "always", "", ""),
    "ARA-024": ("coastal_tier", "FACT(more than 1,000 ft from the Gulf or a coastal bay)", TIER1,
                "distance to the Gulf / bay", "the form's tiers are not distances"),
    "ARA-025": ARI_POOL,
    "ARA-026": ("swimming_pool;pool_accessories", NO_ACCESSORIES, POOL, "", ""),
    "ARA-028": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "ARA-029": ("occupancy_type;primary_home_carrier", "primary_home_carrier == ARI", SEASONAL,
                "ARI insures the primary home", "round 30 step 1: the form's 'Primary home insured with'"),
    "ARA-030": SEASONAL_REFER,
    "ARA-033": ("has_dogs;aggressive_breed", BREED, DOGS, "", "the form's breed list is not ARI's (German Shepherd, "
                                                            "Great Dane...)"),
    "ARA-034": ("has_dogs", "FACT(no bite history)", DOGS, "bite history", ""),
    "ARA-041": ("occupancy_type", NOT_TENANT, "always", "", "Vacant is decided by ARA-028"),
    "ARA-042": same_as("ARA-029 / ARA-030"),
    "ARA-049": ARI_EXPOSED,
    "ARA-050": ("plumbing_type", GALV, "always", "", "mixed-galvanized / lead are not form options"),
    "ARA-056": ("roof_type", "roof_type != Metal", "always", "", ""),
    "ARA-059": ROOF_LIFE,
    "ARA-078": money("dwelling_amount <= 700000"),
    "ARA-079": money("dwelling_amount <= 1000000"),
    "ARA-085": PPC_1_9,
    # ================= ARI HOB
    "ARB-005": ("county", f"county not in {TWIA_TIER1[:-1]}, Harris}} || county not in {TWIA_TIER1}", "always", "",
                "TWIA's Tier 1 counties; Harris only east of Highway 146 (not asked): AMBIGUOUS"),
    "ARB-006": ("roof_type", "roof_type not in {Wood Shake, Slate} || roof_type not in {Wood Shake, Slate, Metal, "
                             "Flat/Built-Up}", "always", "", "as ARA-007, slate included"),
    "ARB-007": ARI_FLAT, "ARB-008": ARI_TILE, "ARB-009": TOWNHOME, "ARB-011": ARI_UNPROTECTED, "ARB-012": WITHIN_5,
    "ARB-014": ("construction_type", MOBILE, "always", "", ""),
    "ARB-021": ARI_POOL,
    "ARB-022": ("swimming_pool;pool_accessories", NO_ACCESSORIES, POOL, "", ""),
    "ARB-024": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "ARB-025": SEASONAL_REFER,
    "ARB-028": ("has_dogs;aggressive_breed", BREED, DOGS, "", "the form's breed list is not ARI's"),
    "ARB-029": ("has_dogs", "FACT(no bite history)", DOGS, "bite history", ""),
    "ARB-035": ("occupancy_type", NOT_TENANT, "always", "", "Vacant is decided by ARB-024"),
    "ARB-036": same_as("ARB-025"), "ARB-039": same_as("ARB-025"),
    "ARB-040": ("year_built", "home_age <= 20", "always", "", "homes over 20 years go to HOA / HOA Plus"),
    "ARB-046": ARI_EXPOSED,
    "ARB-048": ("plumbing_type", GALV, "always", "", "mixed-galvanized / lead are not form options"),
    "ARB-055": ("roof_type", "roof_type != Metal", "always", "", ""),
    "ARB-058": ROOF_LIFE,
    "ARB-083": money("dwelling_amount <= 700000"),
    "ARB-087": money("dwelling_amount <= 1000000"),
    "ARB-093": PPC_1_9,
    # ================= Foremost Choice Homeowners (owner's homes only: the registry's scope)
    "FOR-005": money("dwelling_amount >= 100000"),
    "FOR-006": money("dwelling_amount <= 750000"),
    "FOR-012": ("construction_type", MOBILE, "always", "", ""),
    "FOR-035": ("plumbing_type", "plumbing_type != Polybutylene", "always", "", ""),
    "FOR-036": ("plumbing_type", GALV, "always", "", ""),
    "FOR-053": POOL_4FT,
    "FOR-061": ("has_dogs", "FACT(no dangerous dog or animal that has caused harm)", DOGS, "dangerous dog / harm",
                "the Animal Liability Exclusion endorsement is required if so"),
    "FOR-062": ("has_dogs;aggressive_breed", BREED, DOGS, "", "eligible with the Animal Liability Exclusion"),
    "FOR-063": ("has_dogs", "FACT(no bite history)", DOGS, "bite history", ""),
    "FOR-074": ("county", "FACT(served by TWIA, with a signed Acceptance of Windstorm or Hail Exclusion)",
                f"county in {FOREMOST_COASTAL}", "TWIA area; signed wind/hail exclusion", ""),
    "FOR-075": same_as("FOR-078", "county"),
    "FOR-076": same_as("FOR-074", "county"),
    "FOR-078": ("county", "county not in {Collin, Dallas, Denton, Fort Bend, Harris, Rockwall, Tarrant}", "always",
                "", ""),
    "FOR-087": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "FOR-093": same_as("FOR-094", "ownership_type"), "FOR-095": same_as("FOR-094", "ownership_type"),
    "FOR-094": ("ownership_type", "FACT(no business associated with the LLC's name)", LLC, "LLC business", ""),
    "FOR-096": ("ownership_type", "FACT(the grantor or trustee lives in the home)", TRUST, "grantor / trustee", ""),
    "FOR-097": ("ownership_type", "FACT(not a land trust)", TRUST, "land trust", ""),
    # ================= HOAIC HO3
    "HOA-001": money("dwelling_amount >= 150000"),
    "HOA-002": money("dwelling_amount <= 2000000"),
    "HOA-003": money("dwelling_amount <= 1500000"),
    "HOA-006": ("year_built", "home_age <= 100", "always", "", ""),
    "HOA-008": ("ppc;year_built", "home_age <= 3", "ppc_num >= 8", "", "10W counts as 10"),
    "HOA-009": ("ppc;year_built", "ppc_num <= 7", "ppc_num >= 8 and home_age <= 3", "",
                "PPC 8-10 on a home 3 years old or newer: always referred"),
    # ================= Liberty Mutual / Safeco HO3
    "LIB-043": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "LIB-004": same_as("LIB-043"), "LIB-042": same_as("LIB-043"),
    "LIB-006": ("occupancy_type", NOT_TENANT, "always", "", "seasonal homes are referred (LIB-066); Vacant is LIB-043's"),
    "LIB-028": ("construction_type", MOBILE, "always", "", ""),
    "LIB-033": ("year_built", "FACT(no fuses, knob and tube or aluminum wiring)", "year_built < 1976", "wiring", ""),
    "LIB-034": ("roof_type", "roof_type != Wood Shake", "always", "", ""),
    "LIB-048": ("ownership_type", "ownership_type != LLC", "always", "", ""),
    "LIB-051": ("ppc;dwelling_amount", "dwelling_amount <= 3000000", "ppc_num == 9", "", ""),
    "LIB-052": ("ppc;dwelling_amount", "dwelling_amount <= 1000000", "ppc_num == 10", "", ""),
    "LIB-064": ("ppc;dwelling_amount", "dwelling_amount < 1500000", "ppc_num == 9", "", ""),
    "LIB-065": ("ppc", "ppc_num <= 9", "always", "", "every class 10 home is referred"),
    "LIB-066": ("occupancy_type", "occupancy_type == Owner Occupied", SEASONAL, "", "every seasonal home is referred"),
    "LIB-068": ("ppc;dwelling_amount;fire_station_miles", "fire_station_miles <= 15",
                "(ppc_num == 9 and dwelling_amount between 1500000 and 3000000) or ppc_num == 10",
                "station distance if not given", ""),
    "LIB-069": ("ppc;dwelling_amount", "FACT(no wood or coal stove as the primary heat)",
                "(ppc_num == 9 and dwelling_amount between 1500000 and 3000000) or ppc_num == 10", "primary heat", ""),
    "LIB-070": ("ppc;dwelling_amount", "FACT(smoke or heat alarm on every floor and fire extinguishers)",
                "(ppc_num == 9 and dwelling_amount between 1500000 and 3000000) or ppc_num == 10", "alarms", ""),
    "LIB-071": ("ppc;dwelling_amount", "FACT(a local water source)",
                "(ppc_num == 9 and dwelling_amount between 1500000 and 3000000) or ppc_num == 10", "water source", ""),
    "LIB-072": ("ppc;dwelling_amount", "FACT(accessible year-round)",
                "(ppc_num == 9 and dwelling_amount between 1500000 and 3000000) or ppc_num == 10", "access", ""),
    # ================= Orion180 Flex HO3
    "ORI-003": ("occupancy_type", NOT_TENANT, "always", "", "Vacant is ORI-044's; the deed is not asked"),
    "ORI-004": same_as("ORI-003"), "ORI-043": same_as("ORI-003"),
    "ORI-005": ("dwelling_type", "FACT(fire wall between units to the roof line)", "dwelling_type == Townhome",
                "fire wall", ""),
    "ORI-007": ("dwelling_type", "FACT(an individual residential unit)", "dwelling_type == Townhome", "unit", ""),
    "ORI-012": ("roof_type", "roof_type != Wood Shake", "always", "",
                "Composition = asphalt fiberglass composite shingles; flat roofs are ORI-013's; Other is not decided"),
    "ORI-013": ("roof_shape;roof_type", "FACT(poured concrete or adobe)", FLAT, "flat roof material", ""),
    "ORI-024": ("ownership_type", "FACT(a trust for personal estate planning)", TRUST, "trust purpose", ""),
    "ORI-025": ("ownership_type;occupancy_type", NOT_TENANT, TRUST, "", ""),
    "ORI-028": ("ownership_type", "FACT(no rental, business or commercial use)", TRUST, "trust home use", ""),
    "ORI-029": PPC_1_9, "ORI-097": same_as("ORI-029", "ppc"), "ORI-098": WITHIN_5,
    "ORI-044": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "ORI-048": ("ownership_type", "ownership_type != LLC", "always", "", ""),
    "ORI-050": ("year_built", "year_built >= 1900", "always", "", ""),
    "ORI-056": ("construction_type", MOBILE, "always", "", "barndominiums are not a form option"),
    "ORI-059": ("roof_type", "roof_type != Metal || always", "always", "", "Metal may not be corrugated metal"),
    "ORI-092": ("has_dogs", "FACT(no animal with a bite history or aggression)", DOGS, "bite history", ""),
    "ORI-102": money("dwelling_amount between 350000 and 2000000"),
    # ================= Swyfft Benchmark (Surplus) HO3
    "SBS-001": money("dwelling_amount between 150000 and 2000000"),
    "SBS-003": RENOVATED_100,
    "SBS-005": ("roof_age", "roof_age <= 30", "always", "", ""),
    "SBS-008": POOL_4FT,
    "SBS-020": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "SBS-027": ("occupancy_type;primary_home_miles", "primary_home_miles >= 50", SEASONAL,
                "distance from the primary home", ""),
    "SBS-028": ("occupancy_type", NOT_TENANT, "always", "", ""),
    "SBS-030": ("plumbing_type", GALV_POLY, "always", "", ""),
    "SBS-045": ("construction_type", MOBILE, "always", "", "barndominiums are not a form option"),
    "SBS-049": UNFENCED_IN_GROUND,
    "SBS-054": ("ownership_type", "ownership_type not in {Trust, LLC}", "always", "", ""),
    # ================= Swyfft Lloyd's (Surplus) HO3
    "SLL-002": money("dwelling_amount between 125000 and 2000000"),
    "SLL-003": POOL_4FT,
    "SLL-007": ("swimming_pool;pool_accessories", NO_ACCESSORIES + " or FACT(meets local code)", POOL, "local code", ""),
    "SLL-054": ("year_built", "year_built >= 1950", "always", "", ""),
    "SLL-011": same_as("SLL-054", "year_built"),
    "SLL-015": ("roof_type;roof_age",
                "(roof_type in {Tile, Slate} and roof_age <= 40) or roof_age <= 25 || "
                "(roof_type in {Tile, Slate, Metal} and roof_age <= 40) or roof_age <= 25", "always", "",
                "25 years (shingles, light metal, built-up, wood); 40 years (standing seam metal, tile, slate): "
                "Metal is AMBIGUOUS"),
    "SLL-035": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "SLL-042": ("occupancy_type", "always", SEASONAL, "", "the form's Seasonal / Secondary Home is owner-occupied"),
    "SLL-043": ("occupancy_type", "FACT(the owner's primary residence is in the United States)", SEASONAL,
                "primary residence country", ""),
    "SLL-045": ("plumbing_type", GALV_POLY, "always", "", "steel is not a form option"),
    "SLL-056": ("ppc", "ppc_num <= 8", "always", "", ""),
    "SLL-063": ("construction_type", MOBILE, "always", "", "barndominiums are not a form option"),
    "SLL-069": ("swimming_pool", "swimming_pool != In Ground - Unfenced and FACT(meets local code)", IN_GROUND,
                "local code", ""),
    "SLL-074": ("ownership_type", "ownership_type != LLC", "always", "", ""),
    "SLL-075": ("ownership_type", "FACT(no more than 6 unrelated principals)", LLC, "LLC principals", ""),
    "SLL-076": ("ownership_type", "FACT(owns no more than 10 properties)", LLC, "LLC properties", ""),
    "SLL-077": ("ownership_type", "FACT(no fractional ownership properties)", LLC, "LLC timeshares", ""),
    "SLL-078": ("ownership_type", "FACT(no business other than real estate)", LLC, "LLC business", ""),
    "SLL-080": ("ownership_type", "ownership_type != Trust", "always", "", ""),
    # ================= Swyfft Topa (Surplus) HO3
    "STO-002": money("dwelling_amount between 150000 and 2000000"),
    "STO-004": POOL_4FT,
    "STO-010": RENOVATED_100,
    "STO-012": ("roof_age", "roof_age <= 30", "always", "", ""),
    "STO-018": ("has_dogs;aggressive_breed", BREED, DOGS, "", "the form's breed list is not Swyfft's"),
    "STO-019": ("has_dogs", "FACT(no bite history or aggression)", DOGS, "bite history", ""),
    "STO-024": ("occupancy_type", NOT_VACANT, "always", "", "under construction / for sale are not asked"),
    "STO-029": ("occupancy_type", "always", SEASONAL, "", "the form's Seasonal / Secondary Home is owner-occupied"),
    "STO-030": ("occupancy_type", NOT_TENANT, "always", "", ""),
    "STO-032": ("plumbing_type", GALV_POLY, "always", "", ""),
    "STO-048": ("construction_type", MOBILE, "always", "", "barndominiums are not a form option"),
    "STO-052": UNFENCED_IN_GROUND,
    "STO-057": ("ownership_type", "ownership_type not in {Trust, LLC}", "always", "", ""),
    # ================= TWICO HO3 (standard mounted solar: eligible, Liam 2026-10-06)
    "TWI-002": money("dwelling_amount <= 2000000"),
    "TWI-004": ("occupancy_type", NOT_TENANT, "always", "", ""),
    "TWI-010": same_as("TWI-004"), "TWI-043": same_as("TWI-004"),
    "TWI-005": ("occupancy_type;primary_home_carrier", "primary_home_carrier == TWICO", SEASONAL,
                "primary home written with TWICO", ""),
    "TWI-011": ("ownership_type", "FACT(written in the trustee's name, the trust an Additional Insured)", TRUST,
                "trustee's name", ""),
    "TWI-014": ("year_built", "FACT(plumbing updated within the last 40 years)", "year_built < 1980",
                "plumbing update date", ""),
    "TWI-039": ("plumbing_type", GALV_POLY, "always", "", ""),
    "TWI-020": same_as("TWI-039", "plumbing_type"),
    "TWI-035": ("construction_type", MOBILE, "always", "", "prefabricated homes are not a form option"),
    "TWI-037": ("roof_type", "roof_type not in {Wood Shake, Slate} || roof_type not in {Wood Shake, Slate, Metal}",
                "always", "", "Metal may not be metal tile / shake / shingle or corrugated metal"),
    "TWI-055": same_as("TWI-037", "roof_type"), "TWI-057": same_as("TWI-037", "roof_type"),
    "TWI-042": ("occupancy_type", NOT_VACANT, "always", "", ""),
    "TWI-044": ("coastal_tier", "FACT(not on a barrier island)", TIER1, "barrier island", ""),
    "TWI-046": ("swimming_pool;pool_accessories", NO_ACCESSORIES + " or FACT(signed Liability Exclusion TWIC 03 02)",
                POOL, "signed liability exclusion", ""),
    "TWI-047": ("swimming_pool", FENCED + " or FACT(signed Liability Exclusion TWIC 03 02)", POOL,
                "signed liability exclusion", ""),
    # ================= Travelers Quantum Home 2.0
    "TRV-015": ("has_dogs", "FACT(no animal that has bitten or injured)", DOGS, "bite history", ""),
    "TRV-016": ("has_dogs;aggressive_breed", BREED, DOGS, "", "the form's breed list is not Travelers'"),
    "TRV-017": ("ownership_type", "FACT(no business or commercial exposure)", "ownership_type in {Trust, LLC}",
                "entity's business", ""),
    "TRV-025": ("swimming_pool", FENCED + " or FACT(secured by a retractable safety cover or locking ladder)", POOL,
                "pool cover / ladder", ""),
    "TRV-030": ("construction_type", MOBILE, "always", "", ""),
    "TRV-032": ("dwelling_amount", "FACT(monitored central station fire and burglar alarm)",
                "dwelling_amount >= 1500000", "alarm", ""),
    "TRV-033": ("occupancy_type;dwelling_amount", "FACT(monitored low-temperature sensor and alarm)",
                "occupancy_type in {Seasonal, Secondary Home} and dwelling_amount >= 500000", "sensors", ""),
    "TRV-036": ("ppc;fire_station_miles", "station_miles_iso <= 7", "always",
                "station distance if not given", "a stated distance decides; else ISO classes 1-9 are within "
                                                 "5 road miles"),
    "TRV-039": ("occupancy_type;ppc;primary_home_carrier", "primary_home_carrier == Travelers",
                "occupancy_type in {Seasonal, Secondary Home} and ppc_num >= 9", "primary dwelling with Travelers", ""),
    "TRV-041": ("roof_type", "roof_type != Wood Shake || roof_type not in {Wood Shake, Flat/Built-Up}", "always", "",
                "rolled asphalt may or may not be the form's Flat/Built-Up"),
    "TRV-044": ("roof_age", "FACT(not in Wind/Hail/Tornado UW Classification High 1 or High 2)", "roof_age > 10",
                "wind/hail UW class", "cure: Roof Condition Questionnaire"),
    "TRV-045": ("roof_age", "FACT(not in Wind/Hail/Tornado UW Classification High 3)", "roof_age > 15",
                "wind/hail UW class", "cure: Roof Condition Questionnaire"),
    "TRV-046": ("roof_age", "roof_age <= 25", "always", "", "cure: Roof Condition Questionnaire"),
    "TRV-054": ("plumbing_type", GALV_POLY, "always", "", "lead is not a form option"),
    "TRV-059": ("occupancy_type", NOT_TENANT, "always", "", ""),
    "TRV-073": ("occupancy_type;dwelling_amount", "FACT(monitored central station fire and burglar alarm)",
                "occupancy_type in {Seasonal, Secondary Home} and dwelling_amount >= 500000", "alarm", ""),
    "TRV-074": money("dwelling_amount < 2000000"),
    "TRV-075": ("dwelling_type;dwelling_amount", "dwelling_amount < 500000", "dwelling_type == Condo", "",
                "Coverage A + C combined; Coverage C is not asked, so A alone"),
    "TRV-080": ("coastal_tier", "FACT(not Hurricane UW Classification Extreme)", TIER1, "hurricane UW class", ""),
    "TRV-081": ("coastal_tier", "FACT(not Hurricane UW Classification High 1 or High 2)",
                "coastal_tier in {Tier 1, Tier 2}", "hurricane UW class", ""),
    "TRV-082": ("coastal_tier;year_built", "year_built >= 2000 or FACT(not High 3 or Moderate 1)",
                "coastal_tier in {Tier 1, Tier 2, Tier 3}", "hurricane UW class", ""),
    "TRV-083": ("coastal_tier;dwelling_amount", "dwelling_amount <= 1000000 or FACT(not High 1 to Moderate 2)",
                "coastal_tier in {Tier 1, Tier 2, Tier 3}", "hurricane UW class", ""),
}

# Round 30 step 2 correction 3 (Liam, 2026-10-08): the row's effect is CONDITION, and a failed
# CONDITION reads "Refer" on the card. "Secondary must have an associated primary written in Twico" is
# a requirement, not a referral: unmet, the home is ineligible. The workbook row is not edited; the
# map line's outcome is. (Other CONDITION rows with the same issue are listed in handoff.md.)
OUTCOME_OVERRIDE = {"TWI-005": "DECLINES"}

HO3_NONE_NOTE = dict(BATCH_NONE_NOTE, SOLAR="solar shingles / solar roofs are not the form's (mounted) Solar panels",
                     PROTECTION_CLASS="response time, visibility and water source are not asked",
                     LIABILITY_HAZARDS="liability hazards are not asked")


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
        fh.write("# source: rules_data/build_ho3_batch_map.py over rules_data/carrier_rules_ho3_batch_v1.csv "
                 "(HO3 batch version 1, reviewed by Claude); built 2026-10-08 (round 29 step 7). "
                 "Grammar: rules_data/RULE_FIELD_MAP.md.\n")
        w = csv.writer(fh)
        w.writerow(["row_id", "field", "test", "gate", "outcome_if_fail", "open_fact", "map_note"])
        for r in ev:
            rid = r["Rule ID"]
            cure = r["Tool handling"] == "EVALUATE_CURE_IS_INSPECTION"
            outcome = "NOTE" if cure else OUTCOME_OVERRIDE.get(rid, r["Effect"] or "UNKNOWN")
            if rid in MAP:
                field, test, gate, open_fact, note = MAP[rid]
            else:
                field, test, gate, open_fact = "NONE", "", "", ""
                note = HO3_NONE_NOTE.get(r["Topic"], NONE_NOTE.get(r["Topic"], "the form has no field for this"))
            w.writerow([rid, field, test, gate, outcome, open_fact, note])
    unknown = sorted(set(MAP) - {r["Rule ID"] for r in ev})
    print(f"wrote {OUT}: {len(ev)} lines, {len(MAP)} mapped; map ids not deciding rows: {unknown}")
    print(coverage_table(ev))


if __name__ == "__main__":
    main()
