"""Round 43 step 3 (Liam, 2026-10-24): the Worker (cloudflare/) on every fast tier -- its Node tests (Access, the
routes, the D1 stand-in, the feedback CSV, the log import), the placement port against Python's placement.panel on
every golden profile (the browser never gets the tables: the Worker answers the panel), the config's safety
settings, and the page's feedback / usage bodies against feedback.record and the Worker's fields. Zero API; Node's
built-ins only (no npm install needed). Round 44b: the placement tables are bundled into the Worker (built from the
CSVs before every deploy), not loaded into D1."""
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


@pytest.mark.parametrize("name", ["worker", "gate", "chat"])
def test_the_worker_node_tests_pass(name):
    # round 44: + gate.test.mjs, the password gate (no path without a session, tampered / expired cookies, admin
    # routes, the lockout, missing secrets, access mode unchanged)
    # round 45: + chat.test.mjs, Ask the Guides (retrieval per guaranteed topic, the cost guard, the stream and its
    # citations, the key never leaving the Worker, chat feedback) -- zero API, a fake model
    rc, out = _node("--test", f"cloudflare/test/{name}.test.mjs")
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


PLACEMENT_TABLES = ("placement_zip", "placement_county", "placement_profile", "placement_all", "placement_markets",
                    "placement_meta")


def test_the_placement_tables_are_built_into_every_deploy_not_loaded_into_d1():
    # Round 44b (Liam, 2026-10-25): the D1 load blew the free tier (143k rows written / 100k a day). The tables are
    # now a module the Worker imports, which wrangler builds from the CSVs before every deploy and dev run -- so the
    # monthly refresh is "update the CSVs, push", and no step writes them to D1.
    toml = open(os.path.join(ROOT, "wrangler.toml"), encoding="utf-8").read()
    build = re.search(r"^\[build\]\n(.*?)(?=^\[)", toml, re.M | re.S)
    # CHANGED (round 45, Liam 2026-10-28): the same step also builds Ask the Guides' index, and wrangler dev watches all
    # of rules_data. Was: command = "node cloudflare/scripts/build_placement.mjs", watch_dir rules_data/placement.
    assert build and re.search(r'^command = "node cloudflare/scripts/build_placement\.mjs && '
                               r'node cloudflare/scripts/build_chat_index\.mjs"$', build.group(1), re.M)
    assert re.search(r'^watch_dir = \[.*"rules_data".*\]$', build.group(1), re.M)   # wrangler dev rebuilds on a CSV change
    routes = open(os.path.join(ROOT, "cloudflare", "src", "routes.js"), encoding="utf-8").read()
    assert 'import PLACEMENT from "../build/placement_data.js";' in routes
    post = re.search(r"async function postPlacement\(.*?\n}\n", routes, re.S).group(0)
    assert "env.DB" not in post and "loadPanelTables(PLACEMENT," in post
    ignore = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read().splitlines()
    assert "cloudflare/build/" in ignore                              # generated, never committed
    for gone in ("cloudflare/scripts/sync_placement.mjs", "cloudflare/scripts/check_placement.sql"):
        assert not os.path.exists(os.path.join(ROOT, gone)), gone
    pkg = json.load(open(os.path.join(ROOT, "package.json"), encoding="utf-8"))
    assert "sync:placement" not in pkg["scripts"] and "build_placement.mjs" in pkg["scripts"]["build:placement"]


def test_a_migration_drops_every_placement_table_from_d1():
    mig = os.path.join(ROOT, "cloudflare", "migrations")
    files = sorted(f for f in os.listdir(mig) if f.endswith(".sql"))
    assert "0003_drop_placement.sql" in files, files
    sql = open(os.path.join(mig, "0003_drop_placement.sql"), encoding="utf-8").read()
    dropped = re.findall(r"^DROP TABLE IF EXISTS (\w+);$", sql, re.M)
    created = re.findall(r"^CREATE TABLE (placement_\w+)", open(os.path.join(mig, "0001_init.sql"), encoding="utf-8").read(), re.M)
    assert sorted(dropped) == sorted(created) == sorted(PLACEMENT_TABLES)
    # nothing after 0003 brings one back (worker.test.mjs checks the same on the applied schema)
    later = [open(os.path.join(mig, f), encoding="utf-8").read() for f in files if f > "0003_drop_placement.sql"]
    assert not any(re.search(r"CREATE TABLE\s+(IF NOT EXISTS\s+)?placement_", s) for s in later)


