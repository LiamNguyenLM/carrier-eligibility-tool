"""Round 39 step 5b / 5c: The Hartford's rules table under many profiles, zero API, rules_evaluator only (milliseconds
a profile; verification/fuzz runs the whole pipeline).

  pairwise   every pair of values of the Hartford's factors in at least one profile (greedy covering set)
  random     N weighted random profiles (the Hartford's limits over-sampled)
Each profile is checked against the Round 38 invariants as they apply to one carrier's rules table:
  determinism    the same profile twice gives the same outcomes
  monotonic      a worse fact never turns a decline or referral Eligible (fuzz/checks.worse)
  answer_no_hold answering a blank question never adds a hold (fuzz/checks.answered)
  deciding_row   a decline / referral names its row and cites its quote (a CFIG row: the knowledge base)
  model_free     a hold (OPEN row) rests only on a form field left blank -- never on a FACT the form cannot ask:
                 no row is left to the model (Liam, 2026-10-14)
  scope          an RPP+ row decides only a rental; a row gated off a rental never decides one
and 5c: each of 500 homes run as an owner's home and as an RPP+ rental (owner's home with The Hartford, 1-4 units,
long-term): every row whose outcome differs is an RPP+ row or a row gated on the occupancy.

usage: python verification/hartford_deep.py <n random> <out.json>"""
import collections
import itertools
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

H, WB = "The_Hartford_HO3_-_07.09.2026", "The Hartford HO3"
FMAP = rv._load("map", rv.HARTFORD_MAP_CSV)
RPP_ROWS = {f"HAR-0{n}" for n in range(70, 78)}
OCCUPANCY_GATED = {rid for rid, m in {**FMAP, "CFG-001": rv._map()["CFG-001"]}.items()
                   if "occupancy_type" in (m["gate"] or "")}

FACTORS = {
    "occupancy_type": ["Owner Occupied", "Seasonal", "Secondary Home", "Tenant Occupied"],
    "ownership": ["Individual Owner", "LLC", "Corporation / partnership", "Estate", "Trust:Family trust",
                  "Trust:Land trust", "Trust:Corporate or business trust", "Trust:Unknown"],
    "swimming_pool": ["No Pool", "In Ground - Fenced", "In Ground - Unfenced", "Above Ground - Fenced",
                      "Above Ground - Unfenced"],
    "pool_accessories": ["None", "Slide only", "Diving board only", "Both slide and diving board"],
    "ppc": ["4", "8", "9", "10", "10W", "N/A"],
    "dwelling_amount": [None, 400000, 1500000, 2000000, 2500001],
    "county": ["Travis", "Harris", "Galveston", "Dallas", "Nueces", ""],
    "roof_type": ["Composition Shingle", "Tile", I.ROOF_WOOD, I.ROOF_BUILT_UP, I.ROOF_MEMBRANE, I.ROOF_ASBESTOS,
                  "Other", "Flat/Built-Up"],
    "roof_shape": ["Gable", "Flat"],
    "electrical": [None, ["Circuit breakers"], ["Fuses"], ["Knob-and-tube wiring"], ["Unknown"]],
    "losses": ["", "0", "1:Water", "1:Fire", "1:Liability", "2:Water", "2:Theft,Wind or hail", "3 or more:Water,Theft",
               "Unknown"],
    "primary_home_carrier": ["", "The Hartford", "Travelers", "Other carrier", "Unknown"],
    "rental_units_total": ["", "1-4", "5 or more", "Unknown"],
    "rental_term": ["", "Long-term", "Short-term", "Unknown"],
    "dogs": ["No", "Yes:None of these", "Yes:Rottweiler", "Yes:Not sure"],
    "construction_type": ["Frame", "Masonry", "Manufactured/Mobile"],
    "dwelling_type": ["House", "Townhome"],
}
BASE = {"year_built": 1995, "roof_age": 10, "plumbing_type": "PVC", "coastal_tier": "Not Coastal",
        "pool_fence_4ft": False, "pool_gate_locking": False, "solar_panels": "No", "fire_station_miles": None,
        "hydrant_1000ft": "Unknown", "zip": ""}
TIER1 = {"Galveston", "Nueces"}


