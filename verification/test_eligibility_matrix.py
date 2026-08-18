"""
Regression suite for the carrier eligibility tool.

WHY THIS FILE EXISTS
--------------------
Eleven rounds of manual audits (external agents re-reading real carrier
PDFs) found the same categories of bug more than once: a fix that only
covers the exact wording in the bug report, a fix that "usually" works, and
a bucket/verdict label mismatch that reproduced identically on three
separate customer profiles across three rounds before it got fixed. This
suite exists so those are caught by `pytest`, in seconds, instead of by
another full manual audit. See CLAUDE.md for the policy this file exists
to satisfy.

TWO TIERS
---------
1. Retrieval-layer tests (`@pytest.mark.retrieval`): fast, deterministic,
   no LLM call. They check that the right source passage is actually
   retrievable for a given carrier + topic + phrasing -- this is the layer
   that catches "the fix only works for the exact wording in the bug
   report" before it ships.
2. Baseline profile tests (`@pytest.mark.baseline`): slower, call the real
   `check_eligibility()` pipeline end to end (real Claude API cost) against
   two fixed customer profiles with known-correct expected outcomes, each
   individually verified against the actual carrier PDFs -- not assumed
   from an audit summary. See profiles.py for the two profiles.

Run everything:      pytest verification/test_eligibility_matrix.py -v
Run only fast tests:  pytest verification/test_eligibility_matrix.py -v -m retrieval
Run only baseline:    pytest verification/test_eligibility_matrix.py -v -m baseline
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# NOTE: do not pre-set ANTHROPIC_API_KEY here, even to an empty/default
# value -- eligibility_check.py calls load_dotenv() on import, and
# python-dotenv does not override an already-set environment variable, so
# setting it (even to "") here first silently blocks the real key in .env
# from ever loading.

from datetime import date
from langchain_core.documents import Document

from eligibility_check import (
    assign_buckets,
    build_retrieval_query,
    check_eligibility,
    guaranteed_carrier_lookup,
    is_eligibility_content,
    normalize_chunk_text,
    _mentions_solar,
    _mentions_protection_class,
    _mentions_pool_rule,
    _mentions_roof_life_expectancy,
    _is_ppc_disambiguation_table,
)
from shared_resources import get_vectorstore
from profiles import STANDARD_PROFILE, ALT_PROFILE
from structured_rules import (
    sage_family_fpc_eligibility,
    mercury_roof_eligibility,
    swyfft_lloyds_roof_settlement,
    sage_markel_roof_exclusion,
    swyfft_max_roof_age_30,
    twico_roof_settlement,
)


# ---------------------------------------------------------------------------
# Shared retrieval helpers (thin wrappers around the real pipeline internals
# -- NOT a reimplementation, so these can't drift from production behavior)
# ---------------------------------------------------------------------------

def _all_chunks(carrier):
    vs = get_vectorstore()
    raw = vs._collection.get(where={"carrier": carrier}, include=["documents", "metadatas"])
    return [Document(page_content=d, metadata=m) for d, m in zip(raw["documents"], raw["metadatas"])]


def _kept_main_query_chunks(carrier, profile, k=15, keep=3):
    home_age = date.today().year - profile["year_built"]
    query = build_retrieval_query(profile, home_age)
    vs = get_vectorstore()
    results = vs.similarity_search(query, k=k, filter={"carrier": carrier})
    return [c for c in results if is_eligibility_content(c)][:keep]


def _guaranteed_lookup_chunks(carrier, predicate, keep=3, priority_key=None):
    """Calls the REAL production guarantee-lookup function directly (not a
    reimplementation) so this test can never silently drift from what
    check_eligibility() actually does -- a duplicated copy here previously
    passed while production (with a different priority sort) still dropped
    the chunk that mattered."""
    vs = get_vectorstore()
    return guaranteed_carrier_lookup(
        vs._collection, carrier, predicate=predicate, keep=keep, priority_key=priority_key,
    )


# ---------------------------------------------------------------------------
# TIER 0 -- pure logic, no retrieval, no LLM. Fastest possible tests.
# ---------------------------------------------------------------------------

@pytest.mark.retrieval
class TestSageFamilyStructuredFPC:
    """The Sage family's FPC/distance/hydrant table, extracted from the six
    related documents' actual text into structured_rules.py, evaluated with
    plain code instead of LLM reasoning. Boundary values specifically --
    exactly-at-the-cutoff FPC and distance/hydrant values -- the same kind
    of case that caught Mercury's exclusive '10 years old' roof boundary.
    Deterministic by construction: there is no LLM call in this path at
    all, so these are hard assertions, not flakiness-guard pass-rate
    checks."""

    def test_fpc_1_with_no_distance_data_is_eligible_full_stop(self):
        # The actual Round 11 ground truth: ALT_PROFILE's ppc="1" never
        # touches the FPC>=9 ineligible row under any distance/hydrant
        # combination in the table -- eligible regardless of missing
        # distance data, not insufficient-information.
        status, _ = sage_family_fpc_eligibility("1")
        assert status == "ELIGIBLE"

    def test_fpc_9_with_no_distance_data_is_insufficient_information(self):
        # Unlike FPC 1-8, FPC 9+'s outcome genuinely depends on the missing
        # distance value (eligible at <=5mi, ineligible at >5mi) -- this is
        # a real information gap, not a case to guess through.
        status, _ = sage_family_fpc_eligibility("9")
        assert status == "INSUFFICIENT_INFORMATION"

    def test_fpc_boundary_3_vs_4_beyond_5_miles(self):
        # Row 3 (FPC 1-3) has 3 conditions; row 5 (FPC 4-8) adds 4 more.
        # Both resolve ELIGIBLE, so the boundary must be checked via the
        # attached conditions, not just the status.
        status_3, reasons_3 = sage_family_fpc_eligibility("3", distance_miles=6)
        status_4, reasons_4 = sage_family_fpc_eligibility("4", distance_miles=6)
        assert status_3 == "ELIGIBLE" and status_4 == "ELIGIBLE"
        assert "no rental exposure" not in " ".join(reasons_3).lower()
        assert "no rental exposure" in " ".join(reasons_4).lower(), (
            "FPC 4 beyond 5mi must carry the four extra conditions (home age, "
            "occupancy, rental, prior losses) that FPC 1-3 does not."
        )

    def test_fpc_boundary_8_vs_9_beyond_5_miles(self):
        status_8, _ = sage_family_fpc_eligibility("8", distance_miles=6)
        status_9, _ = sage_family_fpc_eligibility("9", distance_miles=6)
        assert status_8 == "ELIGIBLE"
        assert status_9 == "INELIGIBLE"

    def test_distance_boundary_exactly_5_miles_is_the_close_side(self):
        # Source text: "5 miles or less" -- inclusive of exactly 5.
        status_at_5, _ = sage_family_fpc_eligibility("9", distance_miles=5, hydrant_feet=2000)
        status_over_5, _ = sage_family_fpc_eligibility("9", distance_miles=5.01, hydrant_feet=2000)
        assert status_at_5 == "ELIGIBLE", "exactly 5mi must use the <=5mi row, not the >5mi row"
        assert status_over_5 == "INELIGIBLE"

    def test_hydrant_boundary_exactly_1000_feet_is_the_close_side(self):
        # Source text: "hydrant is within 1,000 feet" -- inclusive of
        # exactly 1,000; "greater than 1,000 feet" starts the conditional row.
        status_at_1000, reasons_at_1000 = sage_family_fpc_eligibility("5", distance_miles=3, hydrant_feet=1000)
        status_over_1000, reasons_over_1000 = sage_family_fpc_eligibility("5", distance_miles=3, hydrant_feet=1001)
        assert status_at_1000 == "ELIGIBLE" and not reasons_at_1000, (
            "hydrant exactly at 1,000ft must be unconditional (row 1), not row 2/4's conditional eligibility"
        )
        assert status_over_1000 == "ELIGIBLE" and reasons_over_1000

    def test_deterministic_across_repeated_calls(self):
        results = [sage_family_fpc_eligibility("1") for _ in range(20)]
        assert all(r == results[0] for r in results)

    def test_occidental_variant_lacks_no_rental_condition_others_have(self):
        # Confirmed directly against Occidental's own source text -- a real
        # per-carrier difference, not a dropped bullet to "fix" back to
        # matching its siblings.
        _, occidental_reasons = sage_family_fpc_eligibility("4", distance_miles=6, carrier="Sage_-_Occidental_HO3")
        _, auros_reasons = sage_family_fpc_eligibility("4", distance_miles=6, carrier="Sage_-_Auros_HO3")
        assert "no rental exposure" not in " ".join(occidental_reasons).lower()
        assert "no prior fire losses" in " ".join(occidental_reasons).lower(), (
            "Occidental is only missing the rental-exposure condition -- it must still "
            "carry the other three (visibility, alarm, access) plus age/occupancy/prior-losses."
        )
        assert "no rental exposure" in " ".join(auros_reasons).lower(), (
            "Auros (and every sibling except Occidental) must keep all four extra conditions."
        )


@pytest.mark.retrieval
class TestStructuredRoofAgeTables:
    """Roof-age structured extraction, scoped to the 6 (of 7 candidate)
    carriers whose tables extracted cleanly enough to code against --
    TWICO's table is explicitly NOT covered (see structured_rules.py) since
    its roof-material column came back blank in extraction; fabricating a
    mapping would be worse than leaving it as a known gap. Boundary values
    only, same rationale as the Sage FPC tests: this is where a fix that
    only covers one carrier's exact reported case would still miss the
    exactly-at-the-cutoff row."""

    def test_mercury_roof_exactly_10_years_gets_rcv_not_endorsement(self):
        status, _ = mercury_roof_eligibility("Composition Shingle", 10)
        assert status == "ELIGIBLE"

    def test_mercury_roof_11_years_requires_endorsement(self):
        status, _ = mercury_roof_eligibility("Composition Shingle", 11)
        assert status == "ELIGIBLE_REQUIRES_ENDORSEMENT"

    def test_mercury_slate_tile_metal_gets_20yr_threshold_not_10yr(self):
        status_20, _ = mercury_roof_eligibility("Slate", 20)
        status_21, _ = mercury_roof_eligibility("Slate", 21)
        assert status_20 == "ELIGIBLE"
        assert status_21 == "ELIGIBLE_REQUIRES_ENDORSEMENT"

    def test_mercury_asbestos_shingle_ineligible_at_any_age(self):
        status, _ = mercury_roof_eligibility("Asbestos Shingle", 1)
        assert status == "INELIGIBLE"

    def test_swyfft_lloyds_asphalt_shingle_boundaries(self):
        rcv, _ = swyfft_lloyds_roof_settlement("Asphalt Shingles", 14)
        acv_low, _ = swyfft_lloyds_roof_settlement("Asphalt Shingles", 15)
        acv_high, _ = swyfft_lloyds_roof_settlement("Asphalt Shingles", 25)
        excluded, _ = swyfft_lloyds_roof_settlement("Asphalt Shingles", 26)
        assert rcv == "RCV"
        assert acv_low == "ACV" and acv_high == "ACV"
        assert excluded == "EXCLUDED"

    def test_swyfft_lloyds_standing_seam_metal_uses_35_40_band_not_15_25(self):
        # Different material families get different age bands in the same
        # table -- a fix generalized from the asphalt-shingle band alone
        # would wrongly exclude a 30-year-old standing seam metal roof.
        status, _ = swyfft_lloyds_roof_settlement("Standing seam metal roofs", 30)
        assert status == "RCV"

    def test_swyfft_lloyds_unknown_roof_type_is_insufficient_information(self):
        status, _ = swyfft_lloyds_roof_settlement("Solar Tile", 10)
        assert status == "INSUFFICIENT_INFORMATION"

    def test_sage_markel_roof_exclusion_25yr_boundary(self):
        covered, _ = sage_markel_roof_exclusion("Composition Shingle", 25)
        excluded, _ = sage_markel_roof_exclusion("Composition Shingle", 26)
        assert covered == "ROOF_COVERED"
        assert excluded == "ROOF_EXCLUDED"

    def test_sage_markel_slate_tile_metal_uses_40yr_boundary(self):
        covered, _ = sage_markel_roof_exclusion("Metal", 40)
        excluded, _ = sage_markel_roof_exclusion("Metal", 41)
        assert covered == "ROOF_COVERED"
        assert excluded == "ROOF_EXCLUDED"

    def test_swyfft_max_roof_age_30_boundary(self):
        at_30, _ = swyfft_max_roof_age_30(30)
        over_30, _ = swyfft_max_roof_age_30(31)
        assert at_30 == "ELIGIBLE"
        assert over_30 == "INELIGIBLE"


@pytest.mark.retrieval
class TestTwicoStructuredRoof:
    """TWICO's roof settlement table -- NOT wired into check_eligibility()
    yet (see structured_rules.py): its RCV/ACV/Exclusion bands depend on
    distinguishing 3-tab from architectural composition shingle, and the
    current intake form's single "Composition Shingle" value can't make
    that distinction. These tests cover the function standalone so its
    logic (including the deliberate ambiguity handling) is locked in before
    it's ever wired to a real check_eligibility() call."""

    def test_3tab_boundary_10_vs_11(self):
        rcv, _ = twico_roof_settlement("Composition (3-tab)", 10)
        acv, _ = twico_roof_settlement("Composition (3-tab)", 11)
        assert rcv == "RCV"
        assert acv == "ACV"

    def test_architectural_boundary_uses_different_band_than_3tab(self):
        # Same nominal material family, different band -- exactly the kind
        # of generalization gap that caught Allied Trust's roof-terminology
        # issue; this locks in that 3-tab and architectural stay distinct.
        status_14yr_3tab, _ = twico_roof_settlement("Composition (3-tab)", 14)
        status_14yr_arch, _ = twico_roof_settlement("Composition (Architectural)", 14)
        assert status_14yr_3tab == "ACV"
        assert status_14yr_arch == "RCV"

    def test_generic_composition_shingle_with_no_subtype_is_insufficient_information(self):
        # The core of item 2: guessing 3-tab vs architectural would be
        # confidently wrong the same way every time. Must not guess.
        status, reasons = twico_roof_settlement("Composition Shingle", 14)
        assert status == "INSUFFICIENT_INFORMATION"
        assert "subtype" in " ".join(reasons).lower()

    def test_standing_seam_metal_not_confused_with_ineligible_metal_shingle(self):
        # Standing-seam metal is banded (0-20 RCV/21-35 ACV/36+ Excluded);
        # plain "Metal Shingle" is unconditionally ineligible. Age 15 is
        # RCV under the standing-seam band -- if the "metal"+"shingle"
        # ineligibility check ever became too loose, this would wrongly
        # come back INELIGIBLE instead.
        status, _ = twico_roof_settlement("Metal (Standing-Seam)", 15)
        assert status == "RCV"

    def test_metal_shingle_is_ineligible_not_banded(self):
        status, _ = twico_roof_settlement("Metal Shingle", 1)
        assert status == "INELIGIBLE"

    def test_tile_concrete_clay_boundary_25_vs_26(self):
        rcv, _ = twico_roof_settlement("Tile (Concrete/Clay)", 25)
        acv, _ = twico_roof_settlement("Tile (Concrete/Clay)", 26)
        assert rcv == "RCV"
        assert acv == "ACV"

    def test_wood_slate_asbestos_corrugated_ineligible_at_any_age(self):
        for roof_type in ["Wood Shingle", "Slate", "Asbestos", "Corrugated Metal"]:
            status, _ = twico_roof_settlement(roof_type, 1)
            assert status == "INELIGIBLE", f"{roof_type} should be ineligible regardless of age"


