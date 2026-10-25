"""The Python side of the placement parity check (round 43 step 3): placement.panel() on the parity golden's profiles.

usage (cwd = the repo root, no API key needed -- run it with ELIGIBILITY_DOTENV unset):
  python cloudflare/scripts/placement_parity_cases.py OUT.json [--native N] [--seed S]

Writes one JSON list of cases {id, variant, as_of, pd, results, expected}. `pd` and `results` are exactly what the
browser posts to /api/placement (the five property fields; per record carrier, status and the FIRST NON-BLANK string
of missing_info and of reasons); `expected` is placement.panel() run on the FULL records and the FULL property details,
as app.py calls it. So a 0-difference run proves both the port and the reduced request body.

Variants:
  golden   every profile in verification/parity/golden.json.xz at as_of 2026-10; missing_info from the golden's held
           lists; reasons in full for the named profiles, [] for the fuzz profiles (the golden keeps only hashes of
           their texts -- so on those the "Usually X here" line falls back to the status words).
  months   the same profiles at as_of 2025-12 and 2027-02 (other windows, other weights, a different age band year).
  edge     the named profiles with the records made awkward: a blank and a whitespace-only item first in every list,
           runs of Python-only whitespace, a 200-code-point reason with emoji (the 110 cut), the county re-cased and
           padded, a zip of "" -- the rules the port copies from Python (split/strip, code points, round half even).
  literal  the golden variant with the contract read literally: missing_info / reasons cut to their first item even
           when it is blank (expected still from the full records) -- counts what "first item only" loses on real cards.
  native   --native N: the named profiles plus N seeded fuzz profiles re-checked by the native engine
           (export_golden.run_check, zero API, ~1-3 s each) so the fuzz profiles get their real reason texts.
"""
import json
import os
import random
import sys
import time

ROOT = os.getcwd()
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "verification", "parity"))
os.environ.pop("ELIGIBILITY_DOTENV", None)

import export_golden as eg  # noqa: E402
import placement  # noqa: E402

PD_KEYS = ("zip", "county", "year_built", "dwelling_amount", "occupancy_type")


def first_nonblank(items):
    return [x for x in items or [] if isinstance(x, str) and x.strip()][:1]


def browser_body(results, pd, literal=False):
    """What the browser sends: the five property fields and, per record, one item of each list."""
    def cut(items):
        return list(items or [])[:1] if literal else first_nonblank(items)
    return ({k: pd.get(k) for k in PD_KEYS},
            [{"carrier": r.get("carrier"), "status": r.get("status"), "missing_info": cut(r.get("missing_info")),
              "reasons": cut(r.get("reasons"))} for r in results])


def case(cid, variant, as_of, results, pd, literal=False):
    small_pd, small = browser_body(results, pd, literal)
    return {"id": cid, "variant": variant, "as_of": as_of, "pd": small_pd, "results": small,
            "expected": placement.panel(results, pd, as_of=as_of)}


def golden_records(doc, p):
    out = []
    for c in p["cards"]:
        reasons = [doc["strings"][i] for i in c["reasons"]] if c["full"] else []
        out.append({"carrier": c["carrier"], "status": c["status"], "missing_info": list(doc["lists"][c["held"]]),
                    "reasons": reasons})
    return out


def awkward(results, n):
    """The edge variant's records: every list led by "" and a whitespace-only item; odd whitespace inside."""
    ws = "  \x1c　"
    out = []
    for k, r in enumerate(results):
        mi = ["", " \t "] + [f"{ws}{x}\n  {ws}" for x in r["missing_info"]]
        rs = ["", ws] + [f"  {x}\x1d\x1e  tail" for x in r["reasons"]]
        if k % 3 == 0:
            rs.insert(2, "\U0001F3E0 " + "Wind/hail deductible must be at least 2% " * 5 + "\U0001F600 end")
        out.append(dict(r, missing_info=mi, reasons=rs))
    if n % 5 == 0:
        out.append({"carrier": None, "status": "ELIGIBLE"})          # no carrier: maps to no market
    return out


def main(out_path, native=0, seed=43):
    t0 = time.time()
    doc = eg.load(eg.GOLDEN)
    cases = []
    named = [pid for pid in doc["profiles"] if not pid.startswith("fuzz_")]
    for pid, p in doc["profiles"].items():
        recs = golden_records(doc, p)
        cases.append(case(pid, "golden", "2026-10", recs, p["pd"]))
        for as_of in ("2025-12", "2027-02"):
            cases.append(case(pid, "months", as_of, recs, p["pd"]))
        cases.append(case(pid, "literal", "2026-10", recs, p["pd"], literal=True))
    for n, pid in enumerate(named):
        p = doc["profiles"][pid]
        recs = awkward(golden_records(doc, p), n)
        pd = dict(p["pd"])
        if n % 4 == 1 and pd.get("county"):
            pd["county"] = f"  {pd['county'].upper()} "
        elif n % 4 == 2 and pd.get("county"):
            pd["county"] = pd["county"].lower()
        elif n % 4 == 3:
            pd["zip"] = ""
        cases.append(case(pid, "edge", "2026-10", recs, pd))
        # a record with no carrier maps to no market in Python; the Worker rejects it, so the browser leaves it out
        cases[-1]["results"] = [r for r in cases[-1]["results"] if r["carrier"] is not None]
    if native:
        fuzz = sorted(pid for pid in doc["profiles"] if pid.startswith("fuzz_"))
        pick = named + random.Random(seed).sample(fuzz, native)
        for n, pid in enumerate(pick, 1):
            p = doc["profiles"][pid]
            res = eg.run_check(p["pd"], p["checked"])
            cases.append(case(pid, "native", "2026-10", res, p["pd"]))
            if n % 50 == 0:
                print(f"native {n}/{len(pick)} ({time.time() - t0:.0f} s)", flush=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(cases, fh, ensure_ascii=False)
    by = {}
    for c in cases:
        by.setdefault(c["variant"], [0, 0])
        by[c["variant"]][0] += 1
        by[c["variant"]][1] += c["expected"] is not None
    print(f"{len(cases)} cases -> {out_path} in {time.time() - t0:.0f} s: "
          + ", ".join(f"{v} {a} ({b} with a panel)" for v, (a, b) in by.items()))


if __name__ == "__main__":
    args = sys.argv[1:]
    nat = int(args[args.index("--native") + 1]) if "--native" in args else 0
    sd = int(args[args.index("--seed") + 1]) if "--seed" in args else 43
    main(args[0], native=nat, seed=sd)
