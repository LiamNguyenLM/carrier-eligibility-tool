"""The rules-table pilot (round 25, Liam 2026-10-03/04): decide a carrier's
structured rule rows from the form, in code, for the six pilot carriers.

Data (committed, see the header line of each file):
  rules_data/carrier_rules_pilot_v5.csv   the rows (pilot workbook version 5)
  rules_data/rule_field_map.csv           one map line per deciding row
  rules_data/RULE_FIELD_MAP.md            the expression grammar and the
                                          guide-word -> form-option table
  rules_data/carrier_rules_sage_batch_v2.csv,
  rules_data/sage_batch_field_map.csv     the Sage batch (round 27, Liam's
                                          decision 4): read only when
                                          eligibility_check.RULES_SAGE_BATCH
                                          is on (v2: Claude's review, 2026-10-07)
Measured in rounds 23-24 on branches structured-rules-test / -eval
(experiments/STRUCTURED_RULES_EVAL_RESULTS.md there); this is condition C2.

Three-valued logic: true, false, unknown (None). A blank optional field, PPC
"N/A", plumbing "Unknown"/"Other", an unticked pool box and FACT(...) are
unknown. Row outcomes:
  SKIP  a topic the row needs is unchecked (round 21)
  N/A   the gate is false
  PASS  every reading of the test is true
  FAIL  every reading is false, gate true -> the row's effect
  OPEN  unknown, or the readings disagree (AMBIGUOUS): the model judges it
  NOTE  never a hold:
          - EVALUATE_CURE_IS_INSPECTION rows that FAIL or are OPEN: the cure
            is an inspection (round 24);
          - decision 1 (Liam, 2026-10-03): a row left open only because
            Coverage A or County is blank -- the rule is shown, "confirm".
            (The Sage county hold and the CHUBB Coverage A hold are separate
            pipeline checks and still fire.)
  NONE  the form has no field for the row: an "Also confirm" note
Rows that are CONDITION_STANDARD (decision 2) are "Also confirm" notes too.
IGNORE_INSPECTION and NOT_ELIGIBILITY rows are never used.

Carrier, from the code alone: any FAIL DECLINES -> INELIGIBLE; else FAIL
REFERS_TO_UW -> REFER; else FAIL CONDITION -> REFER; else OPEN ->
undecided (the model is asked); else ELIGIBLE.
"""
import csv
import datetime
import json
import os
import re

import hold_guard
import intake_fields
from structured_rules import sage_county_in_territory

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_CSV = os.path.join(HERE, "rules_data", "carrier_rules_pilot_v5.csv")
MAP_CSV = os.path.join(HERE, "rules_data", "rule_field_map.csv")
# Round 27 step 6 (Liam's decision 4, 2026-10-06): the Sage batch, read only
# when eligibility_check.RULES_SAGE_BATCH is on. Not yet reviewed.
SAGE_BATCH_RULES_CSV = os.path.join(HERE, "rules_data", "carrier_rules_sage_batch_v2.csv")
SAGE_BATCH_MAP_CSV = os.path.join(HERE, "rules_data", "sage_batch_field_map.csv")
# Round 29 step 7 (2026-10-08): the HO3 batch, read only when eligibility_check.RULES_HO3_BATCH is on.
HO3_BATCH_RULES_CSV = os.path.join(HERE, "rules_data", "carrier_rules_ho3_batch_v1.csv")
HO3_BATCH_MAP_CSV = os.path.join(HERE, "rules_data", "ho3_batch_field_map.csv")
# Round 29 step 8 (2026-10-08): the remaining (dwelling fire) batch, read only when
# eligibility_check.RULES_DP_BATCH is on.
DP_BATCH_RULES_CSV = os.path.join(HERE, "rules_data", "carrier_rules_remaining_v1.csv")
DP_BATCH_MAP_CSV = os.path.join(HERE, "rules_data", "remaining_batch_field_map.csv")
# Round 39 step 1 (2026-10-13): The Hartford HO3, its own batch, switched by the HO3 batch's flag
# (eligibility_check.RULES_BATCH_SWITCHES: no new Railway variable).
HARTFORD_RULES_CSV = os.path.join(HERE, "rules_data", "carrier_rules_hartford_v1.csv")
HARTFORD_MAP_CSV = os.path.join(HERE, "rules_data", "hartford_field_map.csv")
# Round 40 step 2 (Liam, 2026-10-16): the right NatGen Custom360 HO3 and SageSure Occidental HO3 guides, each its own
# batch -- NatGen on the HO3 batch's switch, Occidental on the Sage batch's (no new Railway variable).
NATGEN_C360_RULES_CSV = os.path.join(HERE, "rules_data", "carrier_rules_natgen_c360_ho3_v1.csv")
NATGEN_C360_MAP_CSV = os.path.join(HERE, "rules_data", "natgen_c360_field_map.csv")
OCCIDENTAL_RULES_CSV = os.path.join(HERE, "rules_data", "carrier_rules_occidental_ho3_v1.csv")
OCCIDENTAL_MAP_CSV = os.path.join(HERE, "rules_data", "occidental_field_map.csv")
# Round 39 (Liam's decision 2, 2026-10-12): CFIG's own experience -- rules a carrier's guide does not state. One file,
# each row both a rule and its map line, read with the rows of the carrier it names (rules_data/cfig_knowledge.csv).
CFIG_KNOWLEDGE_CSV = os.path.join(HERE, "rules_data", "cfig_knowledge.csv")

# workbook carrier name -> pipeline carrier
PILOT_CARRIERS = {
    "Allied Trust HO3": "Allied_Trust_HO3",
    "Sage Auros HO3": "Sage_-_Auros_HO3",
    "Chubb HO": "CHUBB_HO_-_05.22.2026",
    "Mercury HO3": "Mercury_HO3_-_01.01.2026",
    "Progressive HO3": "Progressive_HO3_-_04.01.2026",
    "Swyfft Benchmark (Admitted) HO3": "Swyfft_-_Benchmark_(Admitted)_HO3",
}
SAGE_BATCH_CARRIERS = {
    "Sage SURE HO-3": "Sage_-_SURE_HO-3_-_01.31.2026",
    "Sage SafePort HO-3": "Sage_-_SafePort_HO-3_-_01.31.2026",
    "Sage Wilshire HO3": "Sage_-_Wilshire_HO3_-_12.02.2025",
    "Sage Trium Lloyd's HO3/HO5": "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026",
    "Sage Markel HO3": "Sage_-_Markel_HO3",
    "Sage Vave HO3": "Sage_-_Vave_HO3_-_07.01.2026",
}
HO3_BATCH_CARRIERS = {
    "ARI HOA / HOA Plus": "ARI_(HOA+)",
    "ARI HOB": "ARI_(HOB)",
    "Foremost Choice Homeowners": "Foremost_DP3_and_HO3_-_07.01.2026",
    "HOAIC HO3": "HOAIC_-_TX-HOMEOWNERS-0326_HO3",
    "Liberty Mutual / Safeco HO3": "Liberty_Mutual_HO3_-_02.21.2026",
    "Orion180 Flex HO3": "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3",
    "Swyfft Benchmark (Surplus) HO3": "Swyfft_-_Benchmark_(Surplus)_HO3",
    "Swyfft Lloyd's (Surplus) HO3": "Swyfft_-_Lloyds_(Surplus)_HO3",
    "Swyfft Topa (Surplus) HO3": "Swyfft_-_Topa_(Surplus)_HO3",
    "TWICO HO3": "TWICO_HO3",
    "Travelers Quantum Home 2.0": "Travelers_HO3_-_06.12.2026",
}
HARTFORD_CARRIERS = {"The Hartford HO3": "The_Hartford_HO3_-_07.09.2026"}
NATGEN_C360_CARRIERS = {"NatGen Custom360 HO3": "NatGen_Custom360_HO3_-_09.02.2026"}
OCCIDENTAL_CARRIERS = {"Sage Occidental HO3": "Sage_-_Occidental_HO3_-_12.02.2025"}
# An owner's own home (round 29 decision 2): the occupancies a homeowners program sees.
OWNERS_HOMES = ("Owner Occupied", "Seasonal", "Secondary Home")
# The remaining batch (round 29 step 8). NatGen Premier Dwelling Fire (NPD) is not here: it is
# closed to new business, and eligibility_check.CLOSED_PROGRAMS decides it as it does the HO3.
DP_BATCH_CARRIERS = {
    "Centauri DP3": "Centauri_-_DP3_-_11.16.2022",
    "Centauri HO3 (scanned, OCR)": "Centauri_-_HO3_-_05.01.2026",
    "HOAIC Texas Dwelling (TDP3)": "HOAIC_-_DP_Guide_DP3",
    "Liberty Mutual / Safeco Landlord DP3": "Liberty_Mutual_DP3_-_02.21.2026",
    "NatGen Custom360 Landlord": "NatGen_Custom360_DP3_-_06.25.2026",
    "Progressive DP3": "Progressive_DP3_-_10.01.2024",
    "Progressive HO6 (condo)": "Progressive_HO6_-_10.01.2025",
    "Sage Markel DP3": "Sage_-_Markel_DP3",
    "Sage Occidental DP3": "Sage_-_Occidental_DP3",
    "Sage SURE DP3": "Sage_-_SURE_DP-3_-_01.31.2026",
    "Sage SafePort DP3": "Sage_-_SafePort_DP-3_-_01.31.2026",
    "Sage Vave DP3": "Sage_-_Vave_DP3_-_07.01.2026",
    "Steadily DP3": "Steadily_Underwriting_Guidelines_DP3",
    "Foremost Dwelling Fire (TDP-3)": "Foremost_DP3_and_HO3_-_07.01.2026",
}
# A landlord's check (Foremost's one guide holds both programs; the occupancy tells them apart).
NOT_OWNERS_HOMES = ("Tenant Occupied", "Vacant")
# Rules the Foremost guide states once for both programs: the HO3 batch holds them as FOR rows
# marked "All use types (shared Dwelling Fire and Homeowners rule)" or "(all programs)", and
# the FOD rows leave them out on purpose. A Foremost dwelling-fire check reads them too, except
# where an FOD row already decides the same fact (one failing row per fact).
FOREMOST_SHARED_DECIDED_BY_FOD = {"FOR-012": "FOD-020", "FOR-074": "FOD-055", "FOR-076": "FOD-055"}


def _foremost_shared(row):
    aw = row["Applies when"]
    return ((aw.startswith("All use types") or "(all programs)" in aw)
            and row["Rule ID"] not in FOREMOST_SHARED_DECIDED_BY_FOD)

