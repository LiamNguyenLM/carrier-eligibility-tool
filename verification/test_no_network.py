"""Round 42 step 0b (Liam, 2026-10-24): does a normal check still call OpenAI or any paid API? Measured on Liam's
Harris HO3 check and LANDLORD in the live configuration (every rules-table batch on, the placement panel on, the key
loaded): no outbound connection and no DNS lookup, at import or in a check; the model was not called. The only
lookups a check makes are the two local retrieval searches (FastEmbed + Chroma on disk) of the risk-factor pass.
The chat tab ("Ask the Guides", chat.py) is the one feature that calls a paid API (OpenAI); it is not tested here.

These tests keep it so: with every socket connect and DNS lookup made to fail, a check and the placement panel
still run and give the same cards, and nothing tried to reach the network. Zero API."""
import os
import socket
import sys

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import eligibility_check as ec  # noqa: E402
import placement  # noqa: E402
import profiles as P  # noqa: E402
from test_held_reasons import LANDLORD  # noqa: E402

HARRIS = (P.HARRIS_PROFILE, P.HARRIS_CHECKED)

pytestmark = pytest.mark.retrieval


@pytest.fixture
def offline(monkeypatch, tmp_path):
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setenv("ELIGIBILITY_USAGE_LOG", str(tmp_path / "u.jsonl"))
    tried = []

    def no_model(*a, **k):
        tried.append(("model", ""))
        raise RuntimeError("a check called the model")

    def connect(self, address):
        tried.append(("connect", str(address)))
        raise OSError("network blocked by test_no_network")

    def gai(host, *a, **k):
        tried.append(("dns", str(host)))
        raise socket.gaierror("network blocked by test_no_network")
    monkeypatch.setattr(ec, "_complete", no_model)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, address: connect(self, address))
    monkeypatch.setattr(socket, "getaddrinfo", gai)
    monkeypatch.setattr(socket, "create_connection", lambda address, *a, **k: connect(None, address))
    return tried


def _cards(pd, checked):
    return {r["carrier"]: (r["status"], tuple(r.get("reasons") or ())) for r in
            ec.check_eligibility(dict(pd), checked_topics=checked, log_usage=False)}


@pytest.mark.parametrize("name,pd,checked", [("HARRIS", *HARRIS), ("LANDLORD", LANDLORD, None)],
                         ids=["harris_ho3", "landlord"])
def test_a_check_makes_no_network_call_and_no_model_call(offline, name, pd, checked):
    cards = _cards(pd, checked)
    assert offline == [], offline
    assert len(cards) >= 10 and all(s in ("ELIGIBLE", "REFER", "INSUFFICIENT_INFORMATION", "INELIGIBLE")
                                     for s, _ in cards.values()), name


def test_the_cards_are_the_same_with_the_network_blocked(offline, monkeypatch):
    blocked = _cards(*HARRIS)
    monkeypatch.undo()                                      # the network back (nothing is reached either way)
    for flag in ("RULES_PILOT", "RULES_SAGE_BATCH", "RULES_HO3_BATCH", "RULES_DP_BATCH"):
        monkeypatch.setattr(ec, flag, True)
    monkeypatch.setattr(ec, "_complete", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model call")))
    assert _cards(*HARRIS) == blocked


def test_the_placement_panel_makes_no_network_call(offline):
    res = ec.check_eligibility(dict(HARRIS[0]), checked_topics=HARRIS[1], log_usage=False)
    placement.load_tables()
    placement.panel(res, HARRIS[0])
    assert offline == [], offline
