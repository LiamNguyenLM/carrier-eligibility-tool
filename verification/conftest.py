import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "retrieval: fast, deterministic, no LLM call -- run on every commit"
    )
    config.addinivalue_line(
        "markers", "baseline: slow, calls the real pipeline end to end (real API cost)"
    )
