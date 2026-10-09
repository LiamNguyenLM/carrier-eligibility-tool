"""Round 28 step 2 (2026-10-07): every map line with a numeric or ordered test,
pilot v5 and the Sage batch, at its boundary. The expected outcomes come from
each row's PLAIN RULE text ("less than 25 years": 24 passes, 25 fails), never
from the Check type / Value columns and never from the map line itself.
Zero API.

A case is (row id, base profile overrides, field, {value: outcome}). Outcomes
are the evaluator's: PASS / FAIL / N/A (the gate is false) / OPEN (a FACT or a
second reading is left open)."""
import datetime
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rules_evaluator as ev  # noqa: E402

pytestmark = pytest.mark.retrieval

YEAR = datetime.date.today().year
BASE = {"year_built": 2000, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "aggressive_breed": "No", "solar_panels": "No",
        "ppc": "3", "dwelling_type": "House", "county": "Bexar", "dwelling_amount": 450000}


def age(a):
    """year_built for a home a years old (facts() computes home_age from today)."""
    return YEAR - a


B410 = {"hydrant_1000ft": "No", "fire_station_miles": "3"}        # FPC row B
C = {"hydrant_1000ft": "Yes", "fire_station_miles": "7"}           # FPC row C
A_ROW = {"hydrant_1000ft": "Yes", "fire_station_miles": "3"}       # FPC row A

# The FPC table rows, the same in Auros and the four sister guides.
FPC = {
    # "PPC 1-3, station within 5 miles, no hydrant within 1,000 ft": ppc 3 in, 4 out; 5 mi in, 5.1 out
    "b13": [({"hydrant_1000ft": "No"}, "ppc", {"1": "OPEN", "3": "OPEN", "4": "N/A"}),
            ({"hydrant_1000ft": "No", "ppc": "2"}, "fire_station_miles", {"5": "OPEN", "5.1": "N/A"})],
    # "PPC 1-3, station more than 5 miles": 5 out, 5.1 in
    "c13": [({"ppc": "3"}, "fire_station_miles", {"5": "N/A", "5.1": "OPEN"}),
            ({"fire_station_miles": "7"}, "ppc", {"3": "OPEN", "4": "N/A"})],
    # "PPC 4-10 within 5 miles, no hydrant ... the home is under 25": 24 open (other facts), 25 fails
    "b410": [(dict(B410, ppc="6"), "year_built", {age(24): "OPEN", age(25): "FAIL"}),
             (dict(B410, year_built=age(10)), "ppc", {"3": "N/A", "4": "OPEN", "10": "OPEN"})],
    # "PPC 4-8 more than 5 miles ... under 25": ppc 8 in, 9 out
    "c48": [(dict(C, ppc="6"), "year_built", {age(24): "OPEN", age(25): "FAIL"}),
            (dict(C, year_built=age(10)), "ppc", {"4": "OPEN", "8": "OPEN", "9": "N/A"})],
    # "PPC 9 or greater with a station more than 5 miles is ineligible"
    "fpc9": [(dict(C, ppc="9"), "fire_station_miles", {"5": "PASS", "5.1": "FAIL"}),
             (C, "ppc", {"8": "N/A", "9": "FAIL", "10": "FAIL"})],
    # "in the FPC 4-10 (no hydrant, within 5) and FPC 4-8 (over 5 miles) rows ... less than 25 years"
    "age25": [(dict(B410, ppc="6"), "year_built", {age(24): "PASS", age(25): "FAIL"}),
              (dict(C, year_built=age(30)), "ppc", {"3": "N/A", "8": "FAIL", "9": "N/A", "10": "N/A"}),
              (dict(B410, year_built=age(30)), "ppc", {"3": "N/A", "4": "FAIL", "10": "FAIL"}),
              (dict(A_ROW, year_built=age(30)), "ppc", {"6": "N/A"})],
    # the same seven-condition rows: "primary occupancy" (Owner Occupied passes the known part)
    "rows7": [(dict(C, year_built=age(30)), "ppc", {"3": "N/A", "8": "OPEN", "9": "N/A", "10": "N/A"}),
              (dict(B410, year_built=age(30)), "ppc", {"3": "N/A", "4": "OPEN", "10": "OPEN"})],
    "rows7_known": [(dict(C, year_built=age(30)), "ppc", {"3": "N/A", "8": "PASS", "9": "N/A", "10": "N/A"}),
                    (dict(B410, year_built=age(30)), "ppc", {"3": "N/A", "4": "PASS", "10": "PASS"})],
}
SISTER_FPC = {
    "SAG": {"b13": "SAG-073", "c13": "SAG-074", "b410": "SAG-075", "c48": "SAG-076", "fpc9": "SAG-077",
            "age25": "SAG-078"},
    "SUR": {"b13": "SUR-111", "c13": "SUR-112", "b410": "SUR-113", "c48": "SUR-114", "fpc9": "SUR-115",
            "age25": "SUR-116", "rows7": "SUR-117"},
    "SFP": {"b13": "SFP-119", "c13": "SFP-120", "b410": "SFP-121", "c48": "SFP-122", "fpc9": "SFP-123",
            "age25": "SFP-124", "rows7": "SFP-125"},
    "WIL": {"b13": "WIL-116", "c13": "WIL-117", "b410": "WIL-118", "c48": "WIL-119", "fpc9": "WIL-120",
            "age25": "WIL-121", "rows7": ["WIL-122", "WIL-123"]},
    "TRI": {"b13": "TRI-088", "c13": "TRI-089", "b410": "TRI-090", "c48": "TRI-091", "fpc9": "TRI-092",
            "age25": "TRI-035", "rows7": "TRI-020", "rows7_known": "TRI-019"},
}

