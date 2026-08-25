"""
Has a carrier's verdict rate actually DRIFTED, or is a red test just the
known flakiness landing badly?

Round 13 needed this twice and got it wrong once. Swyfft Lloyds' PPC9
exclusion came back 0/3 and was correctly called drift; Orion came back 1/3
in the same test and was wrongly written up alongside it as a second
regression. At Orion's recorded 40% rate, 1-or-fewer successes in 3 trials
happens ~65% of the time -- it was the single most likely outcome. Two
numbers that look equally bad in a test failure can be worlds apart as
evidence, and eyeballing does not tell them apart.

So: compare a FRESH sample against a PRESERVED earlier one, per carrier,
and report the probability of the fresh result under the old rate. Small
samples are labelled as such rather than being quietly treated as decisive.

Usage:
    python verification/analyze_status_drift.py <fresh.json> <baseline.json>
"""
import json
import os
import sys
from collections import Counter
from math import comb

sys.path.insert(0, os.path.dirname(__file__))
from profiles import normalize_carrier_name

# Carriers with a status this suite ACTUALLY ASSERTS for the STANDARD
# profile. Only these get a p-value, because only for these does a shift
# mean a test will start failing.
#
# Keeping this list honest matters. A first version also listed Allied
# Trust as "expected INSUFFICIENT_INFORMATION" and Sage Occidental as
# "expected ELIGIBLE" -- neither is asserted anywhere, and the Occidental
# one was simply wrong: STANDARD is PPC 9, where the Sage FPC table
# correctly yields INSUFFICIENT_INFORMATION. Allied Trust then produced a
# headline "31% -> 8%, p=0.6%, DRIFT" against an expectation invented by
# this script. Measuring against a made-up baseline is how the round 13
# Swyfft "regression" happened in the first place; do not reintroduce it.
TESTED = [
    ("Swyfft Lloyds", "Swyfft Lloyds", "INELIGIBLE"),
    ("Orion", "Orion", "ELIGIBLE"),
    ("Mercury", "Mercury", "ELIGIBLE"),
]

# Carriers worth watching but with NO asserted status. Their distributions
# are printed for context and explicitly NOT labelled drift.
OBSERVED_ONLY = [
    ("ARI (HOA+)", "ARI (HOA+)"),
    ("Sage Occidental", "Sage Occidental"),
    ("Allied Trust", "Allied Trust"),
]


def load(path):
    """Accepts either a raw sweep (sweep_*_results.json) or a condensed
    baseline from make_status_baseline.py. Raw sweeps are gitignored scratch;
    the condensed baselines in verification/baselines/ are what is committed,
    so drift can be checked against something in the repo rather than a rate
    someone typed into a docstring."""
    with open(path) as f:
        data = json.load(f)
    if "carriers" in data and "runs" not in data:
        return {"_baseline": data["carriers"], "_n": data.get("n_runs", 0)}
    return [r for r in data.get("runs", []) if "carriers" in r]


def find(run, needle):
    target = normalize_carrier_name(needle)
    for c in run["carriers"]:
        if target in normalize_carrier_name(c.get("carrier", "")):
            return c
    return None


def distribution(runs, needle):
    counts = Counter()
    if isinstance(runs, dict) and "_baseline" in runs:
        # Condensed baseline: carrier-name keys vary in separator between
        # runs, so fold them together with the same normalisation used
        # everywhere else rather than trusting exact string keys.
        target = normalize_carrier_name(needle)
        for name, statuses in runs["_baseline"].items():
            if target in normalize_carrier_name(name):
                for status, n in statuses.items():
                    counts[status] += n
        return counts
    for run in runs:
        entry = find(run, needle)
        counts[entry["status"] if entry else "ABSENT"] += 1
    return counts


def binom_le(k, n, p):
    """P(X <= k successes in n trials at rate p)."""
    return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))


def binom_ge(k, n, p):
    return sum(comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k, n + 1))


def main():
    fresh = load(sys.argv[1])
    base = load(sys.argv[2])
    def size(x):
        return x.get("_n", 0) if isinstance(x, dict) else len(x)
    print(f"fresh    : {size(fresh):3d} runs  ({os.path.basename(sys.argv[1])})")
    print(f"baseline : {size(base):3d} runs  ({os.path.basename(sys.argv[2])})")
    print()

    for label, needle, expected in TESTED:
        fd = distribution(fresh, needle)
        bd = distribution(base, needle)
        fn, bn = sum(fd.values()), sum(bd.values())
        if not fn or not bn:
            continue
        fk, bk = fd[expected], bd[expected]
        fr, br = fk / fn, bk / bn

        print(f"{label}  -- expected status {expected}")
        print(f"   baseline {bk:3d}/{bn:<3d} = {br:6.0%}   {dict(bd)}")
        print(f"   fresh    {fk:3d}/{fn:<3d} = {fr:6.0%}   {dict(fd)}")

        # Probability of a result at least this extreme under the OLD rate.
        if fr < br:
            p = binom_le(fk, fn, br)
            direction = "worse"
        else:
            p = binom_ge(fk, fn, br)
            direction = "better"
        if br in (0.0, 1.0) and fr != br:
            note = ("baseline was saturated, so any change is categorical -- "
                    "a rate of exactly 0%/100% cannot produce this by chance")
            print(f"   P(this or {direction} | baseline rate) ~ 0        {note}")
        else:
            print(f"   P(this or {direction} | baseline rate) = {p:6.1%}", end="   ")
            print("DRIFT" if p < 0.05 else "consistent with known variance")
        if fn < 10:
            print(f"   NOTE: fresh n={fn} is small; treat as indicative, not settled")
        print()

    print("-" * 72)
    print("OBSERVED ONLY -- no asserted status, so no drift verdict is given.")
    print("A shift here changes nothing that is currently tested.")
    print("-" * 72)
    for label, needle in OBSERVED_ONLY:
        fd, bd = distribution(fresh, needle), distribution(base, needle)
        if not sum(fd.values()) or not sum(bd.values()):
            continue
        print(f"{label}")
        print(f"   baseline {dict(bd)}")
        print(f"   fresh    {dict(fd)}")
        print()


if __name__ == "__main__":
    main()
