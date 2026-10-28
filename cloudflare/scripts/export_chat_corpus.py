"""Round 45 (Liam, 2026-10-28): the guide text "Ask the Guides" answers from, exported from the carrier store.

    python cloudflare/scripts/export_chat_corpus.py [--store carrier_docs_db] [--out rules_data/chat]

Writes two committed files the Worker's chat index is built from (cloudflare/scripts/build_worker_data.mjs, on
every deploy; the Cloudflare build has no Chroma):

  rules_data/chat/guide_chunks.jsonl   every chunk of every program, in reading order -- the same chunks the
                                       Railway chat read (hidden text already dropped at load): one JSON object a
                                       line, {"p": program, "pg": 1-based page, "t": is_table, "s": section, "x": text}
  rules_data/chat/programs.json        each program's display name, guide date, defect / closed / summary-sheet
                                       status, and the rules tables' workbook names for it

Rerun after any change to the store (a reseed, a new guide); verification/test_chat_corpus.py fails while these
files differ from carrier_docs_db. Zero API. Opens a COPY of the store (carrier_docs_db), never the tracked seed:
opening a store writes to its sqlite file.
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from engine import display_names, rules_evaluator  # noqa: E402

WORKBOOK_MAPS = ("PILOT_CARRIERS", "SAGE_BATCH_CARRIERS", "HO3_BATCH_CARRIERS", "HARTFORD_CARRIERS",
                 "NATGEN_C360_CARRIERS", "OCCIDENTAL_CARRIERS", "DP_BATCH_CARRIERS")
# Rules-table rows of programs no batch evaluates (closed to new business: the engine decides them without the rows)
EXTRA_WORKBOOK = {"NatGen Premier Dwelling Fire (closed)": "NatGen_Premier_OneChoice_DP3_-_02.26.2025"}


def store_chunks(store_dir):
    """[(meta, text)] for every chunk, sorted per program by (page, is_table) -- guides._sorted_chunks' order."""
    import chromadb
    col = chromadb.PersistentClient(path=store_dir).get_collection("langchain")
    raw = col.get(include=["documents", "metadatas"])
    by_program = {}
    for meta, text in zip(raw["metadatas"], raw["documents"]):
        by_program.setdefault(meta.get("carrier") or "", []).append((meta, text))
    out = []
    for program in sorted(by_program):
        if not program:
            continue
        out.extend(sorted(by_program[program], key=lambda mt: (mt[0].get("page", 0), bool(mt[0].get("is_table")))))
    return out


def chunk_lines(chunks):
    return [json.dumps({"p": m["carrier"], "pg": int(m.get("page", 0)) + 1, "t": bool(m.get("is_table")),
                        "s": m.get("section") or "", "x": text}, ensure_ascii=False) for m, text in chunks]


def programs(chunk_programs):
    manifest = json.load(open(os.path.join(ROOT, "rules_data", "engine_manifest.json"), encoding="utf-8"))
    workbook = {}
    for name in WORKBOOK_MAPS:
        for label, program in getattr(rules_evaluator, name).items():
            workbook.setdefault(program, []).append(label)
    for label, program in EXTRA_WORKBOOK.items():
        workbook.setdefault(program, []).append(label)
    every = sorted(set(manifest["carriers"]) | set(manifest["closed"]) | set(chunk_programs)
                   | set(display_names.DISPLAY))
    out = []
    for p in every:
        defect = manifest["defects"].get(p)
        out.append({
            "program": p,
            "display": display_names.display_name(p),
            "date": display_names.guide_date(p) or "",
            "has_text": p in chunk_programs,
            "closed": p in manifest["closed"],
            "defect": defect["detail"] if defect else "",
            "summary_sheet": p in display_names.SUMMARY_SHEETS,
            "occupancy_names": display_names.OCCUPANCY_NAMES.get(p, {}),
            "workbook_names": sorted(workbook.get(p, [])),
        })
    return out


def export(store_dir, out_dir):
    chunks = store_chunks(store_dir)
    lines = chunk_lines(chunks)
    progs = programs({m["carrier"] for m, _ in chunks})
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "guide_chunks.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(out_dir, "programs.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(progs, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return len(lines), len(progs)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(ROOT, "carrier_docs_db"))
    ap.add_argument("--out", default=os.path.join(ROOT, "rules_data", "chat"))
    a = ap.parse_args()
    n, p = export(a.store, a.out)
    print(f"chat corpus: {n} chunks, {p} programs -> {a.out}")
