"""Round 43 step 0c (Liam, 2026-10-24): the "Ask the Guides" chat tab is dropped -- it was the one feature that
called a paid API on every use, and the Cloudflare version has no server to run it. The app has two tabs, chat.py
is gone, and nothing imports it. The OpenAI package stays: eligibility_check's fallback model (Luna) uses it. Zero
API."""
import os
import re

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
APP = os.path.join(ROOT, "app.py")
pytestmark = pytest.mark.retrieval


def test_the_app_renders_two_tabs_and_no_chat():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["authenticated"] = True
    at.run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Eligibility Check", "Manage Carriers"]
    assert not at.chat_input


def test_chat_py_is_gone_and_nothing_imports_it():
    assert not os.path.exists(os.path.join(ROOT, "chat.py"))
    for d, _, files in os.walk(ROOT):
        if any(part in d for part in ("venv", "carrier_docs_db", ".git", "node_modules")):
            continue
        for f in files:
            if f.endswith(".py"):
                src = open(os.path.join(d, f), encoding="utf-8", errors="replace").read()
                assert not re.search(r"^\s*(import chat\b|from chat import)", src, re.M), os.path.join(d, f)