def build(choice):
    """A property_details dict from one value per factor (questions present only where the form shows them)."""
    pd = dict(BASE)
    for k in ("occupancy_type", "swimming_pool", "ppc", "dwelling_amount", "county", "roof_type", "roof_shape",
              "construction_type", "dwelling_type"):
        pd[k] = choice[k]
    pd["coastal_tier"] = "Tier 1" if choice["county"] in TIER1 else "Tier 2" if choice["county"] == "Harris" else \
        "Not Coastal"
    pd["pool_accessories"] = "None" if pd["swimming_pool"] == "No Pool" else choice["pool_accessories"]
    owner, _, trust = choice["ownership"].partition(":")
    pd["ownership_type"] = owner
    if trust:
        pd["trust_type"] = trust
    if choice["electrical"] is not None:
        pd["electrical"] = choice["electrical"]
    n, _, types = choice["losses"].partition(":")
    if n:
        pd["losses_5yr"] = n
        if types:
            pd["loss_types"] = types.split(",")
            pd["loss_year"] = 2025
            pd["losses_3yr"] = n
    dogs, _, breed = choice["dogs"].partition(":")
    pd["has_dogs"], pd["dog_breeds"] = dogs, ([breed] if breed else [])
    occ = pd["occupancy_type"]
    if occ in I.OWNERS_OTHER_HOMES or occ == I.RENTAL_OCCUPANCY:
        pd["primary_home_carrier"] = choice["primary_home_carrier"]
    if occ == I.RENTAL_OCCUPANCY:
        for k in ("rental_units_total", "rental_term"):
            if choice[k]:
                pd[k] = choice[k]
    if pd["county"] == "Harris":
        pd["harris_east_146"] = "Unknown"
    return pd


def pairwise(rng, candidates=60):
    """A greedy covering set: every pair of values of two factors appears in some profile."""
    names = list(FACTORS)
    todo = {(a, va, b, vb) for a, b in itertools.combinations(names, 2)
            for va in range(len(FACTORS[a])) for vb in range(len(FACTORS[b]))}
    out = []
    while todo:
        best, gain = None, -1
        for _ in range(candidates):
            c = {k: rng.randrange(len(v)) for k, v in FACTORS.items()}
            a, va, b, vb = next(iter(todo))       # seed each candidate with an uncovered pair
            c[a], c[b] = va, vb
            g = sum((a, c[a], b, c[b]) in todo for a, b in itertools.combinations(names, 2))
            if g > gain:
                best, gain = c, g
        todo -= {(a, best[a], b, best[b]) for a, b in itertools.combinations(names, 2)}
        out.append({k: FACTORS[k][i] for k, i in best.items()})
    return out


WEIGHTS = {"occupancy_type": [5, 1, 1, 4], "swimming_pool": [6, 3, 2, 1, 1], "ppc": [6, 3, 2, 2, 1, 1],
           "dwelling_amount": [3, 8, 2, 2, 1], "losses": [3, 6, 2, 1, 1, 2, 1, 1, 1],
           "primary_home_carrier": [2, 5, 2, 1, 1]}


# A plain answer per factor; each factor departs from it with probability DEPART (so most profiles are clean but
# for one or two answers -- the Eligible, held and single-decline paths all get exercised).
PLAIN = {"occupancy_type": None, "ownership": "Individual Owner", "swimming_pool": "No Pool", "pool_accessories": "None",
         "ppc": "4", "dwelling_amount": 400000, "county": "Travis", "roof_type": "Composition Shingle",
         "roof_shape": "Gable", "electrical": ["Circuit breakers"], "losses": "0", "primary_home_carrier": "The Hartford",
         "rental_units_total": "1-4", "rental_term": "Long-term", "dogs": "No", "construction_type": "Frame",
         "dwelling_type": "House"}
DEPART = 0.12


def random_choice(rng):
    out = {}
    for k, v in FACTORS.items():
        plain = PLAIN.get(k)
        out[k] = (rng.choices(v, weights=WEIGHTS.get(k))[0] if plain is None or rng.random() < DEPART else plain)
    return out


# ---------------------------------------------------------------- one profile
def evaluate(pd):
    out = rv.evaluate_carrier(H, pd, wb=WB)
    return out, rv.code_record(H, out, pd)[0]


