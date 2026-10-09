"""Round 33 step 2 (Liam, 2026-10-09): the "Where we usually place homes like this" panel. Zero API.
Synthetic tables; results are made-up cards."""
import os
import re
import sys
from collections import defaultdict

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import placement  # noqa: E402

pytestmark = pytest.mark.retrieval
AS_OF = "2026-10"
A0 = placement.month_index(AS_OF)
MARKETS = [("Allied_Trust", "Allied Trust"), ("Mercury_", "Mercury"), ("TWICO_", "TWICO"), ("Travelers_", "Travelers"),
           ("Orion_", "Orion180")]
PROGRAM = {"Allied Trust": "Allied_Trust_HO3", "Mercury": "Mercury_HO3_-_01.01.2026", "TWICO": "TWICO_HO3",
           "Travelers": "Travelers_HO3_-_06.12.2026", "Orion180": "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3"}


def tables(zip_sales=None, county_sales=None, other=None, profile=None, ago=1):
    """zip_sales / county_sales: {market: n} for one month `ago` months before as_of in ZIP 77494 / Fort
    Bend; `other`: sales elsewhere (statewide only)."""
    T = {"zip": defaultdict(list), "county": defaultdict(list), "profile": defaultdict(list), "all": [],
         "markets": MARKETS, "meta": {"data_through": "2026-10", "policies": "123"}}
    for m, n in (zip_sales or {}).items():
        T["zip"]["77494"].append((A0 - ago, m, n))
        T["all"].append((A0 - ago, m, n))
    for m, n in (county_sales or {}).items():
        T["county"]["Fort Bend"].append((A0 - ago, m, n))
    for m, n in (other or {}).items():
        T["zip"]["79999"].append((A0 - ago, m, n))
        T["all"].append((A0 - ago, m, n))
    for (dim, val), sales in (profile or {}).items():
        for m, n in sales.items():
            T["profile"][(dim, val)].append((A0 - ago, m, n))
    return T


def card(market, status, missing=(), reasons=("x",)):
    return {"carrier": PROGRAM[market], "status": status, "missing_info": list(missing), "reasons": list(reasons)}


PD = {"zip": "77494", "county": "Fort Bend", "year_built": 2015, "dwelling_amount": 450000}
ALL_ELIGIBLE = [card(m, "ELIGIBLE") for m in PROGRAM]


def build(results, T, pd=PD):
    return placement.panel(results, pd, as_of=AS_OF, T=T)


def test_off_by_default_and_nothing_runs_when_off():
    src = open(os.path.join(ROOT, "app.py"), encoding="utf-8").read()
    call = src.index("placement.panel(")
    guard = src.rindex("if placement.enabled():", 0, call)
    assert src[guard:call].count("\n") <= 3                                  # the only call, right under the guard
    assert src.count("placement.panel(") == 1 and src.count("placement.panel_markdown(") == 1
    # the check itself never reads the placement module or its switch
    ec_src = open(os.path.join(ROOT, "eligibility_check.py"), encoding="utf-8").read()
    assert not re.search(r"\bimport placement\b|\bplacement\.|ELIGIBILITY_PLACEMENT", ec_src)


@pytest.mark.parametrize("results", [
    [card("Allied Trust", "ELIGIBLE")],
    [card("Allied Trust", "ELIGIBLE"), card("Mercury", "INELIGIBLE"), card("TWICO", "REFER")]])
def test_fewer_than_two_candidates_shows_no_panel(results):
    assert build(results, tables(zip_sales={"Allied Trust": 20})) is None


def test_ruled_out_markets_never_appear_in_the_three():
    T = tables(zip_sales={"Mercury": 50, "TWICO": 40, "Allied Trust": 2, "Travelers": 1, "Orion180": 1})
    res = [card("Mercury", "INELIGIBLE"), card("TWICO", "REFER"), card("Allied Trust", "ELIGIBLE"),
           card("Travelers", "ELIGIBLE"), card("Orion180", "INSUFFICIENT_INFORMATION", ["Roof age"])]
    p = build(res, T)
    assert {x["market"] for x in p["picks"]} == {"Allied Trust", "Travelers", "Orion180"}


@pytest.mark.parametrize("missing,want", [(["Roof age", "Hydrant distance"], "Held: confirm Roof age"),
                                          ([], "Held: confirm the open items on its card")])
def test_a_held_pick_says_held(missing, want):
    T = tables(zip_sales={"Orion180": 30, "Allied Trust": 5})
    p = build([card("Orion180", "INSUFFICIENT_INFORMATION", missing), card("Allied Trust", "ELIGIBLE")], T)
    first = p["picks"][0]
    assert first["market"] == "Orion180" and first["held"] == want
    assert p["picks"][1]["held"] is None                                     # an Eligible pick is not held


def test_a_market_with_an_eligible_program_is_not_held():
    res = [{"carrier": "Allied_Trust_HO3", "status": "INSUFFICIENT_INFORMATION", "missing_info": ["Roof age"]},
           {"carrier": "Allied_Trust_HO3_second", "status": "ELIGIBLE"}, card("Mercury", "ELIGIBLE")]
    p = build(res, tables(zip_sales={"Allied Trust": 30, "Mercury": 2}))
    assert p["picks"][0]["held"] is None and p["picks"][0]["programs"][0] == "Allied_Trust_HO3_second"


def test_the_reason_line_uses_the_zip_with_ten_sales():
    T = tables(zip_sales={"Allied Trust": 3, "Mercury": 7})
    p = build(ALL_ELIGIBLE, T)
    assert "Our homeowners sales in ZIP 77494: 3 of 10 with Allied Trust (30%)" in [x["reason"] for x in p["picks"]]