@pytest.mark.retrieval
class TestChunkTextNormalization:
    """ARI (HOA+) and ARI (HOB)'s pool-fence citation, verbatim, hit a real
    ~20% (4/20 in a sampled run) JSON parse failure rate in production --
    traced to the model reproducing this exact citation's raw embedded
    mid-sentence newline inside its own generated JSON string without
    escaping it. Feeds the EXACT problematic string through
    normalize_chunk_text() and confirms both the fix and, via a simulated
    naive JSON embed, that the failure mode this addresses is real."""

    # Exact text pulled from the actual chunk (ARI (HOA+), page 0) --
    # not a simplified stand-in.
    ARI_POOL_FENCE_CITATION = (
        "Homes with swimming pools, spas or hot tubs that are not properly secured. Pools secured by a\n"
        "6’ high fence with locked or self locking gates are acceptable."
    )

    def test_normalizes_removes_raw_linewrap_newline(self):
        normalized = normalize_chunk_text(self.ARI_POOL_FENCE_CITATION)
        assert "\n" not in normalized

    def test_normalizes_curly_apostrophe_to_ascii(self):
        normalized = normalize_chunk_text(self.ARI_POOL_FENCE_CITATION)
        assert "’" not in normalized
        assert "6' high fence" in normalized

    def test_preserves_real_paragraph_breaks(self):
        text = "First paragraph.\n\nSecond paragraph."
        normalized = normalize_chunk_text(text)
        assert normalized == text

    def test_original_text_would_break_naive_json_embedding(self):
        # Simulates the model copying the citation verbatim into a JSON
        # string without escaping the embedded newline -- this is the
        # actual mechanism behind the observed "Expecting ','
        # delimiter" / "Invalid control character" parse errors.
        naive_json = '{"citation": "' + self.ARI_POOL_FENCE_CITATION + '"}'
        with pytest.raises(json.JSONDecodeError):
            json.loads(naive_json)

    def test_normalized_text_survives_the_same_naive_json_embedding(self):
        normalized = normalize_chunk_text(self.ARI_POOL_FENCE_CITATION)
        naive_json = '{"citation": "' + normalized + '"}'
        parsed = json.loads(naive_json)  # must not raise
        assert parsed["citation"] == normalized


