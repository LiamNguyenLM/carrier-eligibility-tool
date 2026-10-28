"""Round 43 step 2 (Liam, 2026-10-24): the static page's build (web/build.mjs) ships exactly the engine's code, the
data files the engine reads (engine.bundle.data_files(), the same list the strict tests register) and the manifest --
never the placement tables (the Worker answers the panel) -- and the page loads the manifest, so no check in the
browser reaches for a store. Zero API, no Node needed (the build itself runs in the harness)."""
import fnmatch
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
import engine.bundle as bundle  # noqa: E402

pytestmark = pytest.mark.retrieval
BUILD = open(os.path.join(ROOT, "web", "build.mjs"), encoding="utf-8").read()


def _build_list():
    block = re.search(r"export const ENGINE_DATA_FILES = \[(.*?)\];", BUILD, re.S).group(1)
    return re.findall(r'"([^"]+)"', block)


def _expand(pattern):
    d, base = os.path.split(pattern)
    names = os.listdir(os.path.join(ROOT, d)) if os.path.isdir(os.path.join(ROOT, d)) else []
    return {f"{d}/{n}" if d else n for n in names if fnmatch.fnmatchcase(n, base)
            and os.path.isfile(os.path.join(ROOT, d, n))}


def test_the_build_ships_exactly_the_engines_data_files_and_the_manifest():
    shipped = set().union(*(_expand(p) for p in _build_list()))
    assert shipped == set(bundle.data_files()) | {bundle.MANIFEST}


@pytest.mark.parametrize("name", ["rules_data/placement/placement_zip.csv", "rules_data/placement/placement_meta.csv",
                                  "placement_county.csv"])
def test_no_placement_table_can_ship(name):
    forbidden = re.search(r"const FORBIDDEN = \[(.*?)\];", BUILD, re.S).group(1)
    assert r"rules_data\/placement" in forbidden and r"placement_[^/]*\.csv" in forbidden
    assert not any(fnmatch.fnmatchcase(name, p) for p in _build_list())


def _forbidden_regexes():
    """build.mjs's FORBIDDEN list as Python regexes (each JS /.../i literal; \\/ means / in both)."""
    block = re.search(r"const FORBIDDEN = \[(.*?)\];", BUILD, re.S).group(1)
    return [re.compile(src, re.I if "i" in flags else 0) for src, flags in re.findall(r"/(.+?)/([a-z]*)(?:,|\s*$)", block)]


# Round 44b (Liam, 2026-10-25): the placement tables are bundled into the Worker as cloudflare/build/placement_data.js.
# The page's build must refuse that module however it gets there: by its own path, by name alone, or renamed.
# Round 45: + Ask the Guides' material (the guides' text and the Worker's chat index), by path, by name or renamed.
@pytest.mark.parametrize("name", ["cloudflare/build/placement_data.js", "placement_data.js", "src/placement_data.min.js",
                                  "cloudflare/build/anything_else.js", "rules_data/placement/placement_markets.csv",
                                  "rules_data/chat/guide_chunks.jsonl", "rules_data/chat/programs.json",
                                  "src/chat_index.js", "guide_chunks.jsonl.gz"])
def test_the_workers_placement_module_can_never_ship_in_the_page(name):
    rx = _forbidden_regexes()
    assert len(rx) >= 5, rx
    assert any(r.search(name) for r in rx), name
    for ok in ("src/app.js", "src/chat.js", "engine.tar.gz", "rules_data/carrier_rules_pilot_v5.csv", "build.json"):
        assert not any(r.search(ok) for r in rx), ok


def test_the_page_loads_the_manifest_before_any_check():
    js = open(os.path.join(ROOT, "web", "src", "engine.js"), encoding="utf-8").read()
    assert "engine_manifest.json" in js and "_web_api.load(manifest=" in js
    assert js.index("_web_api.load(manifest=") < js.index("def _web_call(")
