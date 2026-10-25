"""Round 43 step 1 (Liam, 2026-10-24): the engine is one package (engine/) with no Streamlit, retrieval, model or
file-system dependency; Streamlit and the browser both call it. These tests keep it so:
- importing engine.api loads none of Streamlit, LangChain, Chroma, FastEmbed, Anthropic, OpenAI or the store's
  modules;
- the old module names (eligibility_check, rules_evaluator, cards, ...) are the same module objects as the engine's;
- rules_data/engine_manifest.json (the store's facts for the browser) matches the store;
- with ONLY the bundle's files registered (strictly: no disk) and the manifest, a fresh interpreter gives the same
  results pages as the native pipeline and as the golden file, on named and fuzz profiles;
- a carrier left for the model is "not evaluated" there, never a silent pass (two ways to reach it).
Zero API."""
import json
import os
import subprocess
import sys

import pytest

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(HERE, "parity"))
import engine.api as api  # noqa: E402
import engine.bundle as bundle  # noqa: E402
import engine.pipeline as pipeline  # noqa: E402
import export_golden as eg  # noqa: E402

pytestmark = pytest.mark.retrieval
OLD_NAMES = {"eligibility_check": "pipeline", "rules_evaluator": "rules_evaluator", "intake_fields": "intake_fields",
             "structured_rules": "structured_rules", "hold_guard": "hold_guard", "cards": "cards",
             "confirm_topics": "confirm_topics", "display_names": "display_names", "topics": "topics",
             "quotes": "quotes"}
HEAVY = ("streamlit", "langchain", "langchain_community", "langchain_core", "chromadb", "fastembed", "anthropic",
         "openai", "shared_resources", "store_cache", "data_defects", "guides", "usage_log", "env_setup", "httpx")
SAMPLE = ["LIVE", "LANDLORD", "HARRIS", "HOME", "HARTFORD_e_rpp", "HARTFORD_d_estate", "HARTFORD_k_1_fire",
          "R40_BASE", "R40_DEEP_3", "fuzz_0", "fuzz_7", "fuzz_1000", "fuzz_5003", "fuzz_9001", "fuzz_12681"]
FLAGS = ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH")


def _fresh(code, stdin=""):
    env = {k: v for k, v in os.environ.items() if k != "ELIGIBILITY_DOTENV"}
    for k in ("ELIGIBILITY_RULES_PILOT", "ELIGIBILITY_RULES_SAGE_BATCH", "ELIGIBILITY_RULES_HO3_BATCH",
              "ELIGIBILITY_RULES_DP_BATCH"):
        env[k] = "1"                                     # the live configuration (the browser has no variables)
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, input=stdin, capture_output=True,
                         text=True, encoding="utf-8", timeout=600)
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout


def test_the_engine_imports_no_streamlit_retrieval_model_or_store_module():
    loaded = json.loads(_fresh("import json, sys; import engine.api; print(json.dumps(sorted(sys.modules)))"))
    assert [m for m in loaded if m.split(".")[0] in HEAVY] == []


@pytest.mark.parametrize("old,new", OLD_NAMES.items())
def test_the_old_name_is_the_engine_module(old, new):
    import importlib
    assert importlib.import_module(old) is importlib.import_module(f"engine.{new}")


def test_the_manifest_matches_the_store():
    import build_engine_manifest
    with open(os.path.join(ROOT, bundle.MANIFEST), encoding="utf-8") as fh:
        assert json.load(fh) == json.loads(build_engine_manifest.text(build_engine_manifest.manifest())), \
            "rules_data/engine_manifest.json is stale: run python build_engine_manifest.py and commit it"


BROWSER = r"""
import json, sys
from engine import data
inp = json.load(sys.stdin)
data.register(inp["files"], strict=True)          # before any engine module reads a table
import contextlib
import engine.api as api
api.load(manifest=inp["manifest"])
with contextlib.redirect_stdout(sys.stderr):      # the pipeline's diagnostic prints (the browser's console)
    pages = {pid: api.check(pd, checked) for pid, pd, checked in inp["profiles"]}
print(json.dumps(pages, default=str))
"""


def _browser_pages(profiles):
    files = {p: open(os.path.join(ROOT, p), encoding="utf-8").read() for p in bundle.data_files()}
    with open(os.path.join(ROOT, bundle.MANIFEST), encoding="utf-8") as fh:
        manifest = json.load(fh)
    return json.loads(_fresh(BROWSER, json.dumps({"files": files, "manifest": manifest, "profiles": profiles},
                                                 default=str)))


@pytest.fixture(scope="module")
def sample():
    prof = {pid: (pd, ch) for pid, pd, ch in eg.all_profiles()}
    return [(pid, *prof[pid]) for pid in SAMPLE]


@pytest.fixture(scope="module")
def browser(sample):
    return _browser_pages(sample)


def test_the_browser_engine_matches_the_golden_file(browser):
    assert eg.compare(eg.load(eg.GOLDEN), eg.doc_from_pages(browser), partial=True) == []


def test_the_browser_engine_matches_the_native_pipeline(browser, sample, monkeypatch):
    for f in FLAGS:
        monkeypatch.setattr(pipeline, f, True)
    monkeypatch.setattr(pipeline, "_complete", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model call")))
    native = {pid: api.check(pd, checked) for pid, pd, checked in sample}
    assert json.loads(json.dumps(native, default=str)) == browser


def test_an_unlisted_data_file_is_an_error_in_strict_mode():
    out = _fresh("from engine import data\n"
                 "data.register({}, strict=True)\n"
                 "try:\n    import engine.intake_fields\nexcept FileNotFoundError as e:\n    print('refused', e)\n")
    assert out.startswith("refused") and "texas_counties.csv" in out


@pytest.mark.parametrize("how", ["dp_batch_off", "carrier_without_a_table"])
def test_a_carrier_left_for_the_model_is_not_evaluated_without_a_store(how, monkeypatch):
    with open(os.path.join(ROOT, bundle.MANIFEST), encoding="utf-8") as fh:
        manifest = json.load(fh)
    for f in FLAGS:
        monkeypatch.setattr(pipeline, f, True)
    pd, checked = dict(eg.all_profiles()[4][1]), None          # LANDLORD (tenant occupied: the DP batch)
    assert eg.all_profiles()[4][0] == "LANDLORD"
    if how == "dp_batch_off":
        monkeypatch.setattr(pipeline, "RULES_DP_BATCH", False)
        model_carriers = {c for c in pipeline.rules_evaluator.BATCHES["dp"]["carriers"].values()}
    else:
        manifest = dict(manifest, carriers=manifest["carriers"] + ["New_Carrier_DP3_-_01.01.2027"])
        model_carriers = {"New_Carrier_DP3_-_01.01.2027"}
    called = []
    monkeypatch.setattr(pipeline, "_complete", lambda *a, **k: called.append(1))
    monkeypatch.setattr(pipeline, "FACTS", manifest)
    page = api.check(pd, checked)
    statuses = {c["carrier"]: c["status"] for c in page["cards"]}
    routed = model_carriers & set(statuses)
    assert routed and all(statuses[c] == pipeline.NOT_EVALUATED for c in routed), statuses
    assert called == [] and set(page["header"]["not_checked_names"]) >= {
        c["name"] for c in page["cards"] if c["carrier"] in routed}


def test_the_guide_unavailable_text_names_data_defects_kind():
    import data_defects
    assert set(pipeline._GUIDE_UNAVAILABLE_TEXT) == {data_defects.NO_TEXT}
