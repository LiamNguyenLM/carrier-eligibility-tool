"""
Round 12 priorities 1-3: one combined measurement batch.

Every check_eligibility() call returns ALL carriers, so a single batch of N
runs per profile can measure every hard-assert, every xfail, and every
xpass for that profile simultaneously -- rather than paying N API calls per
individual test. Saves the FULL result list per run so any metric can be
recomputed later without re-running.

Usage:  python experiment_flakiness_sweep.py <STANDARD|ALT|COASTAL> <n_runs>

Resumable: re-running continues from whatever is already saved.

CHANGED (round 13): the first COASTAL A/B attempt produced only 6/16 and
7/16 real completions. Every one of the 19 failures was the identical
string "APIConnectionError: Connection error." in a single contiguous tail,
and both files' last writes were 3 seconds apart -- a transient
connectivity loss that hit both concurrently-running processes at the same
wall-clock moment, NOT a per-call model failure and NOT a recurrence of the
old JSON-truncation bug. The reason it cost 19 slots instead of 19 seconds
of retrying is a harness bug, fixed below:

  1. `while len(state["runs"]) < n_runs` counted ERROR records toward the
     target, so each failure permanently consumed a slot that a successful
     run was supposed to fill. The target now counts completions only.
  2. There was no retry, so a transient error was treated as a final
     verdict on that slot. Transient errors now retry with exponential
     backoff before giving up on the attempt.
  3. There was no circuit breaker, so once connectivity dropped, the loop
     spun through every remaining slot in a few seconds. Consecutive
     failures now abort the batch with a nonzero exit code, leaving the
     saved completions intact and resumable.

Errors are kept (they are evidence) but in a separate `errors` list, so
`runs` means "real trials" and any analysis over it can no longer silently
average in non-completions.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eligibility_check import check_eligibility
from profiles import (STANDARD_PROFILE, ALT_PROFILE, COASTAL_PPC4_PROFILE,
                      AUDIT_R14_DP3_PROFILE)

PROFILES = {
    "STANDARD": STANDARD_PROFILE,
    "ALT": ALT_PROFILE,
    "COASTAL": COASTAL_PPC4_PROFILE,
    "DP3": AUDIT_R14_DP3_PROFILE,
}

# Retry policy for a single attempt. Transient network faults in the
# observed outage lasted long enough that an immediate retry would also
# have failed, so back off rather than hammering.
MAX_ATTEMPT_RETRIES = 4
BACKOFF_BASE_SECONDS = 5

# Circuit breaker: if this many run-slots in a row exhaust their retries,
# the environment is down, not flaky. Stop and preserve what we have.
MAX_CONSECUTIVE_FAILURES = 3

# Errors worth retrying. Anything else (a bug in our own code, a bad
# request) should surface immediately rather than being retried 4 times.
TRANSIENT_ERROR_NAMES = {
    "APIConnectionError",
    "APIConnectionTimeoutError",
    "APITimeoutError",
    "APIStatusError",
    "InternalServerError",
    "RateLimitError",
    "OverloadedError",
    "ServiceUnavailableError",
}

# A completion is only a real trial if the pipeline actually had carrier
# documents to reason over. check_eligibility() does NOT raise when
# retrieval comes back empty or when the model's JSON fails to parse -- it
# returns a short placeholder list ("Parse Error", "No carriers with
# retrieved information"). Recorded naively, those look exactly like
# successful runs and would silently average into every downstream metric.
#
# This bit us for real: shared_resources.DB_FOLDER is the RELATIVE path
# "./carrier_docs_db", so launching this script with the working directory
# set to verification/ (rather than the repo root) makes Chroma silently
# open a brand-new EMPTY database instead of failing. Every run then
# "succeeded" in 4 seconds with a 139-token prompt and one placeholder
# carrier. Both guards below exist so that specific silent failure, and
# anything else that empties the context, is loud instead.
MIN_CARRIERS_FOR_VALID_RUN = 5

_PLACEHOLDER_CARRIER_NAMES = {
    "parse error",
    "no carriers provided",
    "no carriers with retrieved information",
}


def _validate_completion(result):
    """Return None if this is a real trial, else a string explaining why not."""
    if not isinstance(result, list) or len(result) < MIN_CARRIERS_FOR_VALID_RUN:
        names = [str(r.get("carrier", "?")) for r in (result or [])]
        return (
            f"pipeline returned only {len(result or [])} carrier record(s) "
            f"({names}) -- expected at least {MIN_CARRIERS_FOR_VALID_RUN}. "
            f"Retrieval or JSON parsing failed; this is not a valid trial."
        )
    for r in result:
        if str(r.get("carrier", "")).strip().lower() in _PLACEHOLDER_CARRIER_NAMES:
            return f"pipeline returned the placeholder record {r.get('carrier')!r} -- not a valid trial."
    return None


def _assert_database_is_loaded():
    """Fail immediately, before burning any API calls, if the vectorstore
    this process opened has no carriers in it."""
    from eligibility_check import get_all_carriers
    carriers = get_all_carriers()
    if len(carriers) < MIN_CARRIERS_FOR_VALID_RUN:
        sys.exit(
            f"ABORT: the Chroma database this process opened contains "
            f"{len(carriers)} carrier(s). shared_resources.DB_FOLDER is the "
            f"RELATIVE path './carrier_docs_db' -- run this script from the "
            f"REPO ROOT (python verification/experiment_flakiness_sweep.py ...), "
            f"not from inside verification/."
        )
    print(f"  database OK: {len(carriers)} carriers loaded", flush=True)


def _load_state(out_path):
    """Load prior state, migrating the legacy shape (error records stored
    inline in `runs`) to the split runs/errors shape."""
    state = {"runs": [], "errors": []}
    if not os.path.exists(out_path):
        return state
    with open(out_path) as f:
        prior = json.load(f)
    state["errors"] = prior.get("errors", [])
    migrated = 0
    for record in prior.get("runs", []):
        if "error" in record:
            state["errors"].append({
                "error": record["error"],
                "migrated_from_runs": True,
            })
            migrated += 1
        else:
            state["runs"].append(record)
    if migrated:
        print(
            f"  migrated {migrated} legacy error record(s) out of `runs` -- "
            f"`runs` now holds {len(state['runs'])} real completion(s)",
            flush=True,
        )
    return state


def _save(out_path, state):
    with open(out_path, "w") as f:
        json.dump(state, f)


def _attempt(profile):
    """One run slot, with retries. Returns (result, None) or (None, error_string)."""
    last_error = None
    for attempt in range(1, MAX_ATTEMPT_RETRIES + 1):
        try:
            return check_eligibility(profile), None
        except Exception as e:
            name = type(e).__name__
            last_error = f"{name}: {e}"
            if name not in TRANSIENT_ERROR_NAMES:
                # Not transient -- retrying will not help and would hide it.
                return None, last_error
            if attempt < MAX_ATTEMPT_RETRIES:
                delay = BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                print(
                    f"    transient {name} (attempt {attempt}/{MAX_ATTEMPT_RETRIES}), "
                    f"retrying in {delay}s",
                    flush=True,
                )
                time.sleep(delay)
    return None, last_error


def main():
    name = sys.argv[1].upper()
    n_runs = int(sys.argv[2])
    profile = PROFILES[name]
    out_path = os.path.join(os.path.dirname(__file__), f"sweep_{name.lower()}_results.json")

    _assert_database_is_loaded()

    state = _load_state(out_path)
    _save(out_path, state)
    print(f"[{name}] resuming with {len(state['runs'])} completion(s); target {n_runs}", flush=True)

    consecutive_failures = 0

    # NOTE: the target counts COMPLETIONS, not slots. A failed attempt no
    # longer consumes budget -- that was the bug that turned one outage
    # into 19 lost trials.
    while len(state["runs"]) < n_runs:
        t0 = time.time()
        result, error = _attempt(profile)

        if error is not None:
            consecutive_failures += 1
            print(
                f"[{name} {len(state['runs'])}/{n_runs}] FAILED after retries: {error}",
                flush=True,
            )
            state["errors"].append({
                "error": error,
                "after_completions": len(state["runs"]),
                "consecutive_failures": consecutive_failures,
            })
            _save(out_path, state)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(
                    f"=== {name} ABORTED: {consecutive_failures} consecutive failures. "
                    f"{len(state['runs'])} completion(s) preserved in {out_path}; "
                    f"re-run this same command to resume. ===",
                    flush=True,
                )
                sys.exit(1)
            continue

        invalid = _validate_completion(result)
        if invalid is not None:
            consecutive_failures += 1
            print(f"[{name} {len(state['runs'])}/{n_runs}] INVALID RUN: {invalid}", flush=True)
            state["errors"].append({
                "error": "InvalidRun: " + invalid,
                "after_completions": len(state["runs"]),
                "consecutive_failures": consecutive_failures,
            })
            _save(out_path, state)
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(
                    f"=== {name} ABORTED: {consecutive_failures} consecutive invalid/failed runs. "
                    f"{len(state['runs'])} completion(s) preserved in {out_path}. ===",
                    flush=True,
                )
                sys.exit(1)
            continue

        consecutive_failures = 0
        state["runs"].append({"carriers": result})
        _save(out_path, state)
        print(
            f"[{name} {len(state['runs'])}/{n_runs}] {time.time()-t0:.0f}s  {len(result)} carriers",
            flush=True,
        )

    print(
        f"=== {name} DONE: {len(state['runs'])} completion(s) "
        f"({len(state['errors'])} error record(s)) saved to {out_path} ===",
        flush=True,
    )


if __name__ == "__main__":
    main()