def check(pd, rng):
    fails = []
    out, rec = evaluate(pd)
    out2, rec2 = evaluate(json.loads(json.dumps(pd)))
    if out != out2 or rec["status"] != rec2["status"]:
        fails.append(("determinism", ""))
    st = rec["status"]
    w = worse(pd, rng)                                   # (dimension, the profile with that fact made worse)
    if w and st in ("INELIGIBLE", "REFER") and evaluate(w[1])[1]["status"] == "ELIGIBLE":
        fails.append(("monotonic", f"{w[0]}: {pd.get(w[0])} -> {w[1].get(w[0])}"))
    a = answered(pd, rng)
    if a and st != "INSUFFICIENT_INFORMATION":
        field, value = a
        if evaluate(dict(pd, **{field: value}))[1]["status"] == "INSUFFICIENT_INFORMATION":
            fails.append(("answer_no_hold", f"{field}={value}"))
    if st in ("INELIGIBLE", "REFER"):
        ids = re.findall(r"\[([A-Z]{3}-\d{3})\]", rec["reasons"][0])
        if not ids or not any(f"[{ids[0]}]" in c and '"' in c for c in rec["citations"]):
            fails.append(("deciding_row", rec["reasons"][0][:120]))
    f = rv.facts(pd)
    for rid, (o, d) in out.items():
        if o == "OPEN":
            m = rv._map()[rid]
            readings = [rv.evaluate_expr(t, f) for t in m["test"].split("||")]
            gate_unknown = rv.evaluate_expr(m["gate"] or "always", f)[1]
            unknown = [u for _, us in readings for u in us] + gate_unknown
            if not any(u in f for u in unknown):
                fails.append(("model_free", f"{rid} open only on {unknown}"))
        if o in ("FAIL", "OPEN", "PASS"):
            tenant = pd["occupancy_type"] == I.RENTAL_OCCUPANCY
            if rid in RPP_ROWS and not tenant:
                fails.append(("scope", f"{rid} {o} on an owner's home"))
            if tenant and "occupancy_type != Tenant Occupied" in (rv._map()[rid]["gate"] or ""):
                fails.append(("scope", f"{rid} {o} on a rental"))
    return st, rec, fails


def rpp_pair(choice):
    """5c: the same home as an owner's home and as an RPP+ rental."""
    own = build(dict(choice, occupancy_type="Owner Occupied"))
    rent = build(dict(choice, occupancy_type="Tenant Occupied", primary_home_carrier="The Hartford",
                      rental_units_total="1-4", rental_term="Long-term"))
    o1, r1 = evaluate(own)
    o2, r2 = evaluate(rent)
    diff = sorted(rid for rid in set(o1) | set(o2) if o1.get(rid, ("-",))[0] != o2.get(rid, ("-",))[0])
    unexplained = [rid for rid in diff if rid not in RPP_ROWS and rid not in OCCUPANCY_GATED]
    return r1["status"], r2["status"], diff, unexplained


def main(n, out_path, seed=39):
    rng = random.Random(seed)
    profiles = [("pairwise", c) for c in pairwise(rng)] + [("random", random_choice(rng)) for _ in range(n)]
    fails, statuses, rows = collections.Counter(), collections.Counter(), collections.Counter()
    examples = collections.defaultdict(list)
    for kind, c in profiles:
        pd = build(c)
        st, rec, fs = check(pd, rng)
        statuses[(kind, pd["occupancy_type"] == I.RENTAL_OCCUPANCY and "rental" or "owner's home", st)] += 1
        for line in rec["reasons"]:
            for rid in re.findall(r"\[([A-Z]{3}-\d{3})\]", line)[:1]:
                rows[(rid, st)] += 1
        for name, detail in fs:
            fails[name] += 1
            if len(examples[name]) < 5:
                examples[name].append({"profile": pd, "detail": detail})
    pairs = [rpp_pair(random_choice(rng)) for _ in range(500)]
    unexplained = [p for p in pairs if p[3]]
    diff_rows = collections.Counter(rid for p in pairs for rid in p[2])
    status_moves = collections.Counter((p[0], p[1]) for p in pairs)
    report = {
        "profiles": {"pairwise": sum(k == "pairwise" for k, _ in profiles), "random": n},
        "invariant_failures": dict(fails), "examples": dict(examples),
        "statuses": {" / ".join(k): v for k, v in sorted(statuses.items())},
        "deciding_rows": {f"{rid} {st}": v for (rid, st), v in sorted(rows.items())},
        "rpp_pairs": {"homes": len(pairs), "unexplained": len(unexplained), "examples": unexplained[:5],
                      "rows_that_differ": dict(diff_rows.most_common()),
                      "owner_to_rental_status": {f"{a} -> {b}": v for (a, b), v in status_moves.most_common()}},
    }
    json.dump(report, open(out_path, "w", encoding="utf-8"), indent=1, default=str)
    print(json.dumps({k: report[k] for k in ("profiles", "invariant_failures")}, indent=1))
    print("rpp pairs:", report["rpp_pairs"]["homes"], "unexplained:", report["rpp_pairs"]["unexplained"])
    print("owner -> rental:", report["rpp_pairs"]["owner_to_rental_status"])
    print("distinct deciding row / outcome:", len(rows))
    return report


if __name__ == "__main__":
    main(int(sys.argv[1]), sys.argv[2])
