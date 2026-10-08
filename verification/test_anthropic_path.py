"""Round 28 step 5 (2026-10-07): the Anthropic path is production-equal for
Claude 5-generation models (claude-haiku-5-5), for measurement only. Zero API:
the client is replaced by a fake that records the request.

Measured on the real API the same day (claude-haiku-5-5):
- strict structured output works through output_config.format, carrier enum
  included (a third carrier the prompt asked about was refused);
- "For 'array' type, property 'maxItems' is not supported" (400), so the two-item
  limit is enforced on the parsed answer instead;
- "`temperature` is deprecated for this model" (400);
- thinking blocks come back and count against max_tokens."""
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import eligibility_check as ec  # noqa: E402

pytestmark = pytest.mark.retrieval

ROOT = os.path.join(os.path.dirname(__file__), "..")


class FakeMessages:
    def __init__(self, text):
        self.text, self.kwargs = text, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=7,
                                cache_creation_input_tokens=0)
        return SimpleNamespace(content=[SimpleNamespace(type="thinking", thinking="..."),
                                        SimpleNamespace(type="text", text=self.text)],
                               usage=usage, stop_reason="end_turn")


ANSWER = {"carriers": [{"carrier": "A_HO3", "reasons": ["r1", "r2", "r3", "r4"], "citations": ["c1", "c2", "c3"],
                        "missing_info": [], "notes": "", "status": "INELIGIBLE", "flaw_count": 4},
                       {"carrier": "B_HO3", "reasons": ["r1"], "citations": [], "missing_info": [], "notes": "",
                        "status": "ELIGIBLE", "flaw_count": 0}]}


def _call(monkeypatch, model, effort=None, structured=True):
    fake = FakeMessages(json.dumps(ANSWER))
    monkeypatch.setattr(ec, "client", SimpleNamespace(messages=fake))
    monkeypatch.setattr(ec, "ELIGIBILITY_MODEL", model)
    monkeypatch.setattr(ec, "ELIGIBILITY_EFFORT", effort)
    monkeypatch.setattr(ec, "ELIGIBILITY_STRUCTURED", structured)
    text, usage = ec._complete_named(["A_HO3", "B_HO3"], "SYSTEM", "USER", 1000)
    return fake.kwargs, text, usage


@pytest.mark.parametrize("model,gen5", [("claude-haiku-5-5", True), ("claude-sonnet-5", True),
                                        ("claude-sonnet-4-5", False), ("claude-haiku-4-5-20251001", False),
                                        ("gpt-6-luna", False)])
def test_claude_generation_5_detection(model, gen5):
    assert ec._is_claude_gen5(model) is gen5


def test_haiku_5_5_gets_the_production_schema_with_the_carrier_enum(monkeypatch):
    kw, _, _ = _call(monkeypatch, "claude-haiku-5-5")
    fmt = kw["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    item = fmt["schema"]["properties"]["carriers"]["items"]
    assert item["properties"]["carrier"]["enum"] == ["A_HO3", "B_HO3"]
    assert item["properties"]["status"]["enum"] == ["ELIGIBLE", "INELIGIBLE", "REFER", "INSUFFICIENT_INFORMATION"]
    assert "maxItems" not in json.dumps(fmt["schema"])
    assert set(item["required"]) == set(ec.CARRIER_RESULTS_SCHEMA["properties"]["carriers"]["items"]["required"])
    assert "temperature" not in kw
    assert kw["max_tokens"] == 1000 + 4000
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}       # caching on the stable system part
    assert "effort" not in kw["output_config"]                             # unset: the model's default


@pytest.mark.parametrize("effort", ["low", "medium"])
def test_the_effort_setting_is_passed_when_set(monkeypatch, effort):
    kw, _, _ = _call(monkeypatch, "claude-haiku-5-5", effort=effort)
    assert kw["output_config"]["effort"] == effort


def test_two_reasons_and_two_citations_at_most_as_luna(monkeypatch):
    _, text, usage = _call(monkeypatch, "claude-haiku-5-5")
    recs = json.loads(text)["carriers"]
    assert [len(r["reasons"]) for r in recs] == [2, 1] and [len(r["citations"]) for r in recs] == [2, 0]
    assert usage["trimmed_lists"] == 2
    assert usage["cache_read_input_tokens"] == 7


def test_an_older_claude_model_keeps_its_exact_call(monkeypatch):
    kw, text, _ = _call(monkeypatch, "claude-sonnet-4-5")
    assert kw["temperature"] == 0 and kw["max_tokens"] == 1000 and "output_config" not in kw
    assert json.loads(text) == ANSWER


def test_the_default_model_is_haiku_at_low_effort():
    # CHANGED DELIBERATELY (round 31 step 1, 2026-10-08; Liam's decision 1): the tool runs on Claude
    # Haiku 5.5 at low effort; unset variables mean that (was gpt-6-luna with effort unset).
    env = {k: v for k, v in os.environ.items() if k not in ("ELIGIBILITY_MODEL", "ELIGIBILITY_EFFORT")}
    env.update(ANTHROPIC_API_KEY="x", OPENAI_API_KEY="x")
    out = subprocess.run([sys.executable, "-c", "import eligibility_check as e; print(e.ELIGIBILITY_MODEL, "
                                                "e.ELIGIBILITY_EFFORT)"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
    assert out.stdout.strip().splitlines()[-1] == "claude-haiku-5-5 low", out.stderr[-500:]
