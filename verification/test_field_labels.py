"""Round 39 step 0a (Liam): agent text names a form field by its label, never by its key. Before, a row held on a
field with no written open fact read "Held: this guide needs to know plumbing_type" (Centauri DP3), "... trust_type"
(Foremost), "... dog_breeds" (Allied), "... pex_2011" (Progressive), "... solar_type" (Foremost), and the intake
contradiction note quoted "solar_panels: No". Zero API."""
import os
import re
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "fuzz"))
import rules_evaluator as rv  # noqa: E402
from test_held_reasons import HOME, LANDLORD  # noqa: E402

pytestmark = pytest.mark.retrieval
KEY = re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b")
FULL = dict(HOME, trust_type="Family trust", solar_type="Roof-mounted panels", solar_tesla="No",
            primary_home_carrier="Chubb", primary_home_miles=10, rental_units_total="1-4", rental_term="Long-term",
            losses_5yr="1", loss_types=["Water"], loss_year=2025, losses_3yr="1", electrical=["Circuit breakers"])


def _names(expr):
    return {t for t in re.findall(r"[a-z][a-z0-9_]*", re.sub(r"\{[^}]*\}|FACT\([^)]*\)", " ", expr or ""))
            if "_" in t or t in ("county", "zip", "ppc", "electrical")}


def test_every_field_a_map_line_reads_has_a_label():
    facts = set(rv.facts(FULL))
    read = set()
    for m in rv._map().values():
        read |= _names(m["test"]) | _names(m["gate"])
    read &= facts | set(FULL)
    assert read and not sorted(read - set(rv.FIELD_LABELS))


@pytest.mark.parametrize("unknown,want", [
    (["plumbing_type"], "Plumbing Type"),
    (["trust_type", "plumbing_type"], "Trust type; Plumbing Type"),
    (["ppc", "ppc_num"], "PPC Number"),                       # one label, said once
    (["dog_breeds", "the dog has no bite history"], "Breed(s) on the property; the dog has no bite history"),
])
def test_named(unknown, want):
    assert rv._named(unknown) == want


@pytest.fixture
def check(monkeypatch, tmp_path):
    import checks
    import eligibility_check as ec
    for flag in checks.LIVE_FLAGS:
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))
    monkeypatch.setattr(ec, "_complete", checks._fake)
    return lambda pd: {r["carrier"]: r for r in ec.check_eligibility(dict(pd))}


def _agent_texts(r, pd):
    import cards
    import confirm_topics
    yield cards.first_line_markdown(r, pd, None, label=False)
    yield from (cards.agent_text(m) for m in r.get("missing_info") or [] if isinstance(m, str))
    yield re.sub(r"<[^>]+>", " ", cards.confirm_html(r, pd, None))
    yield re.sub(r"<[^>]+>", " ", cards.details_html(r, guide=True))
    yield cards.warning_line(r)
    yield from (it["ask"] for it in confirm_topics.card_items(r, pd, None))


# the two phrasings of the bug: a blank plumbing answer (Centauri DP3) and an Unknown trust type (Foremost)
INLAND = dict(LANDLORD, ownership_type="Individual Owner", county="Travis", zip="", harris_east_146=None)


@pytest.mark.parametrize("pd,carrier,label", [
    (dict(INLAND, plumbing_type="Unknown"), "Centauri_-_DP3_-_11.16.2022", "Plumbing Type"),
    (dict(INLAND, ownership_type="Trust", trust_type="Unknown"), "Foremost_DP3_and_HO3_-_07.01.2026", "Trust type"),
])
def test_a_held_card_names_the_form_label(check, pd, carrier, label):
    r = check(pd)[carrier]
    assert r["status"] == "INSUFFICIENT_INFORMATION" and label in r["reasons"][0], r["reasons"]
    for text in _agent_texts(r, pd):
        assert not KEY.search(text or ""), text


def test_no_field_key_in_any_agent_text_over_fuzz_profiles(check):
    import gen
    leaks = []
    for seed in range(1, 26):
        pd, _ = gen.profile(seed)
        for r in check(pd).values():
            for text in _agent_texts(r, pd):
                leaks += [(seed, r.get("carrier"), k) for k in KEY.findall(text or "")]
    assert not leaks, leaks[:10]
