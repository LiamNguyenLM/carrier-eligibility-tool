"""Round 25 Step 4: one real check with the rules-table pilot ON or OFF,
recorded. Real API cost (cents).

usage: python verification/measure_rules_pilot.py <ON|OFF> <PROFILE> <label> <out.jsonl>
PROFILE: STANDARD LIAM STRESS OLD CLEAN (round 24) or ALT COASTAL_PPC4 OWNERSHIP_BASE (Tier 2).
The model is ELIGIBILITY_MODEL (production default gpt-6-luna)."""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
os.chdir(os.path.join(HERE, ".."))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(".env")

import eligibility_check as ec  # noqa: E402
from profiles import (STANDARD_PROFILE, ALT_PROFILE, COASTAL_PPC4_PROFILE,  # noqa: E402
                      OWNERSHIP_BASE_PROFILE)

LIAM = {"year_built": 2000, "roof_age": 10, "roof_type": "Composition Shingle", "roof_shape": "Gable",
        "construction_type": "Frame", "plumbing_type": "Copper", "occupancy_type": "Owner Occupied",
        "ownership_type": "Individual Owner", "coastal_tier": "Not Coastal", "swimming_pool": "No Pool",
        "pool_accessories": "None", "has_dogs": "No", "aggressive_breed": "No", "solar_panels": "No",
        "ppc": "3"}
PROFILES = {
    "STANDARD": dict(STANDARD_PROFILE, dwelling_type="House"),
    "LIAM": dict(LIAM, dwelling_type="House"),
    "STRESS": dict(STANDARD_PROFILE, dwelling_type="House", county="Harris", dwelling_amount=900000,
                   swimming_pool="In Ground - Fenced", pool_fence_4ft=False, pool_gate_locking=False,
                   ppc="9", year_built=1955),
    "OLD": dict(LIAM, year_built=1970, roof_age=22, plumbing_type="Galvanized", ppc="6", county="Bexar",
                dwelling_amount=350000, dwelling_type="House"),
    "CLEAN": dict(LIAM, year_built=2015, roof_age=3, roof_type="Architectural Shingle", plumbing_type="PEX",
                  ppc="2", construction_type="Masonry Veneer", roof_shape="Hip", county="Travis",
                  dwelling_amount=450000, dwelling_type="House"),
    # the Tier 2 baseline profiles, as the baseline tier uses them
    "ALT": dict(ALT_PROFILE),
    "COASTAL_PPC4": dict(COASTAL_PPC4_PROFILE),
    "OWNERSHIP_BASE": dict(OWNERSHIP_BASE_PROFILE),
}
PRICE = {"in": 0.10, "cached": 0.01, "out": 0.50}   # $ per 1M tokens, gpt-6-luna


def _cost(u):
    if not u:
        return 0.0
    return (u["input_tokens"] * PRICE["in"] + u["cache_read_input_tokens"] * PRICE["cached"]
            + u["output_tokens"] * PRICE["out"]) / 1e6


def main():
    switch, prof, label, out = sys.argv[1:5]
    ec.RULES_PILOT = switch == "ON"
    t0 = time.perf_counter()
    results = ec.check_eligibility(dict(PROFILES[prof]))
    wall = round(time.perf_counter() - t0, 1)
    usage = dict(ec.LAST_CALL_USAGE)
    rec = {"switch": switch, "profile": prof, "label": label, "model": ec.ELIGIBILITY_MODEL, "wall": wall,
           "calls": {k: ({x: v[x] for x in ("input_tokens", "cache_read_input_tokens", "output_tokens")}
                         if v else None) for k, v in usage.items()},
           "cost": round(sum(_cost(v) for v in usage.values()), 5),
           "buckets": {k: len(v) for k, v in ec.assign_buckets(results).items()},
           "final": {r["carrier"]: {k: r.get(k) for k in ("status", "flaw_count", "reasons", "citations",
                                                          "missing_info", "notes", "rules_table", "also_confirm")}
                     for r in results}}
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps({k: rec[k] for k in ("switch", "profile", "label", "wall", "calls", "cost")}))


if __name__ == "__main__":
    main()
