"""
Spike: post-generation guaranteed-lookup verification + single-carrier
repair, scoped FIRST to Progressive HO3's solar case only. Different shape
of problem than Sage's (see Step 2): Progressive's solar exclusion is
confirmed deterministically retrieved into the prompt context on every
single call (guaranteed_carrier_lookup, no ANN/embedding randomness), but
the model sometimes doesn't cite it in the final answer for that one
carrier among ~27 evaluated in one completion. That's a synthesis miss on
an already-solved retrieval problem, not a Sage-style table-reasoning
failure -- so the fix attempted here is much cheaper than restructuring
the whole completion: verify the specific fact made it into the output,
and if not, re-run ONLY that one carrier in isolation (a ~30s single-carrier
call via check_eligibility(carrier_subset=...), not another 27-carrier
completion) and take that result instead.

Not wired into check_eligibility() -- this measures whether the approach
even works before generalizing it to other guaranteed-lookup topics
(PPC, pool) or other carriers. Compare the "final_pass_rate_with_repair"
this produces against Step 1's baseline: 17/20 (85%) with no repair at all.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eligibility_check import check_eligibility
from profiles import ALT_PROFILE

N_RUNS = 20
OUT_PATH = os.path.join(os.path.dirname(__file__), "progressive_repair_spike_results.json")
PROGRESSIVE_HO3 = "Progressive_HO3_-_04.01.2026"


def _find_progressive_ho3(by_carrier):
    for carrier_name, r in by_carrier.items():
        cl = carrier_name.lower()
        if "progressive" in cl and "ho3" in cl and "ho6" not in cl:
            return r
    return None


def _mentions_solar_in_output(r):
    if r is None:
        return False
    blob = " ".join(
        r.get("missing_info", []) + r.get("citations", []) + r.get("reasons", []) + [r.get("notes", "")]
    ).lower()
    return "solar" in blob


def check_eligibility_with_solar_repair(property_details):
    """Returns (result, original_pass, repair_attempted, repair_succeeded).
    original_pass reflects the FIRST full-run result before any repair."""
    result = check_eligibility(property_details)
    by_carrier = {r["carrier"]: r for r in result}
    target = _find_progressive_ho3(by_carrier)

    original_pass = _mentions_solar_in_output(target)
    repair_attempted = False
    repair_succeeded = None

    if target is not None and not original_pass:
        repair_attempted = True
        repaired = check_eligibility(property_details, carrier_subset=[PROGRESSIVE_HO3])
        repaired_r = repaired[0] if repaired else None
        if _mentions_solar_in_output(repaired_r):
            result[result.index(target)] = repaired_r
            repair_succeeded = True
        else:
            repair_succeeded = False
            target["notes"] = (
                target.get("notes", "")
                + " [FLAG: solar exclusion is confirmed retrievable for this carrier but was "
                  "not reflected in the output, even after a single-carrier retry.]"
            ).strip()

    return result, original_pass, repair_attempted, repair_succeeded


def load_state():
    if os.path.exists(OUT_PATH):
        with open(OUT_PATH) as f:
            return json.load(f)
    return {"runs_done": 0, "original_pass": [], "final_pass": [], "repair_attempted": [], "repair_succeeded": []}


def save_state(state):
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, OUT_PATH)


def main():
    state = load_state()
    while state["runs_done"] < N_RUNS:
        t0 = time.time()
        result, original_pass, repair_attempted, repair_succeeded = check_eligibility_with_solar_repair(ALT_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}
        final_target = _find_progressive_ho3(by_carrier)
        final_pass = _mentions_solar_in_output(final_target)

        state["original_pass"].append(original_pass)
        state["final_pass"].append(final_pass)
        state["repair_attempted"].append(repair_attempted)
        state["repair_succeeded"].append(repair_succeeded)
        state["runs_done"] += 1
        save_state(state)
        print(
            f"[REPAIR-SPIKE {state['runs_done']}/{N_RUNS}] {time.time()-t0:.0f}s  "
            f"original_pass={original_pass}  repair_attempted={repair_attempted}  "
            f"repair_succeeded={repair_succeeded}  final_pass={final_pass}",
            flush=True,
        )

    original_rate = sum(state["original_pass"]) / len(state["original_pass"])
    final_rate = sum(state["final_pass"]) / len(state["final_pass"])
    n_attempted = sum(state["repair_attempted"])
    n_succeeded = sum(1 for s in state["repair_succeeded"] if s)
    n_failed_after_retry = sum(1 for s in state["repair_succeeded"] if s is False)

    print("\n=== FINAL SUMMARY (Progressive HO3 solar, post-generation repair spike) ===", flush=True)
    print(json.dumps({
        "original_pass_rate_no_repair": original_rate,
        "final_pass_rate_with_repair": final_rate,
        "repairs_attempted": n_attempted,
        "repairs_succeeded": n_succeeded,
        "repairs_failed_even_after_retry": n_failed_after_retry,
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
