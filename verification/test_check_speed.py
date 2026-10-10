"""Round 36 step 1 (Liam's Railway check, 2026-10-10: just under 2 minutes, then 1 min 37 s; it used to be
about 1 minute). Locally the check of his profile took 12-15 s. Where the code's own time went:

- one check read every row of the carrier store five times (get_all_carriers four times, the defect scan
  once) and re-ran the defect scan (about a second) every time;
- every Streamlit rerun -- any click anywhere -- read the whole store four more times for the Manage
  Carriers tab (fingerprint, carrier list twice);
- nothing said where a slow check's time went.

These tests hold the fixes: one whole-store read per store version (store_cache), a timing breakdown on
every usage-log line (each model call's wall time and HTTP attempts, the stages, the page), the last
check's breakdown in the Fingerprint panel, and a warm-up at app start. Zero API."""
import json
import os
import sys
import time

import httpx
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
import data_defects  # noqa: E402
import eligibility_check as ec  # noqa: E402
import guides  # noqa: E402
import store_cache  # noqa: E402
import upload_carrier  # noqa: E402
import usage_log  # noqa: E402
from profiles import STANDARD_PROFILE  # noqa: E402

pytestmark = pytest.mark.retrieval
APP = os.path.join(ROOT, "app.py")


# ---------------------------------------------------------------- the store cache

class FakeCollection:
    def __init__(self, rows):
        self.rows = rows               # [(document, metadata)]
        self.full_reads = 0

    def count(self):
        return len(self.rows)

    def get(self, include=None, where=None, ids=None):
        if where is None and ids is None:
            self.full_reads += 1
        rows = [(d, m) for d, m in self.rows if not where or all(m.get(k) == v for k, v in where.items())]
        out = {"ids": [str(i) for i in range(len(rows))], "metadatas": [m for _, m in rows]}
        if include and "documents" in include:
            out["documents"] = [d for d, _ in rows]
        return out

    def delete(self, ids):
        self.rows = self.rows[len(ids):]


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(store_cache, "DB_FOLDER", str(tmp_path))
    (tmp_path / "chroma.sqlite3").write_bytes(b"v1")
    store_cache.bump()
    yield FakeCollection([("text a", {"carrier": "A"}), ("text b", {"carrier": "B"}), ("more b", {"carrier": "B"})])
    store_cache.bump()


def _read(coll, documents=False):
    # the module default folder is bound at definition time; read the fake folder explicitly
    return store_cache.read(coll, documents)


def test_an_unchanged_store_is_read_once(fake, monkeypatch):
    monkeypatch.setattr(store_cache, "version", lambda c, folder=None: _version(c))
    for _ in range(4):
        assert store_cache.carriers(fake) == {"A", "B"}
    _read(fake)
    assert fake.full_reads == 1


def _version(c):
    return (id(c), store_cache._generation, c.count(), store_cache._file_stats(store_cache.DB_FOLDER))


@pytest.mark.parametrize("change", ["a write from this app (upload / remove)", "a write from another process",
                                    "a row added or removed"])
def test_any_change_to_the_store_is_seen_by_the_next_read(fake, monkeypatch, tmp_path, change):
    monkeypatch.setattr(store_cache, "version", lambda c, folder=None: _version(c))
    assert store_cache.carriers(fake) == {"A", "B"}
    if change.startswith("a write from this"):
        fake.rows.append(("text c", {"carrier": "C"}))
        fake.rows.pop(0)                                       # same count: only the bump can tell
        store_cache.bump()
    elif change.startswith("a write from another"):
        fake.rows.append(("text c", {"carrier": "C"}))
        fake.rows.pop(0)                                       # same count: only the file can tell
        db = tmp_path / "chroma.sqlite3"
        db.write_bytes(b"v2-longer")
        os.utime(db, ns=(time.time_ns(), time.time_ns() + 10**9))
    else:
        fake.rows.append(("text c", {"carrier": "C"}))
    assert "C" in store_cache.carriers(fake)
    assert fake.full_reads == 2