@pytest.mark.retrieval
class TestBucketAssignment:
    """The bucket/verdict labeling bug: reproduced identically across three
    audit rounds and three different customer profiles (5-for-5 "One Issue"
    == INELIGIBLE, 9-for-9 "Not Eligible" == INSUFFICIENT_INFORMATION).
    Fixed by mapping each of the four buckets to exactly one status --
    these tests encode the exact failure shape directly, with no LLM call
    needed since assign_buckets() is pure Python."""

    def _make(self, status, flaw_count=0, carrier="X"):
        return {"carrier": carrier, "status": status, "flaw_count": flaw_count}

    def test_ineligible_single_flaw_goes_to_one_issue_not_not_eligible(self):
        results = [self._make("INELIGIBLE", flaw_count=1)]
        buckets = assign_buckets(results)
        assert buckets["one_issue"] == results
        assert buckets["not_eligible"] == []

    def test_insufficient_information_goes_to_its_own_bucket_not_not_eligible(self):
        results = [self._make("INSUFFICIENT_INFORMATION")]
        buckets = assign_buckets(results)
        assert buckets["insufficient_info"] == results
        assert buckets["not_eligible"] == []
        assert buckets["one_issue"] == []

    def test_ineligible_multi_flaw_goes_to_not_eligible(self):
        results = [self._make("INELIGIBLE", flaw_count=3)]
        buckets = assign_buckets(results)
        assert buckets["not_eligible"] == results
        assert buckets["one_issue"] == []

    def test_refer_goes_to_one_issue(self):
        results = [self._make("REFER")]
        buckets = assign_buckets(results)
        assert buckets["one_issue"] == results

    def test_reproduces_the_exact_audit_finding_shape(self):
        """5 carriers tagged INELIGIBLE with flaw_count=1, 9 carriers tagged
        INSUFFICIENT_INFORMATION -- the exact 5-for-5 / 9-for-9 split found
        identically in rounds 9, 10, and 11. Before the fix, all 5 landed in
        "one_issue" (correctly) but all 9 landed in "not_eligible" -- a
        bucket labeled "Not Eligible" containing zero actually-ineligible
        carriers. After the fix, they must be in separate, correctly-named
        buckets."""
        results = [self._make("INELIGIBLE", flaw_count=1, carrier=f"one-issue-{i}") for i in range(5)]
        results += [self._make("INSUFFICIENT_INFORMATION", carrier=f"insufficient-{i}") for i in range(9)]
        buckets = assign_buckets(results)
        assert len(buckets["one_issue"]) == 5
        assert all(r["status"] == "INELIGIBLE" for r in buckets["one_issue"])
        assert len(buckets["insufficient_info"]) == 9
        assert all(r["status"] == "INSUFFICIENT_INFORMATION" for r in buckets["insufficient_info"])
        # the actual bug: "not_eligible" must NOT silently absorb the 9
        # INSUFFICIENT_INFORMATION carriers just because they're not ELIGIBLE
        assert buckets["not_eligible"] == []