CASES = []
for _prefix, rows in SISTER_FPC.items():
    for key, rids in rows.items():
        for rid in (rids if isinstance(rids, list) else [rids]):
            CASES += [(rid, base, field, values) for base, field, values in FPC[key]]


def money(rid, limit, kind, gate=None):
    """kind: "max" (at most limit passes), "over_refers" (over limit fails), "min" (at least limit passes),
    "under_refers" (under limit fails), "or_more_refers" (limit or more fails)."""
    base = gate or {}
    if kind in ("max", "over_refers"):
        return (rid, base, "dwelling_amount", {limit - 1: "PASS", limit: "PASS", limit + 1: "FAIL"})
    if kind in ("min", "under_refers"):
        return (rid, base, "dwelling_amount", {limit - 1: "FAIL", limit: "PASS", limit + 1: "PASS"})
    if kind == "or_more_refers":
        return (rid, base, "dwelling_amount", {limit - 1: "PASS", limit: "FAIL", limit + 1: "FAIL"})
    raise ValueError(kind)


CASES += [
    # ---- Allied: home-age bands "40-75 years old", "76 years and older"
    # (ALL-028, ALL-058, ALL-060 and ALL-074 are cure-is-inspection rows: inside the band a FAIL or an
    # OPEN is a NOTE, round 24.)
    *[(rid, {}, "year_built", {age(39): "N/A", age(40): "OPEN", age(75): "OPEN", age(76): "N/A"})
      for rid in ("ALL-065", "ALL-066")],
    ("ALL-028", {}, "year_built", {age(39): "N/A", age(40): "NOTE", age(75): "NOTE", age(76): "N/A"}),
    *[(rid, {}, "year_built", {age(75): "N/A", age(76): "OPEN", age(90): "OPEN"})
      for rid in ("ALL-029", "ALL-031", "ALL-068")],
    ("ALL-074", {}, "year_built", {age(75): "N/A", age(76): "NOTE", age(90): "NOTE"}),
    ("ALL-058", {"plumbing_type": "Galvanized"}, "year_built",
     {age(39): "N/A", age(40): "NOTE", age(75): "NOTE", age(76): "N/A"}),
    ("ALL-058", {"plumbing_type": "Copper"}, "year_built", {age(40): "PASS"}),
    ("ALL-060", {"plumbing_type": "Galvanized"}, "year_built", {age(75): "N/A", age(76): "NOTE"}),
    # ALL-061 left the map 2026-10-09 (round 32 step 1, Claude review): a coverage row, not a rule.
    # Was: ("ALL-061", {"plumbing_type": "PEX"}, "year_built", {age(75): "N/A", age(76): "FAIL"}).
    # "Pre-2011 PEX": PEX in a home built 2010 is pre-2011 on the original-plumbing reading
    *[(rid, {"plumbing_type": "PEX"}, "year_built", {2010: "OPEN", 2011: "PASS", 2012: "PASS"})
      for rid in ("ALL-057", "PRO-039")],
    # roof "less than 5 years of useful life" -- the map note's assumption: no covering ends before 20 years
    *[(rid, {}, "roof_age", {14: "N/A", 15: "OPEN"}) for rid in ("ALL-034", "PRO-022")],
    # "Protection classes 1-9 are eligible"; class 10 is ALL-113's (it has an exception)
    ("ALL-112", {}, "ppc", {"1": "PASS", "9": "PASS", "10": "PASS"}),
    # "Protection class 10 is ineligible unless ... 3 years old or less" and the subdivision rule
    ("ALL-113", {"ppc": "10"}, "year_built", {age(3): "OPEN", age(4): "FAIL"}),
    ("ALL-113", {"year_built": age(2)}, "ppc", {"9": "N/A", "10": "OPEN"}),
    money("ALL-133", 200000, "min"),
    money("ALL-134", 1250000, "over_refers"),
    # ---- Sage: "rentals built before 1980"
    *[(rid, {"occupancy_type": "Tenant Occupied"}, "year_built", {1979: "OPEN", 1980: "N/A"})
      for rid in ("SAG-026", "SUR-028", "SFP-028", "TRI-033")],
    money("SAG-096", 1000000, "max"),
    money("SAG-098", 85000, "under_refers"),
    # ---- Chubb: below the Preferred minimum ($1,000,000) the Standard tier is pre-approval (round 20)
    money("CHU-056", 1000000, "min"),
    # ---- Mercury
    ("MER-010", {}, "year_built", {1939: "OPEN", 1940: "N/A"}),          # "Pre-1940 homes"
    ("MER-060", {}, "ppc", {"9": "PASS", "10": "FAIL"}),                  # "class of 10 or 10W"
    money("MER-077", 1500000, "max"),
    money("MER-078", 750000, "max", {"dwelling_type": "Condo"}),
    money("MER-080", 1250000, "or_more_refers"),                          # "$1,250,000 or more"
    money("MER-081", 500000, "or_more_refers", {"dwelling_type": "Condo"}),
    money("MER-086", 1000000, "max", {"county": "Harris"}),
    # ---- Progressive
    ("PRO-068", {}, "ppc", {"8": "N/A", "9": "OPEN", "10": "OPEN"}),      # "protection class 9 or 10"
    ("PRO-088", {}, "dwelling_amount", {99999: "FAIL", 100000: "PASS", 5000000: "PASS", 5000001: "FAIL"}),
    money("PRO-089", 1500000, "over_refers"),
    ("PRO-095", {}, "ppc", {"7": "N/A", "8": "OPEN", "10": "OPEN"}),      # "protection class 8 or higher"
    # ---- Swyfft
    ("SWY-017", {}, "roof_age", {29: "PASS", 30: "PASS", 31: "FAIL"}),   # "older than 30 years"
    ("SWY-046", {}, "dwelling_amount", {124999: "FAIL", 125000: "PASS", 2000000: "PASS", 2000001: "FAIL"}),
    # ---- Sage batch: Coverage A
    money("SUR-090", 4000000, "max"), money("SFP-095", 5000000, "max"), money("WIL-096", 2000000, "max"),
    money("TRI-110", 2000000, "max"), money("VAV-079", 2000000, "max"),
    money("SUR-092", 2000000, "over_refers"), money("SFP-099", 2000000, "over_refers"),
    money("TRI-111", 1250000, "over_refers"),
    *[money(rid, 85000, "under_refers") for rid in ("SUR-100", "SFP-107", "WIL-105", "TRI-114")],
    money("MKL-079", 100000, "min"), money("VAV-078", 100000, "min"),
    # "For Fire Protection Class B or C risks, maximum Coverage A is $2,000,000"
    *[money(rid, 2000000, "max", B410) for rid in ("SUR-091", "SFP-097")],
    *[(rid, {"dwelling_amount": 2500000, "hydrant_1000ft": "Yes"}, "fire_station_miles",
       {"5": "N/A", "5.1": "FAIL"}) for rid in ("SUR-091", "SFP-097")],
    # ---- Vave: "built before 1900", "1900-1929 ... full gut rehab"
    ("VAV-024", {}, "year_built", {1899: "FAIL", 1900: "PASS"}),
    *[(rid, {}, "year_built", {1899: "N/A", 1900: "OPEN", 1929: "OPEN", 1930: "N/A"})
      for rid in ("VAV-025", "VAV-026")],
]

