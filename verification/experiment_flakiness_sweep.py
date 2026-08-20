"""
Round 12 priorities 1-3: one combined measurement batch.

Every check_eligibility() call returns ALL carriers, so a single batch of N
runs per profile can measure every hard-assert, every xfail, and every
xpass for that profile simultaneously -- rather than paying N API calls per
individual test. Saves the FULL result list per run so any metric can be
recomputed later without re-running.

Usage:  python experiment_flakiness_sweep.py <STANDARD|ALT|COASTAL> <n_runs>

Resumable: re-running continues from whatever is already saved.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eligibility_check import check_eligibility
from profiles import STANDARD_PROFILE, ALT_PROFILE, COASTAL_PPC4_PROFILE

PROFILES = {
    "STANDARD": STANDARD_PROFILE,
    "ALT": ALT_PROFILE,
    "COASTAL": COASTAL_PPC4_PROFILE,
}


def main():
    name = sys.argv[1].upper()
    n_runs = int(sys.argv[2])
    profile = PROFILES[name]
    out_path = os.path.join(os.path.dirname(__file__), f"sweep_{name.lower()}_results.json")

    state = {"runs": []}
    if os.path.exists(out_path):
        with open(out_path) as f:
            state = json.load(f)

    while len(state["runs"]) < n_runs:
        t0 = time.time()
        try:
            result = check_eligibility(profile)
        except Exception as e:
            # Never lose a whole batch to one transient API error.
            print(f"[{name} {len(state['runs'])+1}/{n_runs}] ERROR: {type(e).__name__}: {e}", flush=True)
            state["runs"].append({"error": f"{type(e).__name__}: {e}"})
            with open(out_path, "w") as f:
                json.dump(state, f)
            continue
        state["runs"].append({"carriers": result})
        with open(out_path, "w") as f:
            json.dump(state, f)
        print(f"[{name} {len(state['runs'])}/{n_runs}] {time.time()-t0:.0f}s  {len(result)} carriers", flush=True)

    print(f"=== {name} DONE: {len(state['runs'])} runs saved to {out_path} ===", flush=True)


if __name__ == "__main__":
    main()
