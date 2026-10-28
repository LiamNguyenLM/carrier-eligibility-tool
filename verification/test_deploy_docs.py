"""Round 43 step 4 (Liam, 2026-10-24): the deploy guide and the runbooks name real things -- every `npm run <script>`
is in package.json, every repo file they tell Liam to run or open exists, and the Worker / database name matches
wrangler.toml -- so a document cannot drift from the repo unnoticed. Zero API."""
import json
import os
import re

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOCS = ["DEPLOY_CLOUDFLARE.md", "ADD_CARRIER.md", "cloudflare/README.md", "web/README.md"]
pytestmark = pytest.mark.retrieval


def _text(doc):
    return open(os.path.join(ROOT, doc), encoding="utf-8").read()


@pytest.mark.parametrize("doc", DOCS)
def test_every_npm_script_a_doc_names_exists(doc):
    scripts = json.load(open(os.path.join(ROOT, "package.json"), encoding="utf-8"))["scripts"]
    named = set(re.findall(r"npm run ([\w:]+)", _text(doc)))
    assert named <= set(scripts) | {"build"}, named - set(scripts)


@pytest.mark.parametrize("doc", DOCS)
def test_every_repo_file_a_doc_runs_or_opens_exists(doc):
    # round 45: + jsonl, and an extension must end the name (".jsonl" was read as ".json" + "l")
    paths = set(re.findall(r"\b((?:cloudflare|web|verification|rules_data|engine)/[\w./-]+\.(?:mjs|jsonl|json|js|py|sql|md|csv|xz))(?![\w])",
                           _text(doc)))
    made = re.compile(r"(^|/)(build|out|dist)/|engine_manifest|parity_cases|candidate|placement_data\.py")
    missing = sorted(p for p in paths if not made.search(p) and "<" not in p
                     and not os.path.exists(os.path.join(ROOT, p)))
    assert missing == []


def test_the_deploy_guide_uses_wranglers_names():
    toml = _text("wrangler.toml")
    name = re.search(r'^name = "([^"]+)"', toml, re.M).group(1)
    db = re.search(r'^database_name = "([^"]+)"', toml, re.M).group(1)
    guide = _text("DEPLOY_CLOUDFLARE.md")
    assert name == db == "cfig-eligibility"
    assert f"d1 create {db}" in guide and f"execute {db} --remote" in guide and "workers_dev = true" in guide


@pytest.mark.parametrize("doc", DOCS)
def test_no_doc_loads_the_placement_tables_into_d1(doc):
    # Round 44b (Liam, 2026-10-25): the tables are built into the Worker on every deploy; a D1 load step (which blew
    # the free tier) must not survive in any runbook, under the old script names or as a d1 execute of them.
    text = _text(doc)
    for old in ("sync_placement", "sync:placement", "placement_sync.sql", "check_placement"):
        assert old not in text, (doc, old)
    assert not re.search(r"d1 execute[^\n]*placement", text), doc


def test_the_deploy_guide_says_the_monthly_refresh_is_update_the_csvs_and_push():
    guide = _text("DEPLOY_CLOUDFLARE.md")
    refresh = guide[guide.index("**The monthly placement refresh is"):guide.index("## 4. The address")]
    assert "sync_from_out.py" in refresh and "git push" in refresh and "data through YYYY-MM" in refresh
    assert "No placement load step" in guide and "0003" in guide
    assert "Couldn’t save — try again later." in guide


def test_the_deploy_guide_sets_up_ask_the_guides_with_a_secret():
    # Round 45 (Liam, 2026-10-28): the key goes in with wrangler secret put, never into a file; 0004 is migrated; three
    # questions to try; a note for agents.
    guide = _text("DEPLOY_CLOUDFLARE.md")
    sec = guide[guide.index("## 9. Ask the Guides"):guide.index("## Turning off Railway")]
    assert "npx wrangler secret put ANTHROPIC_API_KEY" in sec and "npm run migrate:remote" in sec and "0004" in sec
    assert sec.count('- "') >= 3 and "Note for agents" in sec
    assert not __import__("re").search(r"sk-ant-[A-Za-z0-9]", guide)


def test_railway_keeps_building_the_python_app():
    """Round 43: package.json sits at the repo root now (the Cloudflare page and Worker). Railway's builders detect
    Node from a root package.json, so both are pinned to Python until Railway is retired (railpack.json for Railpack,
    nixpacks.toml for Nixpacks); the Procfile still starts streamlit."""
    assert json.loads(_text("railpack.json"))["provider"] == "python"
    assert re.search(r"^providers = \['python'\]$", _text("nixpacks.toml"), re.M)
    assert "streamlit run app.py" in _text("Procfile")
