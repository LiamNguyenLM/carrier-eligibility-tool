"""Round 27 step 7 (real API cost, cents): one real Luna check, pilot ON, Sage batch OFF or ON.
usage: python measure_r27s7.py <PROFILE> <OFF|ON> <label> <out.jsonl>
Records usage per call, wall, cost, buckets, every final record and every prompt."""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "verification"))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(".env")
import eligibility_check as ec  # noqa: E402
import measure_rules_pilot as M  # noqa: E402
import profiles as P  # noqa: E402

prof, batch, label, out = sys.argv[1:5]
LIVE = dict(P.LIVE_PROFILE)
BEXAR = dict(LIVE, county="Bexar", zip="")
PROFILES = {"LIVE": (LIVE, P.LIVE_CHECKED), "LIVE+Bexar": (BEXAR, P.LIVE_CHECKED),
            "LIVE+Bexar+7mi/No": (dict(BEXAR, fire_station_miles="7", hydrant_1000ft="No"), P.LIVE_CHECKED),
            "OLD": (M.PROFILES["OLD"], None), "CLEAN": (M.PROFILES["CLEAN"], None),
            "STRESS": (M.PROFILES["STRESS"], None)}
pd, checked = PROFILES[prof]
ec.RULES_PILOT = True
ec.RULES_SAGE_BATCH = batch == "ON"
prompts = []
real = ec._complete


def recording(system, user, max_tokens):
    raw, usage = real(system, user, max_tokens)
    prompts.append({"pilot": "RULE CHECK:" in user, "user": user, "raw": raw})
    return raw, usage


ec._complete = recording
t0 = time.perf_counter()
res = ec.check_eligibility(dict(pd), checked_topics=list(checked) if checked else None)
wall = round(time.perf_counter() - t0, 1)
usage = dict(ec.LAST_CALL_USAGE)
rec = {"profile": prof, "batch": batch, "label": label, "commit": os.popen("git rev-parse --short HEAD").read().strip(),
       "model": ec.ELIGIBILITY_MODEL, "wall": wall,
       "calls": {k: ({x: v.get(x) for x in ("input_tokens", "cache_read_input_tokens", "output_tokens")} if v else None)
                 for k, v in usage.items()},
       "cost": round(sum(M._cost(v) for v in usage.values()), 5),
       "buckets": {k: len(v) for k, v in ec.assign_buckets(res).items()},
       "records": res, "prompts": prompts}
with open(out, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
print(json.dumps({k: rec[k] for k in ("profile", "batch", "label", "wall", "calls", "cost", "buckets")}))