# The batch registry (round 29 step 7): one entry per rules-table batch. "scope" is for a
# pipeline carrier whose one guide holds two programs (Foremost: homeowners and dwelling
# fire): {workbook carrier: the occupancies its rows apply to}. A further batch is one entry
# here plus its switch in eligibility_check.RULES_BATCH_SWITCHES.
BATCHES = {
    "pilot": {"rules": RULES_CSV, "map": MAP_CSV, "carriers": PILOT_CARRIERS},
    "sage": {"rules": SAGE_BATCH_RULES_CSV, "map": SAGE_BATCH_MAP_CSV, "carriers": SAGE_BATCH_CARRIERS},
    "ho3": {"rules": HO3_BATCH_RULES_CSV, "map": HO3_BATCH_MAP_CSV, "carriers": HO3_BATCH_CARRIERS,
            "scope": {"Foremost Choice Homeowners": OWNERS_HOMES}},
    "dp": {"rules": DP_BATCH_RULES_CSV, "map": DP_BATCH_MAP_CSV, "carriers": DP_BATCH_CARRIERS,
           "scope": {"Foremost Dwelling Fire (TDP-3)": NOT_OWNERS_HOMES},
           # workbook carrier -> (the other workbook carrier whose rows it also reads, which of them)
           "shares": {"Foremost Dwelling Fire (TDP-3)": ("Foremost Choice Homeowners", _foremost_shared)}},
    # Round 39: the HO3 and its tenant-occupied HO3 (Rental Property Protection Plus) in one table; the RPP+ rows are
    # gated on a tenant-occupied home (rules_data/build_hartford_map.py)
    "hartford": {"rules": HARTFORD_RULES_CSV, "map": HARTFORD_MAP_CSV, "carriers": HARTFORD_CARRIERS},
    # Round 40 step 2: rules_data/build_natgen_c360_map.py, rules_data/build_occidental_map.py
    "natgen_c360": {"rules": NATGEN_C360_RULES_CSV, "map": NATGEN_C360_MAP_CSV, "carriers": NATGEN_C360_CARRIERS},
    "occidental": {"rules": OCCIDENTAL_RULES_CSV, "map": OCCIDENTAL_MAP_CSV, "carriers": OCCIDENTAL_CARRIERS},
}
WB_TO_CANON = {wb: canon for b in BATCHES.values() for wb, canon in b["carriers"].items()}
CANON_TO_WB = {}
for _wb, _canon in WB_TO_CANON.items():
    CANON_TO_WB.setdefault(_canon, _wb)        # a two-program carrier's first workbook name; see rules_table_wb

DECIDING = ("EVALUATE", "EVALUATE_CURE_IS_INSPECTION")
FIELD_TOPIC = {   # map field -> round 21 topic (always-on fields -> None)
    "ppc": "ppc", "coastal_tier": "coastal", "year_built": "home_age", "roof_age": "roof_age",
    "roof_type": "roof_type", "roof_shape": "roof_shape", "construction_type": "construction",
    "plumbing_type": "plumbing", "swimming_pool": "pool", "pool_accessories": "pool",
    "pool_fence_4ft": "pool", "pool_gate_locking": "pool", "has_dogs": "dogs", "aggressive_breed": "dogs", "dog_breeds": "dogs", "trust_type": None,
    "solar_type": "solar", "solar_tesla": "solar", "harris_east_146": "county",
    "solar_panels": "solar", "county": "county", "zip": "county", "dwelling_amount": "dwelling_amount",
    "occupancy_type": None, "ownership_type": None, "dwelling_type": None,
    "fire_station_miles": "ppc", "hydrant_1000ft": "ppc",     # round 26, decision B
    "primary_home_carrier": None, "primary_home_miles": None,  # round 30 step 1 (with occupancy)
    "rental_units_total": None, "rental_term": None,           # round 39: asked for a tenant-occupied home
    "units_in_building": None,                                 # round 39 step 4: asked for a House
}
# Round 30 step 2, class (c): rows Liam decided by name stay HOLDS even when they are open only on
# a fact the form never asks.
# - The FPC tables (Liam, 2026-10-06, re-affirmed 2026-10-08): with the band B or C -- distance blank
#   OR known -- the visibility / central-alarm / year-round-access / rentals / fire-loss conditions
#   hold, as the batch-OFF path (structured_rules.sage_fpc_with_distance) does.
# - Chubb's coastal sub-territories (with the CHUBB holds, 2026-10-08): the address decides.
FPC_TABLE_HOLDS = (
    "SAG-073", "SAG-074", "SAG-075", "SAG-076",                                  # pilot: Auros
    "SUR-111", "SUR-112", "SUR-113", "SUR-114", "SUR-117",                       # Sage batch v2
    "SFP-119", "SFP-120", "SFP-121", "SFP-122", "SFP-125",
    "WIL-116", "WIL-117", "WIL-118", "WIL-119", "WIL-122", "WIL-123",
    "TRI-020", "TRI-088", "TRI-089", "TRI-090", "TRI-091",
    "OCC-093", "OCC-094", "OCC-095", "OCC-096",                                  # round 40: Occidental HO3
    "ODP-110", "ODP-111", "ODP-112", "ODP-113", "ODP-115",                       # remaining (DP) batch
    "SDP-078", "SDP-079", "SDP-082", "FDP-105", "FDP-111")
CHUBB_TERRITORY_HOLDS = ("CHU-043", "CHU-044", "CHU-047")
HOLD_BY_DECISION = {**{rid: "Sage FPC table (Liam, 2026-10-06 / 2026-10-08)" for rid in FPC_TABLE_HOLDS},
                    **{rid: "Chubb coastal sub-territory (Liam, 2026-10-08)" for rid in CHUBB_TERRITORY_HOLDS}}
# Decision 1: an OPEN that rests only on these blank fields is a NOTE.
# Round 35 step 6: the Harris east-of-146 answer is part of the county -- blank (no Harris county) or Unknown is a
# confirm note as a blank county is. Found by the live check: OWNERSHIP_BASE (no county) held ARI HOB on ARB-005.
BLANK_IS_NOTE = {"dwelling_amount", "county", "zip", "sage_territory", "south_of_31", "harris_east_146"}
# Round 37 step 4 (Liam, 2026-10-10): the losses and electrical questions. Blank or Unknown is a "Confirm:" note,
# never a hold -- alone, and also when the row is open on a FACT besides.
CONFIRM_FIELDS = {"losses_5yr", "losses_3yr", "loss_types", "electrical"}
# Round 39 step 1 (Liam, 2026-10-12): the rental questions for a tenant-occupied home; blank or Unknown is a confirm.
CONFIRM_FIELDS |= {"rental_units_total", "rental_term", "units_in_building"}
BLANK_IS_NOTE = BLANK_IS_NOTE | CONFIRM_FIELDS
BLANK_LABEL = {"dwelling_amount": "Coverage A", "losses_5yr": "losses", "losses_3yr": "losses", "loss_types": "losses",
               "electrical": "electrical", "rental_units_total": "rental units owned", "rental_term": "rental term",
               "units_in_building": "units in the building"}


# --------------------------------------------------------------------------- data
def _read_csv(path):
    with open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(line for line in fh if not line.startswith("#")))


_CACHE = {}


def load_rules():
    if "rules" not in _CACHE:
        _CACHE["rules"] = {r["Rule ID"]: r for r in _read_csv(RULES_CSV)}
    return _CACHE["rules"]


def load_map():
    if "map" not in _CACHE:
        _CACHE["map"] = _with_requirement_outcomes({m["row_id"]: m for m in _read_csv(MAP_CSV)})
    return _CACHE["map"]


def load_batch_rules():
    if "batch_rules" not in _CACHE:
        _CACHE["batch_rules"] = {r["Rule ID"]: r for r in _read_csv(SAGE_BATCH_RULES_CSV)}
    return _CACHE["batch_rules"]


def load_batch_map():
    if "batch_map" not in _CACHE:
        _CACHE["batch_map"] = _with_requirement_outcomes({m["row_id"]: m for m in _read_csv(SAGE_BATCH_MAP_CSV)})
    return _CACHE["batch_map"]


