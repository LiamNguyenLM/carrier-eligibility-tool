"""Round 40 step 3a: NatGen Custom360 HO3 and SageSure Occidental HO3's rules tables under many profiles, zero API,
rules_evaluator only (as verification/hartford_deep.py; verification/fuzz runs the whole pipeline).

N weighted random profiles per carrier (Harris, Fort Bend, Bexar, Galveston, Travis, Dallas over-sampled; mostly
owner-occupied houses; each factor departs from a plain answer with probability DEPART), each checked against the
Round 38 invariants as they apply to one carrier's rules table:
  determinism    the same profile twice gives the same outcomes
  monotonic      a worse fact never turns a decline or referral Eligible (fuzz/checks.worse)
  answer_no_hold answering a blank question never adds a hold (fuzz/checks.answered)
  deciding_row   a decline / referral names its row and cites its quote
  model_free     a hold (OPEN row) rests only on a form field left blank, or on a row Liam decided holds by name
                 (rules_evaluator.HOLD_BY_DECISION: the Sage FPC table) -- never on a FACT the form cannot ask
  blank_is_note  a hold never rests only on fields whose blank is a confirm (rules_evaluator.BLANK_IS_NOTE: Coverage
                 A, County, ...) with a FACT besides (round 40 step 3e: NC3-022 held Liam's profile so)
and Liam's decisions (2026-10-16):
  natgen_cov_a   Coverage A over an approval threshold never declines on NC3-022 / 023 / 026; below $150,000 always
                 declines (NC3-192)
  natgen_cat     no decline rests on a CAT score (NC3-092 / 094 are notes)
  natgen_wood    a wood roof is never Eligible; it declines only when older than 25 years
  occ_county     OCC-001 decides exactly as rules_data/occidental_counties.csv; a blank county never declines on it
  occ_tenant     a tenant-occupied home is never Eligible

usage: python verification/new_guides_deep.py <n random per carrier> <out.json>"""
import collections
import csv
import json
import os
import random
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "fuzz"))
import intake_fields as I  # noqa: E402
import rules_evaluator as rv  # noqa: E402
from checks import answered, worse  # noqa: E402

NG, OC = "NatGen_Custom360_HO3_-_09.02.2026", "Sage_-_Occidental_HO3_-_12.02.2025"
ROW = re.compile(r"\[([A-Z][A-Z0-9]{2}-\d{3})\]")
with open(os.path.join(HERE, "..", "rules_data", "occidental_counties.csv"), encoding="utf-8") as _fh:
    OCC_COUNTIES = {r["county"]: r["occidental"] for r in csv.DictReader(l for l in _fh if not l.startswith("#"))}

FACTORS = {
    "occupancy_type": ["Owner Occupied", "Seasonal", "Secondary Home", "Tenant Occupied", "Vacant"],
    "ownership": ["Individual Owner", "LLC", "Corporation / partnership", "Estate", "Trust:Family trust",
                  "Trust:Land trust", "Trust:Corporate or business trust", "Trust:Unknown"],
    "dwelling_type": ["House", "Townhome", "Condo"],
    "units_in_building": ["1", "2", "3-4", "5 or more", "", "Unknown"],
    "swimming_pool": ["No Pool", "In Ground - Fenced", "In Ground - Unfenced", "Above Ground - Fenced",
                      "Above Ground - Unfenced"],
    "pool_boxes": ["both", "fence only", "gate only", "neither"],
    "pool_accessories": ["None", "Slide only", "Diving board only", "Both slide and diving board"],
    "ppc": ["2", "4", "7", "8", "9", "10", "N/A"],
    "fire_station_miles": [None, 2.0, 5.0, 5.5, 8.0, 10.0, 12.0],
    "hydrant_1000ft": ["Yes", "No", "Unknown"],
    "dwelling_amount": [None, 84999, 85000, 149999, 150000, 400000, 750000, 750001, 1500000, 1500001, 2000000,
                        2000001, 3000000],
    "county": ["Harris", "Fort Bend", "Bexar", "Galveston", "Travis", "Dallas", "Nueces", "Polk", "Walker", "Brazos",
               "Burnet", "Hidalgo", "Tarrant", "Liberty", ""],
    "zip": ["", "77571", "77586", "77493"],
    "harris_east_146": ["Yes", "No", "Unknown"],
    "year_built": [1925, 1939, 1940, 1986, 2002, 2012, 2020],
    "roof_type": ["Composition Shingle", "Architectural Shingle", "Tile", I.ROOF_WOOD, I.ROOF_METAL_SEAM,
                  I.ROOF_METAL_PANEL, I.ROOF_TLOCK, I.ROOF_ROLLED, I.ROOF_BUILT_UP, "Other"],
    "roof_age": [2, 10, 20, 25, 26, 30],
    "roof_shape": ["Gable", "Hip", "Flat"],
    "plumbing_type": ["PVC", "Copper", "Polybutylene", "Galvanized", "Unknown"],
    "electrical": [None, ["Circuit breakers"], ["Fuses"], ["Knob-and-tube wiring"], ["Aluminum branch wiring"],
                   ["Federal Pacific or Zinsco panel"], ["Unknown"]],
    "losses": ["", "0", "1:Water", "1:Theft", "2:Water", "2:Theft", "2:Theft,Water", "2:Fire,Liability",
               "3 or more:Water", "3 or more:Theft", "3 or more:Fire,Other", "1:old", "Unknown"],
    "primary_home_carrier": ["", "National General", "Sage: Occidental", "Chubb", "Other carrier", "Unknown"],
    "coastal_tier": ["Not Coastal", "Tier 1", "Tier 2", "Tier 3", "Tier 4"],
    "construction_type": ["Frame", "Masonry", "Manufactured/Mobile"],
    "dogs": ["No", "Yes:None of these", "Yes:Pit Bull", "Yes:Not sure"],
}
PLAIN = {"occupancy_type": "Owner Occupied", "ownership": "Individual Owner", "dwelling_type": "House",
         "units_in_building": "1", "swimming_pool": "No Pool", "pool_boxes": "both", "pool_accessories": "None",
         "ppc": "4", "fire_station_miles": 2.0, "hydrant_1000ft": "Yes", "dwelling_amount": 400000, "county": None,
         "zip": "", "harris_east_146": "Unknown", "year_built": 2002, "roof_type": "Composition Shingle",
         "roof_age": 10, "roof_shape": "Gable", "plumbing_type": "PVC", "electrical": ["Circuit breakers"],
         "losses": "0", "primary_home_carrier": "", "coastal_tier": None, "construction_type": "Frame", "dogs": "No"}
