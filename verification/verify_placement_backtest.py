"""Round 33 step 1: re-run Claude's 300-home placement backtest with the app's placement.py.

usage: python verification/verify_placement_backtest.py [backtest_test_homes.csv backtest_results.csv]
       [--tables DIR] [--as-of 2026-04]

Needs the git-ignored pilot_structured_rules/backtest/ files (round 32 step 3); no data lives here.
For each home whose actual market the check did not rule out, rank the candidate markets with
history before --as-of and count how often the actual market is first / in the top 3.
Round 34 (2026-10-09): Claude's builder now cleans HawkSoft's county (a Texas county as given, matched
case-insensitively; else the ZIP's main county from zip_counties.csv; else blank), and the test homes'
counties are cleaned the same way here (county_cleaner, as placement_data.county_cleaner). Claude's
reference run (verify_backtest.py with the repo root as REF_DIR): 131/210 in the top 3, 37.1% top 1.
Was 132/210 before the cleaning (round 33).
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import placement  # noqa: E402

BT = os.path.join(ROOT, "pilot_structured_rules", "backtest")


def county_cleaner(ref_dir=ROOT):
    """(county, zip) -> the cleaned county, exactly as Claude's placement_data.county_cleaner."""
    def rows(name):
        with open(os.path.join(ref_dir, name), encoding="utf-8") as fh:
            return list(csv.DictReader(line for line in fh if not line.startswith("#")))
    canon = {r["county"].strip().lower(): r["county"].strip() for r in rows("texas_counties.csv")}
    valid = set(canon.values())
    best = {}
    for r in rows("zip_counties.csv"):
        z, c, share = r["zip"].strip(), canon.get(r["county"].strip().lower(), ""), float(r.get("share") or 0)
        if c in valid and share > best.get(z, ("", -1))[1]:
            best[z] = (c, share)

    def clean(county, zip5):
        return canon.get((county or "").strip().lower()) or best.get(zip5, ("", 0))[0]
    return clean


def run(homes, results, tables=placement.DATA_DIR, as_of="2026-04", clean=None):
    T = placement.load_tables(tables)
    clean = clean or county_cleaner()
    with open(results, encoding="utf-8", newline="") as fh:
        res = defaultdict(list)
        for r in csv.DictReader(fh):
            res[r["home_id"]].append({"carrier": r["program"], "status": r["status"]})
    n = hit1 = hit3 = 0
    with open(homes, encoding="utf-8", newline="") as fh:
        for h in csv.DictReader(fh):
            actual = "Swyfft Benchmark" if h["actual_market"].startswith("Swyfft Benchmark") else h["actual_market"]
            cands = placement.candidates(res[h["home_id"]], T)
            if actual not in cands:
                continue
            yb = int(h["year_built"]) if h["year_built"].isdigit() else None
            cova = float(h["coverage_a"]) if h["coverage_a"] else None
            order = [m for m, _ in placement.rank(T, cands, h["zip"], clean(h["county"], h["zip"]), yb, cova, as_of,
                                                     year=2026)]
            n += 1
            hit1 += order[0] == actual
            hit3 += actual in order[:3]
    return n, hit1, hit3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("homes", nargs="?", default=os.path.join(BT, "backtest_test_homes.csv"))
    ap.add_argument("results", nargs="?", default=os.path.join(BT, "backtest_results.csv"))
    ap.add_argument("--tables", default=placement.DATA_DIR)
    ap.add_argument("--as-of", default="2026-04")
    a = ap.parse_args()
    n, hit1, hit3 = run(a.homes, a.results, a.tables, a.as_of)
    print(f"homes {n}: top1 {hit1 / n:.1%}  top3 {hit3 / n:.1%}  ({hit3}/{n})")


if __name__ == "__main__":
    main()
