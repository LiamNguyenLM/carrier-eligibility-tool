"""Round 31 step 1 (Liam, 2026-10-08, decision 1): Claude Haiku 5.5 at low effort is the default; when
Anthropic is unavailable (after the SDK's own retries) the same call runs once on gpt-6-luna and the
result header says so. A parse problem never falls back. Zero API."""
import json
import os
import re
import subprocess
import sys

import anthropic
import httpx
import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
import eligibility_check as ec  # noqa: E402
from profiles import STANDARD_PROFILE  # noqa: E402

pytestmark = pytest.mark.retrieval
REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status(cls, code):
    return cls(f"{code} error", response=httpx.Response(code, request=REQ), body=None)


UNAVAILABLE = {
    "overloaded (529)": lambda: _status(anthropic.APIStatusError, 529),
    "rate limit (429)": lambda: _status(anthropic.RateLimitError, 429),
    "server error (500)": lambda: _status(anthropic.InternalServerError, 500),
    "bad gateway (502)": lambda: _status(anthropic.APIStatusError, 502),
    "timeout": lambda: anthropic.APITimeoutError(request=REQ),
    "connection": lambda: anthropic.APIConnectionError(request=REQ),
    "rejected key (401)": lambda: _status(anthropic.AuthenticationError, 401),
    "no API key": lambda: TypeError('"Could not resolve authentication method. Expected one of api_key, '
                                    'auth_token, or credentials to be set."'),
}


@pytest.mark.parametrize("env,want", [({}, ("claude-haiku-5-5", "low")),
                                      ({"ELIGIBILITY_MODEL": "gpt-6-luna"}, ("gpt-6-luna", "low")),
                                      ({"ELIGIBILITY_EFFORT": "medium"}, ("claude-haiku-5-5", "medium"))])
def test_the_default_is_haiku_5_5_at_low_effort(env, want):
    base = {k: v for k, v in os.environ.items() if k not in ("ELIGIBILITY_MODEL", "ELIGIBILITY_EFFORT")}
    out = subprocess.run([sys.executable, "-c", "import eligibility_check as e; print(e.ELIGIBILITY_MODEL, "
                                                "e.ELIGIBILITY_EFFORT, e.FALLBACK_MODEL)"],
                         cwd=ROOT, env=dict(base, ANTHROPIC_API_KEY="x", OPENAI_API_KEY="x", **env),
                         capture_output=True, text=True, timeout=300)
    model, effort, fallback = out.stdout.strip().splitlines()[-1].split()
    assert (model, effort) == want and fallback == "gpt-6-luna"


def _patch(monkeypatch, anthropic_behaviour, openai_behaviour=None):
    calls = {"anthropic": 0, "openai": []}

    def fake_anthropic(system, user, max_tokens):
        calls["anthropic"] += 1
        return anthropic_behaviour(calls["anthropic"])

    def fake_openai(system, user, max_tokens, model=None):
        calls["openai"].append(model)
        if openai_behaviour:
            return openai_behaviour()
        return json.dumps({"carriers": []}), {"input_tokens": 1, "output_tokens": 1,
                                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    monkeypatch.setattr(ec, "ELIGIBILITY_MODEL", "claude-haiku-5-5")
    monkeypatch.setattr(ec, "_complete_anthropic", fake_anthropic)
    monkeypatch.setattr(ec, "_complete_openai", fake_openai)
    return calls


def _raise(make):
    def behaviour(n):
        raise make()
    return behaviour


@pytest.mark.parametrize("kind", sorted(UNAVAILABLE))
def test_each_unavailable_error_runs_the_call_once_on_luna(monkeypatch, kind):
    calls = _patch(monkeypatch, _raise(UNAVAILABLE[kind]))
    text, usage = ec._complete("s", "u", 100)
    assert calls["anthropic"] == 1 and calls["openai"] == ["gpt-6-luna"]
    assert usage["fallback"] is True and usage["model"] == "gpt-6-luna"


def test_a_bad_request_is_not_a_fallback(monkeypatch):
    calls = _patch(monkeypatch, _raise(lambda: _status(anthropic.BadRequestError, 400)))
    with pytest.raises(anthropic.BadRequestError):
        ec._complete("s", "u", 100)
    assert calls["openai"] == []


def test_a_parse_problem_never_falls_back(monkeypatch):
    # an empty reply is returned as text; the check's own empty-reply retry runs on Claude again
    empty = {"input_tokens": 1, "output_tokens": 0, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    calls = _patch(monkeypatch, lambda n: ("", dict(empty)))
    res = ec.check_eligibility(dict(STANDARD_PROFILE, county="Bexar"))
    assert calls["openai"] == [] and calls["anthropic"] >= 2
    assert not any(r.get("model_fallback") for r in res)


def test_when_both_fail_the_anthropic_error_is_shown(monkeypatch):
    def luna_down():
        raise RuntimeError("luna down too")
    calls = _patch(monkeypatch, _raise(UNAVAILABLE["overloaded (529)"]), luna_down)
    with pytest.raises(anthropic.APIStatusError):
        ec._complete("s", "u", 100)
    assert calls["openai"] == ["gpt-6-luna"]


def test_a_fallback_check_is_stamped_for_the_header_and_the_panel(monkeypatch):
    def answer():
        return json.dumps({"carriers": []}), {"input_tokens": 1, "output_tokens": 1,
                                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    _patch(monkeypatch, _raise(UNAVAILABLE["timeout"]), answer)
    res = ec.check_eligibility(dict(STANDARD_PROFILE, county="Bexar"))
    assert res and all(r.get("model_fallback") for r in res)
    assert ec.LAST_CHECK_INFO["fallback"] is True
    assert "last check used the FALLBACK model" in ec.model_status_line()
    assert ec.FALLBACK_LINE == "Checked with the fallback model (Anthropic unavailable)"


def test_a_normal_check_is_not_stamped(monkeypatch):
    def ok(n):
        return json.dumps({"carriers": []}), {"input_tokens": 1, "output_tokens": 1,
                                              "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    _patch(monkeypatch, ok)
    res = ec.check_eligibility(dict(STANDARD_PROFILE, county="Bexar"))
    assert not any(r.get("model_fallback") for r in res) and ec.LAST_CHECK_INFO["fallback"] is False
    assert re.search(r"Model: claude-haiku-5-5 \(effort \w+\); fallback gpt-6-luna -- last check used the main",
                     ec.model_status_line())
