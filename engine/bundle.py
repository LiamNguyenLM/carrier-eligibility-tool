"""Round 43 step 1: what the browser bundle carries -- the engine's code and every data file it reads (one list, used
by the web build and the tests; test_engine_split.py runs checks with ONLY these files registered, strictly)."""
import os

from . import data

MANIFEST = "rules_data/engine_manifest.json"


def code_files():
    """engine/*.py, repo-relative."""
    here = os.path.dirname(os.path.abspath(__file__))
    return sorted(data.relpath(os.path.join(here, f)) for f in os.listdir(here) if f.endswith(".py"))


def data_files():
    """Every data file the engine opens (engine.data.open_text), repo-relative: the rules tables and map lines,
    CFIG knowledge, the Occidental counties (rules_evaluator's *_CSV paths) and the county / ZIP tables."""
    from . import intake_fields
    from . import rules_evaluator
    paths = {v for k, v in vars(rules_evaluator).items() if k.endswith("_CSV") and isinstance(v, str)}
    paths |= {intake_fields.TEXAS_COUNTIES_FILE, intake_fields.ZIP_COUNTIES_FILE}
    return sorted(data.relpath(p) for p in paths)