# Round 31 step 4 (Liam, 2026-10-08, decision 2): a requirement row the form shows is NOT met reads
# Ineligible, unless the row's own guide text names an underwriting / referral / approval path (then
# Refer). Decided row by row; the words that decided each are kept here and listed in handoff.md.
# Only the map line's outcome changes: unknown / blank still holds or is a confirm note, as before.
_UNACCEPTABLE_CHUBB = "Secondary locations where Chubb does not write the primary residence are unacceptable."
_TRUST_OCCUPIED = "eligible only when the trustee, grantor, or beneficiary resides at the residence (no path named)"
_FPC_ALL_CRITERIA = "Risk is eligible only if all of the following criteria are met (no path named)"
_POOL_NO_PATH = "Must have pool cage or 4' permanent fence ... with self-latching gate (no path named)"
REQUIREMENT_OUTCOMES = {
    "CHU-004": ("DECLINES", _UNACCEPTABLE_CHUBB),
    "CHU-045": ("DECLINES", _UNACCEPTABLE_CHUBB),
    "CHU-046": ("DECLINES", _UNACCEPTABLE_CHUBB),
    "SAG-019": ("DECLINES", "Residence Held in Trust if the residence is occupied by the trustee, the grantor ... "
                            "(no path named)"),
    "SUR-019": ("DECLINES", _TRUST_OCCUPIED), "SFP-019": ("DECLINES", _TRUST_OCCUPIED),
    "WIL-019": ("DECLINES", _TRUST_OCCUPIED), "TRI-023": ("DECLINES", _TRUST_OCCUPIED),
    "VAV-014": ("DECLINES", _TRUST_OCCUPIED), "VDP-062": ("DECLINES", _TRUST_OCCUPIED),
    "OCC-042": ("DECLINES", _TRUST_OCCUPIED),                                   # round 40, as SUR-019
    # round 40: "Secondary/seasonal homes are eligible when the primary residence is insured by National General or
    # an affiliate company" (p.6) -- no path named
    "NC3-036": ("DECLINES", "Secondary/seasonal homes are eligible when the primary residence is insured by "
                            "National General (no path named)"),
    # round 40 step 3b (the second reader): "Trusts are not to be listed as named insured but can be added as an
    # additional insured if ..." (p.3) and "Properties in flood zones A and V without an active flood policy" (p.16,
    # Ineligible Exposures): no path named
    "NC3-007": ("DECLINES", "Trusts ... can be added as an additional insured if the guarantor, the trustee, and the "
                            "occupant of the home are the same individual (no path named)"),
    "NC3-158": ("DECLINES", "Ineligible Exposures: Properties in flood zones A and V without an active flood policy "
                            "(no path named)"),
    # round 41 A2 (Liam, 2026-10-17): "Pools are fenced in with self-locking gate"; the only approval path is "Rural homes
    # may be acceptable without a fence ... with prior underwriting approval", and the form does not ask rural (no
    # question added): Not eligible, the reason naming the rural path (REASON_SUFFIX). Was: CONDITION (Refer).
    "NC3-084": ("DECLINES", "Pools are fenced in with self-locking gate; rural homes only may be approved (p.8)"),
    "CDP-072": ("DECLINES", "The home is tenant occupied (one of four conditions, all required; underwriting "
                            "approval is needed in addition, not instead)"),
    "PRO-051": ("REFERS_TO_UW", "... or approved alternate enclosure"),
    # round 35 step 2: ALL-093, the bullet before it, allows "an underwriting approved alternate enclosure", and
    # ALL-094's own exception reads "Underwriting may approve (see preceding bullet)": an underwriting path
    "ALL-094": ("REFERS_TO_UW", "... or an underwriting approved alternate enclosure (ALL-093); Underwriting may "
                                "approve"),
    # Round 38b (Liam, 2026-10-12): Centauri DP3 lists "Dwellings having unprotected swimming pools" under "PROPERTY -
    # Ineligible" and names no underwriting path ("alternate approved enclosure" is a kind of enclosure, not a
    # referral; the next item, existing damage, does say "exceptions may be approved by underwriting"). Was REFERS_TO_UW.
    "CDP-053": ("DECLINES", "PROPERTY - Ineligible: Dwellings having unprotected swimming pools (no path named)"),
    "PDP-103": ("REFERS_TO_UW", "... or alternate approved enclosure"),
    "SWY-035": ("DECLINES", _POOL_NO_PATH), "SBS-008": ("DECLINES", _POOL_NO_PATH),
    "SLL-003": ("DECLINES", _POOL_NO_PATH), "STO-004": ("DECLINES", _POOL_NO_PATH),
    "ARA-025": ("DECLINES", "Homes with swimming pools ... that are not properly secured (listed under "
                            "INELIGIBLE RISKS; no path named)"),
    "FOR-053": ("DECLINES", "Properties with pools ... must have a fence minimum four feet high ... AND a "
                            "self-locking gate (Unacceptable Liability Characteristics; no path named)"),
    "NCD-104": ("DECLINES", "Pools are fenced in with self-locking gate (no path named)"),
    **{rid: ("DECLINES", _FPC_ALL_CRITERIA) for rid in (
        "SAG-075", "SAG-076", "SAG-078", "SUR-113", "SUR-114", "SUR-116", "SUR-117", "SFP-121", "SFP-122",
        "SFP-124", "SFP-125", "WIL-118", "WIL-119", "WIL-121", "WIL-122", "TRI-019", "TRI-020", "TRI-035",
        "TRI-090", "TRI-091", "ODP-114", "ODP-115", "SDP-080",
        "OCC-095", "OCC-096",
        # round 41 A6 (Liam, 2026-10-17): Wilshire's "no prior fire losses" cell, in the same table as WIL-121 / 122
        "WIL-123")},                       # round 40: Occidental HO3 p.10, as SUR-113 / SUR-114
}
# Looked at and left as they are (a row's map outcome is unchanged), with the reason:
REQUIREMENT_UNCHANGED = {
    "ALL-093": "ALL-094 already refers an unfenced pool (one failing row per fact); boxes unticked hold",
    "ALL-019": "ALL-020 already declines anything but a single-family dwelling or townhouse unit (one row per fact)",
    "HDP-002": "proof of updates is never asked: it cannot fail on a form fact (a confirm note)",
    "VDP-042": "a gut rehab is never asked: it cannot fail on a form fact (a confirm note)",
    "SLL-007": "meeting local code is never asked: it cannot fail on a form fact (a confirm note)",
    **{rid: "the cure is a signed acknowledgement the form never asks: the form cannot show it unmet"
       for rid in ("SAG-067", "SUR-069", "SFP-070", "TRI-081", "FOR-062")},
}


def _with_requirement_outcomes(rows):
    """A map's lines with REQUIREMENT_OUTCOMES applied (every loader: pilot, Sage batch, the others)."""
    for rid, (outcome, _) in REQUIREMENT_OUTCOMES.items():
        if rid in rows and rows[rid]["outcome_if_fail"] != "NOTE":
            rows[rid]["outcome_if_fail"] = outcome
    return rows


def _load(kind, path):
    key = (kind, path)
    if key not in _CACHE:
        idx = "Rule ID" if kind == "rules" else "row_id"
        rows = {r[idx]: r for r in _read_csv(path)}
        _CACHE[key] = _with_requirement_outcomes(rows) if kind == "map" else rows
    return _CACHE[key]


def _rules():
    """Every row the evaluator can cite: the pilot's rows, then each batch's, in
    registry order (their ids never collide; a carrier only ever reads its own)."""
    if "all_rules" not in _CACHE:
        out = {**load_rules(), **load_batch_rules()}
        for name, b in BATCHES.items():
            if name not in ("pilot", "sage"):
                out.update(_load("rules", b["rules"]))
        out.update(_load("rules", CFIG_KNOWLEDGE_CSV))
        _CACHE["all_rules"] = out
    return _CACHE["all_rules"]


def _map():
    if "all_map" not in _CACHE:
        out = {**load_map(), **load_batch_map()}
        for name, b in BATCHES.items():
            if name not in ("pilot", "sage"):
                out.update(_load("map", b["map"]))
        out.update(_load("map", CFIG_KNOWLEDGE_CSV))
        _CACHE["all_map"] = out
    return _CACHE["all_map"]


# --------------------------------------------------------------------------- facts
def facts(pd, today=None):
    """The values the grammar reads, from a property_details dict."""
    year = (today or datetime.date.today()).year
    f = dict(pd)
    # Round 35 step 1 (Claude's map audit): the map lines compare "Tier 1" / "Tier 2" / "Tier 3". app.py
    # sends that prefix already; any caller passing the form's full label ("Tier 1 - Closest to coast")
    # gets it too, so no coastal line is ever N/A on the label's wording. "Not Coastal" stays as is.
    ct = str(pd.get("coastal_tier") or "").strip()
    if ct.lower().startswith("tier"):
        f["coastal_tier"] = ct.split(" - ")[0].strip().title()
    # Round 35 step 3a: the breeds on the property (None = no answer / Not sure / only the old toggle)
    f["dog_breeds"] = intake_fields.dog_breeds(pd)
    # Round 35 steps 3d-f: the follow-up answers, read only where their question is asked
    f["trust_type"] = intake_fields.answer(pd.get("trust_type")) if pd.get("ownership_type") == "Trust" else None
    f["solar_type"] = intake_fields.answer(pd.get("solar_type"))
    f["solar_tesla"] = intake_fields.answer(pd.get("solar_tesla"))
    # Round 37 step 4: the losses and electrical answers (None = blank or Unknown)
    f.update(intake_fields.loss_answers(pd, today))
    f["electrical"] = intake_fields.electrical_answer(pd)
    # Round 41 B2: a Harris home not known to be west of Hwy 146 (the answer Yes, Unknown or blank); False elsewhere
    f["harris_not_west_146"] = (intake_fields.normalize_county(pd.get("county")) == "Harris"
                                and intake_fields.answer(pd.get("harris_east_146")) != "No")
    f["harris_east_146"] = (intake_fields.answer(pd.get("harris_east_146"))
                            if intake_fields.normalize_county(pd.get("county")) == "Harris" else None)
    # Round 35 step 3b: an old saved "Metal" / "Flat/Built-Up" is unknown; "Wood Shake" is the wood option
    if "roof_type" in pd:
        f["roof_type"] = intake_fields.roof_type_answer(pd.get("roof_type"))
    yb = pd.get("year_built")
    f["home_age"] = year - int(yb) if yb not in (None, "") else None
    m = re.match(r"(\d+)", str(pd.get("ppc", "")).strip())
    f["ppc_num"] = int(m.group(1)) if m else None
    f["ppc_split"] = intake_fields.ppc_split_class(pd.get("ppc")) is not None     # round 41 A5: 1X-8X
    county = intake_fields.normalize_county(pd.get("county")) or None
    f["county"] = county
    t = sage_county_in_territory(county or "", intake_fields.COUNTY_MAX_LATITUDE, True)
    f["sage_territory"] = None if t == "UNKNOWN" else t
    # Round 28 step 3 (Sage batch v2): "a county located entirely south of 31 degrees North"
    lat = intake_fields.COUNTY_MAX_LATITUDE.get(county) if county else None
    f["south_of_31"] = None if lat is None else lat < 31.0
    f["dwelling_amount"] = intake_fields.parse_dwelling_amount(pd.get("dwelling_amount"))
    f["zip"] = intake_fields.parse_zip(pd.get("zip"))[0] or None
    f["dwelling_type"] = intake_fields.normalize_dwelling_type(pd.get("dwelling_type")) or None
    # Round 35 step 3c: an old saved "PEX" is PEX of unknown install year; Unknown / Other are unknown
    f["plumbing_type"] = intake_fields.plumbing_answer(pd.get("plumbing_type"))
    f["pex_2011"] = intake_fields.pex_2011(f["plumbing_type"], pd.get("year_built"))
    if f.get("ppc") in ("N/A", ""):
        f["ppc"] = None
    # Round 26 (decision B): blank / Unknown is unknown, never "no".
    f["fire_station_miles"] = intake_fields.parse_station_miles(pd.get("fire_station_miles"))
    f["hydrant_1000ft"] = intake_fields.hydrant_answer(pd.get("hydrant_1000ft"))
    # Round 29 step 7: "within N road miles of a fire station" (HO3 batch). A stated distance
    # decides; with none, ISO classes 1-9 are within 5 road miles; otherwise unknown.
    f["station_miles_iso"] = (f["fire_station_miles"] if f["fire_station_miles"] is not None
                              else 5.0 if f["ppc_num"] is not None and f["ppc_num"] <= 9 else None)
    # Round 30 step 1 (decision 1): asked only for a Seasonal / Secondary Home; blank / Unknown is unknown.
    f["primary_home_carrier"] = intake_fields.primary_home_carrier(pd.get("primary_home_carrier"))
    f["primary_home_miles"] = intake_fields.parse_primary_home_miles(pd.get("primary_home_miles"))
    # Round 39 step 1: asked only for a tenant-occupied home; blank / Unknown is unknown (a confirm: CONFIRM_FIELDS)
    f["rental_units_total"] = intake_fields.answer(pd.get("rental_units_total"))
    f["rental_term"] = intake_fields.answer(pd.get("rental_term"))
    # Round 39 step 4: asked only for a House; blank / Unknown is unknown (a confirm)
    house = intake_fields.normalize_dwelling_type(pd.get("dwelling_type")) == "House"
    f["units_in_building"] = intake_fields.answer(pd.get("units_in_building")) if house else None
    for box in ("pool_fence_4ft", "pool_gate_locking"):      # unticked = unknown, never "no"
        f[box] = True if intake_fields.pool_box(pd, box) else None
    return f


