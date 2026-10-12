"""Round 38 step 7: summarize a self-audit run directory (results.jsonl, coverage.json).

usage: python verification/fuzz/summarize.py <out dir> [--groups N]

Prints: profiles run, crashes, failures by check, the distinct failure groups (check, carrier, the detail's kind)
with their first seeds, the slowest profiles, and map-line coverage (rows never reached; deciding rows that never
failed)."""
import csv
import glob
import json
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")


def group_key(f):
    d = f["detail"]
    kind = d.get("why") or d.get("dimension") or d.get("field") or d.get("topic") or ""
    extra = d.get("row") or (f"{d.get('before')}->{d.get('after')}" if "before" in d else "")
    return (f["check"], f["carrier"], str(kind), str(extra))


def load(out):
    rows = [json.loads(l) for l in open(os.path.join(out, "results.jsonl"), encoding="utf-8") if l.strip()]
    cov_path = os.path.join(out, "coverage.json")
    cov = json.load(open(cov_path, encoding="utf-8")) if os.path.exists(cov_path) else {}
    return rows, cov


def deciding_rows():
    """{row_id: the workbook's Effect} for map lines that can decide (a test other than always / NONE)."""
    effect = {}
    for f in glob.glob(os.path.join(ROOT, "rules_data", "carrier_rules_*.csv")):
        with open(f, encoding="utf-8-sig") as fh:
            effect.update({r["Rule ID"]: r.get("Effect") or "" for r in csv.DictReader(
                l for l in fh if not l.startswith("#"))})
    out = {}
    for f in glob.glob(os.path.join(ROOT, "rules_data", "*field_map.csv")):
        with open(f, encoding="utf-8-sig") as fh:
            for m in csv.DictReader(l for l in fh if not l.startswith("#")):
                if m["field"] not in ("NONE", "") and m["test"] != "always":
                    out[m["row_id"]] = effect.get(m["row_id"], "")
    return out


def main(out, n_groups=40):
    rows, cov = load(out)
    print(f"profiles {len(rows)}  crashes {sum(1 for r in rows if r.get('error'))}")
    by_check = Counter(f["check"] for r in rows for f in r["fails"])
    ran = Counter(x.split(":")[0] for r in rows for x in r.get("ran") or [])
    print("comparisons run (checks 2-4; the others run on every profile):", dict(ran))
    print("failures by check:", dict(by_check))
    groups = defaultdict(list)
    for r in rows:
        for f in r["fails"]:
            groups[group_key(f)].append(r["seed"])
    print(f"\n{len(groups)} distinct groups (check | carrier | kind | extra | n | first seeds):")
    for k, seeds in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:n_groups]:
        print(" ", " | ".join(k), "|", len(seeds), "|", sorted(seeds)[:4])
    errs = Counter((r.get("error") or "").strip().splitlines()[-1][:160] for r in rows if r.get("error"))
    for e, n in errs.most_common(5):
        print("CRASH", n, e)
    slow = sorted(rows, key=lambda r: -r["s"])[:5]
    print("\nslowest:", [(r["seed"], r["s"]) for r in slow], " median",
          sorted(r["s"] for r in rows)[len(rows) // 2] if rows else None)
    dec = deciding_rows()
    never = [rid for rid in dec if not any(o in ("PASS", "FAIL", "OPEN", "NOTE") for o in cov.get(rid, {}))]
    never_fail = [rid for rid, eff in dec.items() if eff in ("DECLINES", "REFERS_TO_UW")
                  and rid in cov and "FAIL" not in cov[rid] and rid not in never]
    print(f"\nmap lines that can decide: {len(dec)}; never reached: {len(never)}; decline/refer lines never failing: "
          f"{len(never_fail)}")
    return {"groups": groups, "never": never, "never_fail": never_fail, "rows": rows}


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[3]) if len(sys.argv) > 3 else 40)
