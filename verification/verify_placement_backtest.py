"""Round 33 step 1: re-run Claude's 300-home placement backtest with the app's placement.py.

usage: python verification/verify_placement_backtest.py [backtest_test_homes.csv backtest_results.csv]
       [--tables DIR] [--as-of 2026-04]

Needs the git-ignored pilot_structured_rules/backtest/ files (round 32 step 3); no data lives here.
For each home whose actual market the check did not rule out, rank the candidate markets with
history before --as-of and count how often the actual market is first / in the top 3. Claude's
reference run (pilot_structured_rules/placement/verify_backtest.py): 132/210 in the top 3.
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


def run(homes, results, tables=placement.DATA_DIR, as_of="2026-04"):
    T = placement.load_tables(tables)
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
            order = [m for m, _ in placement.rank(T, cands, h["zip"], h["county"], yb, cova, as_of, year=2026)]
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