# --------------------------------------------------------------------------- grammar
_TOKEN = re.compile(r"\s*(\(|\)|\{[^}]*\}|FACT\([^)]*\)|==|!=|<=|>=|<|>|[^\s(){}=!<>]+)")


def _tokens(s):
    out, i, s = [], 0, s.strip()
    while i < len(s):
        m = _TOKEN.match(s, i)
        if not m:
            raise ValueError(f"cannot parse at {s[i:]!r}")
        out.append(m.group(1))
        i = m.end()
    return out


def _and(vals):
    if any(v is False for v in vals):
        return False
    return None if any(v is None for v in vals) else True


def _or(vals):
    if any(v is True for v in vals):
        return True
    return None if any(v is None for v in vals) else False


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class _Parser:
    def __init__(self, text, f):
        self.t, self.i, self.f, self.unknown = _tokens(text), 0, f, []

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def take(self):
        tok = self.t[self.i]
        self.i += 1
        return tok

    def parse(self):
        v = self.or_expr()
        if self.peek() is not None:
            raise ValueError(f"unexpected {self.peek()!r}")
        return v

    # Round 35 step 2: an unknown inside a part that is already decided (an "and" with a false term, an
    # "or" with a true one) cannot change the result, so it is dropped. Before, "(swimming_pool == Above
    # Ground - Fenced and pool_fence_4ft == True ...) or FACT(...)" kept the unticked fence box as an
    # unknown for an UNFENCED pool, and the row held on a form field instead of noting the unasked fact.
    def or_expr(self):
        mark = len(self.unknown)
        vals = [self.and_expr()]
        while self.peek() == "or":
            self.take()
            vals.append(self.and_expr())
        v = _or(vals)
        if v is not None:
            del self.unknown[mark:]
        return v

    def and_expr(self):
        mark = len(self.unknown)
        vals = [self.atom()]
        while self.peek() == "and":
            self.take()
            vals.append(self.atom())
        v = _and(vals)
        if v is not None:
            del self.unknown[mark:]
        return v

    def atom(self):
        tok = self.peek()
        if tok == "always":
            self.take()
            return True
        if tok == "not" and self.peek(1) != "in":
            self.take()
            v = self.atom()
            return None if v is None else (not v)
        if tok == "(":
            self.take()
            v = self.or_expr()
            if self.take() != ")":
                raise ValueError("missing )")
            return v
        if tok.startswith("FACT("):
            self.take()
            self.unknown.append(tok[5:-1])
            return None
        return self.comparison()

    def value_words(self):
        words = []
        while self.peek() not in (None, "and", "or", ")"):
            words.append(self.take())
        return " ".join(words)

    def comparison(self):
        name, op = self.take(), self.take()
        if op == "not" and self.peek() == "in":
            self.take()
            op = "not in"
        val = self.f.get(name, None)
        if op == "none_of":
            # Round 35 step 3a: a multi-answer field (the dog breeds) -- true when no picked value is in the set
            items = {x.strip() for x in self.take().strip("{}").split(",")}
            if val is None:
                self.unknown.append(name)
                return None
            return not (set(val) & items)
        if op in ("in", "not in"):
            items = {x.strip() for x in self.take().strip("{}").split(",")}
            if val is None:
                self.unknown.append(name)
                return None
            hit = str(val) in items
            return hit if op == "in" else not hit
        if op == "between":
            lo = self.take()
            if self.take() != "and":
                raise ValueError("between needs and")
            hi = self.take()
            v = _num(val)
            if v is None:
                self.unknown.append(name)
                return None
            return float(lo) <= v <= float(hi)
        rhs = self.value_words()
        if val is None:
            self.unknown.append(name)
            return None
        if op in ("==", "!="):
            if rhs in ("True", "False"):
                eq = (val is True) == (rhs == "True")
            else:
                a, b = _num(val), _num(rhs)
                eq = (a == b) if a is not None and b is not None else (str(val) == rhs)
            return eq if op == "==" else not eq
        a, b = _num(val), _num(rhs)
        if a is None or b is None:
            self.unknown.append(name)
            return None
        return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[op]


def evaluate_expr(text, f):
    """(value, [unknown names / facts]) for one reading."""
    p = _Parser(text, f)
    return p.parse(), p.unknown


# --------------------------------------------------------------------------- rows
def row_topics(m):
    if m["field"] == "NONE":
        return set()
    return {FIELD_TOPIC[x] for x in m["field"].split(";") if FIELD_TOPIC.get(x)}


def _open_fact_now(open_fact, unknown):
    """The row's open-fact text, without its "... if not given" parts once
    the form gives them (round 27: "station distance if not given" showed
    with the distance stated)."""
    parts = [p.strip() for p in (open_fact or "").split(";") if p.strip()]
    keep = []
    for p in parts:
        # Round 38 step 7 (self-audit F14, 2026-10-11): a bare "station distance" label is the same as "... if not
        # given" -- ODP-116 open only on a PPC of N/A read "needs to know ... station distance" with 5.9 miles entered
        if p == "station distance" and "fire_station_miles" not in unknown:
            continue
        if p.endswith("if not given"):
            fields = [f for w, f in (("station", "fire_station_miles"), ("hydrant", "hydrant_1000ft")) if w in p]
            if fields and not any(f in unknown for f in fields):
                continue
            # Round 38 step 1 (Liam, 2026-10-11): "station / hydrant distance" with the station distance given
            # names only what is still open -- the card's reason is built from this
            if len(fields) == 2 and not all(f in unknown for f in fields):
                p = ("station distance if not given" if "fire_station_miles" in unknown
                     else "hydrant within 1,000 ft if not given")
        keep.append(p)
    if any(u in ("ppc", "ppc_num") for u in unknown) and not re.search(r"\bppc\b|protection class|\bfpc\b",
                                                                      " ".join(keep), re.I):
        keep.append("the protection class (PPC)")          # the open fact the label did not name (F14)
    return "; ".join(keep)


# Round 39 step 0a (Liam): a held row names what it still needs by the form's own label, never by a field key
# ("Held: this guide needs to know plumbing_type" before). Every name facts() makes is here
# (verification/test_field_labels.py); a FACT(...) text is already words.
FIELD_LABELS = {
    "year_built": "Year Built", "home_age": "Year Built", "roof_age": "Roof Age", "roof_type": "Roof Type",
    "roof_shape": "Roof Shape", "construction_type": "Construction Type", "plumbing_type": "Plumbing Type",
    "pex_2011": "Plumbing Type (the PEX install year)", "occupancy_type": "Occupancy Type",
    "ownership_type": "Ownership Structure", "trust_type": "Trust type", "coastal_tier": "Coastal Tier",
    "swimming_pool": "Swimming Pool", "pool_accessories": "Pool Accessories",
    "pool_fence_4ft": "Fence confirmed 4 ft or higher", "pool_gate_locking": "Gate confirmed self-latching and lockable",
    "has_dogs": "Dogs on Premises", "aggressive_breed": "Breed(s) on the property",
    "dog_breeds": "Breed(s) on the property", "solar_panels": "Solar Panels", "solar_type": "Solar type",
    "solar_tesla": "Tesla equipment", "ppc": "PPC Number", "ppc_num": "PPC Number",
    "fire_station_miles": "Distance to fire station", "station_miles_iso": "Distance to fire station",
    "hydrant_1000ft": "Hydrant within 1,000 ft", "zip": "ZIP", "county": "County",
    "sage_territory": "County", "south_of_31": "County", "harris_east_146": "East of Highway 146",
    "dwelling_amount": "Coverage A", "dwelling_type": "Dwelling type",
    "primary_home_carrier": "Primary home insured with", "primary_home_miles": "Distance to the primary home",
    "losses_5yr": "Losses in the last 5 years", "losses_3yr": "Losses in the last 3 years",
    "loss_types": "Loss types", "loss_year": "Most recent loss year", "electrical": "Electrical",
    "rental_units_total": "Rental units the owner has in total", "rental_term": "Rented to",
    "units_in_building": "Units in the building",
}


def _named(unknown):
    """The unknowns as an agent reads them: a field by its form label (once), a FACT(...) as written."""
    return "; ".join(dict.fromkeys(FIELD_LABELS.get(u, u) for u in unknown))


