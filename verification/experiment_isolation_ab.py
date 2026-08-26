"""
OQ-1's decisive experiment: does the fabricated-solar contamination survive
when the shared context is removed?

The bleed hypothesis says the round 14 DP3 audit's 7-of-12 fabricated-solar
event happened because check_eligibility() sends EVERY carrier in ONE
completion, so the model attends to its own earlier output. Passing
carrier_subset=[one carrier] turns that into one call per carrier and
removes the shared context entirely.

WHY BOTH ARMS RUN. A clean isolated arm proves nothing by itself: the
COMBINED arm on this same code is already 0/12 contaminated, so "isolation
was clean" is exactly what a clean combined arm would also produce. The
comparison is only informative if the combined arm actually contaminates in
a matched sample. Both arms therefore run on identical code, same profile,
same n -- and if neither contaminates, the honest reading is "underpowered",
not "bleed confirmed".

CONFOUND, stated up front: isolating calls does not change ONLY shared-context
exposure. Each isolated call also carries a far smaller prompt (~1.2k input
tokens vs ~20k) and a different token budget. A difference between arms is
therefore evidence for bleed, not proof of it.

DETECTION. Round 14 shipped _strip_contradicted_property_claims(), which
REMOVES fabricated claims and rewrites the verdict -- so scanning the final
text alone would now hide the very thing being measured. The guard leaves a
"[Intake contradiction]" note whenever it fires, so that note IS the
detector, and surviving raw claims are counted too.

Usage:
    python verification/experiment_isolation_ab.py <combined|isolated> <n_runs>
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eligibility_check import check_eligibility, get_carriers_for_occupancy
from profiles import AUDIT_R14_DP3_PROFILE

# The carriers the manual audit reported as affected, plus everything else
# the DP3 profile evaluates -- the detection surface must match between arms,
# otherwise the comparison is rigged.
AUDIT_AFFECTED = (
    "Foremost", "NatGen_Custom360", "NatGen_Premier_OneChoice",
    "Progressive_DP3", "Sage_-_Markel_DP3", "Sage_-_Occidental_DP3", "Steadily",
)

ASSERTS_PRESENT = re.compile(
    r"(solar panels?\s*(are|is)\s*(present|installed)|"
    r"(property|home|dwelling|risk)\s+(has|have|with)\s+solar|"
    r"has\s+solar\s+panels?|with\s+solar\s+panels?|presence of solar|"
    r"solar panels?\s*:\s*yes)", re.I)
ASSERTS_ABSENT = re.compile(
    r"(no solar|without solar|does not have solar|not have solar|"
    r"absence of solar|solar panels?\s*:\s*no|lacks solar)", re.I)
ADVERSE = re.compile(r"(exclu|ineligib|not eligible|disqualif)", re.I)
GUARD_FIRED = "[intake contradiction]"


def contamination_in(record):
    """Returns a list of evidence strings, empty if the record is clean."""
    hits = []
    notes = record.get("notes", "") or ""
    if GUARD_FIRED in notes.lower() and "solar" in notes.lower():
        hits.append("GUARD FIRED: " + notes[:200])
    items = (record.get("reasons", []) + record.get("citations", [])
             + record.get("missing_info", []) + [notes])
    for item in items:
        if not item or "solar" not in item.lower():
            continue
        if ASSERTS_ABSENT.search(item):
            continue
        status_adverse = record.get("status") in ("INELIGIBLE", "REFER")
        if ASSERTS_PRESENT.search(item) or (status_adverse and ADVERSE.search(item)):
            hits.append(item[:200])
    return hits


def run_combined():
    return check_eligibility(AUDIT_R14_DP3_PROFILE)


def run_isolated(carriers):
    """One call per carrier. No shared context between them."""
    out = []
    for carrier in carriers:
        try:
            out.extend(check_eligibility(AUDIT_R14_DP3_PROFILE, carrier_subset=[carrier]))
        except Exception as e:
            out.append({"carrier": carrier, "status": "ERROR",
                        "reasons": [f"{type(e).__name__}: {e}"], "citations": [],
                        "missing_info": [], "notes": "", "flaw_count": 0})
    return out


def main():
    mode = sys.argv[1].lower()
    n_runs = int(sys.argv[2])
    assert mode in ("combined", "isolated")
    out_path = os.path.join(os.path.dirname(__file__), f"isolation_ab_{mode}.json")

    carriers = get_carriers_for_occupancy(AUDIT_R14_DP3_PROFILE["occupancy_type"])
    state = {"mode": mode, "runs": []}
    if os.path.exists(out_path):
        state = json.load(open(out_path))

    print(f"[{mode}] resuming with {len(state['runs'])}; target {n_runs}; "
          f"{len(carriers)} carriers per execution", flush=True)

    while len(state["runs"]) < n_runs:
        t0 = time.time()
        try:
            result = run_combined() if mode == "combined" else run_isolated(carriers)
        except Exception as e:
            print(f"[{mode}] EXECUTION FAILED: {type(e).__name__}: {e}", flush=True)
            time.sleep(15)
            continue
        if len(result) < 5:
            print(f"[{mode}] INVALID ({len(result)} records), retrying", flush=True)
            time.sleep(5)
            continue

        contaminated = {}
        for rec in result:
            hits = contamination_in(rec)
            if hits:
                contaminated[rec.get("carrier", "?")] = hits

        state["runs"].append({"carriers": result, "contaminated": contaminated})
        json.dump(state, open(out_path, "w"))
        flag = f"  <<< CONTAMINATED: {list(contaminated)}" if contaminated else ""
        print(f"[{mode} {len(state['runs'])}/{n_runs}] {time.time()-t0:.0f}s "
              f"{len(result)} records{flag}", flush=True)

    n_bad = sum(1 for r in state["runs"] if r["contaminated"])
    print(f"=== {mode} DONE: {n_bad}/{len(state['runs'])} executions contaminated ===",
          flush=True)


if __name__ == "__main__":
    main()
