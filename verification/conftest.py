import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Pin the suite to Sonnet regardless of the app's own default. As of
# 2026-09-29 both eligibility_check.ELIGIBILITY_MODEL and chat.CHAT_MODEL
# default to gpt-6-luna in production (Liam's prototype decision), but every
# baseline, pass rate and xfail this suite carries was measured against
# Sonnet -- CLAUDE.md's whole test-tier structure assumes that. setdefault so
# a developer who explicitly sets the env var before running pytest (to
# smoke-test Luna through the real suite) is not overridden.
os.environ.setdefault("ELIGIBILITY_MODEL", "claude-sonnet-4-5")
os.environ.setdefault("CHAT_MODEL", "claude-sonnet-4-5")
# Round 31 step 2: checks made by the suite log to a throwaway file, never the real usage log.
import tempfile  # noqa: E402
os.environ.setdefault("ELIGIBILITY_USAGE_LOG", os.path.join(tempfile.gettempdir(), "eligibility_usage_test_log.jsonl"))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "retrieval: fast, deterministic, no LLM call -- run on every commit"
    )
    config.addinivalue_line(
        "markers", "baseline: slow, calls the real pipeline end to end (real API cost)"
    )