# ---------------------------------------------------------------------------
# TIER 1 -- retrieval-layer tests (fast, no LLM call, run on every commit)
# ---------------------------------------------------------------------------

@pytest.mark.retrieval
class TestSolarRetrieval:
    """Every carrier confirmed by audit to have real solar-panel language
    must actually be retrievable via the guaranteed solar lookup
    (_mentions_solar). Round 11 found Progressive HO3's solar exclusion
    reported as "verified fixed" but absent from that round's actual
    model output -- this test would NOT have caught that specific failure
    (it's a model-consistency issue, not a retrieval gap; see the
    TestProgressiveSolarConsistency flakiness check below for that), but it
    does confirm the retrieval step itself -- which the model output
    depends on -- is not the bottleneck."""

    @pytest.mark.parametrize("carrier,must_contain", [
        ("TWICO_HO3", "solar panels"),
        ("NatGen_Premier_OneChoice_HO3_-_02.26.2025", "solar panels"),
        ("Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3", "renewable energy"),
        ("Progressive_HO3_-_04.01.2026", "solar panels"),
        ("Progressive_HO6_-_10.01.2025", "solar panels"),
        ("HOAIC_-_TX-HOMEOWNERS-0326_HO3", "solar panel"),
    ])
    def test_solar_clause_retrievable(self, carrier, must_contain):
        candidates = _guaranteed_lookup_chunks(carrier, _mentions_solar, keep=2)
        assert candidates, f"{carrier}: no solar-mentioning chunk found at all via _mentions_solar."
        blob = " ".join(c.page_content for c in candidates).lower()
        assert must_contain.lower() in blob, (
            f"{carrier}'s known solar clause text ({must_contain!r}) was not found in the "
            f"{len(candidates)} guaranteed-lookup candidate(s)."
        )