WEIGHTS = {"county": [6, 4, 4, 4, 4, 4, 1, 1, 1, 1, 1, 1, 1, 1, 1]}
DEPART = 0.12
TIER = {"Galveston": "Tier 1", "Nueces": "Tier 1", "Harris": "Tier 2", "Fort Bend": "Tier 3", "Liberty": "Tier 3"}


def random_choice(rng):
    out = {}
    for k, v in FACTORS.items():
        plain = PLAIN.get(k)
        out[k] = rng.choices(v, weights=WEIGHTS.get(k))[0] if plain is None or rng.random() < DEPART else plain
    return out


def build(c):
    """A property_details dict from one value per factor (questions present only where the form shows them)."""
    pd = {k: c[k] for k in ("occupancy_type", "dwelling_type", "swimming_pool", "ppc", "fire_station_miles",
                            "hydrant_1000ft", "dwelling_amount", "county", "zip", "year_built", "roof_type",
                            "roof_age", "roof_shape", "plumbing_type", "construction_type")}
    pd["roof_age"] = min(pd["roof_age"], 2026 - pd["year_built"])
    pd["coastal_tier"] = c["coastal_tier"] or TIER.get(c["county"], "Not Coastal")
    pd["solar_panels"] = "No"
    if pd["county"] == "Harris":
        pd["harris_east_146"] = c["harris_east_146"]
    if pd["dwelling_type"] == "House" and c["units_in_building"]:
        pd["units_in_building"] = c["units_in_building"]
    pd["pool_accessories"] = "None" if pd["swimming_pool"] == "No Pool" else c["pool_accessories"]
    pd["pool_fence_4ft"] = c["pool_boxes"] in ("both", "fence only")
    pd["pool_gate_locking"] = c["pool_boxes"] in ("both", "gate only")
    owner, _, trust = c["ownership"].partition(":")
    pd["ownership_type"] = owner
    if trust:
        pd["trust_type"] = trust
    if c["electrical"] is not None:
        pd["electrical"] = c["electrical"]
    n, _, types = c["losses"].partition(":")
    if n:
        pd["losses_5yr"] = n
        if types == "old":
            pd["loss_types"], pd["loss_year"] = ["Theft"], 2021
        elif types:
            pd["loss_types"], pd["loss_year"], pd["losses_3yr"] = types.split(","), 2025, n
    dogs, _, breed = c["dogs"].partition(":")
    pd["has_dogs"], pd["dog_breeds"] = dogs, ([breed] if breed else [])
    if pd["occupancy_type"] in I.OWNERS_OTHER_HOMES:
        pd["primary_home_carrier"] = c["primary_home_carrier"]
    return pd


def evaluate(canon, pd):
    out = rv.evaluate_carrier(canon, pd)
    return out, rv.code_record(canon, out, pd)[0]


