"""Build rules_data/rule_field_map.csv -- one line per deciding row (Tool
handling EVALUATE / EVALUATE_CURE_IS_INSPECTION) of
rules_data/carrier_rules_pilot_v5.csv (v3 until round 28).

Round 24 built it for v2 (on the structured-rules-eval branch). Round 25
(2026-10-04) moved it here and updated it for v3: PRO-018 and SWY-018 are no
longer deciding rows (INFO_ONLY), ALL-067 is IGNORE_INSPECTION, and PRO-038
is NONE (it applies only to plumbing replaced as a required update, which the
form does not ask).

Every line is written by hand below (MAP) or is a NONE line: the form has no
field that decides the row. The grammar and the guide-word -> form-option
table are in rules_data/RULE_FIELD_MAP.md.

usage: python rules_data/build_rule_field_map.py
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import intake_fields  # noqa: E402
RULES = os.path.join(HERE, "carrier_rules_pilot_v5.csv")
OUT = os.path.join(HERE, "rule_field_map.csv")

NO_POOL = "swimming_pool != No Pool"
POOL_OK = "pool_fence_4ft == True and pool_gate_locking == True"
# Round 35 step 3b: the roof covering in detail (intake_fields.ROOF_TYPES); values only ever inside {...}.
def _roofs(*names):
    bad = [n for n in names if n not in intake_fields.ROOF_TYPES]
    assert not bad, bad
    return "{" + ", ".join(names) + "}"


I = intake_fields
WOOD, SEAM, PANEL, MSHINGLE = I.ROOF_WOOD, I.ROOF_METAL_SEAM, I.ROOF_METAL_PANEL, I.ROOF_METAL_SHINGLE
BUILT_UP, ROLLED_ROOF, MEMBRANE, ASBESTOS, TLOCK, SOLAR_ROOF = (I.ROOF_BUILT_UP, I.ROOF_ROLLED, I.ROOF_MEMBRANE,
                                                                I.ROOF_ASBESTOS, I.ROOF_TLOCK, I.ROOF_SOLAR)
METAL = _roofs(SEAM, PANEL, MSHINGLE)
NOT_WOOD = "roof_type not in " + _roofs(WOOD)
IS_WOOD = "roof_type in " + _roofs(WOOD)
PROG_ROOF = ("roof_type not in " + _roofs(WOOD, BUILT_UP, ROLLED_ROOF, PANEL)
             + " and (roof_type not in " + _roofs(MEMBRANE) + " or FACT(the membrane is not rubber))")
PROG_ROOF_NOTE = "'wood ..., tar and gravel, rubber membrane, tin, rolled roofing, and corrugated metal'"
FLAT = "(roof_shape == Flat or roof_type in " + _roofs(BUILT_UP, MEMBRANE) + ")"
SEASONAL = "occupancy_type in {Seasonal, Secondary Home}"
DOGS = "has_dogs == Yes"
BREED = "always || aggressive_breed == No"      # before round 35: AMBIGUOUS (the form's list was not the carrier's)


# Round 35 step 3a (Liam, 2026-10-09, decision 1): each carrier's own breed list, as the form's options.
# A generic "pit bull" covers the three pit-bull-type breeds (Markel, Vave and Swyfft Lloyd's spell that
# out); a generic "mastiff(s)" covers Mastiff, Bullmastiff and Neapolitan Mastiff.
def _breeds(*names):
    bad = [n for n in names if n not in intake_fields.DOG_BREEDS]
    assert not bad, bad
    return "{" + ", ".join(dict.fromkeys(names)) + "}"


PIT = ("Pit Bull (American Pit Bull Terrier)", "American Staffordshire Terrier", "Staffordshire Bull Terrier")
MASTIFFS = ("Mastiff", "Bullmastiff", "Neapolitan Mastiff")
HUSKIES = ("Siberian Husky", "Husky (other than Siberian)")
GUARD, WOLF, OVCHARKA = ("Trained guard / attack / police / military dog", "Wolf hybrid or wild dog",
                         "Caucasian Ovcharka (Caucasian Mountain Dog)")
BREEDS = {
    "allied": _breeds("Akita", "Alaskan Malamute", "American Bulldog", "Belgian Malinois", "Bullmastiff", "Cane Corso",
                      "Chow Chow", "Doberman Pinscher", "German Shepherd", "Great Dane", GUARD, *HUSKIES, *PIT,
                      "Presa Canario", "Rottweiler", WOLF),
    # Sage's "Specified Dog Breeds" (HC4421305), guard dog breeds such as Doberman Pinscher and German Shepherd
    "sage": _breeds("Akita", "Alaskan Malamute", "American Staffordshire Terrier", "Boxer", "Bull Terrier",
                    "Bullmastiff", "Chow Chow", "Giant Schnauzer", "Great Dane", "Mastiff", "Neapolitan Mastiff",
                    OVCHARKA, "Pit Bull (American Pit Bull Terrier)", "Presa Canario", "Rhodesian Ridgeback",
                    "Rottweiler", "Siberian Husky", "Staffordshire Bull Terrier", WOLF, "Doberman Pinscher",
                    "German Shepherd", GUARD),
    "mercury": _breeds("Akita", "American Bully", "Cane Corso", "Chow Chow", "Dogo Argentino", *PIT, "Presa Canario",
                       "Rottweiler", WOLF),
    "progressive": _breeds("Akita", "American Bulldog", "Chow Chow", "Doberman Pinscher", *MASTIFFS, *PIT,
                           "Rottweiler", WOLF),
    "swyfft_benchmark": _breeds(*PIT, "Chow Chow", "Doberman Pinscher", "Presa Canario", "Rottweiler", WOLF),
    "swyfft_topa": _breeds("Chow Chow", "Doberman Pinscher", *PIT, "Presa Canario", "Rottweiler", WOLF),
    "ari": _breeds(*PIT, "German Shepherd", "Akita", "Doberman Pinscher", "Chow Chow", "Rottweiler", "Great Dane",
                   "Bullmastiff", "Presa Canario", OVCHARKA, WOLF),
    "foremost": _breeds("Akita", *PIT, "Chow Chow", "Doberman Pinscher", "Presa Canario", "Rottweiler", WOLF),
    "travelers": _breeds("Akita", "Alaskan Malamute", "American Bull Terrier", "Chow Chow", "Doberman Pinscher",
                         *MASTIFFS, *PIT, "Presa Canario", "Rottweiler", WOLF),
    "centauri_dp": _breeds("Akita", "American Bulldog", "Beauceron", OVCHARKA, "Chow Chow", "Doberman Pinscher",
                           "German Shepherd", "Great Dane", *PIT, "Rottweiler", WOLF),
}
DOG_FIELDS = "has_dogs;dog_breeds"
OPEN_LIST = "FACT(no other breed the guide counts as dangerous)"
ACK = "FACT(signed acknowledgement of the dog liability exclusion)"


def breed_line(carrier, kind, note=""):
    """closed: a listed breed fails. open ("includes, but is not limited to"): a listed breed fails; none of them
    is a confirm note. ack: a listed breed is eligible with a signed acknowledgement (a confirm note)."""
    s = "dog_breeds none_of " + BREEDS[carrier]
    test = {"closed": s, "open": s + " and " + OPEN_LIST, "ack": s + " or " + ACK,
            "open_ack": "(" + s + " and " + OPEN_LIST + ") or FACT(Animal Liability Exclusion endorsement)"}[kind]
    fact = {"closed": "", "open": "other dangerous breeds", "ack": "signed acknowledgement",
            "open_ack": "other dangerous breeds; Animal Liability Exclusion endorsement"}[kind]
    return (DOG_FIELDS, test, DOGS, fact, note)
NO_BAD_PLUMB = "plumbing_type not in {Galvanized, Polybutylene}"
# Round 35 step 3c: "PEX installed before 2011" reads the form's install-year options (intake_fields.pex_2011):
# before 2011 fails; unknown install year holds unless the home was built in 2011 or later.
PEX_ANY = "{" + ", ".join(intake_fields.PEX_TYPES) + "}"
PEX_2011 = "plumbing_type not in {Galvanized, Polybutylene} and pex_2011 == True"
PEX_2011_CAST = "plumbing_type not in {Galvanized, Polybutylene, Cast iron} and pex_2011 == True"
TIER2 = ("{Bee, Brooks, Fort Bend, Goliad, Hardin, Harris, Hidalgo, Jackson, Jim Wells, Liberty, Live Oak, "
         "Orange, Victoria, Wharton}")
MER_HIGH = ("{77015, 77034, 77058, 77059, 77062, 77075, 77089, 77465, 77502, 77503, 77504, 77505, 77506, 77507, "
            "77520, 77521, 77523, 77530, 77536, 77546, 77547, 77562, 77571, 77581, 77586, 77587, 77597, 77598, "
            "77969, 77971, 77979, 77991}")
MER_MOD = ("{77001, 77002, 77003, 77004, 77006, 77009, 77010, 77011, 77012, 77013, 77016, 77017, 77019, 77020, "
           "77021, 77023, 77026, 77028, 77029, 77030, 77033, 77044, 77047, 77048, 77049, 77050, 77051, 77054, "
           "77061, 77078, 77087, 77204, 77346, 77396, 77532, 77533, 77535, 77538, 77575, 77582, 77584, 77611, "
           "77630, 77951, 77977, 78387}")
CHUBB_COASTAL = ("{Aransas, Brazoria, Calhoun, Cameron, Chambers, Galveston, Harris, Jefferson, Kenedy, Kleberg, "
                 "Matagorda, Nueces, Refugio, San Patricio, Willacy}")

# row_id: (field, test, gate, open_fact, map_note). outcome_if_fail is the row's effect,
# or NOTE for EVALUATE_CURE_IS_INSPECTION rows (filled in below).
MAP = {
    # ---------------- PROTECTION_CLASS
    # Round 28 step 2: class 10 is ALL-113's, which has an exception (a new home in a protected
    # subdivision); failing it here declined that home anyway.
    "ALL-112": ("ppc", "ppc_num between 1 and 10", "always", "", "class 10 is decided by ALL-113 (its exception)"),
    "ALL-113": ("ppc;year_built", "home_age <= 3 and FACT(Protected Subdivision Rule)", "ppc_num == 10",
                "Protected Subdivision Rule", ""),
    # Round 26 (Liam, 2026-10-05, decision B): the table row is chosen by the
    # optional station distance / hydrant fields; blank / Unknown leaves the
    # row OPEN, as before. SAG-072 (any FPC, <= 5 miles and a hydrant within
    # 1,000 ft: eligible) is ALLOWS -- the rows below simply do not apply then.
    "SAG-073": ("ppc;fire_station_miles;hydrant_1000ft",
                "FACT(visible from road, central station alarm, 10-ft year-round access)",
                "ppc_num between 1 and 3 and fire_station_miles <= 5 and hydrant_1000ft == No",
                "station / hydrant distance if not given; visibility, alarm, access",
                "the FPC table row is chosen by station distance and hydrant"),
    "SAG-074": ("ppc;fire_station_miles", "FACT(visible from road, central station alarm, 10-ft year-round access)",
                "ppc_num between 1 and 3 and fire_station_miles > 5",
                "station distance if not given; visibility, alarm, access", ""),
    "SAG-075": ("ppc;year_built;occupancy_type;fire_station_miles;hydrant_1000ft",
                "home_age < 25 and occupancy_type == Owner Occupied and "
                "FACT(visible from road, central alarm, 10-ft access, no rentals, no prior fire loss)",
                "ppc_num between 4 and 10 and fire_station_miles <= 5 and hydrant_1000ft == No",
                "station / hydrant distance if not given; visibility, alarm, access, fire losses", ""),
    "SAG-076": ("ppc;year_built;occupancy_type;fire_station_miles",
                "home_age < 25 and occupancy_type == Owner Occupied and "
                "FACT(visible from road, central alarm, 10-ft access, no rentals, no prior fire loss)",
                "ppc_num between 4 and 8 and fire_station_miles > 5",
                "station distance if not given; visibility, alarm, access, fire losses", ""),
    "SAG-077": ("ppc;fire_station_miles", "fire_station_miles <= 5", "ppc_num >= 9", "station distance", ""),
    "MER-060": ("ppc", "ppc_num < 10", "always", "", "10W counts as 10"),
    "PRO-068": ("ppc", "FACT(paved road and visible to neighbors)", "ppc_num between 9 and 10",
                "paved road; visibility to neighbors", ""),
    "PRO-095": ("ppc", "FACT(no fire loss)", "ppc_num >= 8", "fire loss history", ""),
    # ---------------- ROOF
    "ALL-034": ("roof_age", "FACT(5+ years of useful life left)", "roof_age >= 15", "remaining roof life",
                "assumption: no covering on the form ends its life before 20 years, so a roof under 15 is N/A"),
    # round 35 step 3b: "T-lock shingles, slate, corrugated metal, copper, tin, rubber membrane, rolled tar paper,
    # built up tar and gravel, solar roof system and ... wood shingles or shakes"
    "ALL-037": ("roof_type", "roof_type not in " + _roofs(TLOCK, "Slate", PANEL, BUILT_UP, ROLLED_ROOF, SOLAR_ROOF, WOOD)
                + " and (roof_type not in " + _roofs(MEMBRANE) + " or FACT(the membrane is not rubber))"
                + " and (roof_type not in " + _roofs(SEAM, MSHINGLE) + " or FACT(the metal is not copper or tin))",
                "always", "membrane / metal kind", "copper is not a form option: a confirm note on metal"),
    "ALL-038": ("roof_shape;roof_type", "FACT(poured reinforced concrete)", FLAT, "flat roof material", ""),
    "ALL-042": ("roof_type", "roof_type not in " + _roofs("Slate", SOLAR_ROOF)
                + " and (roof_type not in {Other} or FACT(not a unique or uncommon roof covering))", "always",
                "uncommon roof covering", "'Solar panel tiles, slate, unique/uncommon roof material' (round 35)"),
    "SAG-032": ("roof_shape;roof_type", "FACT(no prior roof wind/water loss, or fully renovated)", FLAT,
                "prior roof loss; renovation", ""),
    "SAG-033": ("roof_type", "FACT(steel, 29 gauge or heavier)", "roof_type in " + METAL, "metal roof gauge", ""),
    # round 35 step 2: El Paso flat roofs get "underwriting consideration" -- a referral (CHU-111), not a pass
    "CHU-012": ("roof_shape;roof_type;county", "not " + FLAT, "county != El Paso", "", "El Paso is CHU-111's"),
    "CHU-111": ("roof_shape;roof_type;county", "not " + FLAT, "county == El Paso", "",
                "split from CHU-012 (round 35): underwriting consideration in El Paso"),
    "CHU-014": ("roof_type", "FACT(wildfire score not 10-50)", IS_WOOD, "wildfire score", ""),
    "CHU-020": ("roof_type;county", NOT_WOOD, "county not in " + CHUBB_COASTAL, "",
                "outside the coastal areas (CHU-021 is the coast's); tier ignored: other tiers are unacceptable"),
    "CHU-021": ("roof_type;county", NOT_WOOD, "county in " + CHUBB_COASTAL, "", ""),
    # round 35 step 3b: "Asbestos shingles, tin, T-lock shingles, wood shakes, wood shingles"
    "MER-012": ("roof_type", "roof_type not in " + _roofs(ASBESTOS, TLOCK, WOOD)
                + " and (roof_type not in " + _roofs(PANEL) + " or FACT(the panels are not tin))", "always",
                "tin", "the panel option includes tin: a confirm note"),
    "MER-016": ("roof_shape;roof_type", "not " + FLAT, "always", "", ""),
    "PRO-022": ("roof_age", "FACT(5+ years of life expectancy left)", "roof_age >= 15", "remaining roof life",
                "same assumption as ALL-034"),
    "PRO-024": ("roof_type", PROG_ROOF, "always", "membrane kind", PROG_ROOF_NOTE),
    "PRO-025": ("roof_shape;roof_type", "FACT(poured concrete or rubber)", FLAT, "flat roof material", ""),
    "SWY-017": ("roof_age", "roof_age <= 30", "always", "", ""),
    # ---------------- HOME AGE
    "ALL-028": ("year_built", "FACT(electrical, heating/AC and plumbing updated)", "home_age between 40 and 75",
                "system updates", "cure is a service inspection -> NOTE"),
    "ALL-029": ("year_built", "FACT(completely renovated, all updates)", "home_age >= 76", "renovation", ""),
    "ALL-031": ("year_built", "FACT(updates under 20 years old)", "home_age >= 76", "update ages", ""),
    "SAG-026": ("year_built;occupancy_type", "FACT(signed lead exclusion acknowledgement)",
                "occupancy_type == Tenant Occupied and year_built < 1980", "signed acknowledgement", ""),
    "SAG-078": ("year_built;ppc;fire_station_miles;hydrant_1000ft", "home_age < 25",
                ("(ppc_num between 4 and 8 and (hydrant_1000ft == No or fire_station_miles > 5)) or (ppc_n"
                 "um between 9 and 10 and hydrant_1000ft == No and fire_station_miles <= 5)"),
                "station / hydrant distance if not given", ""),
    "MER-010": ("year_built", "FACT(Functional Replacement Cost coverage)", "year_built < 1940", "loss settlement", ""),
    # ---------------- PLUMBING
    "ALL-057": ("plumbing_type;year_built", PEX_2011, "always", "",
                "AMBIGUOUS only for PEX in a home built before 2011 (install year unknown); lead/cast iron not on the form"),
    "ALL-058": ("plumbing_type;year_built", PEX_2011_CAST, "home_age between 40 and 75", "",
                "cure is a service inspection -> NOTE"),
    "ALL-060": ("plumbing_type;year_built", PEX_2011_CAST, "home_age >= 76", "",
                "cure is a service inspection -> NOTE"),
    # ALL-061: COVERAGE_ONLY since 2026-10-09 (round 32 step 1) -- the Limited Water Damage re-plumb, not a rule
    "SAG-042": ("plumbing_type", "plumbing_type != Polybutylene", "always", "", ""),
    "MER-029": ("plumbing_type", "plumbing_type in {Copper, PVC, " + ", ".join(intake_fields.PEX_TYPES) + "}",
                "always", "",
                "cure (plumber statement, over 50 years) is an inspection -> NOTE"),
    "MER-030": ("plumbing_type", "plumbing_type not in {Galvanized, Polybutylene, Cast iron}", "always", "",
                "'Galvanized, cast-iron and polybutylene' (round 35: cast iron is a form option)"),
    "PRO-039": ("plumbing_type;year_built", PEX_2011, "always", "",
                "AMBIGUOUS only for PEX in a home built before 2011"),
    "SWY-026": ("plumbing_type", NO_BAD_PLUMB, "always", "", ""),
    # ---------------- POOL
    "ALL-093": ("swimming_pool;pool_fence_4ft;pool_gate_locking", POOL_OK, NO_POOL, "fence 4 ft; locking gate",
                "approved alternate enclosure also cures"),
    "ALL-094": ("swimming_pool;pool_fence_4ft;pool_gate_locking",
                "swimming_pool not in {Above Ground - Unfenced, In Ground - Unfenced} and " + POOL_OK, NO_POOL,
                "fence 4 ft; locking gate", ""),
    "SAG-055": ("swimming_pool;pool_fence_4ft;pool_gate_locking", "swimming_pool != In Ground - Unfenced and " + POOL_OK,
                "swimming_pool in {In Ground - Fenced, In Ground - Unfenced}", "fence 4 ft; gate", ""),
    "SAG-056": ("swimming_pool;pool_fence_4ft;pool_gate_locking", "(swimming_pool == Above Ground - Fenced and pool_fence_4ft == True and pool_gate_locking == True) or FACT(above-ground pool wall 4 ft or higher)",
                "swimming_pool in {Above Ground - Fenced, Above Ground - Unfenced}", "fence 4 ft; gate; pool wall height",
                "round 35 step 2: the rule is for above-ground pools under 4 ft; an unfenced one is a confirm note on the wall height, never a hold on the fence boxes"),
    "SAG-060": ("pool_accessories", "FACT(signed acknowledgement of the slide/diving board exclusion)",
                "pool_accessories != None", "signed acknowledgement", ""),
    "MER-047": ("swimming_pool", "swimming_pool != In Ground - Unfenced", "always", "", ""),
    # Round 31 step 4: an explicitly unfenced pool fails (an unticked box is still unknown)
    "PRO-051": ("swimming_pool;pool_fence_4ft;pool_gate_locking",
                "swimming_pool not in {Above Ground - Unfenced, In Ground - Unfenced} and " + POOL_OK, NO_POOL,
                "fence 4 ft; locking gate", "approved alternate enclosure also cures"),
    "SWY-035": ("swimming_pool;pool_fence_4ft;pool_gate_locking", "swimming_pool != Above Ground - Unfenced and " + POOL_OK,
                NO_POOL, "fence 4 ft; self-latching gate",
                "a pool cage also cures; an unfenced in-ground pool is SWY-036's (one failing row per fact)"),
    "SWY-036": ("swimming_pool", "swimming_pool != In Ground - Unfenced", "always", "", ""),
    # ---------------- ANIMALS (dogs only: the form asks nothing about other animals)
    "ALL-102": ("has_dogs", "FACT(no dangerous propensities)", DOGS, "dog history", "other animals not asked"),
    "ALL-103": ("has_dogs", "FACT(no bite history)", DOGS, "bite history", ""),
    "ALL-106": breed_line("allied", "closed", "Allied p7 'prohibited breeds' (round 35: the breed field)"),
    "ALL-107": ("has_dogs;dog_breeds", "always", "always", "", "decided by ALL-106 (a picked breed is that breed or a mix)"),
    "SAG-067": breed_line("sage", "ack", "Specified Dog Breeds: eligible with a signed acknowledgement"),
    "SAG-068": ("has_dogs", "FACT(no bite history)", DOGS, "bite history", ""),
    "MER-054": breed_line("mercury", "closed", "wolf hybrids are in the same sentence"),
    "MER-056": ("has_dogs", "FACT(no biting history)", DOGS, "bite history", ""),
    "MER-057": ("has_dogs;dog_breeds", "always", "always", "", "decided by MER-054 (a picked breed is that breed or a mix)"),
    "MER-058": ("has_dogs", "FACT(3 or fewer dogs)", DOGS, "number of dogs", ""),
    "PRO-061": breed_line("progressive", "open", "'includes, but is not limited to'"),
    "PRO-062": ("has_dogs", "FACT(no bite history)", DOGS, "bite history", ""),
    "SWY-040": breed_line("swyfft_benchmark", "closed"),
    "SWY-041": ("has_dogs", "FACT(no bite history or aggression)", DOGS, "bite history", ""),
    # ---------------- SOLAR
    "ALL-109": ("solar_panels", "always || solar_panels == No", "solar_panels == Yes", "",
                "AMBIGUOUS: the form's Solar Panels does not say mounted panels or a solar roof system"),
    "ALL-110": ("solar_panels", "always || solar_panels == No", "solar_panels == Yes", "", "AMBIGUOUS: solar tiles"),
    "SWY-043": ("solar_panels", "always || solar_panels == No", "solar_panels == Yes", "", "AMBIGUOUS: Tesla solar roof"),
    # ---------------- OCCUPANCY
    "ALL-001": ("occupancy_type", "FACT(owner-occupied at least 9 months a year)", "occupancy_type == Owner Occupied",
                "9 months a year", "Owner Occupied = primary residence; the months are not asked (round 35)"),
    "ALL-002": ("occupancy_type", "FACT(3+ months a year, no rental exposure)", SEASONAL, "months occupied; rentals", ""),
    "ALL-004": ("occupancy_type", "occupancy_type in {Owner Occupied, Seasonal, Secondary Home}", "always", "", ""),
    "ALL-005": ("occupancy_type", "occupancy_type not in {Tenant Occupied, Vacant}", "always", "", ""),
    "ALL-006": ("occupancy_type", "occupancy_type != Vacant", "always", "", ""),
    "ALL-007": ("occupancy_type", "occupancy_type != Vacant", "always", "", ""),
    "ALL-008": ("occupancy_type", "occupancy_type != Tenant Occupied", "always", "", ""),
    "ALL-009": ("occupancy_type", "occupancy_type != Tenant Occupied", "always", "", "a rented other structure is not asked"),
    "ALL-010": ("occupancy_type", "FACT(no rental exposure)", SEASONAL, "rentals", ""),
    # v4 (2026-10-07): the owner-occupied heading covers primary AND seasonal / secondary homes.
    "SAG-001": ("occupancy_type", "occupancy_type != Tenant Occupied", "always", "",
                "owner occupied = primary, seasonal or secondary residence; Vacant is decided by SAG-005"),
    # Round 28 (v4/v5, 2026-10-07): one failing row per fact, as the Sage batch.
    "SAG-002": ("occupancy_type", "always", "always", "", "decided by SAG-005 (the same rule); never a second flaw"),
    "SAG-003": ("occupancy_type;dwelling_type", "dwelling_type == House", SEASONAL, "", ""),
    "SAG-004": ("occupancy_type", "FACT(checked monthly while away)", SEASONAL, "monthly checks", ""),
    "SAG-005": ("occupancy_type", "occupancy_type != Vacant", "always", "", "for sale is not asked"),
    "CHU-002": ("occupancy_type", "occupancy_type != Vacant", "always", "", ""),
    "CHU-004": ("occupancy_type;dwelling_type;primary_home_carrier", "primary_home_carrier == Chubb",
                "occupancy_type in {Seasonal, Secondary Home, Tenant Occupied}",   # round 35: no primary condos
                "Chubb writes the primary", ""),
    "CHU-005": ("occupancy_type", "FACT(Chubb writes the primary residence)", "occupancy_type == Tenant Occupied",
                "Chubb writes the primary", ""),
    "MER-001": ("occupancy_type", "occupancy_type != Vacant", "always", "", ""),
    "MER-002": ("occupancy_type", "occupancy_type != Vacant", "always", "", ""),
    "MER-003": ("occupancy_type;primary_home_carrier", "primary_home_carrier == Mercury", SEASONAL,
                "Mercury writes the primary", "round 30 step 1: the form's 'Primary home insured with'"),
    "PRO-003": ("occupancy_type", "FACT(disclosed, family-occupied, no rental)", SEASONAL, "rentals", ""),
    "PRO-004": ("occupancy_type", "occupancy_type != Vacant", "always", "", ""),
    "SWY-001": ("occupancy_type", "occupancy_type != Vacant", "always", "", ""),
    "SWY-007": ("occupancy_type;primary_home_miles", "primary_home_miles >= 50", SEASONAL, "distance from primary",
                "round 30 step 1: 'less than 50 miles from the primary residence'; the home is the owner's (decision 2)"),
    "SWY-009": ("occupancy_type", "occupancy_type != Tenant Occupied", "always", "", ""),
    # ---------------- OWNERSHIP
    "ALL-015": ("ownership_type", "FACT(grantor resides and is the named insured)", "ownership_type == Trust",
                "trust grantor", ""),
    "ALL-016": ("ownership_type", "ownership_type != Trust", "always", "", "trust: submit documents (REFER)"),
    "ALL-017": ("ownership_type", "ownership_type != LLC", "always", "", ""),
    "SAG-017": ("ownership_type", "ownership_type != LLC", "always", "", ""),
    # Round 31 step 5: "occupied by the trustee, the grantor ... or the beneficiary": a seasonal / secondary
    # home is the owner's own home too (was Owner Occupied only, which declined a trust's seasonal home)
    "SAG-019": ("ownership_type;occupancy_type", "occupancy_type in {Owner Occupied, Seasonal, Secondary Home} and "
                "FACT(occupied by the trustee, grantor or beneficiary)",
                "ownership_type == Trust", "who lives there", "as the Sage sister guides' trust-occupancy rows"),
    "MER-005": ("ownership_type", "ownership_type != LLC || ownership_type not in {LLC, Trust}", "always", "",
                "AMBIGUOUS: a form Trust may be a corporate trust"),
    "PRO-012": ("ownership_type", "ownership_type != LLC || ownership_type not in {LLC, Trust}", "always", "",
                "AMBIGUOUS: a form Trust may be a land trust"),
    "PRO-013": ("ownership_type", "ownership_type != Trust", "always", "", "trust: refer"),
    "SWY-011": ("ownership_type", "ownership_type not in {Trust, LLC}", "always", "", "trust or LLC: refer"),
    # ---------------- DWELLING TYPE / CONSTRUCTION
    "ALL-019": ("dwelling_type", "dwelling_type in {House, Townhome}", "always", "", ""),
    "ALL-020": ("dwelling_type", "dwelling_type in {House, Townhome}", "always", "", "multi-family is not asked"),
    "ALL-021": ("construction_type", "construction_type != Manufactured/Mobile", "always", "", "modular/kit not on the form"),
    "ALL-026": ("dwelling_type", "FACT(2-hour firewalls between units)", "dwelling_type == Townhome", "firewalls", ""),
    "SAG-021": ("construction_type", "construction_type != Manufactured/Mobile", "always", "", ""),
    "MER-009": ("construction_type", "construction_type != Manufactured/Mobile", "always", "", ""),
    "PRO-016": ("construction_type", "construction_type != Manufactured/Mobile", "always", "", ""),
    "PRO-017": ("dwelling_type", "FACT(4 or fewer units per fire division)", "dwelling_type == Townhome", "fire division", ""),
    "SWY-012": ("construction_type", "construction_type != Manufactured/Mobile", "always", "", ""),
    # ---------------- DWELLING LIMITS (Coverage A)
    "ALL-133": ("dwelling_amount", "dwelling_amount >= 200000", "always", "", ""),
    "ALL-134": ("dwelling_amount", "dwelling_amount <= 1250000", "always", "", ""),
    "SAG-096": ("dwelling_amount", "dwelling_amount <= 1000000", "always", "", ""),
    "SAG-098": ("dwelling_amount", "dwelling_amount >= 85000", "always", "", ""),
    "CHU-056": ("dwelling_amount;dwelling_type;occupancy_type", "dwelling_amount between 1000000 and 30000000",
                "dwelling_type == House and occupancy_type == Owner Occupied", "",
                "primary houses (round 35); below the Preferred minimum or over the $30M maximum: pre-approval"),
    "CHU-059": ("dwelling_type;occupancy_type", "dwelling_type != Condo", "occupancy_type == Owner Occupied", "",
                "primary condominiums (round 35); others are CHU-004's"),
    "MER-077": ("dwelling_amount", "dwelling_amount <= 1500000", "always", "", ""),
    "MER-078": ("dwelling_amount;dwelling_type", "dwelling_amount <= 750000", "dwelling_type == Condo", "",
                "Coverage C is not asked; A alone tested"),
    "MER-080": ("dwelling_amount", "dwelling_amount < 1250000", "always", "", ""),
    "MER-081": ("dwelling_amount;dwelling_type", "dwelling_amount < 500000", "dwelling_type == Condo", "", ""),
    # round 35 step 2: the $1M new-business cap is for the Tier II High and Moderate ZIP lists only
    "MER-086": ("dwelling_amount;county;zip", "dwelling_amount <= 1000000",
                "county in " + TIER2 + " and zip in " + MER_HIGH[:-1] + ", " + MER_MOD[1:], "ZIP",
                "Tier II High / Moderate ZIP codes (MER-068 / MER-069)"),
    "PRO-088": ("dwelling_amount", "dwelling_amount between 100000 and 5000000", "always", "", ""),
    "PRO-089": ("dwelling_amount", "dwelling_amount <= 1500000", "always", "", ""),
    "SWY-046": ("dwelling_amount", "dwelling_amount between 125000 and 2000000", "always", "", ""),
    # ---------------- LOCATION
    "SAG-081": ("county", "sage_territory == IN or county == Nueces", "always", "",
                "south of 31 N or the eight East Texas counties; Nueces is decided by SAG-082"),
    "SAG-082": ("county", "county != Nueces", "always", "", ""),
    "SAG-083": ("county", "always", "always", "", "decided by SAG-081 (the same rule); never a second flaw"),
    "SAG-088": ("coastal_tier", "FACT(not an extreme hazard location)", "coastal_tier == Tier 1",
                "distance to shoreline", "the form's tiers are not the guide's tiers"),
    # round 35 step 1: "within 3 miles of the designated primary shoreline in a tier 1 county" can be the
    # form's Tier 3 (the guide's tier is the county's, the form's is the distance band)
    "SAG-089": ("coastal_tier", "FACT(not within the shoreline distances)",
                "coastal_tier in {Tier 1, Tier 2, Tier 3}", "distance to shoreline", ""),
    "MER-061": ("coastal_tier", "FACT(1/2 mile or more from sea, bay, tidal water)", "coastal_tier == Tier 1",
                "distance to water", "Tier 1 = within 1 mile of Gulf or bay water (form help text)"),
    "MER-068": ("county;zip", "zip not in " + MER_HIGH, "county in " + TIER2, "ZIP; Harris side of Hwy 146",
                "Harris east of Hwy 146 is Tier I, not this row"),
    "MER-069": ("county;zip", "zip not in " + MER_MOD, "county in " + TIER2, "ZIP; Harris side of Hwy 146", ""),
    "PRO-072": ("county", "county not in {Hidalgo, Webb}", "always", "", ""),
    "PRO-073": ("coastal_tier", "FACT(more than 1,000 ft from the Gulf)", "coastal_tier == Tier 1", "distance to Gulf", ""),
    "PRO-087": ("coastal_tier", "FACT(above base flood elevation)", "coastal_tier == Tier 1", "elevation", ""),
    "PRO-108": ("county", "always", "always", "", "decided by PRO-072 (the same rule); never a second flaw"),
    "CHU-043": ("county;occupancy_type", "FACT(not Territory 8/9/10 or Harris 1A)",
                "county in " + CHUBB_COASTAL + " and occupancy_type == Owner Occupied",
                "Chubb territory", "primary houses (round 35); CHU-047 is the others'; no ZIP list in the guide"),
    "CHU-044": ("county;occupancy_type", "FACT(not Harris 1B/1C/1E)",
                "county == Harris and occupancy_type == Owner Occupied", "Chubb territory", "primary houses (round 35)"),
    "CHU-045": ("county;occupancy_type;primary_home_carrier", "primary_home_carrier == Chubb", "county == Harris and " + SEASONAL,
                "Chubb territory; primary", ""),
    "CHU-046": ("county;occupancy_type;primary_home_carrier", "primary_home_carrier == Chubb and FACT($25,000 non-CAT premium)",
                "county == Harris and " + SEASONAL,
                "Chubb territory; premium", ""),
    "CHU-047": ("county;occupancy_type", "FACT(not Harris 1A-east or Territory 8/9/10)",
                "county in " + CHUBB_COASTAL + " and " + SEASONAL, "Chubb territory", ""),
    # ---------------- ELECTRICAL / SYSTEMS by home age (the system ages are not asked)
    "ALL-065": ("year_built", "FACT(service panel updated or under 40 years old)", "home_age between 40 and 75", "panel age", ""),
    "ALL-066": ("year_built", "FACT(breakers updated and under 40 years old)", "home_age between 40 and 75", "breaker age", ""),
    "ALL-068": ("year_built", "FACT(completely re-wired)", "home_age >= 76", "re-wiring", ""),
    "ALL-074": ("year_built", "FACT(furnace under 40, heat pump/AC under 25)", "home_age >= 76", "system ages",
                "cure is a service inspection -> NOTE"),
}

NONE_NOTE = {
    "LOSS_HISTORY": "loss / claims history is not asked", "ELECTRICAL": "wiring and panels are not asked",
    "OTHER_SYSTEMS": "heating, cooling and water heater are not asked", "FOUNDATION": "foundation is not asked",
    "ACREAGE": "acreage is not asked", "LIABILITY_HAZARDS": "liability hazards are not asked",
    "OTHER": "not asked by the form", "CONSTRUCTION": "siding / construction details are not form options",
    "FLOOD": "flood zone is not asked", "LOCATION": "location detail beyond county / tier is not asked",
    "PRODUCT_STATUS": "product / binding status is not a property fact",
    "PLUMBING": "applies only to plumbing replaced as a required update, which the form does not ask",
}


def main():
    rows = list(csv.DictReader(l for l in open(RULES, encoding="utf-8-sig") if not l.startswith("#")))
    ev = [r for r in rows if r["Tool handling"] in ("EVALUATE", "EVALUATE_CURE_IS_INSPECTION")]
    with open(OUT, "w", encoding="utf-8", newline="") as fh:
        fh.write("# source: rules_data/build_rule_field_map.py over rules_data/carrier_rules_pilot_v5.csv "
                 "(pilot workbook version 5); built 2026-10-07 (round 28: SAG-001, one flaw per fact). "
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
                note = NONE_NOTE.get(r["Topic"], "the form has no field for this")
            w.writerow([rid, field, test, gate, outcome, open_fact, note])
    unknown = sorted(set(MAP) - {r["Rule ID"] for r in ev})
    print(f"wrote {OUT}: {len(ev)} lines, {len(MAP)} mapped; map ids not deciding rows: {unknown}")


if __name__ == "__main__":
    main()
