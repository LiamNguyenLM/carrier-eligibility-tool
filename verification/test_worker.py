"""Round 43 step 3 (Liam, 2026-10-24): the Worker (cloudflare/) on every fast tier -- its Node tests (Access, the
routes, the D1 stand-in, the feedback CSV, the log import), the placement port against Python's placement.panel on
every golden profile (the browser never gets the tables: the Worker answers the panel), the config's safety
settings, and the page's feedback / usage bodies against feedback.record and the Worker's fields. Zero API; Node's
built-ins only (no npm install needed)."""
import json
import os
import re
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
pytestmark = pytest.mark.retrieval


def _node(*args, timeout=900):
    out = subprocess.run(["node", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    return out.returncode, out.stdout + out.stderr


def test_the_worker_node_tests_pass():
    rc, out = _node("--test", "cloudflare/test/worker.test.mjs")
    assert rc == 0 and re.search(r"\bfail 0\b", out), out[-3000:]


def test_the_placement_port_matches_python_on_every_golden_profile(tmp_path):
    cases = tmp_path / "cases.json"
    env = {k: v for k, v in os.environ.items() if k != "ELIGIBILITY_DOTENV"}
    py = subprocess.run([sys.executable, "cloudflare/scripts/placement_parity_cases.py", str(cases)], cwd=ROOT, env=env,
                        capture_output=True, text=True, encoding="utf-8", timeout=1200)
    assert py.returncode == 0, py.stderr[-2000:]
    rc, out = _node("cloudflare/scripts/placement_parity.mjs", str(cases))
    assert rc == 0 and re.search(r"TOTAL\s+\d+ cases: 0 differences", out), out[-3000:]
    assert re.search(r"golden\s+3569 cases", out), out[-1000:]


def test_the_config_keeps_the_site_behind_access():
    toml = open(os.path.join(ROOT, "wrangler.toml"), encoding="utf-8").read()
    assert re.search(r"^workers_dev = false$", toml, re.M)          # until Access is on (DEPLOY_CLOUDFLARE.md)
    assert re.search(r"^preview_urls = false$", toml, re.M)
    assert 'directory = "web/dist"' in toml and 'run_worker_first = ["/api/*"]' in toml
    assert not re.search(r"^DEV_AUTH_EMAIL\s*=", toml, re.M)


def test_the_pages_feedback_line_has_feedback_records_fields():
    import feedback
    from engine import form
    card = {"carrier": "X", "name": "X (HO3)", "status": "ELIGIBLE", "reasons": ["r [ARA-001]"],
            "deciding_rows": ["ARA-001"], "rules_table": True}
    page = form.feedback_record(card, {"zip": "77002"}, "Not sure", " c ", " me ", ["ppc"], "abc1234")
    py = feedback.record(dict(card, carrier="X"), {"zip": "77002"}, "Not sure", " c ", name=" me ", model="",
                         display_name="X (HO3)", checked_topics=["ppc"])
    assert list(page) == list(py)
    assert {k: v for k, v in page.items() if k not in ("ts", "app_version")} == \
        {k: v for k, v in py.items() if k not in ("ts", "app_version")}


@pytest.mark.parametrize("body", ["usage", "placement"])
def test_the_pages_bodies_are_what_the_worker_reads(body):
    from engine import form
    src = open(os.path.join(ROOT, "cloudflare", "src", "routes.js" if body == "usage" else "placement.js"),
               encoding="utf-8").read()
    if body == "usage":
        sent = form.usage_record("abc1234", 1.2, 28, 0.3, 0.1, 0.05)
        for k in ("wall_s", "carriers", "timings"):
            assert k in sent and k in src, k
    else:
        sent = form.placement_request({"property_details": {"zip": "77002", "county": "Harris", "year_built": 2000,
                                                            "dwelling_amount": None, "occupancy_type": "Owner Occupied"},
                                       "cards": [{"carrier": "X", "status": "ELIGIBLE", "missing_info": ["", "a"],
                                                  "reasons": ["b"]}]})
        assert sent["results"] == [{"carrier": "X", "status": "ELIGIBLE", "missing_info": ["a"], "reasons": ["b"]}]
        for k in ("zip", "county", "year_built", "dwelling_amount", "occupancy_type", "missing_info", "reasons"):
            assert k in src, k
    json.dumps(sent)
