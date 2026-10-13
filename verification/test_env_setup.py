"""Round 38d step 1 (Liam, 2026-10-13): env_setup.load_env() loads the .env named by ELIGIBILITY_DOTENV when it is set and
exists, otherwise load_dotenv() as before, and never overwrites a value already in the environment. Zero API: the
"key" here is a made-up variable in a temporary file, never a real key name or value."""
import glob
import os
import sys

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import env_setup  # noqa: E402

pytestmark = pytest.mark.retrieval
FAKE = "ELIGIBILITY_TEST_FAKE_KEY"


@pytest.fixture
def clean(monkeypatch):
    monkeypatch.delenv(FAKE, raising=False)
    yield monkeypatch
    os.environ.pop(FAKE, None)            # load_dotenv sets it outside monkeypatch's bookkeeping


def _fake_env(tmp_path, value="fake-value-123"):
    p = tmp_path / "fake.env"
    p.write_text(f"{FAKE}={value}\n", encoding="utf-8")
    return str(p)


def test_the_named_file_is_loaded(clean, tmp_path):
    clean.setenv(env_setup.ENV_VAR, _fake_env(tmp_path))
    assert env_setup.load_env() == os.environ[env_setup.ENV_VAR]
    assert os.environ[FAKE] == "fake-value-123"


def test_without_the_variable_the_old_search_runs(clean, monkeypatch):
    clean.delenv(env_setup.ENV_VAR, raising=False)
    calls = []
    monkeypatch.setattr(env_setup, "load_dotenv", lambda *a, **k: calls.append((a, k)))
    assert env_setup.load_env() is None
    assert calls == [((), {"override": False})]


def test_a_missing_file_falls_back_to_the_old_search(clean, monkeypatch, tmp_path):
    clean.setenv(env_setup.ENV_VAR, str(tmp_path / "does-not-exist.env"))
    calls = []
    monkeypatch.setattr(env_setup, "load_dotenv", lambda *a, **k: calls.append((a, k)))
    assert env_setup.load_env() is None and calls == [((), {"override": False})]


def test_a_value_already_in_the_environment_wins(clean, tmp_path):
    clean.setenv(FAKE, "set-by-railway")
    clean.setenv(env_setup.ENV_VAR, _fake_env(tmp_path))
    env_setup.load_env()
    assert os.environ[FAKE] == "set-by-railway"


def test_no_module_calls_load_dotenv_itself():
    """Every entry point goes through env_setup (the comment in test_eligibility_matrix is not a call)."""
    offenders = []
    for path in glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "verification", "*.py")):
        if os.path.basename(path) in ("env_setup.py", "test_env_setup.py"):
            continue
        text = open(path, encoding="utf-8", errors="replace").read()
        if "load_dotenv(" in text.replace("# value -- eligibility_check.py calls load_dotenv() on import", ""):
            offenders.append(os.path.basename(path))
    assert offenders == []
