"""Round 27 step 7 (real API cost, cents): one real Luna check, pilot ON, Sage batch OFF or ON.
usage: python measure_sage_batch.py <PROFILE> <OFF|ON> <label> <out.jsonl> [HO3 OFF|ON] [DP OFF|ON]
(round 29: the HO3 and DP batch switches; both default OFF)
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
ho3 = sys.argv[5] if len(sys.argv) > 5 else "OFF"
dp = sys.argv[6] if len(sys.argv) > 6 else "OFF"
LIVE = dict(P.LIVE_PROFILE)
BEXAR = dict(LIVE, county="Bexar", zip="")
PROFILES = {"LIVE": (LIVE, P.LIVE_CHECKED), "LIVE+Bexar": (BEXAR, P.LIVE_CHECKED),
            "LIVE+Bexar+7mi/No": (dict(BEXAR, fire_station_miles="7", hydrant_1000ft="No"), P.LIVE_CHECKED),
            "OLD": (M.PROFILES["OLD"], None), "CLEAN": (M.PROFILES["CLEAN"], None),
            "STRESS": (M.PROFILES["STRESS"], None),
            # round 28 step 4: occupancy and ownership on the live form's profile, County Bexar
            "SEASONAL": (dict(BEXAR, occupancy_type="Seasonal"), P.LIVE_CHECKED),
            "SECONDARY": (dict(BEXAR, occupancy_type="Secondary Home"), P.LIVE_CHECKED),
            "TRUST": (dict(BEXAR, ownership_type="Trust"), P.LIVE_CHECKED),
            # round 29 step 8: the dwelling fire (DP) batch's profiles
            "LIVE+Tenant": (dict(LIVE, occupancy_type="Tenant Occupied"), P.LIVE_CHECKED),
            "OLD+Tenant": (dict(M.PROFILES["OLD"], occupancy_type="Tenant Occupied"), None),
            "Tenant+LLC": (dict(BEXAR, occupancy_type="Tenant Occupied", ownership_type="LLC"), P.LIVE_CHECKED),
            "VACANT": (dict(BEXAR, occupancy_type="Vacant"), P.LIVE_CHECKED),
            "CONDO": (dict(BEXAR, dwelling_type="Condo"), P.LIVE_CHECKED),
            # round 30: the primary-home questions (step 1) and condo routing (step 4)
            "SEASONAL+Chubb40": (dict(BEXAR, occupancy_type="Seasonal", primary_home_carrier="Chubb",
                                      primary_home_miles=40), P.LIVE_CHECKED),
            "SEASONAL+Unknown": (dict(BEXAR, occupancy_type="Seasonal", primary_home_carrier="Unknown",
                                      primary_home_miles=None), P.LIVE_CHECKED),
            "SECONDARY+Chubb40": (dict(BEXAR, occupancy_type="Secondary Home", primary_home_carrier="Chubb",
                                       primary_home_miles=40), P.LIVE_CHECKED),
            "CONDO+Tenant": (dict(BEXAR, dwelling_type="Condo", occupancy_type="Tenant Occupied"), P.LIVE_CHECKED),
            "CONDO+Seasonal": (dict(BEXAR, dwelling_type="Condo", occupancy_type="Seasonal"), P.LIVE_CHECKED)}
pd, checked = PROFILES[prof]
ec.RULES_PILOT = True
ec.RULES_SAGE_BATCH = batch == "ON"
ec.RULES_HO3_BATCH = ho3 == "ON"
if hasattr(ec, "RULES_DP_BATCH"):
    ec.RULES_DP_BATCH = dp == "ON"
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
rec = {"profile": prof, "batch": batch, "ho3": ho3, "dp": dp, "label": label, "commit": os.popen("git rev-parse --short HEAD").read().strip(),
       "model": ec.ELIGIBILITY_MODEL, "wall": wall,
       "calls": {k: ({x: v.get(x) for x in ("input_tokens", "cache_read_input_tokens", "output_tokens")} if v else None)
                 for k, v in usage.items()},
       "cost": round(sum(M._cost(v) for v in usage.values() if v), 5),
       "buckets": {k: len(v) for k, v in ec.assign_buckets(res).items()},
       "records": res, "prompts": prompts}
with open(out, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
print(json.dumps({k: rec[k] for k in ("profile", "batch", "label", "wall", "calls", "cost", "buckets")}))
