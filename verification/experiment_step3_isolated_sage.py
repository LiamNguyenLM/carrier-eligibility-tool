"""
Step 3 of the prompt-splitting scoping investigation: pilot isolating the
six related Sage documents (the ones implicated in the FPC cross-
contamination finding -- Auros/Occidental/Wilshire as victims,
Trium/SURE/SafePort as the source of the leaked "Classification A/B/C"
terminology) into their own call via check_eligibility(carrier_subset=...),
instead of an even 4-way split of all ~27 carriers.

Measures, per run:
  1. Whether Auros/Occidental/Wilshire resolve to something other than
     INSUFFICIENT_INFORMATION for an FPC-1 (ALT_PROFILE) risk -- same
     pass/fail definition as Step 1's baseline measurement, so the two
     numbers are directly comparable.
  2. Whether "classification" terminology leaks into Auros/Occidental/
     Wilshire's own reasons/citations/notes -- watching explicitly for
     contamination getting WORSE when the six similar documents are
     isolated together, not just better convergence on shared table logic.

Resumable / incremental, same pattern as experiment_step1_baseline.py.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eligibility_check import check_eligibility
from profiles import ALT_PROFILE

N_RUNS = 20
OUT_PATH = os.path.join(os.path.dirname(__file__), "step3_isolated_sage_results.json")

SAGE_ISOLATED_CARRIERS = [
    "Sage_-_Auros_HO3",
    "Sage_-_Occidental_HO3",
    "Sage_-_Wilshire_HO3_-_12.02.2025",
    "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026",
    "Sage_-_SURE_HO-3_-_01.31.2026",
    "Sage_-_SafePort_HO-3_-_01.31.2026",
]

TARGET_CARRIERS = ["Auros", "Occidental", "Wilshire"]


def find(by_carrier, substr):
    matches = [r for c, r in by_carrier.items() if substr.lower() in c.lower()]
    return matches[0] if matches else None


def load_state():
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            return json.load(f)
    return {
        "runs_done": 0,
        "sage": {c: [] for c in TARGET_CARRIERS},
        "contamination": {c: [] for c in TARGET_CARRIERS},
        "missing_carrier_events": [],
    }


def save_state(state):
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, OUT_PATH)


def summarize(state):
    summary = {}
    for c in TARGET_CARRIERS:
        outcomes = state["sage"][c]
        if outcomes:
            summary[f"isolated_sage_{c.lower()}_pass_rate"] = sum(outcomes) / len(outcomes)
        contam = state["contamination"][c]
        if contam:
            summary[f"isolated_sage_{c.lower()}_contamination_rate"] = sum(contam) / len(contam)
    summary["missing_carrier_events"] = len(state["missing_carrier_events"])
    return summary


def main():
    state = load_state()

    while state["runs_done"] < N_RUNS:
        t0 = time.time()
        result = check_eligibility(ALT_PROFILE, carrier_subset=SAGE_ISOLATED_CARRIERS)
        by_carrier = {r["carrier"]: r for r in result}

        run_line = []
        for c in TARGET_CARRIERS:
            r = find(by_carrier, c)
            if r is None:
                state["missing_carrier_events"].append(
                    {"run": state["runs_done"] + 1, "carrier": c}
                )
                run_line.append(f"{c}=MISSING")
                continue
            status = r["status"]
            state["sage"][c].append(status != "INSUFFICIENT_INFORMATION")
            blob = " ".join(
                r.get("reasons", []) + r.get("citations", []) + [r.get("notes", "")]
            ).lower()
            contaminated = "classification" in blob
            state["contamination"][c].append(contaminated)
            run_line.append(f"{c}={status}" + (" [CONTAM]" if contaminated else ""))

        state["runs_done"] += 1
        save_state(state)
        print(
            f"[ISOLATED-SAGE {state['runs_done']}/{N_RUNS}] {time.time()-t0:.0f}s  " + "  ".join(run_line),
            flush=True,
        )

    print("\n=== FINAL SUMMARY (Step 3 experiment A, isolated 6-doc Sage call) ===", flush=True)
    print(json.dumps(summarize(state), indent=2), flush=True)
    print("\nRaw per-run data:", flush=True)
    print(json.dumps(state, indent=2), flush=True)


if __name__ == "__main__":
    main()
