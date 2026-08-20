"""
Round 12 audit investigation: 5 fresh check_eligibility(COASTAL_PPC4_PROFILE)
runs, full result dicts saved per run (not just a boolean), so every
finding in the round 12 audit can be checked against the SAME real data
instead of requiring a separate run per finding. Also satisfies finding
2's explicit "run 3-5 times, report the actual pass rate" requirement for
ARI HOA+'s cross-contamination check.

Not a pytest file -- a one-time data-gathering script, same pattern as
the prior rounds' experiment_step*.py scripts.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eligibility_check import check_eligibility
from profiles import COASTAL_PPC4_PROFILE

N_RUNS = 5
OUT_PATH = os.path.join(os.path.dirname(__file__), "round12_investigation_results.json")


def load_state():
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            return json.load(f)
    return {"runs_done": 0, "runs": []}


def save_state(state):
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, OUT_PATH)


def main():
    state = load_state()
    while state["runs_done"] < N_RUNS:
        t0 = time.time()
        result = check_eligibility(COASTAL_PPC4_PROFILE)
        state["runs"].append(result)
        state["runs_done"] += 1
        save_state(state)
        print(f"[ROUND12 {state['runs_done']}/{N_RUNS}] {time.time()-t0:.0f}s  {len(result)} carriers returned", flush=True)

    print("\n=== DONE -- all runs saved to round12_investigation_results.json ===", flush=True)


if __name__ == "__main__":
    main()