def evaluate_row(m, f, checked=None):
    """(outcome, detail) for one map line."""
    if checked is not None and m["field"] != "NONE" and not row_topics(m) <= set(checked):
        return "SKIP", ""
    if m["field"] == "NONE":
        return "NONE", m["map_note"]
    gate, gate_unknown = evaluate_expr(m["gate"] or "always", f)
    if gate is False:
        return "N/A", ""
    readings = [evaluate_expr(t, f) for t in m["test"].split("||")]
    vals = [v for v, _ in readings]
    unknown = [u for _, us in readings for u in us] + (gate_unknown if gate is None else [])
    if all(v is True for v in vals):
        result = "PASS"
    elif all(v is False for v in vals) and gate is True:
        result = "FAIL"
    else:
        result = "OPEN"
    ambiguous = result == "OPEN" and len(vals) > 1 and None not in vals
    detail = ("ambiguous: " + (m["map_note"] or "the readings disagree")) if ambiguous else \
        _open_fact_now(m["open_fact"], unknown) or _named(unknown)
    if m["outcome_if_fail"] == "NOTE" and result in ("FAIL", "OPEN"):
        return "NOTE", "cure is an inspection (not checked)"
    # Decision 1: the row hinges on a blank Coverage A or County -- either the
    # whole unknown is that field, or the gate (which decides whether the row
    # applies at all) is unknown only because of it.
    blank = set(gate_unknown) if gate is None and gate_unknown and set(gate_unknown) <= BLANK_IS_NOTE \
        else (set(unknown) if unknown and set(unknown) <= BLANK_IS_NOTE else None)
    if result == "OPEN" and not ambiguous and blank:
        return "NOTE", "blank " + " / ".join(sorted({BLANK_LABEL.get(u, "County") for u in blank})) + "; confirm"
    if result == "FAIL" and m["outcome_if_fail"] == "UNKNOWN":
        return "OPEN", "the row's effect is UNKNOWN"
    # Round 30 step 2 (Liam, 2026-10-08, decision 2: the project rule, applied to the rules table):
    # a row open ONLY on facts the form never asks (FACT(...); never a blank form field, never two
    # readings that disagree, and no reading that fails) is a "Confirm:" note, never a hold. A blank
    # form field (the station distance, PPC N/A, plumbing Unknown, an unticked pool box, a blank
    # primary-home answer) still holds. Rows Liam decided by name (HOLD_BY_DECISION) still hold.
    if (result == "OPEN" and not ambiguous and unknown and False not in vals
            and all(u not in f or u in CONFIRM_FIELDS for u in unknown) and m["outcome_if_fail"] != "UNKNOWN"
            and m.get("row_id") not in HOLD_BY_DECISION):
        return "NOTE", "confirm: " + (_open_fact_now(m["open_fact"], unknown) or _named(unknown))
    return result, detail


def _page(r):
    try:
        return str(int(float(r["PDF page"])))
    except (TypeError, ValueError):
        return "?"


# Round 38b (Liam, 2026-10-12, finding F07): Chubb's tier tables repeat by region -- p.10 "Dallas/Fort Worth, Collin
# County & Rest of Northern counties", p.11 "Austin, San Antonio and surrounding counties, and East and South counties",
# p.12 "Coastal Areas" -- and p.14 lists each region's counties (Harris: territories 01A-C and 01E are coastal, 01D is
# Austin / East / South). A row the workbook cites at p.10 cites the county's own table.
def _county_names(text):
    return frozenset(" ".join(x.split()) for x in text.split(",") if x.strip())


CHUBB_COASTAL_COUNTIES = _county_names("""
    Aransas, Brazoria, Calhoun, Cameron, Chambers, Galveston, Harris, Jefferson, Kenedy, Kleberg, Matagorda,
    Nueces, Refugio, San Patricio, Willacy
""")
CHUBB_SOUTH_EAST_COUNTIES = _county_names("""
    Anderson, Angelina, Atascosa, Austin, Bandera, Bastrop, Bee, Bexar, Blanco, Brazos, Brooks, Burleson,
    Burnet, Caldwell, Cherokee, Colorado, Comal, De Witt, Dimmit, Duval, Edwards, Ellis, Falls, Fayette,
    Fort Bend, Freestone, Frio, Goliad, Gonzales, Gregg, Grimes, Guadalupe, Hardin, Harris, Hays, Henderson,
    Hidalgo, Houston, Jackson, Jasper, Jim Hogg, Jim Wells, Karnes, Kerr, Kinney, La Salle, Lavaca, Lee,
    Leon, Liberty, Limestone, Live Oak, Llano, Madison, Maverick, McMullen, Medina, Milam, Montgomery,
    Nacogdoches, Navarro, Newton, Orange, Panola, Polk, Real, Robertson, Rusk, Sabine, San Augustine, San
    Jacinto, Shelby, Smith, Starr, Travis, Trinity, Tyler, Uvalde, Val Verde, Victoria, Walker, Waller,
    Washington, Webb, Wharton, Williamson, Wilson, Zapata, Zavala
""")


def chubb_region_page(county):
    """The page of Chubb's tier table for this county: "10", "11", "12", "11-12" (Harris: by territory), or "10-12"
    when the county is not given."""
    key = lambda name: "".join(str(name or "").split()).lower()     # "De Witt" / "DeWitt", "McMullen" / "Mcmullen"
    c = key(intake_fields.normalize_county(county) or county)
    if not c:
        return "10-12"
    if c == "harris":
        return "11-12"
    if c in {key(x) for x in CHUBB_COASTAL_COUNTIES}:
        return "12"
    if c in {key(x) for x in CHUBB_SOUTH_EAST_COUNTIES}:
        return "11"
    return "10"


def citation(r, property_details=None):
    """The citation code attaches for a row: id + page + the workbook quote. property_details (round 38b): a Chubb
    tier-table row cites the county's region page."""
    if is_cfig(r):       # round 39: CFIG's experience, not the guide's words
        return f"{WB_TO_CANON[r['Carrier']]}: [{r['Rule ID']}] CFIG knowledge base: \"{r['Plain rule']}\""
    page = _page(r)
    if property_details is not None and r["Carrier"] == "Chubb HO" and str(page) == "10":
        page = chubb_region_page(property_details.get("county"))
    return f"{WB_TO_CANON[r['Carrier']]}: [{r['Rule ID']}] p.{page}: \"{r['Verbatim quote from guide']}\""


def is_cfig(r):
    """A row of the CFIG knowledge base (rules_data/cfig_knowledge.csv), not of a guide."""
    return r["Rule ID"].startswith("CFG-")


def evaluate_carrier(canon, pd, checked=None, wb=None):
    """{row_id: (outcome, detail)} for one rules-table carrier's deciding rows. wb: the workbook
    carrier (rules_table_wb picks it for a carrier whose guide holds two programs)."""
    rules, fmap = _rules(), _map()
    wb = wb or CANON_TO_WB[canon]
    f = facts(pd)
    if f.get("ppc_split") and wb in SPLIT_CLASS_AS:          # round 41 A5: the guide says how a split class rates
        f["ppc_num"] = SPLIT_CLASS_AS[wb]
        f["station_miles_iso"] = (f["fire_station_miles"] if f["fire_station_miles"] is not None
                                  else 5.0 if f["ppc_num"] <= 9 else None)
    out = {rid: evaluate_row(m, f, checked) for rid, m in fmap.items()
           if rules[rid]["Carrier"] == wb and rules[rid]["Tool handling"] in DECIDING}
    # round 29 step 8: rows another workbook carrier states for both programs (after the
    # carrier's own, so _wb_of still names this one)
    for b in BATCHES.values():
        other, pick = b.get("shares", {}).get(wb, (None, None))
        if other:
            out.update({rid: evaluate_row(m, f, checked) for rid, m in fmap.items()
                        if rules[rid]["Carrier"] == other and rules[rid]["Tool handling"] in DECIDING
                        and pick(rules[rid])})
    return out


# Round 41 A2 (Liam, 2026-10-17): a decline's reason that names the one way out the form does not ask about, in Liam's
# words (row id -> the clause added to the guide's rule).
REASON_SUFFIX = {"NC3-084": "unless the home is rural (underwriting may then approve)"}


# Round 41 A5 (Liam, 2026-10-17): the guides that name split classes, and how each rates 1X-8X (workbook carrier ->
# the protection class it reads). Read from every guide's text (round 41): NatGen Custom360 HO3 p.5 and Custom360
# Landlord (DP3) p.5 -- "*Includes all PC 9 or 1X - 8X variations". The Hartford, Mercury and HOAIC name only "10W"
# (with PC 10), which is not a form choice; no other guide mentions split classes.
SPLIT_CLASS_AS = {"NatGen Custom360 HO3": 9, "NatGen Custom360 Landlord": 9}


def split_class_item(wb, pd):
    """The confirm item for a split class (1X-8X) on a rules table whose guide does not mention split classes, or
    None (no split class, or a guide that rates them: SPLIT_CLASS_AS)."""
    n = intake_fields.ppc_split_class((pd or {}).get("ppc"))
    if n is None or wb is None or wb in SPLIT_CLASS_AS:
        return None
    x = str(pd.get("ppc")).strip().upper()
    return {"row": "", "category": "PROTECTION_CLASS", "effect": "", "kind": "not_asked",
            "rule": f"Split class ({x}): this guide does not mention split classes; its rules read PC {n}.",
            "say": f"Split class ({x}): check how this carrier rates it."}


def also_confirm(canon, outcomes):
    """The carrier's never-a-hold notes: NONE rows and CONDITION_STANDARD rows
    grouped by topic, then each NOTE row with its reason."""
    rules = _rules()
    wb = _wb_of(canon, outcomes)
    groups = {}
    for rid, (o, _) in outcomes.items():
        if o == "NONE":
            groups.setdefault(rules[rid]["Topic"], []).append(rid)
    for r in rules.values():
        if r["Carrier"] == wb and r["Tool handling"] == "CONDITION_STANDARD":
            groups.setdefault(r["Topic"], []).append(r["Rule ID"])
    # round 30 step 2: a never-asked fact reads "Confirm: <fact> ([row] <the guide's rule>)", so the
    # consequence is visible on the card
    notes = [f"Confirm: {d[len('confirm: '):]} ([{rid}] {rules[rid]['Plain rule']})" if d.startswith("confirm: ")
             else f"[{rid}] {rules[rid]['Plain rule']} ({d})" for rid, (o, d) in outcomes.items() if o == "NOTE"]
    if groups:
        notes.append("Also confirm (not asked by the form; never a hold): " + "; ".join(
            f"{t}: {', '.join(ids)}" for t, ids in sorted(groups.items())) + ".")
    return notes


# Round 39 (Liam, 2026-10-14): confirms whose wording Liam set. row -> the FACT(...) text of its map line; when the
# row is a confirm on exactly that fact, the card shows the text as written instead of its topic's question.
CARD_WORDING = {
    # round 41 B1 (Liam, 2026-10-17): mold claims too. (the confirm's FACT text, the words the card shows)
    "HAR-027": ("2 water losses: only acceptable if both were appliance-related or mold claims and remediated, with "
                "Hartford form PC-327 for appliance or PC-326 for mold; otherwise Not eligible",
                "2 water losses: only acceptable if both were appliance-related or mold claims and remediated, with Hartford form PC-327 (appliance) or PC-326 (mold); otherwise Not eligible"),
}