def test_a_read_with_documents_also_serves_a_metadata_read(fake, monkeypatch):
    monkeypatch.setattr(store_cache, "version", lambda c, folder=None: _version(c))
    _read(fake, documents=True)
    _read(fake)
    assert fake.full_reads == 1


@pytest.mark.parametrize("write", ["remove", "add"])
def test_upload_and_remove_drop_the_cached_reads(fake, monkeypatch, write):
    class Store:
        _collection = fake

        def add_documents(self, batch):
            fake.rows.extend((d.page_content, d.metadata) for d in batch)
    monkeypatch.setattr(upload_carrier, "get_vectorstore", lambda: Store())
    store_cache.derived("probe", fake, lambda raw: 1)
    before = store_cache._generation
    if write == "remove":
        assert upload_carrier.remove_carrier_from_database("B") == 2
    else:
        from langchain_core.documents import Document
        monkeypatch.setattr(upload_carrier, "load_pdf_as_documents",
                            lambda *a, **k: [Document(page_content="x " * 400, metadata={"page": 1})])
        monkeypatch.setattr(upload_carrier, "chunk_documents", lambda docs, splitter: docs)
        assert upload_carrier.add_carrier_to_database(b"%PDF-1.4", "Zeta_HO3") == (1, None)
        assert any(m.get("carrier") == "Zeta_HO3" for _, m in fake.rows)
    assert store_cache._generation > before
    assert ("derived", "probe") not in store_cache._cache


# ---------------------------------------------------------------- the real store

def _count_full_reads(monkeypatch):
    coll = ec.get_vectorstore()._collection
    counter = {"n": 0}
    real = coll.get

    def get(*a, **k):
        if not k.get("where") and not k.get("ids") and not a:
            counter["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(coll, "get", get)
    return counter


def _fake_complete(system, user, max_tokens):
    import re
    names = (re.findall(r"--- (.+?) \(rule check\) ---", user) if "RULE CHECK:" in user
             else sorted(set(re.findall(r"\n--- (.+?) \(page", user))))
    return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                     "citations": [], "missing_info": [], "notes": ""} for n in names]}), {
        "input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


@pytest.fixture
def no_log(tmp_path, monkeypatch):
    p = tmp_path / "usage.jsonl"
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(p))
    monkeypatch.setattr(ec, "_complete", _fake_complete)
    return p


@pytest.mark.parametrize("pd", [dict(STANDARD_PROFILE, county="Harris", zip="77248"),
                                dict(STANDARD_PROFILE, county="", occupancy_type="Tenant Occupied")])
def test_a_check_reads_the_whole_store_at_most_once_and_a_second_check_not_at_all(no_log, monkeypatch, pd):
    # was: 5 whole-store reads in every check (round 36 step 1, measured on Liam's profile)
    store_cache.bump()
    reads = _count_full_reads(monkeypatch)
    ec.check_eligibility(dict(pd))
    assert reads["n"] <= 2                  # metadata, and the documents for the defect scan
    reads["n"] = 0
    ec.check_eligibility(dict(pd))
    assert reads["n"] == 0


def test_the_manage_tab_reads_the_store_once_not_on_every_rerun(monkeypatch):
    # was: fingerprint + carrier list twice = 3 whole-store reads on every rerun (any click in the app)
    store_cache.bump()
    reads = _count_full_reads(monkeypatch)
    for _ in range(3):
        fp = upload_carrier.database_fingerprint()
        carriers = upload_carrier.list_carriers_in_database()
        upload_carrier.list_carriers_in_database()
        guides.all_programs()
    assert reads["n"] == 1
    # the cached values are the values a fresh read gives
    coll = ec.get_vectorstore()._collection
    assert fp == upload_carrier.database_fingerprint(coll)
    assert carriers == sorted({m["carrier"] for m in coll.get(include=["metadatas"])["metadatas"] if "carrier" in m})
    assert set(carriers) == ec.get_all_carriers()