# ---- Round 29 step 7: the HO3 batch (plain rule in each comment)
CASES += [
    # "Unprotected property (class 10) that is not visible ... is ineligible"
    *[(rid, {}, "ppc", {"9": "N/A", "10": "OPEN"}) for rid in ("ARA-013", "ARB-011")],
    # "more than 5 miles from an ISO-rated responding fire department are ineligible": a stated distance decides
    *[(rid, {"ppc": "N/A"}, "fire_station_miles", {"5": "PASS", "5.1": "FAIL"}) for rid in ("ARA-014", "ARB-012", "ORI-098")],
    *[(rid, {"ppc": "9"}, "fire_station_miles", {"": "PASS", "7": "FAIL"}) for rid in ("ARA-014", "ARB-012", "ORI-098")],
    *[(rid, {}, "ppc", {"10": "OPEN"}) for rid in ("ARA-014", "ARB-012", "ORI-098")],      # PPC 10, no distance
    *[(rid, {}, "roof_age", {14: "N/A", 15: "OPEN"}) for rid in ("ARA-059", "ARB-058")],      # 5 years' life left
    *[money(rid, 700000, "over_refers") for rid in ("ARA-078", "ARB-083")],                    # binding limit $700,000
    *[money(rid, 1000000, "max") for rid in ("ARA-079", "ARB-087")],                           # Coverage A max $1,000,000
    *[(rid, {}, "ppc", {"9": "PASS", "10": "FAIL"}) for rid in ("ARA-085", "ARB-093", "ORI-029")],  # class 10 ineligible
    ("ARB-040", {}, "year_built", {age(20): "PASS", age(21): "FAIL"}),                        # "homes 0-20 years old"
    money("FOR-005", 100000, "min"), money("FOR-006", 750000, "max"),
    money("HOA-001", 150000, "min"), money("HOA-002", 2000000, "max"),
    money("HOA-003", 1500000, "over_refers"),                                                  # "over $1,500,000 ... approval"
    ("HOA-006", {}, "year_built", {age(100): "PASS", age(101): "FAIL"}),                       # "older than 100 years"
    ("HOA-008", {"ppc": "8"}, "year_built", {age(3): "PASS", age(4): "FAIL"}),                 # "3 years old or newer"
    ("HOA-008", {"year_built": age(10)}, "ppc", {"7": "N/A", "8": "FAIL", "10": "FAIL"}),
    ("HOA-009", {"ppc": "8"}, "year_built", {age(3): "FAIL", age(4): "N/A"}),                  # 8-10 and <= 3 years: refer
    ("LIB-033", {}, "year_built", {1975: "OPEN", 1976: "N/A"}),                                # "built before 1976"
    ("LIB-051", {"ppc": "9"}, "dwelling_amount", {3000000: "PASS", 3000001: "FAIL"}),          # PC 9, over $3 million
    ("LIB-051", {"dwelling_amount": 3500000}, "ppc", {"8": "N/A", "9": "FAIL"}),
    ("LIB-052", {"ppc": "10"}, "dwelling_amount", {1000000: "PASS", 1000001: "FAIL"}),         # PC 10, over $1 million
    ("LIB-064", {"ppc": "9"}, "dwelling_amount", {1499999: "PASS", 1500000: "FAIL"}),          # "$1.5 million or more"
    ("LIB-065", {}, "ppc", {"9": "PASS", "10": "FAIL"}),
    # PC 9 with Coverage A $1.5-3 million, or any PC 10: within 15 miles of a responding fire department
    ("LIB-068", {"ppc": "10"}, "fire_station_miles", {"15": "PASS", "15.1": "FAIL"}),
    ("LIB-068", {"ppc": "9", "fire_station_miles": "20"}, "dwelling_amount",
     {1499999: "N/A", 1500000: "FAIL", 3000000: "FAIL", 3000001: "N/A"}),
    *[(rid, {"ppc": "9"}, "dwelling_amount", {1499999: "N/A", 1500000: "OPEN", 3000000: "OPEN"})
      for rid in ("LIB-069", "LIB-070", "LIB-071", "LIB-072")],
    ("ORI-050", {}, "year_built", {1899: "FAIL", 1900: "PASS"}),                               # "built before 1900"
    ("ORI-102", {}, "dwelling_amount", {349999: "FAIL", 350000: "PASS", 2000000: "PASS", 2000001: "FAIL"}),
    *[(rid, {}, "dwelling_amount", {149999: "FAIL", 150000: "PASS", 2000000: "PASS", 2000001: "FAIL"})
      for rid in ("SBS-001", "STO-002")],
    ("SLL-002", {}, "dwelling_amount", {124999: "FAIL", 125000: "PASS", 2000000: "PASS", 2000001: "FAIL"}),
    *[(rid, {}, "year_built", {age(100): "PASS", age(101): "OPEN"}) for rid in ("SBS-003", "STO-010")],
    *[(rid, {}, "roof_age", {30: "PASS", 31: "FAIL"}) for rid in ("SBS-005", "STO-012")],     # "older than 30 years"
    # "Roofs older than 25 years" (shingles, light metal, built-up, wood); 40 for standing seam metal, tile, slate
    ("SLL-015", {"roof_type": "Composition Shingle"}, "roof_age", {25: "PASS", 26: "FAIL"}),
    ("SLL-015", {"roof_type": "Tile"}, "roof_age", {40: "PASS", 41: "FAIL"}),
    ("SLL-015", {"roof_type": "Metal"}, "roof_age", {25: "PASS", 26: "OPEN", 41: "FAIL"}),
    ("SLL-054", {}, "year_built", {1949: "FAIL", 1950: "PASS"}),                               # "1950 or newer"
    ("SLL-056", {}, "ppc", {"8": "PASS", "9": "FAIL"}),                                        # "class 9 or 10"
    money("TWI-002", 2000000, "max"),
    ("TWI-014", {}, "year_built", {1979: "OPEN", 1980: "N/A"}),                                # "built before 1980"
    ("TRV-032", {}, "dwelling_amount", {1499999: "N/A", 1500000: "OPEN"}),                     # "$1,500,000 or more"
    ("TRV-033", {"occupancy_type": "Seasonal"}, "dwelling_amount", {499999: "N/A", 500000: "OPEN"}),
    ("TRV-073", {"occupancy_type": "Secondary Home"}, "dwelling_amount", {499999: "N/A", 500000: "OPEN"}),
    # "more than 7 road miles from the first responding fire department": a stated distance decides
    ("TRV-036", {"ppc": "N/A"}, "fire_station_miles", {"7": "PASS", "7.1": "FAIL"}),
    ("TRV-036", {"ppc": "3"}, "fire_station_miles", {"": "PASS"}),
    ("TRV-039", {"occupancy_type": "Seasonal"}, "ppc", {"8": "N/A", "9": "OPEN"}),             # "class 9, 10 ..."
    ("TRV-044", {}, "roof_age", {10: "N/A", 11: "NOTE"}),                                      # not replaced in 10 years
    ("TRV-045", {}, "roof_age", {15: "N/A", 16: "NOTE"}),
    ("TRV-046", {}, "roof_age", {25: "PASS", 26: "NOTE"}),                                     # cure: questionnaire
    money("TRV-074", 2000000, "or_more_refers"),                                               # "$2,000,000 or more"
    money("TRV-075", 500000, "or_more_refers", {"dwelling_type": "Condo"}),
    ("TRV-082", {"coastal_tier": "Tier 2"}, "year_built", {1999: "OPEN", 2000: "PASS"}),       # "unless built in 2000 or newer"
    ("TRV-083", {"coastal_tier": "Tier 2"}, "dwelling_amount", {1000000: "PASS", 1000001: "OPEN"}),
]