def confirm_items(canon, outcomes):
    """Round 37 step 1: also_confirm's rows as data, for the card's "Before you quote, confirm:" list
    (confirm_topics): [{row, category, effect, rule, kind}], kind "not_asked" (a NONE row, or a NOTE on a fact
    the form never asks), "blank" (a NOTE left by a blank field), "note" (another NOTE, e.g. an inspection
    cure) or "standard" (CONDITION_STANDARD)."""
    rules = _rules()
    wb = _wb_of(canon, outcomes)
    out = []
    for rid, (o, d) in outcomes.items():
        if o == "NONE" or (o == "NOTE" and d.startswith("confirm: ")):
            kind = "not_asked"
        elif o == "NOTE":
            kind = "blank" if d.startswith("blank ") else "note"
        else:
            continue
        r = rules[rid]
        item = {"row": rid, "category": r["Topic"], "effect": r["Effect"], "rule": r["Plain rule"], "kind": kind}
        say = CARD_WORDING.get(rid)
        when, shown = say if isinstance(say, tuple) else (say, say)      # round 41 B1: (the FACT's text, the card's)
        if say and d == "confirm: " + when:
            item["say"] = shown + "."            # the card shows it word for word (confirm_topics.card_items)
        out.append(item)
    for r in rules.values():
        if r["Carrier"] == wb and r["Tool handling"] == "CONDITION_STANDARD":
            out.append({"row": r["Rule ID"], "category": r["Topic"], "effect": r["Effect"], "rule": r["Plain rule"],
                        "kind": "standard"})
    return out


# Round 38b (Liam, 2026-10-12, finding F12): a decline / referral names the answer that fails the rule -- "County:
# Wheeler — Property must be in South Texas ...", not the rule alone. The map line's fields, as the form answered them.
_LOSS_FIELDS = ("losses_5yr", "losses_3yr", "loss_types", "loss_year")
_ANSWER_LABEL = {
    "roof_type": "Roof", "roof_shape": "Roof shape", "construction_type": "Construction", "plumbing_type": "Plumbing",
    "occupancy_type": "Occupancy", "ownership_type": "Owner", "trust_type": "Trust type", "county": "County",
    "coastal_tier": "Coastal tier", "ppc": "PPC", "hydrant_1000ft": "Hydrant within 1,000 ft",
    "dwelling_type": "Dwelling", "swimming_pool": "Pool", "pool_accessories": "Pool extras", "solar_type": "Solar",
    "primary_home_carrier": "Primary home with", "harris_east_146": "East of Hwy 146",
    "rental_units_total": "Rental units owned", "rental_term": "Rental term", "units_in_building": "Units",
}


def _answer_parts(field, pd):
    v = pd.get(field)
    if v in (None, "", [], "Unknown"):
        return []
    if field == "roof_age":
        return [f"Roof {v} yrs"]
    if field == "year_built":
        return [f"Built {v}"]
    if field == "fire_station_miles":
        return [f"Fire station {v} mi"]
    if field == "dwelling_amount":
        try:
            return [f"Coverage A ${int(v):,}"]
        except (TypeError, ValueError):
            return []
    if field in ("has_dogs", "dog_breeds"):
        breeds = [b for b in (pd.get("dog_breeds") or []) if b]
        return [("Dogs: " + ", ".join(breeds)) if breeds else ("Dogs: " + str(pd.get("has_dogs")))]
    if field in ("solar_panels",):
        return [f"Solar panels: {v}"]
    if field == "electrical":
        picked = [intake_fields.ELECTRICAL_LABELS.get(x, x) for x in (v if isinstance(v, list) else [v])]
        return ["Electrical: " + ", ".join(picked)]
    if field in _ANSWER_LABEL:
        shown = intake_fields.ROOF_LABELS.get(v, v) if field == "roof_type" else v
        return [f"{_ANSWER_LABEL[field]}: {shown}"]
    return []


def answer_phrase(fields, pd):
    """The answers behind a map line, e.g. "Roof: Slate" or "Losses: 2 in 5 yrs (water, theft), 1 in 3 yrs"."""
    parts, losses = [], False
    for field in [f for f in (fields or "").split(";") if f]:
        if field in _LOSS_FIELDS:
            losses = True
            continue
        for p in _answer_parts(field, pd):
            if p not in parts:
                parts.append(p)
    if losses:
        a = intake_fields.loss_answers(pd)
        if a["losses_5yr"] is not None:
            types = ", ".join(t.lower() for t in a["loss_types"] or [])
            s = f"Losses: {a['losses_5yr']} in 5 yrs" + (f" ({types})" if types else "")
            if a["losses_3yr"] is not None:
                s += f", {a['losses_3yr']} in 3 yrs"
            parts.insert(0, s)
    return "; ".join(parts)


def code_record(canon, outcomes, property_details=None):
    """The record when code decides alone. Returns (record, decided):
    decided is False when OPEN rows are left for the model. property_details (round 38b): each cited row's reason
    names the answers that fail it."""
    rules, fmap = _rules(), _map()
    fails = {e: [rid for rid, (o, _) in outcomes.items() if o == "FAIL" and fmap[rid]["outcome_if_fail"] == e]
             for e in ("DECLINES", "REFERS_TO_UW", "CONDITION")}
    opens = [rid for rid, (o, _) in outcomes.items() if o == "OPEN"]
    if fails["DECLINES"]:
        status, flaws, cited = "INELIGIBLE", len(fails["DECLINES"]), fails["DECLINES"]
    elif fails["REFERS_TO_UW"]:
        status, flaws, cited = "REFER", 0, fails["REFERS_TO_UW"]
    elif fails["CONDITION"]:
        status, flaws, cited = "REFER", 0, fails["CONDITION"]
    elif opens:
        status, flaws, cited = "INSUFFICIENT_INFORMATION", 0, []    # its reason: held_reason (below)
    else:
        status, flaws, cited = "ELIGIBLE", 0, []
    label = {"DECLINES": "declines", "REFERS_TO_UW": "refers to underwriting", "CONDITION": "condition not met"}
    def said(rid):
        answer = answer_phrase(fmap[rid]["field"], property_details) if property_details else ""
        rule = rules[rid]["Plain rule"]
        if rid in REASON_SUFFIX:                   # round 41 A2: a path Liam named, in his words
            rule = rule.rstrip(". ") + ", " + REASON_SUFFIX[rid] + "."
        return (answer + " — " if answer else "") + rule
    reasons = [f"[{rid}] {label[fmap[rid]['outcome_if_fail']]}: {said(rid)}" for rid in cited]
    npass = sum(1 for o, _ in outcomes.values() if o == "PASS")
    if not reasons:
        reasons = ([held_reason(outcomes, opens)] if status == "INSUFFICIENT_INFORMATION"   # round 37 follow-up 2
                   else [f"Rules table: {npass} rule(s) decided from the form pass; none fails."])
    open_items = [f"{outcomes[rid][1]} -- [{rid}] {rules[rid]['Plain rule']}" for rid in opens]
    rec = {"carrier": canon, "status": status, "flaw_count": flaws, "reasons": reasons,
           "citations": [citation(rules[rid], property_details) for rid in cited],
           "missing_info": open_items,
           "notes": "", "rules_table": True, "also_confirm": also_confirm(canon, outcomes),
           "confirm_items": confirm_items(canon, outcomes)}
    if status == "INELIGIBLE":
        # Round 26 step 2 (Liam, 2026-10-05): nothing still open can change a
        # decline, so the card lists none of it; the open rows stay here.
        rec["missing_info"] = []
        rec["diagnostics"] = {"open_rows": open_items}
    if cited:
        rec["decided_by_code"] = True
    return rec, not (opens and not cited)


# --------------------------------------------------------------------------- the model's part
PILOT_INSTRUCTION = (
    "RULE CHECK: for each carrier below, code has already checked the carrier's rules against PROPERTY "
    "DETAILS. Its results are facts. Judge only the rules listed under \"Not decided by code\": a rule that "
    "needs a fact PROPERTY DETAILS does not give makes the carrier INSUFFICIENT_INFORMATION; a fact that is "
    "given and breaks a rule decides by that rule's effect (DECLINES -> INELIGIBLE, REFERS_TO_UW or "
    "CONDITION -> REFER). Unknown is not a failure. Cite a rule by its row id only, e.g. \"[ALL-109]\": code "
    "adds the guide's own words, so never copy a rule's text into citations. Give exactly one record for each "
    "carrier listed below under \"(rule check)\", and no record for any other carrier. "
    # Round 37 follow-up 2 (Liam, 2026-10-11)
    "The form asks two optional questions: losses in the last 5 years (with their types and how many in the "
    "last 3 years) and the electrical system. When PROPERTY DETAILS gives no answer to one, that fact is "
    "unknown -- never say the form does not ask it.")


def _cell(v):
    return " ".join(str(v or "").split())


def _row_line(r, extra=""):
    value = " ".join(x for x in (_cell(r["Value"]), _cell(r["Unit"])) if x)
    # round 31 step 4: the effect code applies (a requirement row's decided outcome), not the workbook's
    effect = REQUIREMENT_OUTCOMES.get(r["Rule ID"], (r["Effect"],))[0]
    return " | ".join([f"[{r['Rule ID']}] {_cell(r['Topic'])}", _cell(effect), _cell(r["Plain rule"]),
                       value or "-", _cell(r["Applies when"]) or "-", _cell(r["Exceptions / cure"]) or "-"]) + extra


def evidence_text(open_carriers):
    """The user-message section for the separate pilot call: for each
    carrier the code could not decide, the code's results and its OPEN rows."""
    rules = _rules()
    out = [PILOT_INSTRUCTION, ""]
    for canon, outcomes in open_carriers.items():
        npass = sum(1 for o, _ in outcomes.values() if o == "PASS")
        nna = sum(1 for o, _ in outcomes.values() if o == "N/A")
        out.append(f"--- {canon} (rule check) ---")
        out.append(f"Decided by code: {npass} rule(s) PASS, {nna} do not apply; none fails.")
        out.append("Not decided by code:")
        out += [_row_line(rules[rid], f" | open: {d}") for rid, (o, d) in outcomes.items() if o == "OPEN"]
        out.append("")
    return "\n".join(out)


_ROW_ID = re.compile(r"\b[A-Z][A-Z0-9]{2}-\d{3}\b")   # PH6-NNN too (round 38, F08)      # any batch's row id; filtered to the carrier's own rows


