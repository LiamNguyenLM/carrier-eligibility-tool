"""Round 35 step 5: the usage log loses no line when many processes append at once (round 32: 300 checks in
3 processes wrote 299 lines). Zero API."""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import usage_log  # noqa: E402

pytestmark = pytest.mark.retrieval
WRITERS, LINES_EACH = 50, 20
CHILD = (
    "import os, sys; sys.path.insert(0, {root!r}); os.environ['ELIGIBILITY_USAGE_LOG'] = {log!r}\n"
    "import usage_log\n"
    "w = int(sys.argv[1])\n"
    "for i in range({n}):\n"
    "    usage_log.append({{'writer': w, 'i': i, 'pad': 'x' * 3000}})\n")


def test_fifty_parallel_writers_lose_no_line(tmp_path):
    log = str(tmp_path / "usage_log.jsonl")
    code = CHILD.format(root=os.path.abspath(ROOT), log=log, n=LINES_EACH)
    procs = [subprocess.Popen([sys.executable, "-c", code, str(w)]) for w in range(WRITERS)]
    assert all(p.wait(timeout=300) == 0 for p in procs)
    with open(log, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    records = [json.loads(x) for x in lines]                       # every line is whole JSON
    assert len(records) == WRITERS * LINES_EACH
    assert {(r["writer"], r["i"]) for r in records} == {(w, i) for w in range(WRITERS) for i in range(LINES_EACH)}


def test_threads_in_one_process_lose_no_line(tmp_path, monkeypatch):
    import threading
    log = str(tmp_path / "usage_log.jsonl")
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", log)
    threads = [threading.Thread(target=lambda w=w: [usage_log.append({"w": w, "i": i}) for i in range(50)])
               for w in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with open(log, encoding="utf-8") as fh:
        assert len([json.loads(x) for x in fh]) == 1000


def test_a_write_failure_never_raises(monkeypatch, capsys):
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", os.path.join(os.devnull, "nope", "usage_log.jsonl"))
    usage_log.append({"x": 1})                                       # must not raise
    assert "could not write" in capsys.readouterr().out
