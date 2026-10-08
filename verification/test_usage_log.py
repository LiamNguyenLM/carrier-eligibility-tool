"""Round 31 step 2 (Liam, 2026-10-08): one usage line per check -- tokens, cost, wall time, counts --
never property details or client data; the panel shows this month's total against the budget, and
nothing blocks a check. Zero API."""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
import eligibility_check as ec  # noqa: E402
import usage_log  # noqa: E402
from profiles import STANDARD_PROFILE  # noqa: E402

pytestmark = pytest.mark.retrieval
U = {"input_tokens": 1000, "cache_read_input_tokens": 9000, "cache_creation_input_tokens": 200, "output_tokens": 800}
ALLOWED_KEYS = {"ts", "model", "effort", "fallback", "calls", "cost", "wall_s", "carriers", "retries"}


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "usage.jsonl"
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(p))
    return p


def _lines(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")] if p.exists() else []


def test_cost_comes_from_the_one_price_table():
    # Haiku 5.5: 1000 x 0.10 + 9000 x 0.01 + 200 x 0.125 + 800 x 0.50, per million
    assert usage_log.call_cost("claude-haiku-5-5", U) == pytest.approx((100 + 90 + 25 + 400) / 1e6)
    assert usage_log.call_cost("gpt-6-luna", U) == pytest.approx((100 + 90 + 0 + 400) / 1e6)
    assert usage_log.call_cost("some-unknown-model", U) == 0.0


def test_a_record_holds_counts_and_costs_only():
    rec = usage_log.record("claude-haiku-5-5", "low", {"main": U, "pilot": dict(U), "main_retry": dict(U),
                                                       "pilot_retry": None}, 12.345, 27)
    assert set(rec) == ALLOWED_KEYS
    assert rec["retries"] == 1 and rec["carriers"] == 27 and rec["wall_s"] == 12.35 and rec["fallback"] is False
    assert set(rec["calls"]) == {"main", "pilot", "main_retry"}
    assert rec["calls"]["main"] == {"model": "claude-haiku-5-5", "input": 1000, "cache_read": 9000,
                                    "cache_write": 200, "output": 800, "cost": 0.000615}


def test_a_fallback_call_is_priced_and_flagged_as_luna():
    rec = usage_log.record("claude-haiku-5-5", "low", {"main": dict(U, fallback=True, model="gpt-6-luna")}, 1, 1)
    assert rec["fallback"] is True and rec["calls"]["main"]["model"] == "gpt-6-luna"
    assert rec["cost"] == pytest.approx(usage_log.call_cost("gpt-6-luna", U), abs=1e-6)


def _fake(system, user, max_tokens):
    names = (re.findall(r"--- (.+?) \(rule check\) ---", user) if "RULE CHECK:" in user
             else sorted(set(re.findall(r"\n--- (.+?) \(page", user))))
    return json.dumps({"carriers": [{"carrier": n, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["x"],
                                     "citations": [], "missing_info": [], "notes": ""} for n in names]}), dict(U)


@pytest.mark.parametrize("pd", [dict(STANDARD_PROFILE, county="Bexar", zip="78205"),
                                dict(STANDARD_PROFILE, county="Harris", occupancy_type="Tenant Occupied")])
def test_each_check_appends_one_line_and_no_property_data(log, monkeypatch, pd):
    monkeypatch.setattr(ec, "_complete", _fake)
    monkeypatch.setattr(ec, "ELIGIBILITY_MODEL", "claude-haiku-5-5")      # the live model (conftest pins Sonnet)
    res = ec.check_eligibility(dict(pd))
    lines = _lines(log)
    assert len(lines) == 1 and set(lines[0]) == ALLOWED_KEYS
    assert lines[0]["carriers"] == len(res) and lines[0]["cost"] > 0
    text = log.read_text(encoding="utf-8")
    for v in (pd["county"], pd.get("zip"), pd["occupancy_type"], pd["roof_type"], str(pd["year_built"])):
        if v:
            assert v not in text, v
    ec.check_eligibility(dict(pd))
    assert len(_lines(log)) == 2


def test_a_broken_log_never_breaks_a_check(monkeypatch, tmp_path):
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path))          # a directory: the open() fails
    monkeypatch.setattr(ec, "_complete", _fake)
    assert ec.check_eligibility(dict(STANDARD_PROFILE, county="Bexar"))


def test_the_month_total_and_the_budget(log, monkeypatch):
    now = datetime.datetime(2026, 10, 8, 12, tzinfo=datetime.timezone.utc)
    with open(log, "w", encoding="utf-8") as fh:
        for ts, cost in (("2026-09-30T23:59:59+00:00", 5.0), ("2026-10-01T00:00:00+00:00", 0.002),
                         ("2026-10-08T10:00:00+00:00", 0.003)):
            fh.write(json.dumps({"ts": ts, "cost": cost}) + "\n")
        fh.write("not json\n")
    assert usage_log.month_summary(now) == (2, pytest.approx(0.005))
    monkeypatch.delenv("ELIGIBILITY_MONTHLY_BUDGET", raising=False)
    assert usage_log.panel_line(now) == "This month: 2 checks, $0.01 of the $260 budget (display only)"
    monkeypatch.setenv("ELIGIBILITY_MONTHLY_BUDGET", "100")
    assert "of the $100 budget" in usage_log.panel_line(now)


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX sh")
@pytest.mark.parametrize("force", ["1", ""])
def test_the_seed_script_keeps_the_usage_log(tmp_path, force):
    shutil.copy(os.path.join(ROOT, "seed_db.sh"), tmp_path / "seed_db.sh")
    (tmp_path / "carrier_docs_db_seed").mkdir()
    (tmp_path / "carrier_docs_db_seed" / "chroma.sqlite3").write_text("seed")
    vol = tmp_path / "carrier_docs_db"
    vol.mkdir()
    (vol / "usage_log.jsonl").write_text('{"ts": "2026-10-08"}\n')
    # force: a populated volume is wiped and re-seeded; not forced: a volume holding only the log is
    # still "empty" and gets seeded. Either way the log stays.
    if force:
        (vol / "chroma.sqlite3").write_text("old")
    env = dict(os.environ, FORCE_RESEED=force)
    subprocess.run(["sh", "seed_db.sh"], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
                   check=True)
    assert (vol / "usage_log.jsonl").read_text() == '{"ts": "2026-10-08"}\n'
    assert (vol / "chroma.sqlite3").read_text() == "seed"