def test_the_cached_defect_scan_is_the_fresh_one(monkeypatch):
    store_cache.bump()
    cached = data_defects.defective_programs()
    assert data_defects.defective_programs() == cached
    # a replaced _chunks_by_carrier (the tests' own corpora) is scanned fresh, every call
    fresh = data_defects._group(ec.get_vectorstore()._collection.get(include=["documents", "metadatas"]))
    monkeypatch.setattr(data_defects, "_chunks_by_carrier", lambda: fresh)
    assert data_defects.defective_programs() == cached
    assert list(data_defects.defective_programs()) == list(cached)
    monkeypatch.setattr(data_defects, "_chunks_by_carrier", lambda: {})
    assert set(data_defects.defective_programs()) == data_defects.expected_programs()


# ---------------------------------------------------------------- the model calls' wall time and attempts

def _reply(text='{"carriers": []}'):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5}}


def _transport(statuses):
    seq = list(statuses)

    def handler(request):
        status = seq.pop(0) if seq else 529
        if status == 200:
            return httpx.Response(200, json=_reply())
        return httpx.Response(status, headers={"retry-after-ms": "1"},
                              json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
    return httpx.MockTransport(handler)


def test_the_live_client_counts_every_http_request():
    assert ec._count_attempt in ec.client._client.event_hooks["request"]


@pytest.mark.parametrize("statuses,attempts", [([200], 1), ([529, 529, 200], 3), ([500, 200], 2)])
def test_each_model_call_reports_its_wall_time_and_http_attempts(monkeypatch, statuses, attempts):
    monkeypatch.setattr(ec.client._client, "_transport", _transport(statuses))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    text, usage = ec._complete("system", "user", 100)
    assert usage["attempts"] == attempts and usage["wall_s"] >= 0 and not usage.get("fallback")


def test_a_fallback_call_reports_the_attempts_it_spent_on_anthropic(monkeypatch):
    monkeypatch.setattr(ec.client._client, "_transport", _transport([529] * 20))
    monkeypatch.setattr(ec, "_complete_openai", lambda *a, **k: ("{}", {"input_tokens": 1, "output_tokens": 1}))
    text, usage = ec._complete("system", "user", 100)
    assert usage["fallback"] is True and usage["attempts"] == 7          # max_retries=6: 1 + 6
    line = usage_log.record("claude-haiku-5-5", "low", {"main": usage}, 1.0, 1)
    assert line["calls"]["main"]["attempts"] == 7 and line["calls"]["main"]["fallback"] is True
    assert "7 attempts" in usage_log.timing_line(dict(line, timings={"models": 1.0, "total": 1.0}))


def test_parallel_calls_report_the_slowest_wall_and_every_attempt():
    u = ec._sum_usage([{"input_tokens": 1, "wall_s": 4.0, "attempts": 1},
                       {"input_tokens": 2, "wall_s": 9.5, "attempts": 3}])
    assert u["wall_s"] == 9.5 and u["attempts"] == 4 and u["input_tokens"] == 3


# ---------------------------------------------------------------- the stages and the page

def test_a_check_records_every_stage(no_log):
    ec.check_eligibility(dict(STANDARD_PROFILE, county="Bexar"))
    t = ec.LAST_TIMINGS
    for k in ("routing", "code_eval", "retrieval", "before_models", "models", "after_models", "total"):
        assert k in t, k
    assert t["routing"] + t["code_eval"] + t["retrieval"] == pytest.approx(t["before_models"], abs=0.01)
    assert t["before_models"] + t["models"] + t["after_models"] == pytest.approx(t["total"], abs=0.01)
    line = json.loads(no_log.read_text(encoding="utf-8").splitlines()[-1])
    assert set(line["timings"]) >= {"routing", "code_eval", "retrieval", "models", "after_models", "total"}
    assert all(isinstance(v, (int, float)) for v in line["timings"].values())


def test_the_app_writes_the_line_after_the_page_with_its_time(no_log, monkeypatch):
    monkeypatch.setattr(ec, "_check_eligibility", lambda *a, **k: [{"carrier": "X", "status": "ELIGIBLE"}])
    ec.check_eligibility({}, log_usage=False)
    assert not no_log.exists() or no_log.read_text(encoding="utf-8") == ""
    ec.log_check_usage(placement=0.25, render=0.5)
    line = json.loads(no_log.read_text(encoding="utf-8"))
    assert line["timings"]["placement"] == 0.25 and line["timings"]["render"] == 0.5
    assert line["timings"]["total_with_page"] == pytest.approx(line["wall_s"] + 0.75, abs=0.011)
    ec.log_check_usage(render=1.0)                                       # nothing held: nothing written
    assert len(no_log.read_text(encoding="utf-8").splitlines()) == 1


def test_a_held_line_the_page_never_finished_is_written_by_the_next_check(no_log, monkeypatch):
    monkeypatch.setattr(ec, "_check_eligibility", lambda *a, **k: [{"carrier": "X", "status": "ELIGIBLE"}])
    ec.check_eligibility({}, log_usage=False)                            # the page raised: never finished
    ec.check_eligibility({})
    lines = no_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and "render" not in json.loads(lines[0])["timings"]


@pytest.mark.parametrize("line,want", [
    ({"ts": "2026-10-10T07:33:51+00:00", "calls": {"pilot": {"wall_s": 9.08, "attempts": 1}},
      "timings": {"routing": 0.6, "code_eval": 0.05, "retrieval": 0.12, "models": 9.09, "after_models": 0.06,
                  "placement": 0.01, "render": 0.04, "total": 9.92, "total_with_page": 9.97}},
     ["Last check (2026-10-10 07:33 UTC): 10.0s", "model calls 9.1s", "routing 0.6s", "page 0.0s",
      "calls: pilot 9.1s)"]),
    ({"ts": "2026-10-10T08:00:00+00:00", "calls": {"main": {"wall_s": 70.2, "attempts": 4},
                                                  "pilot": {"wall_s": 30.0, "attempts": 1, "fallback": True}},
      "timings": {"models": 70.3, "total": 75.0}},
     ["75.0s", "main 70.2s, 4 attempts", "pilot 30.0s, FALLBACK"]),
])
def test_the_panel_names_where_the_last_check_went(line, want):
    out = usage_log.timing_line(line)
    for w in want:
        assert w in out, (w, out)


def test_a_log_without_timings_shows_no_breakdown(tmp_path, monkeypatch):
    p = tmp_path / "u.jsonl"
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(p))
    assert usage_log.timing_line() == ""
    p.write_text(json.dumps({"ts": "2026-10-01T00:00:00+00:00", "cost": 0.1}) + "\nnot json", encoding="utf-8")
    assert usage_log.last_line() == {"ts": "2026-10-01T00:00:00+00:00", "cost": 0.1}
    assert usage_log.timing_line() == ""


def test_the_fingerprint_panel_shows_the_last_checks_breakdown(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    p = tmp_path / "u.jsonl"
    p.write_text(json.dumps({"ts": "2026-10-10T07:33:51+00:00", "calls": {"pilot": {"wall_s": 9.08, "attempts": 1}},
                             "timings": {"models": 9.09, "total": 9.92}}) + "\n", encoding="utf-8")
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(p))
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    assert not at.exception
    assert any("Last check (2026-10-10 07:33 UTC)" in c.value for c in at.caption)


# ---------------------------------------------------------------- the warm-up

def test_the_warm_up_fills_what_the_first_check_would_pay_for():
    store_cache.bump()
    assert ec.warm_up() >= 0
    keys = set(store_cache._cache)
    assert {("derived", "carriers"), ("derived", "defect_scan")} <= keys


def test_a_warm_up_problem_never_stops_the_app(monkeypatch):
    def broken():
        raise RuntimeError("no store")
    monkeypatch.setattr(ec, "get_vectorstore", broken)
    assert ec.warm_up() >= 0
