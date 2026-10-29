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
    for ok in ("src/app.js", "src/chat.js", "src/chat_cards.js", "src/theme.js", "src/cfig-logo.png",
               "src/cfig-logo-dark.png", "engine.tar.gz", "rules_data/carrier_rules_pilot_v5.csv", "build.json"):
        assert not any(r.search(ok) for r in rx), ok


def test_the_page_loads_the_manifest_before_any_check():
    js = open(os.path.join(ROOT, "web", "src", "engine.js"), encoding="utf-8").read()
    assert "engine_manifest.json" in js and "_web_api.load(manifest=" in js
    assert js.index("_web_api.load(manifest=") < js.index("def _web_call(")


# Round 46 (Liam, 2026-10-29): the CFIG logo at the top (a light-text copy in dark mode), light / dark mode, and the
# chat's carrier cards. The page ships each file; theme.js is a classic script ahead of the stylesheet, so the saved
# theme is set before the page paints; every colour in the stylesheet has a dark value.
def test_the_page_ships_the_logo_the_theme_and_the_chat_cards():
    page = re.search(r"const PAGE_FILES = \[(.*?)\];", BUILD, re.S).group(1)
    html = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
    for f in ("src/chat_cards.js", "src/theme.js", "src/cfig-logo.png", "src/cfig-logo-dark.png"):
        assert f'"{f}"' in page, f
        assert os.path.getsize(os.path.join(ROOT, "web", f)) > 0, f
    assert 'src="src/cfig-logo.png" alt="CFIG"' in html and 'src="src/cfig-logo-dark.png"' in html
    assert html.index('<script src="src/theme.js"></script>') < html.index('href="src/styles.css"')
    assert 'id="theme-toggle"' in html


def test_every_colour_token_has_a_dark_value():
    css = open(os.path.join(ROOT, "web", "src", "styles.css"), encoding="utf-8").read()
    light = re.search(r":root \{(.*?)\}", css, re.S).group(1)
    auto = re.search(r'@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{(.*?)\}', css, re.S).group(1)
    picked = re.search(r':root\[data-theme="dark"\] \{(.*?)\}', css, re.S).group(1)
    names = lambda block: set(re.findall(r"(--[a-z-]+):\s*#", block))
    assert names(light) and names(light) == names(auto) == names(picked)
    # outside the tokens only white is written out (text on the red buttons, the switch's knob)
    rules = re.sub(r":root[^{]*\{[^}]*\}", "", css)
    assert set(re.findall(r"#[0-9a-fA-F]{3,8}", rules)) <= {"#fff"}


def test_the_chat_cards_split_in_node():
    import subprocess
    out = subprocess.run(["node", "--test", "web/tests/chat_cards.test.mjs"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", timeout=300)
    assert out.returncode == 0, (out.stdout + out.stderr)[-3000:]