@pytest.mark.retrieval
class TestRoofTerminologySynonyms:
    """'Composition Shingle' and 'Composite or Architectural Shingle' must
    resolve to the same underlying rule in Allied Trust's document. Round
    10 found a fix that worked only for the exact phrasing already in the
    bug report -- this parametrizes over FOUR different phrasings of the
    same roofing category, per CLAUDE.md's requirement that a
    generalization fix be tested with more than one phrasing."""

    @pytest.mark.parametrize("roof_type_phrasing", [
        "Composition Shingle",
        "Composite or Architectural Shingle",
        "Architectural Shingle",
        "3-tab shingle",
    ])
    def test_allied_trust_both_roof_clauses_retrievable(self, roof_type_phrasing):
        # What actually reaches the prompt in production is the UNION of the
        # main per-carrier query AND the guaranteed roof-life-expectancy
        # lookup (keyword-based, independent of roof_type phrasing) -- test
        # against that union, not the main query alone. The main-query-only
        # version of this test is what originally caught the "Architectural
        # Shingle" gap that motivated adding the guarantee.
        profile = dict(ALT_PROFILE, roof_type=roof_type_phrasing)
        kept = _kept_main_query_chunks("Allied_Trust_HO3", profile, k=15, keep=3)
        guaranteed = _guaranteed_lookup_chunks(
            "Allied_Trust_HO3", _mentions_roof_life_expectancy, keep=3,
            priority_key=lambda c: "shingle" not in c.page_content.lower(),
        )
        blob = " ".join(c.page_content for c in kept + guaranteed)
        assert "¾ of its life expectancy" in blob, (
            f"roof phrasing {roof_type_phrasing!r}: the '3/4 of its life expectancy' "
            f"clause was not retrieved."
        )
        assert "21 years old" in blob, (
            f"roof phrasing {roof_type_phrasing!r}: the '21 years old' total-life-expectancy "
            f"clause was not retrieved. If this passes for 'Composite or Architectural Shingle' "
            f"but fails for 'Composition Shingle', the terminology fix did not generalize."
        )


