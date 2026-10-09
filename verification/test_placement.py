"""Round 33 step 1 (Liam, 2026-10-09): the placement scorer. Zero API.

Synthetic tables with hand-computed values, then the app's placement.rank against Claude's reference
scorer (verification/placement_score_reference.py, a verbatim copy) on the tracked tables."""
import csv
import math
import os
import random
import sys
from collections import defaultdict

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))
import intake_fields  # noqa: E402
import placement  # noqa: E402
import placement_score_reference as ref  # noqa: E402

pytestmark = pytest.mark.retrieval
AS_OF = "2026-10"
A0 = placement.month_index(AS_OF)
W1 = 0.5 ** (1 / 4)          # weight of a sale 1 month before as_of = 0.8409
W4 = 0.5                     # 4 months before (one half-life)


def tables(all_=(), zip_=None, county=None, profile=None):
    """T from (months_ago, market, n) tuples."""
    def idx(entries):
        return [(A0 - ago, m, n) for ago, m, n in entries]
    T = {"zip": defaultdict(list), "county": defaultdict(list), "profile": defaultdict(list), "all": idx(all_)}
    for k, v in (zip_ or {}).items():
        T["zip"][k] = idx(v)
    for k, v in (county or {}).items():
        T["county"][k] = idx(v)
    for k, v in (profile or {}).items():
        T["profile"][k] = idx(v)
    return T


def order(T, cands=("A", "B"), zip5="", county="", yb=None, cova=None):
    return [m for m, _ in placement.rank(T, cands, zip5, county, yb, cova, AS_OF)]


# -- hand-computed ------------------------------------------------------------------------------------
def test_recent_sales_count_more():
    # A sold 1 month ago, B 5 months ago: g = (w + .5) / (W + 1), so A ahead
    T = tables(all_=[(1, "A", 1), (5, "B", 1)])
    got = dict(placement.rank(T, ["A", "B"], "", "", None, None, AS_OF))
    tot = W1 + 0.5 ** (5 / 4)
    assert got["A"] == pytest.approx(math.log((W1 + 0.5) / (tot + 1)))
    assert got["B"] == pytest.approx(math.log((0.5 ** (5 / 4) + 0.5) / (tot + 1)))
    assert order(T) == ["A", "B"]


def test_only_whole_months_before_as_of_within_36_count():
    T = tables(all_=[(0, "B", 50), (37, "B", 50), (36, "A", 1)])
    assert order(T) == ["A", "B"]          # B's sales this month and 37 months ago do not count


def _zip_vs_county(zip_b):
    # the county says A (30 sales), the ZIP says B (zip_b sales); all 1 month ago
    return tables(all_=[(1, "A", 30), (1, "B", zip_b)], zip_={"77494": [(1, "B", zip_b)]},
                  county={"Fort Bend": [(1, "A", 30)]})


def test_a_thin_zip_is_shrunk_toward_its_county():
    T = _zip_vs_county(3)
    got = dict(placement.rank(T, ["A", "B"], "77494", "Fort Bend", None, None, AS_OF))
    tot = 33 * W1
    g = {"A": (30 * W1 + .5) / (tot + 1), "B": (3 * W1 + .5) / (tot + 1)}
    cty = {m: ((30 * W1 if m == "A" else 0) + 30 * g[m]) / (30 * W1 + 30) for m in g}
    z = {m: ((3 * W1 if m == "B" else 0) + 15 * cty[m]) / (3 * W1 + 15) for m in g}
    assert got == pytest.approx({m: math.log(z[m]) for m in g})
    assert order(T, zip5="77494", county="Fort Bend") == ["A", "B"]


def test_a_busy_zip_outweighs_its_county():
    assert order(_zip_vs_county(30), zip5="77494", county="Fort Bend") == ["B", "A"]


def test_an_unknown_zip_falls_back_to_the_county():
    # overall A 200 / B 60 (g_A .768, g_B .232); Harris B 60: cty_B = (60w + 30 g_B) / (60w + 30) = .714
    T = tables(all_=[(1, "A", 200), (1, "B", 60)], county={"Harris": [(1, "B", 60)]}, zip_={"77002": [(1, "A", 5)]})
    assert order(T, zip5="99999", county="Harris") == ["B", "A"]           # no rows for the ZIP: county decides
    assert order(T, zip5="99999", county="harris ") == ["B", "A"]          # the reference's strip().title()
    assert order(T, zip5="", county="") == ["A", "B"]                      # neither: the overall mix


def test_a_missing_band_is_skipped():
    prof = {("age_band", "10-19"): [(1, "B", 100)], ("covA_band", "<200K"): [(1, "B", 100)]}
    T = tables(all_=[(1, "A", 20), (1, "B", 10)], profile=prof)
    base = placement.rank(T, ["A", "B"], "", "", None, None, AS_OF)
    assert placement.rank(T, ["A", "B"], "", "", None, 19999, AS_OF) == base   # Coverage A under 20,000: no band
    assert order(T, yb=2012) == ["B", "A"]                                     # age 14 -> 10-19 applies


