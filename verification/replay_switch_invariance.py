"""Round 27 step 6 (the proof that ELIGIBILITY_RULES_SAGE_BATCH OFF is byte-identical): replay the pipeline with a fixed fake model and dump every
prompt and every result, so two code versions can be compared byte for byte.

usage: python replay.py <code_dir_or_-> <ELIGIBILITY_RULES_PILOT> <ELIGIBILITY_RULES_SAGE_BATCH or -> <out.json>
code_dir: a folder whose eligibility_check.py / rules_evaluator.py / rules_data
shadow the repo's ("-" = the working tree). Runs in the repo root, so both
versions read the same vector store and guides."""
import json
import os
import re
import sys

ROOT = r"C:\Users\Intern\carrier\carrier-eligibility-tool"
code, pilot, batch, out = sys.argv[1:5]
os.environ["ANTHROPIC_API_KEY"] = os.environ["OPENAI_API_KEY"] = "invalid-guard"
os.environ["ELIGIBILITY_RULES_PILOT"] = pilot
if batch != "-":
    os.environ["ELIGIBILITY_RULES_SAGE_BATCH"] = batch
else:
    os.environ.pop("ELIGIBILITY_RULES_SAGE_BATCH", None)
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "verification"))
if code != "-":
    sys.path.insert(0, code)
import eligibility_check as ec  # noqa: E402
from profiles import ALT_PROFILE, LIVE_CHECKED, LIVE_PROFILE, STANDARD_PROFILE  # noqa: E402

assert (code == "-") == (os.path.dirname(os.path.abspath(ec.__file__)) == ROOT), ec.__file__
USAGE = {"input_tokens": 1, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0, "output_tokens": 1}
OLD = dict(STANDARD_PROFILE, year_built=1970, roof_age=22, plumbing_type="Galvanized", ppc="6", county="Bexar",
           dwelling_amount=350000)
CASES = [
    ("STANDARD", STANDARD_PROFILE, None), ("ALT", ALT_PROFILE, None), ("LIVE", LIVE_PROFILE, LIVE_CHECKED),
    ("LIVE+Bexar", dict(LIVE_PROFILE, county="Bexar", zip=""), LIVE_CHECKED),
    ("LIVE+Bexar+7mi/No", dict(LIVE_PROFILE, county="Bexar", zip="", fire_station_miles="7", hydrant_1000ft="No"),
     LIVE_CHECKED),
    ("OLD", OLD, None), ("STANDARD+Dallas", dict(STANDARD_PROFILE, county="Dallas"), None),
    ("STANDARD+Nueces", dict(STANDARD_PROFILE, county="Nueces"), None),
    ("STANDARD+Seasonal", dict(STANDARD_PROFILE, occupancy_type="Seasonal", county="Bexar"), None),
    ("STANDARD+blank county", dict(STANDARD_PROFILE, county=""), None),
]


def record(n, status):
    return {"carrier": n, "status": status, "flaw_count": 1 if status == "INELIGIBLE" else 0,
            "reasons": ["fixture reason"], "citations": [], "missing_info": ["fixture item"] if status ==
            "INSUFFICIENT_INFORMATION" else [], "notes": ""}


dump = {"status_line": getattr(ec, "rules_pilot_status_line", lambda: "")(), "help": getattr(ec, "RULES_PILOT_HELP", ""),
        "runs": {}}
for name, pd, checked in CASES:
    for status in ("ELIGIBLE", "INSUFFICIENT_INFORMATION", "INELIGIBLE"):
        prompts = []

        def fake(system, user, max_tokens):
            prompts.append(user)
            if "RULE CHECK:" in user:
                names = re.findall(r"--- (.+?) \(rule check\) ---", user)
            else:
                names = sorted(set(re.findall(r"\n--- (.+?) \(page", user)))
            return json.dumps({"carriers": [record(n, status) for n in names]}), dict(USAGE)

        ec._complete = fake
        res = ec.check_eligibility(dict(pd), checked_topics=checked)
        dump["runs"][f"{name} | {status}"] = {
            "prompts": sorted(prompts),
            "results": json.loads(json.dumps(sorted(res, key=lambda r: r["carrier"]), sort_keys=True, default=str))}
json.dump(dump, open(out, "w", encoding="utf-8"), sort_keys=True, indent=0)
print(out, len(dump["runs"]), "runs;", dump["status_line"])