@pytest.mark.retrieval
class TestSageFamilyFPCRetrieval:
    """Round 11: an FPC-1 risk is eligible under every row of the Sage
    family's FPC/distance/hydrant table -- the "ineligible" row is reserved
    exclusively for FPC 9+. The model can only draw the correct
    eligible-with-conditions conclusion if BOTH the low-FPC eligible rows
    AND the high-FPC ineligible row are actually retrieved, not just
    whichever one embeds closest to the query."""

    @pytest.mark.parametrize("carrier", [
        "Sage_-_Auros_HO3",
        "Sage_-_Occidental_HO3",
        "Sage_-_Wilshire_HO3_-_12.02.2025",
    ])
    def test_both_low_and_high_fpc_rows_retrievable(self, carrier):
        candidates = [
            c for c in _all_chunks(carrier)
            if _mentions_protection_class(c.page_content) and not _is_ppc_disambiguation_table(c.page_content)
        ]
        candidates = [c for c in candidates if is_eligibility_content(c)]
        blob = " ".join(c.page_content for c in candidates)
        assert "FPC is 9 or greater" in blob or "FPC 9" in blob, (
            f"{carrier}: the FPC>=9 ineligible row was not found among guaranteed PPC candidates."
        )
        assert "FPC is 1" in blob or "FPC 1" in blob or "1 – 3" in blob or "1-3" in blob, (
            f"{carrier}: no FPC 1-3 (eligible) row was found among guaranteed PPC candidates -- "
            f"the model can't conclude 'eligible under every applicable row' without seeing it."
        )

    def test_classification_terminology_not_present_in_auros_occidental_wilshire(self):
        """The fabricated 'Classification A/B/C' terminology that bled in
        from the Trium/SURE/SafePort documents was confirmed gone in round
        11 -- this is a retrieval-level guard against it ever silently
        reappearing (it should never exist in these three carriers' own
        chunks at all)."""
        for carrier in ["Sage_-_Auros_HO3", "Sage_-_Occidental_HO3", "Sage_-_Wilshire_HO3_-_12.02.2025"]:
            chunks = _all_chunks(carrier)
            assert not any("classification" in c.page_content.lower() for c in chunks), (
                f"{carrier}: 'classification' terminology found in its own chunks -- "
                f"re-verify this isn't the cross-contamination bug reappearing from a document update."
            )


# ---------------------------------------------------------------------------
# TIER 2 -- baseline end-to-end tests (slow, real API cost; run before
# merging any change to prompts, retrieval, ranking, or bucket logic)
# ---------------------------------------------------------------------------

@pytest.mark.baseline
class TestBaselineStandardProfile:
    """Known-correct verdicts for the original round 1-9 profile (PPC 9,
    2009-built, 10-yr roof, fenced pool, no solar), each individually
    verified against the actual carrier PDFs during this session -- not
    assumed from an audit summary."""

    @classmethod
    def setup_class(cls):
        cls.result = check_eligibility(STANDARD_PROFILE)
        cls.by_carrier = {r["carrier"]: r for r in cls.result}

    def _find(self, substr):
        matches = [r for c, r in self.by_carrier.items() if substr.lower() in c.lower()]
        assert matches, f"No carrier matching {substr!r} in output: {list(self.by_carrier)}"
        return matches[0]

    def test_swyfft_lloyds_excluded_for_ppc9(self):
        # "ISO Protection Class 9 or 10" ineligible -- the headline fix that
        # took 4 rounds to hold (see eligibility_check.py context-grouping fix)
        assert self._find("Lloyds")["status"] == "INELIGIBLE"

    def test_mercury_roof_exactly_10_years_gets_rcv_not_endorsement(self):
        # Source doc says "older than 10 years old" -- exclusive of exactly-10
        assert self._find("Mercury")["status"] == "ELIGIBLE"

    def test_orion_ppc9_is_eligible_not_ppc10(self):
        # Only PPC 10 is excluded; PPC 9 is fine.
        assert self._find("Orion")["status"] == "ELIGIBLE"

    @pytest.mark.xfail(reason="Foremost county/territory restriction table unflagged since round 3 (backlog, still open as of round 11)")
    def test_foremost_flags_county_restriction(self):
        r = self._find("Foremost")
        blob = " ".join(r.get("missing_info", [])).lower()
        assert "county" in blob

    @pytest.mark.xfail(reason="CHUBB cites the multi-unit clause instead of the single-family 'a house' clause (backlog, rounds 9-11)")
    def test_chubb_cites_correct_eligible_persons_clause(self):
        r = self._find("CHUBB")
        assert "house" in " ".join(r.get("citations", [])).lower()

    @pytest.mark.xfail(reason="Liberty Mutual HO6 source file is identical to HO3; condo-only claim isn't grounded in any retrieved rule text, only the filename (backlog, rounds 9-11)")
    def test_liberty_mutual_ho6_condo_claim_is_grounded_in_real_text(self):
        r = self._find("Liberty Mutual HO6")
        citations = r.get("citations", [])
        assert citations and "condominium" in " ".join(citations).lower()