def finish_model_record(rec, canon, outcomes):
    """A model record for a pilot carrier: attach id + page + quote for every
    row id it names, keep its reasons, add the never-a-hold notes, mark it."""
    rules = _rules()
    wb = _wb_of(canon, outcomes)
    text = " ".join((rec.get("reasons") or []) + (rec.get("citations") or []) + (rec.get("missing_info") or []))
    ids = [rid for rid in dict.fromkeys(_ROW_ID.findall(text)) if rid in rules and rules[rid]["Carrier"] == wb]
    rec["citations"] = [citation(rules[rid]) for rid in ids]
    rec["carrier"] = canon
    rec["rules_table"] = True
    rec["also_confirm"] = also_confirm(canon, outcomes)
    rec["confirm_items"] = confirm_items(canon, outcomes)
    readable_reasons(rec)                      # round 37 follow-up 2
    # Round 37 follow-up 2: a held card leads with code's reason (the model's own wording of the hold cited rows
    # inline); its other reasons follow, as readable_reasons left them
    opens = [rid for rid, (o, _) in outcomes.items() if o == "OPEN"]
    if rec.get("status") == "INSUFFICIENT_INFORMATION" and opens:
        rec["reasons"] = [held_reason(outcomes, opens)] + [r for r in rec.get("reasons") or []
                                                            if not r.startswith("This guide: ")]
        if not rec.get("missing_info"):        # the reason and Missing name the same rows
            rec["missing_info"] = [f"{outcomes[rid][1]} -- [{rid}] {rules[rid]['Plain rule']}" for rid in opens]
    _hold_unknown_as_insufficient(rec, outcomes, ids)
    _release_unasked_holds(rec, outcomes)
    return rec


def _release_unasked_holds(rec, outcomes):
    """Round 31 step 3c (decision 2, 2026-10-08): the hold guard on a rules-check record. Only when every
    row still open for the carrier is one the model was asked to decide (its readings disagree on known
    facts, or its effect is UNKNOWN) -- never with a row Liam holds by name (HOLD_BY_DECISION) or a row
    open on a blank form field -- the model's items about facts the form never asks become a "Confirm:"
    note; with nothing else open the card is ELIGIBLE. Round 30: Haiku held SWY-043 on the panel maker."""
    if rec.get("status") != "INSUFFICIENT_INFORMATION":
        return
    opens = [rid for rid, (o, _) in outcomes.items() if o == "OPEN"]
    if not opens or any(rid in HOLD_BY_DECISION or not _model_can_decide(outcomes[rid][1]) for rid in opens):
        return
    items = list(rec.get("missing_info") or [])
    confirm = [m for m in items if hold_guard.classify(m)[0] == "c"]
    if not confirm:
        return
    keep = [m for m in items if m not in confirm]
    note = "Confirm (not asked by the form; never a hold): " + "; ".join(confirm) + "."
    rec["notes"] = ((rec.get("notes") or "") + " " + note).strip()
    rec["missing_info"] = keep
    if not keep:
        rec["status"], rec["flaw_count"] = "ELIGIBLE", 0
        rec["reasons"] = ["Only facts the intake form does not ask were open; they are listed to confirm, "
                          "never as a hold."]


def only_blank_holds(outcomes):
    """Round 39 step 5e: every row still open for the carrier is a hold on a blank form field -- the model cannot
    decide any of them (it never sees the missing answer), so code's held record is the verdict."""
    opens = [d for o, d in outcomes.values() if o == "OPEN"]
    return bool(opens) and not any(_model_can_decide(d) for d in opens)


def _model_can_decide(detail):
    """An OPEN row the pilot call can legitimately fail: its readings disagree
    on known facts, or a known fact breaks it and only the effect is unknown.
    Every other OPEN row is open because the form does not give a fact."""
    return detail.startswith("ambiguous:") or detail == "the row's effect is UNKNOWN"


def _hold_unknown_as_insufficient(rec, outcomes, cited_ids):
    """Round 25 step 4 (2026-10-04). On the same open pool-fence rows -- facts
    the form does not give -- Luna answered REFER in one set of runs and
    ELIGIBLE in the next, with reasons saying the fence was unknown. Code
    knows why each row is open, so it decides these, both ways:
    - REFER / INELIGIBLE stands only when it cites a row the model can decide
      (readings disagree, or a known fact with an UNKNOWN effect);
    - otherwise, while any row is open on a fact the form does not give, the
      carrier is INSUFFICIENT_INFORMATION on those facts -- never ELIGIBLE,
      as code_record already does when it decides alone.
    An INSUFFICIENT_INFORMATION answer is left as the model wrote it."""
    status = rec.get("status")
    if status == "INSUFFICIENT_INFORMATION":
        return
    if status in ("REFER", "INELIGIBLE") and any(
            outcomes.get(rid, ("", ""))[0] == "OPEN" and _model_can_decide(outcomes[rid][1]) for rid in cited_ids):
        return
    rules = _rules()
    opens = [rid for rid, (o, d) in outcomes.items() if o == "OPEN" and not _model_can_decide(d)]
    if status not in ("REFER", "INELIGIBLE") and not opens:
        return
    # Round 37 follow-up 2 (Liam, 2026-10-11): no internal note ("the pilot answer said ..."), and the card's
    # reason is code's own (held_reason): the model's text argued for the verdict code just overruled.
    rec["status"], rec["flaw_count"] = "INSUFFICIENT_INFORMATION", 0
    opens = opens or [rid for rid, (o, _) in outcomes.items() if o == "OPEN"]   # an uncited decidable row
    rec["reasons"] = [held_reason(outcomes, opens)]
    rec["missing_info"] = [f"{outcomes[rid][1]} -- [{rid}] {rules[rid]['Plain rule']}" for rid in opens]
    rec["citations"] = rec["citations"] or [citation(rules[rid]) for rid in opens]


# Round 37 follow-up 2 (Liam, 2026-10-11): a held card's first line, written by code, that reads without row IDs.
# Named row groups get Liam's own wording; the protection-class rows a fire-station distance opens get one line;
# anything else says which facts the form does not give and quotes the first open rule.
HELD_REASON_BY_ROWS = (
    (frozenset({"CHU-043", "CHU-044"}),
     "Chubb restricts all of Harris County (unacceptable in 1A, pre-approval in 1B/1C/1E); the form can't tell "
     "which area."),
)


def held_reason(outcomes, opens):
    rules = _rules()
    opens = [rid for rid in opens if rid in outcomes]
    for rows, text in HELD_REASON_BY_ROWS:
        if rows & set(opens):
            return text
    # Round 38 step 1 (Liam, 2026-10-11): built from what the holding rows still lack -- never a fact the form
    # answered. The 5-mile rule is named only when the station distance is blank.
    parts = [p.strip() for rid in opens for p in outcomes[rid][1].split(";") if p.strip()]
    parts = [p for p in parts if not p.startswith(("ambiguous", "the row's effect"))]
    low = [p.lower() for p in parts]
    station = any("station" in p and "if not given" in p for p in low)
    hydrant = any("hydrant" in p and "if not given" in p for p in low)
    if station:
        return ("Held: if the fire station is more than 5 miles away" + (" (or no hydrant is within 1,000 ft)" if hydrant
                                                                           else "")
                + ", this guide's higher-risk fire protection rules apply (for example, the home must be under 25 "
                  "years old). Confirm the distance" + (" and the hydrant." if hydrant else "."))
    needs, fire_table = [], False

    def add(x):
        if x not in needs:
            needs.append(x)
    for orig, p in zip(parts, low):
        if "hydrant" in p and "if not given" in p:
            fire_table = True
            add("whether a hydrant is within 1,000 ft")
        elif any(w in p for w in ("visibility", "visible", "alarm", "access")):
            fire_table = True
            add("whether the home is visible from the road, has a central station alarm and 10-ft year-round "
                "fire-truck access")
        elif "fire loss" in p:
            add("whether there were prior fire losses")
        elif p:
            add(re.sub(r"\s*if not given", "", orig).strip())     # as written ("PPC", F14)
    if not needs:
        first = rules[opens[0]]["Plain rule"].rstrip(".") if opens else ""
        return "Held: this guide needs a fact the form does not give" + (f" ({first})" if first else "") + ". Confirm it."
    joined = needs[0] if len(needs) == 1 else ", ".join(needs[:-1]) + ", and " + needs[-1]
    return ("Held: " + ("this guide's fire-protection table needs to know " if fire_table else "this guide needs to "
                        "know ") + joined + (". Confirm these." if len(needs) > 1 else ". Confirm it."))


def readable_reasons(rec):
    """Round 37 follow-up 2: a model reason that cites rows inline ("... decline in [CHU-043] and ...") is
    replaced by those rows' own rules, so nothing reads with a hole where an ID was."""
    rules = _rules()
    out = []
    for reason in rec.get("reasons") or []:
        ids = [rid for rid in dict.fromkeys(_ROW_ID.findall(str(reason))) if rid in rules]
        if not ids:
            out.append(reason)
            continue
        for rid in ids:
            text = "This guide: " + rules[rid]["Plain rule"]
            if text not in out:
                out.append(text)
    rec["reasons"] = out


def is_pilot(carrier):
    return carrier in PILOT_CARRIERS.values()


def is_sage_batch(carrier):
    return carrier in SAGE_BATCH_CARRIERS.values()


def is_rules_table(carrier, sage_batch=False, batches_on=(), pd=None):
    """The rules table decides this carrier: a pilot carrier, or one of a batch whose switch is on
    (sage_batch: the round 27 form of batches_on={"sage"})."""
    on = set(batches_on) | ({"sage"} if sage_batch else set())
    return rules_table_wb(carrier, on, pd) is not None


def rules_table_wb(carrier, batches_on=(), pd=None):
    """The workbook carrier whose rows decide `carrier` for this property, or None: the pilot's,
    or that of a batch in batches_on whose scope (if any) covers the property's occupancy."""
    occupancy = (pd or {}).get("occupancy_type")
    for name, b in BATCHES.items():
        if name != "pilot" and name not in batches_on:
            continue
        for wb, canon in b["carriers"].items():
            if canon != carrier:
                continue
            scope = b.get("scope", {}).get(wb)
            if scope is None or occupancy in scope:
                return wb
    return None


def _wb_of(canon, outcomes):
    """The workbook carrier behind these outcomes (the rows evaluated), else the carrier's first."""
    rules = _rules()
    for rid in outcomes:
        if rid in rules:
            return rules[rid]["Carrier"]
    return CANON_TO_WB[canon]