def check(canon, pd, rng):
    fails = []
    out, rec = evaluate(canon, pd)
    out2, rec2 = evaluate(canon, json.loads(json.dumps(pd)))
    if out != out2 or rec["status"] != rec2["status"]:
        fails.append(("determinism", ""))
    st = rec["status"]
    w = worse(pd, rng)
    if w and st in ("INELIGIBLE", "REFER") and evaluate(canon, w[1])[1]["status"] == "ELIGIBLE":
        fails.append(("monotonic", f"{w[0]}: {pd.get(w[0])} -> {w[1].get(w[0])}"))
    a = answered(pd, rng)
    if a and st != "INSUFFICIENT_INFORMATION":
        field, value = a
        if evaluate(canon, dict(pd, **{field: value}))[1]["status"] == "INSUFFICIENT_INFORMATION":
            fails.append(("answer_no_hold", f"{field}={value}"))
    cited = ROW.findall(rec["reasons"][0]) if st in ("INELIGIBLE", "REFER") else []
    if st in ("INELIGIBLE", "REFER") and (not cited or not any(f"[{cited[0]}]" in c and '"' in c
                                                                 for c in rec["citations"])):
        fails.append(("deciding_row", rec["reasons"][0][:120]))
    f = rv.facts(pd)
    for rid, (o, _) in out.items():
        if o == "OPEN" and rid not in rv.HOLD_BY_DECISION:
            m = rv._map()[rid]
            unknown = [u for t in m["test"].split("||") for u in rv.evaluate_expr(t, f)[1]] + \
                rv.evaluate_expr(m["gate"] or "always", f)[1]
            if not any(u in f for u in unknown):
                fails.append(("model_free", f"{rid} open only on {unknown}"))
            elif all(u in rv.BLANK_IS_NOTE for u in unknown if u in f):
                fails.append(("blank_is_note", f"{rid} held on {[u for u in unknown if u in f]} with a FACT"))
    declines = {rid for rid, (o, _) in out.items() if o == "FAIL" and rv._map()[rid]["outcome_if_fail"] == "DECLINES"}
    amount = pd.get("dwelling_amount")
    if canon == NG:
        if declines & {"NC3-022", "NC3-023", "NC3-026"}:
            fails.append(("natgen_cov_a", f"a Coverage A threshold row declines: {sorted(declines)}"))
        if isinstance(amount, int) and amount < 150000 and (out["NC3-192"][0] != "FAIL" or st != "INELIGIBLE"):
            fails.append(("natgen_cov_a", f"${amount:,} not declined"))
        if declines & {"NC3-092", "NC3-094"} or any("CAT" in r for r in rec["reasons"]):
            fails.append(("natgen_cat", "a decline rests on a CAT score"))
        if rv.facts(pd)["roof_type"] == I.ROOF_WOOD:
            if st == "ELIGIBLE":
                fails.append(("natgen_wood", "a wood roof is Eligible"))
            if ("NC3-062" in declines) != (pd["roof_age"] > 25):
                fails.append(("natgen_wood", f"NC3-062 at roof age {pd['roof_age']}"))
    else:
        want = OCC_COUNTIES.get(pd["county"])
        got = out["OCC-001"][0]
        if (want == "IN" and got != "PASS") or (want == "OUT" and got != "FAIL") or (want is None and got == "FAIL"):
            fails.append(("occ_county", f"{pd['county'] or 'blank'}: {got}"))
        if pd["occupancy_type"] == "Tenant Occupied" and st == "ELIGIBLE":
            fails.append(("occ_tenant", "a tenant-occupied home is Eligible"))
    return st, rec, fails


def main(n, out_path, seed=40):
    report = {}
    for canon in (NG, OC):
        rng = random.Random(seed)
        fails, statuses, rows = collections.Counter(), collections.Counter(), collections.Counter()
        examples = collections.defaultdict(list)
        for _ in range(n):
            pd = build(random_choice(rng))
            st, rec, fs = check(canon, pd, rng)
            statuses[st] += 1
            if st in ("INELIGIBLE", "REFER"):
                for rid in ROW.findall(rec["reasons"][0])[:1]:
                    rows[(rid, st)] += 1
            for name, detail in fs:
                fails[name] += 1
                if len(examples[name]) < 5:
                    examples[name].append({"profile": pd, "detail": detail})
        report[canon] = {"profiles": n, "invariant_failures": dict(fails), "examples": dict(examples),
                         "statuses": dict(statuses.most_common()),
                         "deciding_rows": {f"{rid} {st}": v for (rid, st), v in sorted(rows.items())}}
        print(canon, json.dumps({"profiles": n, "invariant_failures": dict(fails), "statuses": dict(statuses)}))
        print("  distinct deciding row / outcome:", len(rows))
    json.dump(report, open(out_path, "w", encoding="utf-8"), indent=1, default=str)
    return report


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2])