@pytest.mark.baseline
class TestBaselineAltProfile:
    """Known-correct verdicts for the round 10/11 alternate profile (PPC 1,
    1994-built, 14-yr roof, no pool, solar panels present)."""

    @classmethod
    def setup_class(cls):
        cls.result = check_eligibility(ALT_PROFILE)
        cls.by_carrier = {r["carrier"]: r for r in cls.result}

    def _find(self, substr):
        matches = [r for c, r in self.by_carrier.items() if substr.lower() in c.lower()]
        assert matches, f"No carrier matching {substr!r} in output: {list(self.by_carrier)}"
        return matches[0]

    def test_mercury_no_spurious_ppc10_question(self):
        # Round 10 bug (fixed): asked about PPC 10 eligibility for a PPC-1 customer.
        r = self._find("Mercury")
        blob = " ".join(r.get("missing_info", [])).lower()
        assert "ppc 10" not in blob and "ppc-10" not in blob

    @pytest.mark.xfail(
        reason="Round 11: added a 'check every applicable branch before using "
        "INSUFFICIENT_INFORMATION' instruction for this exact issue. Measured "
        "pass rate across 4 real runs: 1/4 (25%) -- this is NOT the same as "
        "Progressive HO3's solar flakiness (which passes most runs); this fix "
        "mostly does not work yet. Auros/Occidental/Wilshire flip TOGETHER "
        "(same status across all three in every run observed), consistent "
        "with the model settling into one 'mode' per completion rather than "
        "evaluating each carrier independently. Needs a stronger fix, not "
        "just a longer prompt instruction -- see test_sage_family_ppc1_pass_rate.",
        strict=False,
    )
    @pytest.mark.parametrize("carrier_substr", [
        "Auros", "Occidental", "Wilshire",
    ])
    def test_sage_family_ppc1_is_eligible_not_insufficient(self, carrier_substr):
        """Round 11: a full read of all six Sage documents' FPC tables
        confirms an FPC-1 risk is eligible under every row -- the
        ineligible row requires FPC>=9, which this customer can never
        reach. Missing distance data only determines which additional
        conditions apply, not whether the risk qualifies."""
        r = self._find(carrier_substr)
        assert r["status"] != "INSUFFICIENT_INFORMATION", (
            f"{carrier_substr}: PPC 1 can never fail the FPC>=9 exclusion clause; "
            f"expected ELIGIBLE (with conditions to confirm), got {r['status']}."
        )

    def test_allied_trust_14yr_roof_does_not_pass_as_clean_eligible(self):
        # 21yr total life expectancy - 14yr age = 7yr remaining, vs 15.75yr
        # required (3/4 of 21). A 7yr-remaining roof fails this threshold.
        assert self._find("Allied Trust")["status"] != "ELIGIBLE"

    @pytest.mark.xfail(reason="TWICO's circuit-panel rule (35yr window, built 1960+) was dropped entirely after removing an unsound 'auto-satisfied by home age' inference, rather than being surfaced as a genuine open question (round 11)")
    def test_twico_surfaces_circuit_panel_question(self):
        r = self._find("TWICO")
        blob = " ".join(r.get("missing_info", [])).lower()
        assert "circuit panel" in blob

    @pytest.mark.xfail(reason="Round 9: TWICO's 'fire department response time greater than 10 minutes' ineligibility rule was flagged as never surfaced -- confirmed still true as of this round: no test existed for it, and grepping the whole codebase for 'response time' / 'fire department' finds no prompt instruction or guaranteed lookup covering it either. The intake form also has no field for this value, so today it can only ever be a missing_info question, never a resolved verdict.")
    def test_twico_surfaces_fire_department_response_time_question(self):
        r = self._find("TWICO")
        blob = " ".join(r.get("missing_info", [])).lower()
        assert "response time" in blob or "fire department" in blob

    @pytest.mark.xfail(
        reason="Progressive HO3's solar windstorm/hail exclusion is retrievable (see TestSolarRetrieval) but reported absent from round 11's actual output despite prior same-day verification -- run-to-run model inconsistency, tracked by test_progressive_ho3_solar_consistency below rather than asserted as a hard pass here",
        strict=False,
    )
    def test_progressive_ho3_surfaces_solar_exclusion(self):
        r = self._find("Progressive_HO3") if "Progressive_HO3" in self.by_carrier else self._find("Progressive HO3")
        blob = " ".join(r.get("missing_info", []) + r.get("citations", [])).lower()
        assert "solar" in blob


# ---------------------------------------------------------------------------
# Flakiness guard -- run a baseline case N times, report the ACTUAL pass
# rate rather than asserting a single run proves anything. Per CLAUDE.md:
# "occasionally gets distracted, not fully solved" belongs in an assertion,
# not only in a prose summary.
# ---------------------------------------------------------------------------