# ---- Round 30 step 1: "less than 50 miles from the primary residence" (the new distance question)
CASES += [(rid, {"occupancy_type": "Seasonal"}, "primary_home_miles", {"49.9": "FAIL", "50": "PASS", "": "OPEN"})
          for rid in ("SWY-007", "SBS-027")]

NUMERIC = re.compile(r"\b\w+ (?:<=|>=|<|>|between)\s+[\d.]|\b\w+ ==\s*\d")


def r30_label(rid, pd, values_out):
    """CHANGED DELIBERATELY (round 30 step 2, 2026-10-08; Liam's decision 2: a fact the form never asks
    is a "Confirm:" note, never a hold). A row that APPLIES and is open only on never-asked facts --
    no blank form field in its gate or test -- is now NOTE where these cases said OPEN. The boundary
    values themselves (where an outcome switches) are unchanged; the rule is pinned with literals in
    test_confirm_not_hold.py. A blank form field's OPEN stays OPEN, and so does every row Liam decided by
    name (rules_evaluator.HOLD_BY_DECISION: the FPC tables and Chubb's coastal sub-territories)."""
    m = ev._map()[rid]
    if "FACT(" not in m["test"] + m["gate"] or rid in ev.HOLD_BY_DECISION:   # (c): still holds
        return values_out
    out = {}
    for v, want in values_out.items():
        if want == "OPEN":
            f = ev.facts(dict(pd(v)))
            gate, gu = ev.evaluate_expr(m["gate"] or "always", f)
            unknown = list(gu if gate is None else []) + [u for t in m["test"].split("||")
                                                          for u in ev.evaluate_expr(t, f)[1]]
            if unknown and not any(u in f for u in unknown) and "||" not in m["test"]:
                want = "NOTE"
        out[v] = want
    return out


def _outcome(rid, base, field, value):
    pd = dict(BASE, **base)
    pd[field] = value
    return ev.evaluate_row(ev._map()[rid], ev.facts(pd))[0]


@pytest.mark.parametrize("rid,base,field,values", CASES, ids=[f"{c[0]}:{c[2]}" for c in CASES])
def test_boundary(rid, base, field, values):
    got = {v: _outcome(rid, base, field, v) for v in values}
    assert got == r30_label(rid, lambda v: {**BASE, **base, field: v}, values)


def test_every_numeric_map_line_has_a_boundary_case():
    # round 29 step 8: the remaining batch's cases live in test_remaining_batch_boundaries.py
    from test_remaining_batch_boundaries import CASES as REMAINING
    covered = {c[0] for c in CASES + REMAINING}
    numeric = {rid for rid, m in ev._map().items()
               if m["field"] != "NONE" and NUMERIC.search(m["test"] + " " + m["gate"])}
    assert sorted(numeric - covered) == []
