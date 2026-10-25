"""Round 43 step 2: the page harness's candidate (tests/parity.mjs --out) in the parity golden's format, compared with
verification/parity/golden.json.xz by export_golden.compare (only the candidate's profiles).

The page's texts (name, first, missing, confirm, details, ids, warning) are what the harness read back from the DOM;
the record fields the golden also compares exactly (raw status, flaw_count, the rows in the reasons, missing_info,
the confirm rows, reasons, citations, notes, also_confirm, confirm_items) are the engine output the page received.

usage (cwd = the repo; zero API, writes nothing in the repo):
  env -u ELIGIBILITY_DOTENV PYTHONDONTWRITEBYTECODE=1 <venv python> web/tests/candidate_to_golden.py \
      <candidate.json> [verification/parity/golden.json.xz] [--save <candidate_golden.json.gz>]
Exit 1 on any difference.
"""
import datetime
import json
import os
import sys

sys.dont_write_bytecode = True
os.environ.pop("ELIGIBILITY_DOTENV", None)
sys.path.insert(0, os.path.join(os.getcwd(), "verification", "parity"))
import export_golden as eg  # noqa: E402

FIELD = {"name": "name", "first": "first", "missing": "missing", "confirm": "confirm_html", "details": "details_html",
         "ids": "ids_html", "warning": "warning"}


def read_candidate(path):
    """(profile id, profile) from the harness's candidate: JSONL, one profile per line with its "id"."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                p = json.loads(line)
                yield p.pop("id"), p


def to_golden(candidate):
    S, H, L, profiles = eg.Table(), eg.Table(), eg.Table(), {}
    for pid, p in candidate:
        cards = []
        for c in p["cards"]:
            rec = c["record"]
            raw = {k: c[v] for k, v in FIELD.items()}
            raw.update({k: rec.get(k) or ([] if k != "notes" else "") for k in
                        ("reasons", "citations", "notes", "also_confirm", "confirm_items")})
            out = {"carrier": c["carrier"], "status": c["status"], "raw": rec.get("raw_status"),
                   "flaws": rec.get("flaw_count"),
                   "rows": L(sorted(set(eg.ROW.findall(" ".join(map(str, rec.get("reasons") or [])))))),
                   "held": L([eg.norm(x) for x in rec.get("missing_info") or []]),
                   "confirm_rows": L(sorted({i.get("row") or "" for i in rec.get("confirm_items") or []}))}
            for k in eg.TEXTS:
                v = eg.canonical(k, raw[k])
                out[k] = [S(x) for x in v] if isinstance(v, list) else S(v)
            out["full"] = True
            cards.append(out)
        profiles[pid] = {"pd": p["pd"], "checked": p["checked"],
                         "top_box": [[S(eg.norm(t)), a, b] for t, a, b in p["top_box"]], "cards": cards}
    return {"meta": {"made": datetime.date.today().isoformat(), "year": datetime.date.today().year,
                     "profiles": len(profiles), "exact": list(eg.EXACT), "texts": list(eg.TEXTS),
                     "note": "from the static page's parity harness (tests/parity.mjs)"},
            "strings": S.table, "hashes": H.table, "lists": L.table, "profiles": profiles}


def main():
    args = sys.argv[1:]
    save = None
    if "--save" in args:
        i = args.index("--save")
        save = args[i + 1]
        del args[i:i + 2]
    cand_path = args[0]
    golden = args[1] if len(args) > 1 else eg.GOLDEN
    doc = to_golden(read_candidate(cand_path))
    if save:
        eg.write(doc, save)
    diffs = eg.compare(golden, doc, partial=True)
    sys.exit(1 if diffs else 0)


if __name__ == "__main__":
    main()
