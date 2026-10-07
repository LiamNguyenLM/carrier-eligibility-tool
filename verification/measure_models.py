"""Round 28 step 6 (2026-10-07): one real check on a given model, pilot ON and
Sage batch ON, recorded for the Haiku 5.5 vs Luna comparison. Real API cost.
Measurement only: the production default stays gpt-6-luna.

usage: python verification/measure_models.py <model> <effort|-> <PROFILE> <label> <out.jsonl>
PROFILE: LIVE, LIVE+Bexar, OLD, CLEAN, STRESS, or a Tier 2 baseline profile (ALT, COASTAL_PPC4,
OWNERSHIP_BASE). Each call's raw answer is checked against the carrier enum the call sent.

Prices per 1M tokens (below 100K input): gpt-6-luna in $0.10, cached $0.01, out $0.50.
claude-haiku-5-5 in $0.10, out $0.50 (Anthropic's page, 2026-10-07); cache read $0.01 and cache
write $0.125 ASSUMED at Anthropic's usual 0.1x / 1.25x of input -- not confirmed."""
import json
import os
import re
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

model, effort, prof, label, out = sys.argv[1:6]
LIVE = dict(P.LIVE_PROFILE)
PROFILES = {"LIVE": (LIVE, P.LIVE_CHECKED), "LIVE+Bexar": (dict(LIVE, county="Bexar", zip=""), P.LIVE_CHECKED),
            **{k: (M.PROFILES[k], None) for k in ("OLD", "CLEAN", "STRESS", "ALT", "COASTAL_PPC4",
                                                    "OWNERSHIP_BASE")}}
PRICE = {"gpt": {"in": 0.10, "cached": 0.01, "write": 0.0, "out": 0.50},
         "claude": {"in": 0.10, "cached": 0.01, "write": 0.125, "out": 0.50}}
pd, checked = PROFILES[prof]
ec.ELIGIBILITY_MODEL = model
ec.ELIGIBILITY_EFFORT = None if effort == "-" else effort
ec.RULES_PILOT = True
ec.RULES_SAGE_BATCH = True
calls = []
real = ec._complete


def recording(system, user, max_tokens):
    enum = list(getattr(ec._CALL, "carriers", None) or [])
    t0 = time.perf_counter()
    raw, usage = real(system, user, max_tokens)
    try:
        recs = json.loads(raw).get("carriers", [])
    except (ValueError, AttributeError):
        recs = None
    calls.append({"pilot": "RULE CHECK:" in user, "enum": enum, "wall": round(time.perf_counter() - t0, 1),
                  "usage": {k: v for k, v in usage.items() if k != "stop_reason"},
                  "stop_reason": str(usage.get("stop_reason")),
                  "parsed": recs is not None,
                  "names_outside_enum": None if recs is None else
                  sorted({r.get("carrier") for r in recs if isinstance(r, dict)} - set(enum)),
                  "missing_status": None if recs is None else
                  sum(1 for r in recs if not isinstance(r, dict) or r.get("status") not in
                      ("ELIGIBLE", "INELIGIBLE", "REFER", "INSUFFICIENT_INFORMATION")),
                  "omitted": None if recs is None else
                  sorted(set(enum) - {r.get("carrier") for r in recs if isinstance(r, dict)}),
                  "raw": raw})
    return raw, usage


ec._complete = recording
t0 = time.perf_counter()
res = ec.check_eligibility(dict(pd), checked_topics=list(checked) if checked else None)
wall = round(time.perf_counter() - t0, 1)
price = PRICE["gpt" if model.startswith("gpt") else "claude"]
cost = sum((c["usage"].get("input_tokens", 0) * price["in"] + c["usage"].get("cache_read_input_tokens", 0) * price["cached"]
            + c["usage"].get("cache_creation_input_tokens", 0) * price["write"]
            + c["usage"].get("output_tokens", 0) * price["out"]) / 1e6 for c in calls)
rec = {"model": model, "effort": effort, "profile": prof, "label": label,
       "commit": os.popen("git rev-parse --short HEAD").read().strip(), "wall": wall, "cost": round(cost, 5),
       "calls": calls, "buckets": {k: len(v) for k, v in ec.assign_buckets(res).items()},
       "records": res}
with open(out, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
print(json.dumps({"model": model, "effort": effort, "profile": prof, "label": label, "wall": wall,
                  "cost": rec["cost"], "buckets": rec["buckets"],
                  "calls": [{k: c[k] for k in ("pilot", "wall", "usage", "names_outside_enum", "missing_status")}
                            for c in calls]}))