# Round 29 step 9 (2026-10-08): COVERAGE_ONLY rows are never eligibility, so the rules table
# never evaluated them -- and two decided notes went missing from rules-table cards: Progressive
# HO3's solar wind/hail exclusion (Liam, decision C, 2026-10-05) and Allied's replacement-cost
# limit for a composite roof (round 26). A COVERAGE_ONLY row whose exposure the property shows is
# a coverage note: solar rows when Solar panels is Yes; roof-settlement rows that name the
# property's roof material. Never a status change.
_ROOF_WORDS = {"Composition Shingle": ("composition", "composite", "3-tab", "asphalt"),
               "Architectural Shingle": ("architectural", "dimensional", "laminate"),
               "Tile": ("tile",), "Slate": ("slate",), intake_fields.ROOF_WOOD: ("wood",),
               **{m: ("metal",) for m in intake_fields.ROOF_METALS},
               intake_fields.ROOF_BUILT_UP: ("flat", "built-up", "built up"),
               intake_fields.ROOF_MEMBRANE: ("flat", "membrane"), intake_fields.ROOF_ROLLED: ("rolled",),
               # old saved values: a "Metal" roof is metal and "Flat/Built-Up" is flat, whatever the kind
               "Metal": ("metal",), "Flat/Built-Up": ("flat", "built-up", "built up")}


def _coverage_note_applies(row, pd):
    text = row["Plain rule"].lower()
    if row["Topic"] == "SOLAR":
        return pd.get("solar_panels") == "Yes"
    if row["Topic"] == "ROOF_SETTLEMENT":
        roof = pd.get("roof_type")
        named = re.sub(r"\(except [^)]*\)", " ", text)       # "(except metal, slate, tile)" names no covering
        if any(w in named for w in _ROOF_WORDS.get(roof, ())):
            return True
        # Round 39 step 0c (a 23-year roof, every roof type): an architectural shingle IS an asphalt shingle (Vave
        # VAV-031..033 / VDP-077, Swyfft SLL-025 never showed for it) -- unless the row is the 3-tab one (Centauri
        # CHO-028 next to its own architectural row)
        if roof == "Architectural Shingle" and "asphalt" in text and not _NOT_ARCHITECTURAL.search(text):
            return True
        # ... and "all other roofs / roof types" (Mercury MER-019, NatGen NCD-101 showed for no covering): every
        # covering that neither this row's "except (...)" nor the carrier's other settlement rows name
        if _ALL_OTHER.search(text) and roof:
            words = _ROOF_WORDS.get(roof, ())
            excepted = " ".join(re.findall(r"except ([^)]*)", text))
            siblings = " ".join(r["Plain rule"].lower() for r in _rules().values()
                                if r["Carrier"] == row["Carrier"] and r["Topic"] == "ROOF_SETTLEMENT"
                                and r["Effect"] == "COVERAGE_ONLY" and r["Rule ID"] != row["Rule ID"])
            return not any(w in excepted or w in siblings for w in words)
    return False


_NOT_ARCHITECTURAL = re.compile(r"3-tab|other than architectural|except architectural|not architectural")
_ALL_OTHER = re.compile(r"\ball other roof")


# Round 30 step 3 (Liam, 2026-10-08, decision 3): INFO_ONLY rows the card still states when they apply.
# row id -> (applies to this property?, the card's note). FOD-005: TDP-3 has no vacant use type, and
# Foremost writes vacant dwellings on TDP-1 -- a note, never a decline (it was inferred from the grid).
def _county_in(names):
    return lambda pd: intake_fields.normalize_county(pd.get("county")) in names


# Round 39 step 1 (Liam, 2026-10-12): The Hartford's wind/hail rows are notes (p.7, Catastrophe Management).
HARTFORD_TIER_I = _county_names("""Aransas, Brazoria, Calhoun, Cameron, Chambers, Galveston, Jefferson, Kenedy,
    Kleberg, Matagorda, Nueces, Refugio, San Patricio, Willacy""")
HARTFORD_TIER_II = _county_names("Harris, Fort Bend, Hardin, Jackson, Liberty, Orange, Wharton")
# Round 40 step 2 (Liam, 2026-10-16): NatGen Custom360 HO3's coastal zones (p.9) are notes. Harris ZIPs 77571 / 77586
# east of Highway 146 are Coastal Zone 1 (the form's "East of Highway 146" answer with the ZIP); all of Harris is also
# Zone 2 Houston. "An acceptable CAT score" (NC3-092 / NC3-094) has no threshold: a note, never a decline.
NATGEN_ZONE_1 = HARTFORD_TIER_I
NATGEN_ZONE_2 = _county_names("""Bee, Brooks, Goliad, Hardin, Hidalgo, Jackson, Jim Wells, Liberty, Live Oak, Orange,
    Victoria, Wharton""")
NATGEN_ZONE_2_HOUSTON = _county_names("Fort Bend, Harris")
NATGEN_INLAND_ZONE_1 = _county_names("Collin, Dallas, Denton, Johnson, Kaufman, Parker, Rockwall, Tarrant")
NATGEN_HARRIS_ZONE_1_ZIPS = ("77571", "77586")
_NATGEN_EXCLUSION = "NatGen requires a Windstorm/Hail exclusion, with the signed exclusion form before binding"
_CAT_SCORE = "the home must have an acceptable CAT score (NatGen states no threshold; it does not rule the home out here)"
# Round 40 step 2: SageSure Occidental HO3's wind/hail deductibles (p.4, Coastal - Proximity to Water) and the
# pre-1940 replacement cost (p.9) are notes.
OCCIDENTAL_VERY_HIGH = _county_names("Galveston, Brazoria, Chambers")
OCCIDENTAL_MODERATE = _county_names("Harris, Fort Bend")


def _natgen_harris_zone_1(pd):
    return (intake_fields.normalize_county(pd.get("county")) == "Harris"
            and str(pd.get("zip") or "").strip()[:5] in NATGEN_HARRIS_ZONE_1_ZIPS
            and intake_fields.answer(pd.get("harris_east_146")) != "No")


def _natgen_harris_zone_1_note(pd):
    if intake_fields.answer(pd.get("harris_east_146")) == "Yes":
        return (f"Coverage (not eligibility): Coastal Zone 1 (Harris ZIP 77571 / 77586 east of Highway 146) -- "
                f"{_NATGEN_EXCLUSION} (NC3-091).")
    return (f"Coverage (not eligibility): Harris ZIP 77571 / 77586 -- if the home is east of Highway 146 it is "
            f"Coastal Zone 1 and {_NATGEN_EXCLUSION} (NC3-091).")


PROGRAM_NOTES = {
    "FOD-005": (lambda pd: pd.get("occupancy_type") == "Vacant",
                "Foremost writes vacant dwellings on TDP-1, not TDP-3; quote TDP-1 (FOD-005)."),
    "HAR-053": (_county_in(HARTFORD_TIER_I),
                "Coverage (not eligibility): Tier I county -- The Hartford requires a windstorm or hail exclusion "
                "(HAR-053)."),
    "HAR-054": (_county_in(HARTFORD_TIER_II),
                "Coverage (not eligibility): Tier II county -- a minimum 2% windstorm or hail deductible is required "
                "(HAR-054)."),
    "NC3-090": (_county_in(NATGEN_ZONE_1),
                f"Coverage (not eligibility): Coastal Zone 1 county -- {_NATGEN_EXCLUSION} (NC3-090)."),
    "NC3-091": (_natgen_harris_zone_1, _natgen_harris_zone_1_note),
    "NC3-093": (_county_in(NATGEN_ZONE_2),
                f"Coverage (not eligibility): Coastal Zone 2 county -- a 2% Windstorm/Hail deductible is mandatory, "
                f"and {_CAT_SCORE} (NC3-092, NC3-093)."),
    "NC3-095": (_county_in(NATGEN_ZONE_2_HOUSTON),
                f"Coverage (not eligibility): Coastal Zone 2 - Houston -- a 3% Windstorm/Hail deductible is mandatory, "
                f"and {_CAT_SCORE} (NC3-094, NC3-095)."),
    "NC3-096": (_county_in(NATGEN_INLAND_ZONE_1),
                "Coverage (not eligibility): Inland Windstorm/Hail Deductible Zone 1 -- a Windstorm/Hail deductible of "
                "at least 2% is mandatory (NC3-096)."),
    "OCC-013": (_county_in(OCCIDENTAL_VERY_HIGH),
                "Coverage (not eligibility): Very High Hazard county -- a 5% Wind and Hail deductible, or a 5% "
                "Hurricane deductible with a 1.5% AOP deductible, is required (OCC-013)."),
    "OCC-015": (_county_in(OCCIDENTAL_MODERATE),
                "Coverage (not eligibility): Harris / Fort Bend -- a 3% or higher Wind and Hail deductible, or a 3% "
                "or higher Hurricane deductible with a 1.5% AOP deductible, is required (OCC-014, OCC-015)."),
    "OCC-016": (lambda pd: bool(intake_fields.normalize_county(pd.get("county")))
                and intake_fields.normalize_county(pd.get("county")) not in OCCIDENTAL_VERY_HIGH | OCCIDENTAL_MODERATE,
                "Coverage (not eligibility): a 1.5% or higher Wind and Hail deductible is required (OCC-016)."),
    "OCC-049": (lambda pd: str(pd.get("year_built") or "").strip().isdigit() and int(pd["year_built"]) < 1940,
                "Coverage (not eligibility): a home built before 1940 gets replacement cost through the Functional "
                "Replacement Cost endorsement HO 05 30, unless the customer accepts the full factor (OCC-049)."),
}


def program_notes(canon, outcomes, pd):
    """The PROGRAM_NOTES lines for this carrier's workbook program that apply to the property."""
    wb, rules = _wb_of(canon, outcomes), _rules()
    return [note(pd) if callable(note) else note for rid, (applies, note) in PROGRAM_NOTES.items()
            if rid in rules and rules[rid]["Carrier"] == wb and applies(pd)]


def coverage_notes(canon, outcomes, pd):
    """The carrier's COVERAGE_ONLY rows this property triggers, as "[id] plain rule" lines."""
    wb = _wb_of(canon, outcomes)
    return [f"[{r['Rule ID']}] {r['Plain rule']}" for r in _rules().values()
            if r["Carrier"] == wb and r["Effect"] == "COVERAGE_ONLY" and _coverage_note_applies(r, pd)]


def territory_rows(canon):
    """The carrier's map lines decided by the County alone: its territory
    rows (south of 31 N / East Texas, and Nueces)."""
    wb = CANON_TO_WB[canon]
    rules = _rules()
    return {rid for rid, m in _map().items() if rules[rid]["Carrier"] == wb and m["field"] == "county"}
