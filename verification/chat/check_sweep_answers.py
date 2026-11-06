"""Round 47 step 3 (Liam, 2026-11): check live cross-carrier answers -- completeness and agreement with the checker.

    python verification/chat/check_sweep_answers.py <run.jsonl> [--questions verification/chat/sweep_questions.csv]

(a) completeness: every program the checker shows for the question's scope (and every program the value routes in,
    e.g. a vacant home's dwelling programs) is in the answer, with a line that is not empty.
(b) agreement: each program's label in the answer equals the label from a FRESH run of the checker (the export's code
    run now into a temporary folder -- not the committed outcomes.json the Worker read). Also listed: where the label
    differs from the checker's raw status, and why (the neutral profile already lacked the fact, e.g. a county).
Zero API (the checker makes no model call). Prints a report; exit 1 on any (a) or (b) failure.
"""
import argparse
import csv
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "cloudflare", "scripts"))
sys.path.insert(0, ROOT)

RAW = {"ELIGIBLE": {"Eligible", "Guide silent", "Coverage limited", "Confirm"}, "REFER": {"Refer"},
       "INELIGIBLE": {"Not eligible", "Closed"}, "INSUFFICIENT_INFORMATION": {"Confirm"}, "NOT_OFFERED": {"Not eligible"}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--questions", default=os.path.join(HERE, "sweep_questions.csv"))
    a = ap.parse_args()
    import export_chat_outcomes as E
    with tempfile.TemporaryDirectory() as tmp:
        _, fresh = E.export(tmp)
    want = {r["id"]: r for r in csv.DictReader(open(a.questions, encoding="utf-8"))}
    rows = [json.loads(l) for l in open(a.run, encoding="utf-8") if l.strip()]
    fail = 0
    for rec in rows:
        q = want.get(rec["id"])
        if not q:
            continue
        if not rec.get("sweep"):
            print(f"{rec['id']}: NOT A SWEEP ({rec.get('mode')})")
            fail += 1
            continue
        sw, lines = rec["sweep"], rec.get("sweep_lines") or {}
        per = fresh["sweeps"][q["key"]][q["scope"]]
        shown = {p["name"]: p for p in sw["programs"]}
        missing = sorted(o["name"] for o in per.values() if o["name"] not in shown)
        empty = [p["name"] for p in sw["programs"] if not str(lines.get(str(p["k"]), "")).strip()]
        mismatch = []
        explained = []
        for prog, o in per.items():
            p = shown.get(o["name"])
            if not p:
                continue
            if p["label"] != o["label"]:
                mismatch.append(f"{o['name']}: chat {p['label']}, checker now {o['label']}")
            if p["label"] not in RAW.get(o["status"], {p["label"]}):
                explained.append(f"{o['name']} ({o['status']} -> {p['label']})")
        ok = not (missing or empty or mismatch) and sw["scope"] == q["scope"]
        fail += 0 if ok else 1
        filled = rec.get("sweep_filled") or []
        print(f"{rec['id']}: {'OK ' if ok else 'BAD'} {q['key']} {sw['scope']}: {len(sw['programs'])} programs, "
              f"{len(sw['programs']) - len(empty)} with a line ({len(filled)} filled from the rule)"
              + (f"; MISSING {missing}" if missing else "") + (f"; EMPTY {empty}" if empty else "")
              + (f"; MISMATCH {mismatch}" if mismatch else ""))
        if explained:
            print(f"     label differs from the raw status (the neutral profile already lacked it): {', '.join(explained)}")
    print("ALL OK" if not fail else f"{fail} question(s) failed")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