def test_a_thin_zip_falls_back_to_the_county():
    T = tables(zip_sales={"Allied Trust": 3, "Mercury": 6}, county_sales={"Allied Trust": 12, "Mercury": 8})
    reasons = [x["reason"] for x in build(ALL_ELIGIBLE, T)["picks"]]
    assert "Our homeowners sales in Fort Bend County: 12 of 20 with Allied Trust (60%)" in reasons


def test_a_thin_county_says_statewide():
    T = tables(zip_sales={"Allied Trust": 3}, county_sales={"Allied Trust": 9}, other={"Mercury": 40})
    p = build(ALL_ELIGIBLE, T)
    assert all(x["reason"] == placement.STATEWIDE for x in p["picks"]) and p["usual"] is None


def test_only_the_last_twelve_months_count_in_the_reason_line():
    T = tables(zip_sales={"Allied Trust": 3, "Mercury": 7})
    T["zip"]["77494"].append((A0 - 13, "Mercury", 50))                        # 13 months ago: not counted
    T["zip"]["77494"].append((A0, "Mercury", 50))                             # this month: not counted
    assert "3 of 10 with Allied Trust" in " ".join(x["reason"] for x in build(ALL_ELIGIBLE, T)["picks"])


def test_usually_here_line_when_the_top_market_is_ruled_out():
    T = tables(zip_sales={"Mercury": 30, "Allied Trust": 5, "TWICO": 3})
    res = [card("Mercury", "INELIGIBLE", reasons=["[MER-029] declines:   Plumbing must be copper,\nPVC or PEX."]),
           card("Allied Trust", "ELIGIBLE"), card("TWICO", "ELIGIBLE")]
    p = build(res, T)
    assert p["usual"] == ("Usually Mercury here (30 of 38); not for this home: "
                          "[MER-029] declines: Plumbing must be copper, PVC or PEX.")


def test_no_usually_line_when_the_top_market_is_a_candidate():
    p = build(ALL_ELIGIBLE, tables(zip_sales={"Mercury": 30, "Allied Trust": 5}))
    assert p["usual"] is None


@pytest.mark.parametrize("band_sales,band_n,want", [
    ({"Allied Trust": 3, "Mercury": 7}, 10, "30% of our 10-19-year-old homes vs 20% overall"),   # 1.5x, 10 in band
    ({"Allied Trust": 3, "Mercury": 6}, 9, None),                                                # 9 in band
    ({"Allied Trust": 2, "Mercury": 6, "TWICO": 2}, 10, None)])                                 # 20% vs 20%: 1.0x
def test_the_fit_line(band_sales, band_n, want):
    assert sum(band_sales.values()) == band_n
    T = tables(zip_sales={"Allied Trust": 4, "Mercury": 16}, profile={("age_band", "10-19"): band_sales})
    p = build(ALL_ELIGIBLE, T, dict(PD, dwelling_amount=None))
    allied = next(x for x in p["picks"] if x["market"] == "Allied Trust")
    assert allied["fit"] == want


def test_the_coverage_a_fit_line_names_the_band():
    T = tables(zip_sales={"Allied Trust": 4, "Mercury": 16},
               profile={("covA_band", "600-999K"): {"Allied Trust": 5, "Mercury": 5}})
    p = build(ALL_ELIGIBLE, T, dict(PD, year_built=None, dwelling_amount=650000))
    allied = next(x for x in p["picks"] if x["market"] == "Allied Trust")
    assert allied["fit"] == "50% of our $600-999K Coverage A homes vs 20% overall"


def test_the_words_and_the_footer():
    T = tables(zip_sales={"Mercury": 30, "Allied Trust": 5, "TWICO": 3})
    res = [card("Mercury", "INELIGIBLE"), card("Allied Trust", "ELIGIBLE"),
           card("TWICO", "INSUFFICIENT_INFORMATION", ["Roof age"])]
    p = build(res, T)
    text = placement.panel_markdown(p) + "\n" + p["footer"]
    assert text.startswith("#### Where we usually place homes like this")
    assert not re.search(r"\bbest\b|recommend", text, re.I)
    assert p["footer"] == ("From our HawkSoft placements through 2026-10. Where we have placed similar homes, "
                           "not a price comparison.")


def test_the_panel_never_changes_a_card():
    import copy
    res = [card("Mercury", "INELIGIBLE"), card("Allied Trust", "ELIGIBLE"), card("TWICO", "ELIGIBLE")]
    before = copy.deepcopy(res)
    build(res, tables(zip_sales={"Mercury": 30, "Allied Trust": 5, "TWICO": 3}))
    assert res == before


def test_the_status_line(monkeypatch):
    T = tables()
    monkeypatch.delenv("ELIGIBILITY_PLACEMENT", raising=False)
    assert placement.status_line(T) == "Placement panel: OFF (data through 2026-10, 123 policies)"
    monkeypatch.setenv("ELIGIBILITY_PLACEMENT", "1")
    assert placement.status_line(T).startswith("Placement panel: ON")


def test_the_real_tables_build_a_panel():
    res = [{"carrier": p, "status": "ELIGIBLE"} for p in ("Allied_Trust_HO3", "TWICO_HO3", "Travelers_HO3_-_06.12.2026")]
    p = placement.panel(res, {"zip": "77494", "county": "Fort Bend", "year_built": 2015, "dwelling_amount": 450000},
                        as_of="2026-10")
    assert len(p["picks"]) == 3 and p["footer"].startswith("From our HawkSoft placements through 2026-10.")
