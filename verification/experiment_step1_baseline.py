"""
Step 1 of the prompt-splitting scoping investigation (see conversation /
CLAUDE.md flakiness policy): get REAL pass-rate numbers for the three
already-suspected-flaky baseline cases against the CURRENT single combined
prompt, before touching anything. Not a pytest file on purpose -- this is a
throwaway measurement script, run once, whose output feeds a decision.

Writes incremental progress to stdout (so a background run is watchable)
and to a JSON file after every single API call (so a partial run is never
lost if this is interrupted).
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eligibility_check import check_eligibility
from profiles import STANDARD_PROFILE, ALT_PROFILE

N_RUNS = 20
OUT_PATH = os.path.join(os.path.dirname(__file__), "step1_baseline_results.json")

SAGE_CARRIERS = ["Auros", "Occidental", "Wilshire"]


def find(by_carrier, substr):
    matches = [r for c, r in by_carrier.items() if substr.lower() in c.lower()]
    return matches[0] if matches else None


def load_state():
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            return json.load(f)
    return {
        "alt_runs_done": 0,
        "std_runs_done": 0,
        "sage": {c: [] for c in SAGE_CARRIERS},
        "progressive_ho3_solar": [],
        "sage_occidental_pool_fence": [],
    }


def save_state(state):
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, OUT_PATH)


def summarize(state):
    summary = {}
    for c in SAGE_CARRIERS:
        outcomes = state["sage"][c]
        if outcomes:
            summary[f"sage_{c.lower()}_pass_rate"] = sum(outcomes) / len(outcomes)
    if state["progressive_ho3_solar"]:
        summary["progressive_ho3_solar_pass_rate"] = (
            sum(state["progressive_ho3_solar"]) / len(state["progressive_ho3_solar"])
        )
    if state["sage_occidental_pool_fence"]:
        summary["sage_occidental_pool_fence_pass_rate"] = (
            sum(state["sage_occidental_pool_fence"]) / len(state["sage_occidental_pool_fence"])
        )
    return summary


def main():
    state = load_state()

    while state["alt_runs_done"] < N_RUNS:
        t0 = time.time()
        result = check_eligibility(ALT_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}

        run_line = []
        for c in SAGE_CARRIERS:
            r = find(by_carrier, c)
            status = r["status"] if r else "NOT_FOUND"
            state["sage"][c].append(status != "INSUFFICIENT_INFORMATION")
            run_line.append(f"{c}={status}")

        prog = [
            r for cname, r in by_carrier.items()
            if "progressive" in cname.lower() and "ho3" in cname.lower() and "ho6" not in cname.lower()
        ]
        r = prog[0] if prog else None
        blob = " ".join((r.get("missing_info", []) + r.get("citations", [])) if r else []).lower()
        prog_pass = "solar" in blob
        state["progressive_ho3_solar"].append(prog_pass)
        run_line.append(f"Progressive_HO3_solar={prog_pass}")

        state["alt_runs_done"] += 1
        save_state(state)
        print(
            f"[ALT {state['alt_runs_done']}/{N_RUNS}] {time.time()-t0:.0f}s  " + "  ".join(run_line),
            flush=True,
        )

    while state["std_runs_done"] < N_RUNS:
        t0 = time.time()
        result = check_eligibility(STANDARD_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}
        r = find(by_carrier, "Occidental")
        blob = " ".join(
            (r.get("reasons", []) + r.get("citations", []) + r.get("missing_info", [])) if r else []
        ).lower()
        found = "fenc" in blob or "gate" in blob
        state["sage_occidental_pool_fence"].append(found)
        state["std_runs_done"] += 1
        save_state(state)
        print(
            f"[STD {state['std_runs_done']}/{N_RUNS}] {time.time()-t0:.0f}s  pool_fence_found={found}",
            flush=True,
        )

    print("\n=== FINAL SUMMARY (Step 1 baseline, current single combined prompt) ===", flush=True)
    print(json.dumps(summarize(state), indent=2), flush=True)
    print("\nRaw per-run data:", flush=True)
    print(json.dumps(state, indent=2), flush=True)


if __name__ == "__main__":
    main()
