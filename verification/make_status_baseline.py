"""
Condense a sweep_*_results.json into a small, COMMITTABLE status baseline.

Why this exists: round 13 spent real effort chasing two "regressions" that
were not regressions, because the rates quoted in test docstrings were from
n=5 samples and the far larger sweeps that contradicted them were sitting in
untracked, gitignored scratch files. A raw sweep is ~700KB-1.4MB of run data
-- too heavy to commit and not reviewable anyway -- but the per-carrier
status distribution is a few KB and is the only part anyone compares against.

Committing the distribution means the next person to see a red flakiness
test can check it against a real baseline in the repo instead of a number
someone typed into a docstring months ago.

Usage:
    python verification/make_status_baseline.py <sweep.json> <profile-label> <out.json>
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))
from profiles import normalize_carrier_name


def main():
    sweep_path, label, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    with open(sweep_path) as f:
        data = json.load(f)
    runs = [r for r in data.get("runs", []) if "carriers" in r]

    per_carrier = {}
    for run in runs:
        for entry in run["carriers"]:
            name = entry.get("carrier", "")
            per_carrier.setdefault(name, Counter())[entry.get("status", "?")] += 1

    baseline = {
        "profile": label,
        "n_runs": len(runs),
        "source_file": os.path.basename(sweep_path),
        "note": (
            "Per-carrier status distribution only. Compare a fresh sweep against this "
            "with analyze_status_drift.py before believing any 'regressed from X%' claim "
            "written in a test docstring."
        ),
        "carriers": {
            name: dict(counts) for name, counts in sorted(per_carrier.items())
        },
    }
    with open(out_path, "w") as f:
        json.dump(baseline, f, indent=2, sort_keys=True)
    print(f"wrote {out_path}: {len(runs)} runs, {len(per_carrier)} carriers")


if __name__ == "__main__":
    main()