@pytest.mark.baseline
def test_progressive_ho3_solar_consistency(record_property):
    n_runs = 3
    outcomes = []
    for _ in range(n_runs):
        result = check_eligibility(ALT_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}
        matches = [r for c, r in by_carrier.items() if "progressive" in c.lower() and "ho3" in c.lower() and "ho6" not in c.lower()]
        assert matches
        r = matches[0]
        blob = " ".join(r.get("missing_info", []) + r.get("citations", [])).lower()
        outcomes.append("solar" in blob)
    pass_rate = sum(outcomes) / len(outcomes)
    record_property("progressive_ho3_solar_pass_rate", pass_rate)
    print(f"\nProgressive HO3 solar-mention pass rate: {pass_rate:.0%} over {n_runs} runs ({outcomes})")
    # Not asserting == 1.0: this is a known-flaky case being TRACKED, not a
    # green/red gate yet. Fails loudly (and visibly, via the printed rate)
    # if it drops to 0% -- silence would be worse than a known partial rate.
    assert pass_rate > 0.0, (
        f"Progressive HO3's solar clause did not surface in ANY of {n_runs} runs -- "
        f"this has regressed from partial to total failure."
    )


@pytest.mark.baseline
def test_sage_occidental_pool_fence_consistency(record_property):
    """Was a hard, unconditional assert (test_sage_occidental_pool_fence_rule_is_found)
    until a 20-run measurement this session found it actually passes only
    55% (11/20) of the time -- meaning it had been passing or failing by
    luck depending on which run CI happened to catch, silently, with no
    record of the real rate. Converted to the same tracked pattern as
    test_progressive_ho3_solar_consistency above rather than continuing to
    hide that number behind a single green/red result.

    Same failure SHAPE as Progressive HO3's solar case, not Sage's FPC
    table: Occidental's pool-fence rule is retrieved via a deterministic
    guaranteed lookup (confirmed identical across 8 repeated calls, same
    as Progressive's solar chunk) -- this is a synthesis-layer miss on
    already-solved retrieval, not multi-branch table reasoning. Queued for
    the same post-generation verify+single-carrier-repair fix piloted on
    Progressive (see experiment_progressive_repair_spike.py, which took
    that case from 90% to 100% over 20 runs) once that pattern is wired
    into production -- not applied here yet, so this stays an honest
    tracked number in the meantime rather than an accepted 55%."""
    n_runs = 3
    outcomes = []
    for _ in range(n_runs):
        result = check_eligibility(STANDARD_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}
        matches = [r for c, r in by_carrier.items() if "occidental" in c.lower()]
        assert matches, "Occidental: not found in output"
        r = matches[0]
        blob = " ".join(r.get("reasons", []) + r.get("citations", []) + r.get("missing_info", [])).lower()
        outcomes.append("fenc" in blob or "gate" in blob)
    pass_rate = sum(outcomes) / len(outcomes)
    record_property("sage_occidental_pool_fence_pass_rate", pass_rate)
    print(f"\nSage Occidental pool-fence pass rate: {pass_rate:.0%} over {n_runs} runs ({outcomes})")
    assert pass_rate > 0.0, (
        f"Sage Occidental's pool-fence rule did not surface in ANY of {n_runs} runs -- "
        f"this has regressed from partial (55% measured over 20 runs) to total failure."
    )


@pytest.mark.baseline
def test_sage_family_ppc1_pass_rate(record_property):
    """Measured pass rate as of round 11 + same-day fix attempt: 1/4 (25%)
    across (1 pytest run + 3 ad-hoc runs, not all captured by this specific
    function call). This test re-measures with its OWN fresh runs so the
    number stays live and re-checkable, rather than being a one-time
    finding that ages out of visibility. Unlike Progressive HO3's solar
    case (which mostly passes), this one mostly does NOT -- do not let a
    single good run get reported as "fixed" without re-running this."""
    n_runs = 3
    target_carriers = ["Auros", "Occidental", "Wilshire"]
    per_carrier_outcomes = {c: [] for c in target_carriers}
    for _ in range(n_runs):
        result = check_eligibility(ALT_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}
        for target in target_carriers:
            matches = [r for c, r in by_carrier.items() if target.lower() in c.lower()]
            assert matches, f"{target}: not found in output"
            per_carrier_outcomes[target].append(matches[0]["status"] != "INSUFFICIENT_INFORMATION")
    for carrier, outcomes in per_carrier_outcomes.items():
        rate = sum(outcomes) / len(outcomes)
        record_property(f"sage_{carrier.lower()}_ppc1_pass_rate", rate)
        print(f"\nSage {carrier} PPC-1 eligible-not-insufficient pass rate: {rate:.0%} over {n_runs} runs ({outcomes})")
    # Not a hard gate at any particular threshold yet -- this test's job is
    # to keep the real number visible on every run, not to silently pass or
    # fail. If it's reliably 0% going forward, that's a stronger signal to
    # invest in a structural fix (e.g. a dedicated per-branch check) rather
    # than another prompt instruction.