def test_a_failed_d1_write_reaches_the_agent_only_for_feedback():
    # Round 44b (Liam, 2026-10-25): feedback that couldn't be saved says "couldn't save -- try again later"; a usage
    # row that couldn't be saved is never shown. The Worker side is in worker.test.mjs / gate.test.mjs.
    js = open(os.path.join(ROOT, "web", "src", "app.js"), encoding="utf-8").read()
    routes = open(os.path.join(ROOT, "cloudflare", "src", "routes.js"), encoding="utf-8").read()
    api = open(os.path.join(ROOT, "web", "src", "worker_api.js"), encoding="utf-8").read()
    const = r'const FEEDBACK_NOT_SAVED = "(.*?)";'
    page, worker = re.search(const, js).group(1), re.search("export " + const, routes).group(1)
    assert page == worker == r"Couldn’t save — try again later."
    wire = re.search(r"function wireFeedback\(.*?\n}\n", js, re.S).group(0)
    assert re.search(r"catch \(e\) \{.*?\.send-failed\", box\)\.textContent = FEEDBACK_NOT_SAVED;", wire, re.S)
    assert "Could not send" not in js
    # the page's two Worker calls: feedback throws on any non-2xx (so a 503 shows the message); usage never throws
    assert re.search(r"export async function feedback\(record\) \{\s*await postJson\(\"/api/feedback\", record\);", api)
    assert re.search(r"export async function usage\(body\) \{\s*try \{ await postJson\(\"/api/usage\", body\); \} catch", api)
    assert "if (!r.ok) throw" in api


def test_the_config_keeps_the_site_behind_a_gate():
    # CHANGED (round 44 step 1, Liam 2026-10-25: a shared-password gate until Access): the address is on from the
    # first deploy because the Worker runs first for every path and its gate fails closed without its secrets. Was:
    # workers_dev = false and run_worker_first = ["/api/*"] until Access is on.
    toml = open(os.path.join(ROOT, "wrangler.toml"), encoding="utf-8").read()
    mode = re.search(r'^AUTH_MODE = "(\w+)"', toml, re.M).group(1)
    assert mode in ("password", "access")
    if mode == "password":                       # the gate must see every path, static files included
        assert re.search(r"^run_worker_first = true$", toml, re.M)
    assert re.search(r"^preview_urls = false$", toml, re.M)
    assert 'directory = "web/dist"' in toml
    for secret in ("APP_PASSWORD", "ADMIN_PASSWORD", "SESSION_SECRET", "DEV_AUTH_EMAIL"):
        assert not re.search(rf"^{secret}\s*=", toml, re.M), secret      # secrets: wrangler secret put, never here


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


def test_ask_the_guides_is_configured_with_a_secret_key_and_a_cost_guard():
    # Round 45 (Liam, 2026-10-28): the key is a Worker secret (never in wrangler.toml); the model, the daily cap and the
    # hourly limit are vars; chat_log and feedback.kind come from migration 0004; the Worker calls the API itself.
    toml = open(os.path.join(ROOT, "wrangler.toml"), encoding="utf-8").read()
    assert not re.search(r"^ANTHROPIC_API_KEY\s*=", toml, re.M)
    assert re.search(r'^CHAT_MODEL = "claude-haiku-5-5"$', toml, re.M)
    assert re.search(r'^CHAT_DAILY_CAP_USD = "3"$', toml, re.M)
    assert re.search(r'^CHAT_RATE_PER_HOUR = "30"$', toml, re.M)
    mig = open(os.path.join(ROOT, "cloudflare", "migrations", "0004_chat.sql"), encoding="utf-8").read()
    assert "CREATE TABLE chat_log" in mig and "ALTER TABLE feedback ADD COLUMN kind" in mig
    assert mig.count("CREATE INDEX") == 1                                 # one index: two rows written a question
    src = open(os.path.join(ROOT, "cloudflare", "src", "chat_route.js"), encoding="utf-8").read()
    assert 'API_URL = "https://api.anthropic.com/v1/messages"' in src and "env.ANTHROPIC_API_KEY" in src
    for leak in ("console.log(env", "JSON.stringify(env", "ANTHROPIC_API_KEY}"):
        assert leak not in src, leak
    pkg = json.load(open(os.path.join(ROOT, "package.json"), encoding="utf-8"))
    assert "build_chat_index.mjs" in pkg["scripts"]["build:chat"]
    assert "@anthropic-ai/sdk" not in json.dumps(pkg)                   # measured too slow for 10 ms (chat_route.js)
