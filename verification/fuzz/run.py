"""Round 38 step 7: run the zero-API self-audit over seeded profiles in parallel (cores - 2 workers).

usage: python verification/fuzz/run.py <first seed> <count> <out dir> [workers]

Writes to <out dir>:
  results.jsonl    one line per profile: seed, seconds, statuses, failures (and an error, if the check raised)
  coverage.json    map-line outcomes seen: {row_id: {outcome: count}}
It never calls a model; the fake answers Eligible to whatever it is asked."""
import json
import multiprocessing as mp
import os
import sys
import time
import traceback
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def _init():
    global checks, gen
    import checks  # noqa: F401 -- loads the store and the rules once per worker
    import gen     # noqa: F401


def one(seed):
    t = time.perf_counter()
    try:
        pd, checked = gen.profile(seed)
        fails, coverage, base = checks.check_profile(pd, checked, seed)
        return {"seed": seed, "s": round(time.perf_counter() - t, 2), "fails": fails, "coverage": coverage,
                "statuses": {r.get("carrier"): r.get("status") for r in base}}
    except Exception:                                  # noqa: BLE001 -- a crash is a finding
        return {"seed": seed, "s": round(time.perf_counter() - t, 2), "fails": [], "coverage": {},
                "error": traceback.format_exc()[-1500:]}


def main(first, count, out, workers=None):
    os.makedirs(out, exist_ok=True)
    workers = workers or max(1, (os.cpu_count() or 4) - 2)
    cov = defaultdict(Counter)
    cov_path = os.path.join(out, "coverage.json")
    if os.path.exists(cov_path):
        for rid, c in json.load(open(cov_path, encoding="utf-8")).items():
            cov[rid].update(c)
    with mp.Pool(workers, initializer=_init) as pool, open(os.path.join(out, "results.jsonl"), "a",
                                                             encoding="utf-8") as fh:
        for i, res in enumerate(pool.imap_unordered(one, range(first, first + count), chunksize=1), 1):
            for rid, outcome in res.pop("coverage").items():
                cov[rid][outcome] += 1
            fh.write(json.dumps(res) + "\n")
            fh.flush()
            if i % 50 == 0:
                json.dump(cov, open(cov_path, "w", encoding="utf-8"))
    json.dump(cov, open(cov_path, "w", encoding="utf-8"))


if __name__ == "__main__":
    main(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else None)
