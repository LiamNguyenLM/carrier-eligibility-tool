"""carrier_mcp.py -- the MCP server Hermes / CFIG-GPT calls (Liam, 2026-10-16).

Fast tier only (marker: retrieval): no model call, no API key needed. The paid end-to-end comparison with the
app is verification/mcp_parity.py, run by hand.
"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

pytest.importorskip("mcp")
import carrier_mcp  # noqa: E402

pytestmark = pytest.mark.retrieval


# --- the server itself -------------------------------------------------------------------------------------------
# 2026-10-24, office laptop: this test hung (10 min) while the server's warm-up ran in a background thread next to a
# pending stdin read -- a Windows handle stall, not the index (diag_load.py loaded everything in 27 s on one thread).
# The server now loads before it reads stdin. Kept first in the file so a run never has two processes loading at once.

# Generous (a cold start loads the index and embedding model), but still a hard stop.
TIMEOUT_S = 600


def test_server_speaks_mcp_over_clean_stdout():
    """Start carrier_mcp.py the way Hermes does and talk raw JSON-RPC to it. Every stdout line must be a protocol
    message: a stray print would break this. No MCP client library here -- its stdio client hung under pytest on
    Windows (2026-10-24, the test ran 12 minutes) -- and a hard timeout so this test can never hang the suite."""
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_carriers", "arguments": {}}},
    ]
    import tempfile
    import time
    errlog = tempfile.TemporaryFile()              # the server's own timing log, shown if this test fails
    started = time.perf_counter()
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "carrier_mcp.py")], cwd=ROOT,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errlog)
    try:
        for msg in msgs:
            proc.stdin.write((json.dumps(msg) + "\n").encode())
            proc.stdin.flush()
        replies = {}
        import threading
        def read():
            for raw in proc.stdout:
                line = raw.decode("utf-8").strip()
                if line:
                    msg = json.loads(line)              # a non-JSON line (a stray print) fails here
                    replies[msg.get("id")] = msg
                if 3 in replies:
                    return
        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        reader.join(timeout=TIMEOUT_S)
        if 3 not in replies:
            errlog.seek(0)
            log = [l for l in errlog.read().decode("utf-8", "replace").splitlines() if "carrier_mcp" in l]
            pytest.fail(f"server answered only {sorted(k for k in replies if k is not None)} within {TIMEOUT_S} s "
                        f"(waited {time.perf_counter() - started:.0f} s). Server log:\n" + "\n".join(log[-15:]))
    finally:
        proc.kill()
        proc.wait(timeout=30)
    tools = {t["name"] for t in replies[2]["result"]["tools"]}
    assert tools == {"list_carriers", "search_guidelines", "check_eligibility", "carrier_details"}
    assert not replies[3]["result"].get("isError")


# --- profile -> property_details / checked topics ---------------------------------------------------------

def test_occupancy_ownership_and_dwelling_type_are_required():
    _, _, errors = carrier_mcp.build_property_details({"roof_age": 12})
    for key in ("occupancy_type", "ownership_type", "dwelling_type"):
        assert any(key in e for e in errors), key


def test_blank_dwelling_type_is_not_a_house():
    """Round 41 live run (2026-10-24): a blank dwelling type held 18 carriers on units / firewalls and let Progressive
    HO6 (condo only) through as ELIGIBLE for a house. The form always sends one, so the server must too."""
    _, _, errors = carrier_mcp.build_property_details(
        {"occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner", "dwelling_type": ""})
    assert any("dwelling_type" in e for e in errors)


def test_only_given_topics_are_checked():
    pd, checked, errors = carrier_mcp.build_property_details(
        {"occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner", "dwelling_type": "House", "roof_age": 12,
         "roof_type": "Tile"})
    assert errors == []
    assert set(checked) == {"roof_age", "roof_type"}
    assert pd["roof_age"] == 12 and pd["roof_type"] == "Tile"


def test_pool_fields_check_the_pool_topic_two_ways():
    for extra in ({"swimming_pool": "In Ground - Fenced"}, {"pool_accessories": "Slide only"}):
        _, checked, errors = carrier_mcp.build_property_details(
            {"occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner", "dwelling_type": "House", **extra})
        assert errors == [] and checked == ["pool"]


def test_wrong_value_returns_the_allowed_list():
    _, _, errors = carrier_mcp.build_property_details(
        {"occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner", "dwelling_type": "House", "roof_shape": "Pointy"})
    assert any("roof_shape" in e and "Gable" in e for e in errors)


def test_unknown_field_is_rejected_not_ignored():
    _, _, errors = carrier_mcp.build_property_details(
        {"occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner", "dwelling_type": "House", "trampoline": "Yes"})
    assert any("trampoline" in e for e in errors)


@pytest.mark.parametrize("label", ["Tier 1 - Closest to coast", "Tier 1"])
def test_coastal_tier_takes_the_form_label_or_the_short_value(label):
    pd, checked, errors = carrier_mcp.build_property_details(
        {"occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner", "dwelling_type": "House", "coastal_tier": label})
    assert errors == [] and pd["coastal_tier"] == "Tier 1" and checked == ["coastal"]


@pytest.mark.parametrize("amount", [450000, "450,000", "$450000"])
def test_dwelling_amount_parses_like_the_form(amount):
    pd, _, errors = carrier_mcp.build_property_details(
        {"occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner", "dwelling_type": "House", "dwelling_amount": amount})
    assert errors == [] and pd["dwelling_amount"] == 450000


def test_dog_breeds_dropped_when_no_dogs():
    pd, _, _ = carrier_mcp.build_property_details(
        {"occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner", "dwelling_type": "House", "has_dogs": "No"})
    assert pd["dog_breeds"] == []


# --- search_guidelines: carrier isolation ------------------------------------------------------------------

def _two_carriers():
    names = [c["carrier"] for c in carrier_mcp.list_carriers()]
    assert len(names) >= 2
    return names[0], names[-1]


def test_list_carriers_names_resolve_exactly():
    for row in carrier_mcp.list_carriers():
        resolved, err = carrier_mcp._resolve_carrier(row["carrier"])
        assert err is None and resolved == row["carrier"]


@pytest.mark.parametrize("query", ["roof age requirements", "prior losses claims history"])
def test_carrier_filter_never_returns_another_carriers_text(query):
    for carrier in _two_carriers():
        out = carrier_mcp.search_guidelines(query, carrier=carrier, k=8)
        assert out["passages"], f"no passages for {carrier}"
        assert {p["carrier"] for p in out["passages"]} == {carrier}


def test_ambiguous_carrier_name_is_a_choice_not_a_guess():
    names = [c["carrier"] for c in carrier_mcp.list_carriers()]
    sage = [n for n in names if "sage" in n.lower()]
    if len(sage) < 2:
        pytest.skip("needs two Sage programs in the index")
    out = carrier_mcp.search_guidelines("roof", carrier="Sage")
    assert "error" in out and set(sage) <= set(out["candidates"])


def test_allied_trust_overview_is_readable():
    """Open issue (carrier-eligibility memory): Allied Trust HO3 used to return only a table header."""
    names = [c["carrier"] for c in carrier_mcp.list_carriers() if "allied" in c["carrier"].lower()]
    if not names:
        pytest.skip("Allied Trust not in the index")
    out = carrier_mcp.search_guidelines("quick program overview claims history liability fire ineligible",
                                        carrier=names[0], k=8)
    assert any(not p["header_only"] and "Liability" in p["text"] for p in out["passages"])


def test_search_reply_fits_under_hermes_spill_limit():
    """Hermes saves tool results over ~8,000 characters to a file and the model then reads pieces of it."""
    out = carrier_mcp.search_guidelines("roof age requirements and ineligible roofs", k=8)
    assert len(json.dumps(out)) < 8000


def test_card_guide_date_falls_back_to_the_file_name():
    """Live run 2026-10-24: Mercury's card said "not stated" while the app showed 01/01/2026 (from the file name)."""
    mercury = [c["carrier"] for c in carrier_mcp.list_carriers() if c["carrier"].lower().startswith("mercury")]
    if not mercury:
        pytest.skip("Mercury not in the index")
    pd, checked, _ = carrier_mcp.build_property_details(
        {"occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner", "dwelling_type": "House"})
    out = carrier_mcp.card({"carrier": mercury[0], "status": "ELIGIBLE", "reasons": []}, pd, checked)
    assert out["guide_date"] != "not stated" or "." not in mercury[0]


@pytest.mark.parametrize("dwelling, quote, ok", [
    ("House", "owner-occupied home", False),          # the 2026-10-24 live run: "home" is not a dwelling type
    ("House", "", False),
    ("House", "House", True),
    ("House", "it's a single-family house", True),
    ("Townhome", "it's a townhouse", True),
    ("Condo", "a condo unit", True),
    ("Condo", "it's a house", False),                  # words name a different type than the one passed
])
def test_dwelling_type_must_be_the_agents_words(dwelling, quote, ok):
    assert (carrier_mcp.dwelling_quote_problem(dwelling, quote) is None) == ok


def test_check_refuses_a_guessed_dwelling_type_before_any_paid_call():
    out = carrier_mcp.check_eligibility(
        {"occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner", "dwelling_type": "House"},
        dwelling_type_quote="owner-occupied home")
    assert out.startswith("PROFILE NOT ACCEPTED") and "ASK" in out
