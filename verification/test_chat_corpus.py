"""Round 45 (Liam, 2026-10-28): Ask the Guides' material and its test set, on every fast tier. Zero API.

- rules_data/chat/ (guide_chunks.jsonl, programs.json) is what the Worker's chat answers from. It is exported from the
  carrier store by cloudflare/scripts/export_chat_corpus.py and committed (the Cloudflare build has no Chroma), so it
  must equal a fresh export of carrier_docs_db: a reseed without a re-export fails here.
- verification/chat/questions.csv is the 40-question live test (verification/chat/run_live.py, paid): every
  category Liam asked for is in it, each with an expected answer and its source rows.
"""
import csv
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
pytestmark = pytest.mark.retrieval
CHAT = os.path.join(ROOT, "rules_data", "chat")


def test_the_committed_chat_corpus_is_a_fresh_export_of_the_store(tmp_path):
    out = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "cloudflare", "scripts", "export_chat_corpus.py"),
                          "--store", os.path.join(ROOT, "carrier_docs_db"), "--out", str(tmp_path)],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=600)
    assert out.returncode == 0, out.stderr[-2000:]
    for name in ("guide_chunks.jsonl", "programs.json"):
        fresh = open(tmp_path / name, encoding="utf-8").read()
        committed = open(os.path.join(CHAT, name), encoding="utf-8").read()
        assert fresh == committed, f"{name} is stale: rerun python cloudflare/scripts/export_chat_corpus.py"


def test_every_program_with_a_guide_is_in_the_chat_and_defects_are_marked():
    progs = {p["program"]: p for p in json.load(open(os.path.join(CHAT, "programs.json"), encoding="utf-8"))}
    manifest = json.load(open(os.path.join(ROOT, "rules_data", "engine_manifest.json"), encoding="utf-8"))
    assert set(manifest["carriers"]) <= set(progs)
    for p in manifest["closed"]:
        assert progs[p]["closed"], p
    for p in manifest["defects"]:
        assert progs[p]["defect"], p                      # the chat says the guide is unusable, never answers from it
    chunks = [json.loads(l) for l in open(os.path.join(CHAT, "guide_chunks.jsonl"), encoding="utf-8")]
    with_text = {c["p"] for c in chunks}
    assert with_text == {p for p, v in progs.items() if v["has_text"]}
    assert all(c["x"].strip() and c["pg"] >= 1 for c in chunks)


REQUIRED = {"single_yes_no": 6, "cfig_experience": 1, "numeric": 6, "occupancy": 4, "cross_carrier": 5,
            "county_rule": 1, "not_in_guides": 1, "unknown_carrier": 1, "injection": 3, "follow_up": 1}


def test_the_live_test_set_has_40_questions_covering_every_category():
    rows = list(csv.DictReader(open(os.path.join(HERE, "chat", "questions.csv"), encoding="utf-8")))
    assert len(rows) == 40
    assert len({r["id"] for r in rows}) == 40
    counts = {}
    for r in rows:
        counts[r["category"]] = counts.get(r["category"], 0) + 1
        assert r["question"].strip() and r["expected"].strip() and r["sources"].strip(), r["id"]
        if r["history"]:
            assert isinstance(json.loads(r["history"]), list)
    for cat, n in REQUIRED.items():
        assert counts.get(cat, 0) >= n, (cat, counts.get(cat, 0))
    qs = " ".join(r["question"] for r in rows).lower()
    for must in ("hartford", "diving board", "rental property protection plus", "natgen", "federal pacific",
                 "occidental", "state farm", "api key", "ignore your previous instructions"):
        assert must in qs, must