@pytest.mark.parametrize("n_b,applied", [(38, False), (40, True)])
def test_a_band_counts_only_with_min_dim_weighted_sales(n_b, applied):
    # 4 months ago weighs exactly 0.5: 38 sales -> 19 (< MIN_DIM 20, skipped), 40 -> 20 (applied)
    T = tables(all_=[(1, "A", 20), (1, "B", 10)], profile={("age_band", "10-19"): [(4, "B", n_b)]})
    assert (order(T, yb=2012) == ["B", "A"]) is applied


def test_ties_go_to_the_market_name():
    T = tables(all_=[(1, "Zeta", 5), (1, "Alpha", 5)])
    assert order(T, cands=("Zeta", "Alpha")) == ["Alpha", "Zeta"]


def test_bands():
    assert [placement.band(a, placement.AGE) for a in (0, 9, 10, 59, 60)] == ["0-9", "0-9", "10-19", "40-59", "60+"]
    assert [placement.band(c, placement.COVA) for c in (199999, 200000, 650000, 1000000)] == \
           ["<200K", "200-299K", "600-999K", "1M+"]


# -- candidates: what the check did not rule out -------------------------------------------------------
@pytest.mark.parametrize("statuses,cand", [
    (["ELIGIBLE"], True), (["INSUFFICIENT_INFORMATION"], True), (["INELIGIBLE", "INSUFFICIENT_INFORMATION"], True),
    (["INELIGIBLE"], False), (["REFER"], False), (["GUIDE_UNAVAILABLE", "NOT_EVALUATED"], False),
    (["INELIGIBLE", "REFER"], False)])
def test_a_market_is_a_candidate_when_any_program_is_eligible_or_held(statuses, cand):
    progs = ["Swyfft_-_Benchmark_(Admitted)_HO3", "Swyfft_-_Benchmark_(Surplus)_HO3"]
    results = [{"carrier": p, "status": s} for p, s in zip(progs, statuses)]
    assert ("Swyfft Benchmark" in placement.candidates(results)) is cand


def test_market_of():
    assert placement.market_of("Sage_-_SURE_HO-3_-_01.31.2026") == "SageSure SURE"
    assert placement.market_of("Sage_-_SafePort_DP-3_-_01.31.2026") == "SageSure SafePort"
    assert placement.market_of("NatGen_Premier_OneChoice_HO3_-_02.26.2025") == "National General"
    assert placement.market_of("Parse Error") is None


def test_current_month():
    import datetime
    assert placement.current_month(datetime.date(2026, 4, 30)) == "2026-04"


def test_off_unless_exactly_1(monkeypatch):
    for v, on in (("1", True), ("", False), ("true", False), ("0", False), (" 1", False)):
        monkeypatch.setenv("ELIGIBILITY_PLACEMENT", v)
        assert placement.enabled() is on


# -- the tracked tables ---------------------------------------------------------------------------------
def test_every_county_key_in_the_tracked_table_is_a_texas_county():
    # round 33 step 1: HawkSoft's county field held street-name and lender fragments; never track them
    texas = {c.title() for c in intake_fields.TEXAS_COUNTIES}
    with open(os.path.join(placement.DATA_DIR, "placement_county.csv"), encoding="utf-8") as fh:
        bad = {r["county"] for r in csv.DictReader(fh) if r["county"].strip().title() not in texas}
    assert not bad, sorted(bad)


def test_every_program_in_the_store_maps_to_a_market():
    import eligibility_check as ec
    unmapped = [p for p in ec._all_programs() if placement.market_of(p) is None]
    assert not unmapped, unmapped


def test_the_app_ranks_exactly_as_the_reference_on_the_tracked_tables():
    T, R = placement.load_tables(), ref.load_tables(placement.DATA_DIR)
    markets = sorted({m for _, m in T["markets"]})
    zips = sorted(T["zip"])
    counties = sorted(T["county"])
    rnd = random.Random(20261009)
    for _ in range(400):
        cands = rnd.sample(markets, rnd.randint(1, len(markets)))
        z = rnd.choice(zips + ["", "00000"])
        c = rnd.choice(counties + ["", "Loving"])
        yb = rnd.choice([None, rnd.randint(1900, 2026)])
        cova = rnd.choice([None, 0, 15000, rnd.randint(50000, 2500000)])
        as_of = f"{rnd.randint(2024, 2026)}-{rnd.randint(1, 12):02d}"
        mine = placement.rank(T, cands, z, c, yb, cova, as_of)
        theirs = ref.rank(R, cands, z, c, yb, cova, as_of)
        assert [m for m, _ in mine] == [m for m, _ in theirs]
        assert [s for _, s in mine] == pytest.approx([s for _, s in theirs], abs=1e-12)
