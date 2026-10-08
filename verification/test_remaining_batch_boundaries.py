"""Round 29 step 8 (2026-10-08): every numeric map line of the remaining (dwelling fire)
batch at its boundary, the Round 28 step 2 method: the expected outcomes come from each
row's PLAIN RULE text (quoted in the comment), never from the map line. These test the map
lines directly, so they do not need ELIGIBILITY_RULES_DP_BATCH. Zero API."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rules_evaluator as ev  # noqa: E402
from test_map_boundaries import A_ROW, B410, BASE, C, YEAR, age, money  # noqa: E402

pytestmark = pytest.mark.retrieval

# A landlord's check is the dwelling-fire base case.
DP_BASE = dict(BASE, occupancy_type="Tenant Occupied")


def fpc_age(rid):
    # "for the FPC 4-10 (no hydrant) and FPC 4-8 (over 5 miles) bands, the home must be less than 25 years old"
    return [(rid, dict(B410, ppc="6"), "year_built", {age(24): "PASS", age(25): "FAIL"}),
            (rid, dict(C, year_built=age(30)), "ppc", {"3": "N/A", "8": "FAIL", "9": "N/A", "10": "N/A"}),
            (rid, dict(B410, year_built=age(30)), "ppc", {"3": "N/A", "4": "FAIL", "10": "FAIL"}),
            (rid, dict(A_ROW, year_built=age(30)), "ppc", {"6": "N/A"})]


def fpc_9(rid):
    # "FPC 9 or higher with a fire station more than 5 driving miles away is ineligible"
    return [(rid, dict(C, ppc="9"), "fire_station_miles", {"5": "PASS", "5.1": "FAIL"}),
            (rid, C, "ppc", {"8": "N/A", "9": "FAIL", "10": "FAIL"})]


def fpc_bands_fact(rid):
    # a condition of the FPC 4-10 "B" (station <= 5, hydrant over 1,000 ft / none) and FPC 4-8 "C" bands
    return [(rid, B410, "ppc", {"3": "N/A", "4": "OPEN", "10": "OPEN"}),
            (rid, C, "ppc", {"4": "OPEN", "8": "OPEN", "9": "N/A"}),
            (rid, dict(A_ROW, ppc="6"), "fire_station_miles", {"3": "N/A"})]


def vacant_or_bc(rid):
    # "for vacant/unoccupied dwellings and FPC 'B' or 'C' risks, Coverage A may not exceed $2,000,000"
    return [money(rid, 2000000, "max", {"occupancy_type": "Vacant"}),
            (rid, {"dwelling_amount": 2500000, "hydrant_1000ft": "Yes"}, "fire_station_miles",
             {"3": "N/A", "5.1": "FAIL"}),
            (rid, {"dwelling_amount": 2500000, "hydrant_1000ft": "No"}, "fire_station_miles", {"3": "FAIL"})]


CASES = [
    # ---- Centauri DP3
    ("CDP-048", {}, "ppc", {"8": "PASS", "8B": "PASS", "9": "FAIL", "10": "FAIL"}),  # "class 9 or 10 ... unless approved"
    money("CDP-094", 2000000, "max"),                         # "Coverage A above $2,000,000 is not provided for"
    money("CDP-096", 1000000, "over_refers"),                 # "may not bind Coverage A above $1,000,000"
    # ---- Centauri HO3
    money("CHO-009", 1250000, "over_refers"),                 # "above $1,250,000 ... submitted to underwriting"
    ("CHO-059", {}, "ppc", {"8": "PASS", "9": "FAIL", "10": "FAIL"}),               # "class 9 or 10 is ineligible"
    # ---- HOAIC Texas Dwelling
    ("HDP-001", {}, "year_built", {age(100): "PASS", age(101): "FAIL"}),            # "older than 100 years"
    ("HDP-002", {}, "year_built", {age(50): "PASS", age(51): "OPEN"}),              # "older than 50 ... proof of updates"
    money("HDP-003", 500000, "max", {"ppc": "7"}),                                  # "PPC 1-7 ... at most $500,000"
    ("HDP-003", {"dwelling_amount": 600000}, "ppc", {"1": "FAIL", "7": "FAIL", "8": "N/A"}),
    money("HDP-004", 300000, "max", {"ppc": "8"}),                                  # "PPC 8-10 ... at most $300,000"
    ("HDP-004", {"dwelling_amount": 350000}, "ppc", {"7": "N/A", "8": "FAIL", "10": "FAIL"}),
    # ---- Liberty / Safeco Landlord
    money("LDP-069", 1500000, "over_refers"),                 # "Coverage A over $1.5 million must be referred"
    # ---- NatGen Custom360 Landlord
    money("NCD-027", 1500000, "max", {"ppc": "8"}),           # "protection class 1-8 ... maximum $1,500,000"
    ("NCD-027", {"dwelling_amount": 1600000}, "ppc", {"1": "FAIL", "8": "FAIL", "9": "N/A"}),
    # "protection class 1-8, dwelling limits between $1,000,000 and $1,500,000 need underwriting approval"
    ("NCD-030", {"ppc": "5"}, "dwelling_amount", {1000000: "PASS", 1000001: "FAIL", 1500000: "FAIL", 1500001: "PASS"}),
    money("NCD-028", 750000, "max", {"ppc": "9"}),            # "protection class 9 ... maximum $750,000"
    ("NCD-028", {"dwelling_amount": 800000}, "ppc", {"8": "N/A", "9": "FAIL", "10": "N/A"}),
    money("NCD-029", 500000, "max", {"ppc": "10"}),           # "protection class 10 ... maximum $500,000"
    ("NCD-029", {"dwelling_amount": 600000}, "ppc", {"9": "N/A", "10": "FAIL"}),
    # "central station fire alarm is required when the amount of insurance is over $1,000,000 / $750,000 / $500,000"
    ("NCD-042", {"ppc": "8"}, "dwelling_amount", {1000000: "N/A", 1000001: "OPEN"}),
    ("NCD-043", {"ppc": "9"}, "dwelling_amount", {750000: "N/A", 750001: "OPEN"}),
    ("NCD-044", {"ppc": "10"}, "dwelling_amount", {500000: "N/A", 500001: "OPEN"}),
    # "frame townhouses or rowhouses with more than 4 units built before 1980"
    ("NCD-059", {"dwelling_type": "Townhome", "construction_type": "Frame"}, "year_built", {1979: "OPEN", 1980: "N/A"}),
    # "in protection class 9-10, dwellings must be within 10 road miles"; a blank distance holds
    ("NCD-116", {"ppc": "9"}, "fire_station_miles", {"10": "PASS", "10.1": "FAIL", "": "OPEN"}),
    ("NCD-116", {"fire_station_miles": "12"}, "ppc", {"8": "N/A", "9": "FAIL", "10": "FAIL"}),
    # ---- Progressive DP3
    # "Coverage A above $500,000 ($750,000 for current-year construction) must be submitted"
    money("PDP-006", 500000, "over_refers"),
    money("PDP-006", 750000, "over_refers", {"year_built": YEAR}),
    money("PDP-007", 5000000, "max"),                         # "Coverage A above $5,000,000 is not available"
    ("PDP-096", {}, "roof_age", {14: "N/A", 15: "OPEN"}),     # "less than 5 years of life expectancy" (as ARA-059)
    ("PDP-116", {}, "ppc", {"8": "N/A", "9": "OPEN", "10": "OPEN"}),               # "PC 9 or 10 ... visible to neighbors"
    # ---- Progressive HO6
    ("PH6-050", {}, "ppc", {"8": "N/A", "9": "OPEN", "10": "OPEN"}),
    ("PH6-069", {}, "year_built", {age(100): "PASS", age(101): "FAIL"}),            # "older than 100 years ... referred"
    ("PH6-074", {"plumbing_type": "PEX"}, "year_built", {2010: "FAIL", 2011: "PASS"}),  # "PEX installed before 2011"
    money("PH6-092", 500000, "over_refers"),                  # "Coverage A over $500,000 must be submitted"
    ("PH6-094", {}, "dwelling_amount", {19999: "FAIL", 20000: "PASS", 1000000: "PASS", 1000001: "FAIL"}),
    # ---- Sage Markel DP3
    money("MDP-081", 100000, "min"),                          # "Coverage A must be at least $100,000"
    # ---- Sage Occidental DP3: the FPC table
    # "FPC 1-3, station within 5 miles and no hydrant within 1,000 ft"
    ("ODP-110", {"hydrant_1000ft": "No"}, "ppc", {"1": "OPEN", "3": "OPEN", "4": "N/A"}),
    ("ODP-110", {"hydrant_1000ft": "No", "ppc": "2"}, "fire_station_miles", {"5": "OPEN", "5.1": "N/A"}),
    # "FPC 1-3 and a fire station more than 5 driving miles away"
    ("ODP-111", {"ppc": "3"}, "fire_station_miles", {"5": "N/A", "5.1": "OPEN"}),
    ("ODP-111", {"fire_station_miles": "7"}, "ppc", {"3": "OPEN", "4": "N/A"}),
    # "FPC 4-10, station within 5 driving miles and no hydrant within 1,000 ft"
    ("ODP-112", B410, "ppc", {"3": "N/A", "4": "OPEN", "10": "OPEN"}),
    ("ODP-112", {"hydrant_1000ft": "No", "ppc": "6"}, "fire_station_miles", {"5": "OPEN", "5.1": "N/A"}),
    # "FPC 4-8 and a fire station more than 5 driving miles away"
    ("ODP-113", C, "ppc", {"3": "N/A", "4": "OPEN", "8": "OPEN", "9": "N/A"}),
    ("ODP-113", {"ppc": "6"}, "fire_station_miles", {"5": "N/A", "5.1": "OPEN"}),
    *fpc_age("ODP-114"),
    # "only primary-occupancy dwellings with no prior fire losses": primary vs secondary / seasonal
    ("ODP-115", dict(C, ppc="6"), "occupancy_type",
     {"Owner Occupied": "OPEN", "Tenant Occupied": "OPEN", "Seasonal": "FAIL", "Secondary Home": "FAIL"}),
    ("ODP-115", dict(C, occupancy_type="Seasonal"), "ppc", {"8": "FAIL", "9": "N/A"}),
    *fpc_9("ODP-116"),
    money("ODP-117", 2000000, "max"),                         # "Maximum Coverage A is $2,000,000"
    money("ODP-118", 1250000, "over_refers"),                 # "Coverage A over $1,250,000 must be referred"
    money("ODP-119", 85000, "under_refers"),                  # "Coverage A under $85,000 is referred"
    # ---- Sage SURE DP3
    money("SDP-069", 4000000, "max"),                         # "Coverage A may not exceed $4,000,000"
    *vacant_or_bc("SDP-070"),
    money("SDP-071", 2000000, "over_refers"),                 # "Coverage A over $2,000,000 must be referred"
    money("SDP-072", 85000, "under_refers"),                  # "Coverage A under $85,000 must be referred"
    # "FPC 1-3 with hydrant over 1,000 ft or none (B), or fire station over 5 driving miles (C)"
    ("SDP-078", {"hydrant_1000ft": "No", "fire_station_miles": "3"}, "ppc", {"3": "OPEN", "4": "N/A"}),
    ("SDP-078", {"ppc": "3", "hydrant_1000ft": "Yes"}, "fire_station_miles", {"5": "N/A", "5.1": "OPEN"}),
    *fpc_bands_fact("SDP-079"),
    *fpc_age("SDP-080"),
    # "only primary-occupancy dwellings are eligible and any rental exposure makes the risk ineligible"
    ("SDP-081", dict(C, ppc="6"), "occupancy_type",
     {"Owner Occupied": "PASS", "Tenant Occupied": "FAIL", "Seasonal": "FAIL", "Secondary Home": "FAIL"}),
    ("SDP-081", dict(B410, occupancy_type="Tenant Occupied"), "ppc", {"3": "N/A", "4": "FAIL", "10": "FAIL"}),
    ("SDP-081", dict(A_ROW, occupancy_type="Tenant Occupied"), "ppc", {"6": "N/A"}),
    *fpc_bands_fact("SDP-082"),
    *fpc_9("SDP-083"),
    # ---- Sage SafePort DP3
    money("FDP-093", 5000000, "max"),                         # "Maximum is $5,000,000 Coverage A"
    *vacant_or_bc("FDP-094"),
    money("FDP-095", 2000000, "over_refers"),
    money("FDP-097", 85000, "under_refers"),
    *fpc_9("FDP-104"),
    # "On 'B' or 'C' risks in FPC 1-8 and FPC 9-10 B"
    ("FDP-105", {"hydrant_1000ft": "No", "fire_station_miles": "3"}, "ppc",
     {"1": "OPEN", "3": "OPEN", "4": "OPEN", "10": "OPEN"}),
    ("FDP-105", C, "ppc", {"3": "OPEN", "8": "OPEN", "9": "N/A"}),
    ("FDP-105", A_ROW, "ppc", {"3": "N/A", "9": "N/A"}),
    *fpc_age("FDP-108"),
    # "only primary-occupancy dwellings are eligible" / "no rental exposures are allowed"
    ("FDP-109", dict(C, ppc="6"), "occupancy_type", {"Owner Occupied": "PASS", "Tenant Occupied": "PASS",
                                                     "Seasonal": "FAIL", "Secondary Home": "FAIL", "Vacant": "FAIL"}),
    ("FDP-110", dict(C, ppc="6"), "occupancy_type", {"Owner Occupied": "PASS", "Tenant Occupied": "FAIL",
                                                     "Seasonal": "PASS"}),
    ("FDP-110", dict(B410, occupancy_type="Tenant Occupied"), "ppc", {"3": "N/A", "4": "FAIL", "10": "FAIL"}),
    *fpc_bands_fact("FDP-111"),
    # ---- Sage Vave DP3
    money("VDP-005", 100000, "min"),                          # "Coverage A below $100,000 is not available"
    money("VDP-006", 2000000, "max"),                         # "Coverage A above $2,000,000 is not available"
    ("VDP-031", {}, "year_built", {1899: "FAIL", 1900: "PASS"}),                    # "built before 1900"
    ("VDP-042", {}, "year_built", {1899: "N/A", 1900: "OPEN", 1929: "OPEN", 1930: "PASS"}),  # "1900-1929 ... gut rehab"
    # ---- Steadily DP3
    ("STD-045", {}, "year_built", {age(100): "PASS", age(101): "FAIL"}),            # "within the last 100 years"
    ("STD-095", {}, "ppc", {"8": "PASS", "9": "FAIL", "10": "FAIL"}),               # "PPC 9-10 ... additional review"
    money("STD-102", 1500000, "max"),                         # "Maximum dwelling limit is $1,500,000"
    money("STD-104", 350000, "or_more_refers", {"dwelling_type": "Condo"}),  # "$350,000 or more require approval"
    # ---- Foremost Dwelling Fire (TDP-3)
    money("FOD-031", 100000, "min"),                          # "a value of at least $100,000"
    money("FOD-033", 1000000, "over_refers"),                 # "Coverage A may not exceed $1,000,000"
]

MAP = ev._load("map", ev.DP_BATCH_MAP_CSV)


def _outcome(rid, base, field, value):
    pd = dict(DP_BASE, **base)
    pd[field] = value
    return ev.evaluate_row(MAP[rid], ev.facts(pd))[0]


@pytest.mark.parametrize("rid,base,field,values", CASES, ids=[f"{c[0]}:{c[2]}" for c in CASES])
def test_boundary(rid, base, field, values):
    got = {v: _outcome(rid, base, field, v) for v in values}
    assert got == values
