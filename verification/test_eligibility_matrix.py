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
import re
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
    build_risk_factors,
    check_eligibility,
    guaranteed_carrier_lookup,
    is_eligibility_content,
    normalize_chunk_text,
    _apply_structured_overrides,
    _strip_misattributed_citations,
    _citation_attributed_carrier,
    _resolve_structured_carrier,
    _carrier_words,
    _occupancy_guarantee_applies,
    _is_tier_placement,
    _mentions_solar,
    _mentions_protection_class,
    _mentions_pool_rule,
    _mentions_roof_life_expectancy,
    _is_ppc_disambiguation_table,
    _enforce_pool_spec_support,
    _extract_pool_spec,
    _intake_states_pool_specifics,
    _note_solar_roofing_does_not_apply,
    _is_manufactured_pool_question,
    _INTEGRATED_SOLAR_ROOFING_PHRASES,
    classify_solar_text,
    classify_carrier_solar_text,
    get_carriers_for_occupancy,
    parse_carrier_json,
    repair_unescaped_quotes,
    _strip_contradicted_property_claims,
    _mentions_roof_shape_rule,
    _RESTRICTED_ROOF_SHAPES,
    _mentions_occupancy_eligibility,
    _mentions_occupancy_rule,
    _mentions_ownership_entity_rule,
    _occupancy_predicate_for,
    _occupancy_cap_for,
    _occupancy_priority_key,
    _carrier_brand,
    MAX_OCCUPANCY_CHUNKS_PER_CARRIER,
    MAX_OWNERSHIP_CHUNKS_PER_CARRIER,
    _SAGE_ROOFER_STATEMENT_CARRIERS,
    _SAGE_FPC_CARRIERS,
    _TWICO_CARRIERS,
    carrier_programs,
    get_combined_program_carriers,
    get_all_carriers,
    GUIDE_UNAVAILABLE,
    NOT_EVALUATED,
    _is_openai_model,
    UNRECOGNISED_VERDICT,
    usable_answer_count,
    _mentions_coverage_a_limit,
    _coverage_a_priority_key,
    _county_item_present,
)
from shared_resources import get_vectorstore
from profiles import (STANDARD_PROFILE, ALT_PROFILE, COASTAL_PPC4_PROFILE,
                      AUDIT_R13_PROFILE, AUDIT_R14_DP3_PROFILE, normalize_carrier_name)
from structured_rules import (
    sage_family_fpc_eligibility,
    mercury_roof_eligibility,
    swyfft_lloyds_roof_settlement,
    sage_markel_roof_exclusion,
    swyfft_max_roof_age_30,
    twico_roof_settlement,
    twico_roof_subtype_is_ambiguous,
    shingle_subtype_is_ambiguous,
    sage_roofer_statement_required,
    centauri_dp3_flat_roof,
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


def _carrier_matches(needle, carrier_name):
    """Carrier-name matching that ignores separators.

    Round 13: five baseline tests failed with "not found in output" while the
    carrier was plainly THERE -- the model had echoed "Allied_Trust_HO3"
    that run instead of "Allied Trust HO3", and every match site did a naive
    `"allied trust" in name.lower()`, which an underscore defeats. The model
    restates carrier names freely and its separator choice varies run to
    run, so tests must not depend on it. profiles.normalize_carrier_name()
    already existed for exactly this; it just was not being used here.
    """
    return normalize_carrier_name(needle) in normalize_carrier_name(carrier_name)


def _find_carrier(by_carrier, *needles, exclude=()):
    """The results whose carrier name matches every needle and no exclusion.

    A needle set that matches MORE THAN ONE carrier is a hard error, not a
    silently-taken first match. Every caller here does `matches[0]` or
    `next(...)`, so an ambiguous needle resolves by dict insertion order --
    i.e. by whatever order the model happened to emit carriers in.

    Round 13 learned this the expensive way. Normalising names to compare
    them (the fix for "Allied_Trust_HO3" vs "allied trust") also strips the
    apostrophe from "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5", so the
    needle "lloyds" began matching BOTH that carrier and
    "Swyfft_-_Lloyds_(Surplus)_HO3" -- and Sage Trium sorts first. The
    Swyfft PPC9 test then read Sage Trium's INSUFFICIENT_INFORMATION and
    reported it as Swyfft's status, which was written up as an 80% -> 0%
    product regression with a p-value attached to it. A 25-run sweep of the
    same profile showed Swyfft at 100% INELIGIBLE the whole time. The old
    naive substring match had excluded Sage Trium only by accident of that
    apostrophe.

    "hoa+" is the same trap: the "+" is not alphanumeric, so the needle
    normalises to bare "HOA" and matches HOAIC as well as ARI (HOA+). That
    one happens to resolve correctly today purely because ARI sorts first.

    This mirrors what production already does in
    eligibility_check._citation_attributed_carrier, whose comment says an
    ambiguous label must resolve to exactly one carrier because "stripping
    evidence must never rest on a coin flip". Neither may a measurement.
    """
    matches = [
        (name, r) for name, r in by_carrier.items()
        if all(_carrier_matches(n, name) for n in needles)
        and not any(_carrier_matches(x, name) for x in exclude)
    ]
    if len(matches) > 1:
        raise AssertionError(
            "carrier needle {!r} is AMBIGUOUS -- it matches {}. Make the needle "
            "specific enough to identify one carrier; resolving this by dict "
            "order would silently measure the wrong carrier.".format(
                list(needles), [name for name, _ in matches]
            )
        )
    return [r for _, r in matches]


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
        # A real per-carrier difference, not a dropped bullet to "fix" back to
        # matching its siblings -- but confirmed for the DP3 (DWELLING FIRE)
        # program only. Retargeted to the DP3 record in round 17: the HO3
        # record holds the DP3 guide too (DD-4), so this was never HO3
        # evidence, and the source-text premise is now asserted against the
        # record it is actually true of.
        dp3_text = " ".join(c.page_content for c in _all_chunks("Sage_-_Occidental_DP3")).lower()
        assert "dwelling fire program" in dp3_text, "premise: this is Occidental's DP3 guide"
        assert "no rental exposures allowed" not in dp3_text, (
            "premise: Occidental's DP3 guide lacks row 5's no-rental condition"
        )
        _, occidental_reasons = sage_family_fpc_eligibility("4", distance_miles=6, carrier="Sage_-_Occidental_DP3")
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

    # Round 12 priority 4: a live run claimed "21 years falls within the
    # 11-20 year range for composition shingles (assuming standard
    # composition)" -- age 21 is EXCLUDED under 3-tab, not ACV. These pin
    # every crossover point in the source table for BOTH sub-types, so an
    # off-by-one in either band can never pass silently. (The bracket
    # function itself was verified correct at all of these -- the live
    # error came from the model's own prose, see
    # TestTwicoOverrideWiring::test_ambiguous_subtype_states_both_outcomes.)
    @pytest.mark.parametrize("roof_type,age,expected", [
        # Composition (3-tab): RCV 0-10 | ACV 11-20 | Excluded 21+
        ("Composition (3-tab)", 10, "RCV"),
        ("Composition (3-tab)", 11, "ACV"),
        ("Composition (3-tab)", 20, "ACV"),
        ("Composition (3-tab)", 21, "EXCLUDED"),
        # Composition (Architectural): RCV 0-15 | ACV 16-25 | Excluded 26+
        ("Composition (Architectural)", 15, "RCV"),
        ("Composition (Architectural)", 16, "ACV"),
        ("Composition (Architectural)", 25, "ACV"),
        ("Composition (Architectural)", 26, "EXCLUDED"),
        # The two sub-types must genuinely diverge at the ages where the
        # live error occurred -- if these ever agree, the bands collapsed.
        ("Composition (3-tab)", 16, "ACV"),
        ("Composition (Architectural)", 21, "ACV"),
    ])
    def test_both_subtype_bracket_boundaries(self, roof_type, age, expected):
        status, _ = twico_roof_settlement(roof_type, age)
        assert status == expected, f"{roof_type} at age {age} should be {expected}, got {status}"


@pytest.mark.retrieval
class TestSageFPCOverrideWiring:
    """Round 12: sage_family_fpc_eligibility() computed the right answer
    (FPC 4 -> ELIGIBLE) and the model's own narrative said so too -- but the
    carrier's final status field still showed INSUFFICIENT_INFORMATION,
    because _apply_structured_overrides()'s keyword-detection blob only
    scanned missing_info/reasons, never `notes` (where the model's FPC
    conclusion actually landed). This is a wiring gap, not a table-logic
    gap -- sage_family_fpc_eligibility() itself was never wrong. These
    tests call _apply_structured_overrides() directly -- the REAL wiring
    function, not a reimplementation -- with realistic result shapes, so
    the verdict-level bug can't ship again hidden behind a passing unit
    test on the pure function alone (that's exactly what let this one
    through)."""

    def _make_carrier_result(self, carrier, notes="", reasons=None, missing_info=None):
        return {
            "carrier": carrier,
            "status": "INSUFFICIENT_INFORMATION",
            "flaw_count": 0,
            "reasons": reasons or [],
            "citations": [],
            "missing_info": missing_info or [],
            "notes": notes,
        }

    def test_fpc_conclusion_in_notes_only_still_upgrades_verdict(self):
        # Exact shape of the round 12 bug.
        result = self._make_carrier_result(
            "Sage - Auros HO3",
            notes="FPC 1-8 is eligible regardless of driving distance to the fire station.",
        )
        _apply_structured_overrides([result], ["Sage_-_Auros_HO3"], dict(COASTAL_PPC4_PROFILE))
        assert result["status"] == "ELIGIBLE", (
            "The structured FPC check computed ELIGIBLE and the model's own notes said so too -- "
            "the verdict must reflect that, not silently stay INSUFFICIENT_INFORMATION."
        )

    def test_fpc_conclusion_in_reasons_still_upgrades_verdict(self):
        # Different field/phrasing -- generalization check per CLAUDE.md.
        # Carrier moved off Sage_-_Occidental_HO3 in round 17: that record
        # holds the DP3 guide (DD-4), and this test is about override wiring,
        # which any Sage FPC carrier with a correct HO3 document exercises.
        result = self._make_carrier_result(
            "Sage - SURE HO-3",
            reasons=["Protection Class 4 does not trigger the FPC 9 or greater ineligible row."],
        )
        _apply_structured_overrides([result], ["Sage_-_SURE_HO-3_-_01.31.2026"], dict(COASTAL_PPC4_PROFILE))
        assert result["status"] == "ELIGIBLE"

    def test_unrelated_missing_info_is_not_forced_eligible(self):
        # Guard rail: an unrelated open question must not be silently
        # steamrolled just because the FPC/PPC value alone resolves eligible.
        result = self._make_carrier_result(
            "Sage - Wilshire HO3",
            missing_info=["Confirmation of central station fire alarm on the risk."],
        )
        _apply_structured_overrides(
            [result], ["Sage_-_Wilshire_HO3_-_12.02.2025"], dict(COASTAL_PPC4_PROFILE),
        )
        assert result["status"] == "INSUFFICIENT_INFORMATION", (
            "An unrelated missing fact should not be silently overridden just because "
            "the FPC/PPC value alone happens to resolve eligible."
        )


@pytest.mark.retrieval
class TestTwicoOverrideWiring:
    """Round 12: twico_roof_settlement() was built and unit-tested, but
    held out of _apply_structured_overrides() entirely -- gating the whole
    function rather than just the genuinely ambiguous bare-"Composition
    Shingle" case. This silently dropped roof-age transparency for every
    unambiguous material (Tile, Metal Standing-Seam, Wood/Slate/Metal
    Shingle, Asbestos, Corrugated Metal). Tests the real wiring function
    directly, same rationale as TestSageFPCOverrideWiring above."""

    def _make_carrier_result(self, carrier="TWICO HO3"):
        return {
            "carrier": carrier, "status": "ELIGIBLE", "flaw_count": 0,
            "reasons": [], "citations": [], "missing_info": [], "notes": "",
        }

    def test_tile_roof_settlement_surfaced_in_notes(self):
        # A real end-to-end run showed the model can go completely silent
        # on roof/tile for the "boring" RCV case, since TWICO's roof table
        # doesn't match the generic roof-life-expectancy guaranteed lookup
        # -- nothing else guarantees this carrier's roof clause is even
        # retrieved. The override must ALWAYS leave a visible trace, not
        # just for the "notable" ACV/Excluded/ineligible outcomes.
        profile = dict(COASTAL_PPC4_PROFILE, roof_type="Tile", roof_age=16)
        result = self._make_carrier_result()
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        assert result["status"] == "ELIGIBLE"
        assert "roof" in result["notes"].lower() or "tile" in result["notes"].lower()

    def test_tile_roof_in_acv_band_surfaces_a_note(self):
        profile = dict(COASTAL_PPC4_PROFILE, roof_type="Tile", roof_age=30)
        result = self._make_carrier_result()
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        assert "acv" in result["notes"].lower() or "ACV" in result["notes"]

    def test_wood_shingle_forces_ineligible(self):
        profile = dict(COASTAL_PPC4_PROFILE, roof_type="Wood Shingle", roof_age=5)
        result = self._make_carrier_result()
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        assert result["status"] == "INELIGIBLE"

    def test_bare_composition_shingle_still_gated_as_insufficient_info(self):
        # The one case that SHOULD stay gated -- confirms un-gating the
        # unambiguous materials didn't accidentally un-gate this one too.
        profile = dict(COASTAL_PPC4_PROFILE, roof_type="Composition Shingle", roof_age=14)
        result = self._make_carrier_result()
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        assert any("subtype" in m.lower() for m in result["missing_info"])

    @pytest.mark.parametrize("age,three_tab,architectural", [
        (21, "EXCLUDED", "ACV"),   # the exact live-run failure case
        (14, "ACV", "RCV"),
        (26, "EXCLUDED", "EXCLUDED"),  # both agree -- no contradiction note needed
    ])
    def test_ambiguous_subtype_states_both_outcomes(self, age, three_tab, architectural):
        """Round 12 priority 4: the missing_info caveat alone let a
        confidently WRONG bracket claim from the model's own prose ship
        beside it. When the two sub-types diverge, the exact outcome for
        each must appear in the output so the model's guess isn't the only
        concrete number a reader sees."""
        profile = dict(COASTAL_PPC4_PROFILE, roof_type="Composition Shingle", roof_age=age)
        result = self._make_carrier_result()
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        if three_tab == architectural:
            assert "3-tab resolves to" not in result["notes"]
            return
        notes = result["notes"]
        assert f"3-tab resolves to {three_tab}" in notes, notes
        assert f"architectural resolves to {architectural}" in notes, notes


@pytest.mark.retrieval
class TestOtherRoofOverridesAlwaysLeaveATrace:
    """Same round-12 lesson applied to the other three roof-structured
    overrides (Mercury, Sage Markel, Swyfft max-30yr): a silent no-op on
    the "boring" default outcome relies on the model's own retrieval and
    narrative to independently mention roof age at all, which a real run
    proved isn't guaranteed. Every branch must now leave a visible note."""

    def _make_carrier_result(self, carrier):
        return {
            "carrier": carrier, "status": "ELIGIBLE", "flaw_count": 0,
            "reasons": [], "citations": [], "missing_info": [], "notes": "",
        }

    def test_mercury_default_case_gets_a_note(self):
        profile = dict(COASTAL_PPC4_PROFILE, roof_type="Composition Shingle", roof_age=5)
        result = self._make_carrier_result("Mercury HO3")
        _apply_structured_overrides([result], ["Mercury_HO3_-_01.01.2026"], profile)
        assert result["notes"]

    def test_sage_markel_default_case_gets_a_note(self):
        profile = dict(COASTAL_PPC4_PROFILE, roof_type="Composition Shingle", roof_age=5)
        result = self._make_carrier_result("Sage Markel HO3")
        _apply_structured_overrides([result], ["Sage_-_Markel_HO3"], profile)
        assert result["notes"]

    def test_swyfft_max30_default_case_gets_a_note(self):
        profile = dict(COASTAL_PPC4_PROFILE, roof_age=5)
        result = self._make_carrier_result("Swyfft Benchmark Admitted HO3")
        _apply_structured_overrides([result], ["Swyfft_-_Benchmark_(Admitted)_HO3"], profile)
        assert result["notes"]


@pytest.mark.retrieval
class TestCitationAttributionValidator:
    """Round 12 priority 1: ARI (HOA+) inherited ARI (HOB)'s age-cap rule in
    40% of measured runs -- sometimes while correctly labeling the citation
    "ARI (HOB):" in its own citations list. Retrieval is clean (HOA+'s own
    chunks never contain that text), so this is cross-carrier bleed-through
    inside one combined completion. Mechanical post-generation attribution
    check, tested against the REAL production function.

    Parametrized across three unrelated carrier families (ARI, Sage,
    Swyfft) per CLAUDE.md's 2+-phrasings requirement for a general-rule
    fix -- this is not an ARI-specific patch."""

    def _result(self, carrier, status, citations, flaw_count=1):
        return {
            "carrier": carrier, "status": status, "flaw_count": flaw_count,
            "reasons": [], "citations": list(citations), "missing_info": [], "notes": "",
        }

    def test_reproduces_the_exact_ari_finding(self):
        # The literal citation pair from a captured contaminated run.
        r = self._result(
            "ARI (HOA+)", "INELIGIBLE",
            [
                "ARI (HOB): 'Homes 0-20 years old are eligible for this program. "
                "Homes over 20 years old can be considered for coverage under the HOA/HOA Plus.'",
            ],
        )
        _strip_misattributed_citations([r], ["ARI_(HOA+)", "ARI_(HOB)"])
        assert not r["citations"], "the foreign citation must be removed"
        assert r["status"] == "INSUFFICIENT_INFORMATION", (
            "an INELIGIBLE resting only on another carrier's rule is unsupported once "
            "that rule is removed -- it must not stand as a decline."
        )
        assert "attribution check" in r["notes"].lower()

    @pytest.mark.parametrize("own,foreign,carriers", [
        ("ARI (HOA+)", "ARI (HOB)", ["ARI_(HOA+)", "ARI_(HOB)"]),
        ("Sage - Auros HO3", "Sage - Wilshire HO3",
         ["Sage_-_Auros_HO3", "Sage_-_Wilshire_HO3_-_12.02.2025"]),
        ("Swyfft - Benchmark (Admitted) HO3", "Swyfft - Lloyds (Surplus) HO3",
         ["Swyfft_-_Benchmark_(Admitted)_HO3", "Swyfft_-_Lloyds_(Surplus)_HO3"]),
    ])
    def test_foreign_citation_stripped_across_carrier_families(self, own, foreign, carriers):
        r = self._result(own, "INELIGIBLE", [f"{foreign}: 'some rule from the wrong document'"])
        _strip_misattributed_citations([r], carriers)
        assert not r["citations"]
        assert r["status"] == "INSUFFICIENT_INFORMATION"

    def test_own_citation_is_preserved_and_verdict_untouched(self):
        # The critical guard rail: a legitimate self-cited decline must
        # survive completely untouched.
        r = self._result(
            "Swyfft - Lloyds (Surplus) HO3", "INELIGIBLE",
            ["Swyfft - Lloyds (Surplus) HO3: 'ISO Protection Class 9 or 10.'"],
        )
        _strip_misattributed_citations([r], ["Swyfft_-_Lloyds_(Surplus)_HO3", "ARI_(HOB)"])
        assert len(r["citations"]) == 1
        assert r["status"] == "INELIGIBLE"
        assert "attribution check" not in r["notes"].lower()

    def test_adverse_verdict_survives_if_one_own_citation_remains(self):
        # Mixed case: a foreign citation is stripped, but the carrier's own
        # rule still supports the decline -- the verdict must stand.
        r = self._result(
            "ARI (HOA+)", "INELIGIBLE",
            [
                "ARI (HOB): 'Homes 0-20 years old are eligible for this program.'",
                "ARI (HOA+): 'Roofs that are 15 years or older will be covered on an ACV basis.'",
            ],
        )
        _strip_misattributed_citations([r], ["ARI_(HOA+)", "ARI_(HOB)"])
        assert len(r["citations"]) == 1
        assert r["status"] == "INELIGIBLE", (
            "the carrier's own citation still supports the decline -- it must not be downgraded."
        )

    def test_unlabeled_citation_is_never_treated_as_misattributed(self):
        r = self._result("ARI (HOA+)", "INELIGIBLE", ["'Homes 0-20 years old are eligible.'"])
        _strip_misattributed_citations([r], ["ARI_(HOA+)", "ARI_(HOB)"])
        assert len(r["citations"]) == 1
        assert r["status"] == "INELIGIBLE"

    def test_eligible_verdict_is_never_downgraded(self):
        # Stripping evidence can only ever weaken an ADVERSE finding.
        r = self._result("ARI (HOA+)", "ELIGIBLE", ["ARI (HOB): 'some other rule'"], flaw_count=0)
        _strip_misattributed_citations([r], ["ARI_(HOA+)", "ARI_(HOB)"])
        assert r["status"] == "ELIGIBLE"

    def test_ambiguous_label_is_treated_as_unknown_not_guessed(self):
        """A bare "ARI:" prefix matches BOTH ARI_(HOA+) and ARI_(HOB).
        Resolving it by sort order would mean that, while evaluating
        whichever one loses the tiebreak, a perfectly legitimate
        self-citation looks foreign and gets stripped -- and could then
        downgrade a real decline. Stripping evidence must never rest on a
        coin flip, so an ambiguous label is unknown, not guessed."""
        assert _citation_attributed_carrier(
            "ARI: 'some rule'", ["ARI_(HOA+)", "ARI_(HOB)"]
        ) is None

    def test_ambiguous_label_does_not_strip_or_downgrade(self):
        r = self._result("ARI (HOB)", "INELIGIBLE", ["ARI: 'Homes 0-20 years old are eligible.'"])
        _strip_misattributed_citations([r], ["ARI_(HOA+)", "ARI_(HOB)"])
        assert len(r["citations"]) == 1, "an ambiguous label must not be stripped"
        assert r["status"] == "INELIGIBLE", "an ambiguous label must not downgrade a verdict"

    def test_DOCUMENTED_LIMITATION_prose_only_bleed_is_not_caught(self):
        """EXPLICIT SCOPE LIMIT -- do not read the attribution validator as
        "cross-carrier contamination: solved".

        It acts on citations carrying a carrier LABEL. Cross-carrier bleed
        that appears only as prose in reasons/notes, with no citation to
        attribute, passes through completely untouched -- which is exactly
        the shape of the historical Sage "Classification A/B/C" bleed
        (terminology from Trium/SURE/SafePort written into Auros/
        Occidental/Wilshire's prose). That failure mode is covered ONLY by
        the prompt instruction and the retrieval-level guard
        (TestSageFamilyFPCRetrieval::
        test_classification_terminology_not_present_in_auros_occidental_wilshire),
        both of which are weaker than a mechanical post-generation check.

        This test asserts the CURRENT limitation, so it fails loudly if
        someone later extends the validator to cover prose -- at which
        point this should be rewritten as a real regression test rather
        than silently left behind. See also the xfail end-to-end test
        test_prose_only_cross_carrier_bleed_is_absent below."""
        r = self._result(
            "Sage - Auros HO3", "INSUFFICIENT_INFORMATION",
            citations=[],  # no citation to attribute -- the whole point
            flaw_count=0,
        )
        # Terminology that exists only in sibling carriers' documents.
        r["reasons"] = ["This risk is a Classification B location under the FPC table."]
        _strip_misattributed_citations([r], ["Sage_-_Auros_HO3", "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026"])
        assert "classification b" in " ".join(r["reasons"]).lower(), (
            "Prose-only bleed is currently NOT stripped. If the validator was just extended "
            "to cover prose, rewrite this test as a regression test instead of deleting it."
        )
        assert "attribution check" not in r["notes"].lower()

    def test_long_prose_prefix_with_colon_is_not_parsed_as_a_label(self):
        long_prefix = (
            "The carrier's guidelines state the following regarding roof age and the "
            "applicable loss settlement basis for this particular risk: 'ACV applies'"
        )
        assert _citation_attributed_carrier(long_prefix, ["ARI_(HOA+)", "ARI_(HOB)"]) is None


@pytest.mark.retrieval
class TestCoastalTierRiskFactors:
    """Round 12: build_risk_factors() only triggered its coastal
    wind-coverage retrieval term for Tier 1/Tier 2, silently excluding Tier
    3 ("outer coastal zone" per app.py's own dropdown -- still explicitly
    coastal, not "Not Coastal"). Whether Tier 3 should trigger any GIVEN
    carrier's specific wind-pool-zone rule is genuinely unconfirmed (this
    tool has no ground-truth mapping from its own Tier 1/2/3 scheme to
    carriers' own geographic definitions) -- this test only locks in that
    the RETRIEVAL trigger fires for Tier 3, not that any particular
    carrier's verdict changes as a result."""

    def test_tier_3_triggers_coastal_wind_risk_factor(self):
        profile = dict(COASTAL_PPC4_PROFILE, coastal_tier="Tier 3")
        factors = build_risk_factors(profile, profile["occupancy_type"])
        assert any("wind" in f.lower() and "coastal" in f.lower() for f in factors)

    def test_tier_1_and_2_still_trigger_it_too(self):
        for tier in ["Tier 1", "Tier 2"]:
            profile = dict(COASTAL_PPC4_PROFILE, coastal_tier=tier)
            factors = build_risk_factors(profile, profile["occupancy_type"])
            assert any("wind" in f.lower() and "coastal" in f.lower() for f in factors), tier

    def test_not_coastal_does_not_trigger_it(self):
        profile = dict(COASTAL_PPC4_PROFILE, coastal_tier="Not Coastal")
        factors = build_risk_factors(profile, profile["occupancy_type"])
        assert not any("wind" in f.lower() and "coastal" in f.lower() for f in factors)


@pytest.mark.retrieval
class TestAriCrossContaminationRetrieval:
    """Round 12: ARI (HOA+) incorrectly borrowed ARI (HOB)'s age-cap
    citation ("Homes 0-20 years old are eligible... over 20 years old can
    be considered for coverage under the HOA/HOA Plus") and returned a
    false Ineligible. Confirmed directly against both source PDFs: this
    citation lives ONLY in HOB's document -- HOA+'s own document has no
    age-cap language anywhere. Retrieval-level guard against it reappearing,
    same pattern as the Sage "classification" contamination guard."""

    def test_ari_hoa_plus_has_no_age_cap_language(self):
        vs = get_vectorstore()
        raw = vs._collection.get(where={"carrier": "ARI_(HOA+)"}, include=["documents"])
        assert not any(
            "0-20 years" in d or "hoa/hoa plus" in d.lower() for d in raw["documents"]
        ), "ARI (HOA+)'s own chunks must never contain HOB's age-cap language."


@pytest.mark.retrieval
class TestMaxResponseTokenBudget:
    """Round 12: a real, untruncated capture of a "JSON PARSE ERROR" proved
    it was plain output-token truncation, not a character-escaping issue --
    the response cut off mid-object after only ~20 of ~28 carriers.
    Confirms the raised budget is actually in place and can't silently
    shrink back down without this test noticing."""

    def test_max_response_tokens_is_at_least_20000(self):
        from eligibility_check import MAX_RESPONSE_TOKENS
        assert MAX_RESPONSE_TOKENS >= 20000, (
            "12000 was measured insufficient for a ~28-carrier response and produced "
            "truncated, unparseable JSON in a real, captured failure -- do not lower this "
            "without re-measuring headroom against the current carrier count/verbosity."
        )


@pytest.mark.retrieval
class TestChunkTextNormalization:
    """ARI (HOA+) and ARI (HOB)'s pool-fence citation has a raw embedded
    mid-sentence newline (a PDF line-wrap artifact) and a curly apostrophe
    (U+2019) -- if the model ever reproduces the newline verbatim inside its
    own generated JSON string without escaping it, that breaks parsing (see
    the naive-embed test below). This is a real, demonstrated failure mode,
    but round 12 traced the recurring ~20-30% "JSON PARSE ERROR" actually
    seen in production to something else entirely: plain output-token
    truncation on a long ~28-carrier response (see MAX_RESPONSE_TOKENS in
    eligibility_check.py) -- every earlier debug print only showed
    raw[:1000], which always happens to contain ARI's section since it
    sorts first alphabetically, regardless of where a truncation actually
    occurs (much later). normalize_chunk_text() is kept as a real,
    worthwhile cleanup, not withdrawn -- it just wasn't the fix for the
    failures actually observed."""

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

    def test_every_status_lands_in_exactly_one_bucket(self):
        """The bucket/label bug took three rounds to catch because a status
        can silently land in the WRONG bucket. The mirror risk is a status
        landing in NO bucket -- it would vanish from the UI entirely, with
        no error anywhere. Covers all four documented statuses (including
        REFER, which is long-standing and intentional, not new) plus an
        unrecognized status, which must be caught rather than disappear."""
        results = [
            self._make("ELIGIBLE", carrier="e"),
            self._make("INELIGIBLE", flaw_count=1, carrier="one"),
            self._make("INELIGIBLE", flaw_count=3, carrier="multi"),
            self._make("REFER", carrier="refer"),
            self._make("INSUFFICIENT_INFORMATION", carrier="info"),
            # the two pipeline-written statuses (Step 2, 2026-09-29)
            self._make(GUIDE_UNAVAILABLE, carrier="wrong-guide"),
            self._make(NOT_EVALUATED, carrier="skipped"),
        ]
        buckets = assign_buckets(results)
        assert buckets["guide_unavailable"] == [results[5]]
        assert buckets["not_evaluated"] == [results[6]]
        placed = [r for b in buckets.values() for r in b]
        placed_names = sorted(r["carrier"] for r in placed)
        assert placed_names == sorted(r["carrier"] for r in results), (
            f"every result must land in a bucket; got {placed_names}"
        )
        assert len(placed) == len(results), "a result was placed in more than one bucket"

    def test_unrecognized_status_does_not_silently_vanish(self):
        # This used to document that an unknown status was DROPPED from every
        # bucket, on the premise that "the model is constrained to the four
        # documented statuses". 2026-09-30 disproved the premise live:
        # gpt-6-luna returned 23 records with no status key at all and the
        # screen showed four empty columns. An unknown status now lands in
        # the catch-all "unrecognised" bucket, rendered under Could Not Be
        # Checked.
        results = [self._make("SOME_NEW_STATUS", carrier="x")]
        buckets = assign_buckets(results)
        assert buckets["unrecognised"] == results
        assert sum(len(b) for b in buckets.values()) == 1

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
class TestIntegratedSolarRoofingVsMountedPanels:
    """Round 12 priority 5: Allied Trust HO3 was declined INELIGIBLE because
    "solar panels are listed among ineligible roof types" -- but its actual
    exclusion list names "solar roof system" and "solar panel tiles",
    integrated solar ROOFING (the roof covering itself), listed alongside
    slate, tin, corrugated metal and built-up tar and gravel. A customer
    with ordinary PV panels mounted on a composition shingle roof does not
    have a solar roof covering, so that exclusion cannot apply.

    Correcting a premise in the audit: this is NOT a generalization of
    logic that already worked elsewhere. Foremost ("Solar shingles") and
    Swyfft ("Tesla Solar Roofs") get it right only because their own source
    wording is unambiguous -- grep confirmed there was no solar
    disambiguation rule anywhere in the prompt. Allied Trust's wording is
    the hard case precisely because "solar panel tiles" literally contains
    the words "solar panel". So a genuinely new general rule was added; the
    tests below pin the source-text distinction it depends on across three
    carriers phrasing it three different ways."""

    @pytest.mark.parametrize("carrier,integrated_phrase", [
        ("Allied_Trust_HO3", "solar roof system"),
        ("Allied_Trust_HO3", "solar panel tiles"),
        ("Foremost_DP3_and_HO3_-_07.01.2026", "solar shingles"),
        ("Swyfft_-_Lloyds_(Surplus)_HO3", "tesla solar roof"),
    ])
    def test_integrated_roofing_phrase_is_retrievable(self, carrier, integrated_phrase):
        found = _guaranteed_lookup_chunks(carrier, _mentions_solar, keep=2)
        assert found, f"{carrier}: no solar chunk retrieved at all."
        blob = " ".join(c.page_content for c in found).lower()
        assert integrated_phrase in blob, (
            f"{carrier}: {integrated_phrase!r} not retrieved -- the model cannot make the "
            f"integrated-roofing vs. mounted-panel distinction without this text."
        )

    def test_allied_trust_solar_text_is_only_about_roof_coverings(self):
        """The substantive point: every solar mention in Allied Trust's
        document is a roof COVERING material, with no rule about panels
        mounted on an ordinary roof. So there is nothing in this carrier's
        text that a mounted-panel customer can fail."""
        found = _guaranteed_lookup_chunks("Allied_Trust_HO3", _mentions_solar, keep=2)
        blob = " ".join(c.page_content for c in found).lower()
        assert "solar roof system" in blob or "solar panel tiles" in blob
        # Wording that would indicate a genuine mounted-panel rule.
        for mounted_rule in ("mounted", "attached to the roof", "panel installation", "installed on"):
            assert mounted_rule not in blob, (
                f"Allied Trust's solar text now contains {mounted_rule!r} -- it may have gained a "
                f"real mounted-panel rule, so the 'exclusion cannot apply' reasoning needs re-checking."
            )

    def test_solar_retrieval_is_deterministic(self):
        """Allied Trust produced two different live behaviors on the same
        input (declined-over-solar in one run, no solar mention in the
        next). This confirms retrieval is NOT the variable -- identical
        context both times -- so that divergence is synthesis-layer
        variance, which is why the end-to-end check below is a tracked
        pass-rate test rather than a hard assert."""
        runs = [
            tuple(c.page_content for c in _guaranteed_lookup_chunks("Allied_Trust_HO3", _mentions_solar, keep=2))
            for _ in range(5)
        ]
        assert all(r == runs[0] for r in runs)


@pytest.mark.retrieval
class TestOptionalCoverageIsNotARestriction:
    """Round 12 priority 7: HOAIC HO3 was bucketed INSUFFICIENT_INFORMATION
    partly because "solar panel treatment needs clarification" -- but its
    ONLY solar text is a coverage-availability row ("Solar Panel Coverage |
    Available on endorsement"). An available optional coverage is not an
    eligibility restriction and raises no question to clarify.

    Pins the source-text fact the prompt rule depends on: HOAIC's solar
    text is availability wording with no restrictive language anywhere.
    Covers two carriers with availability-style wording so this isn't a
    single-carrier patch."""

    @pytest.mark.parametrize("carrier", [
        "HOAIC_-_TX-HOMEOWNERS-0326_HO3",
        "HOAIC_-_DP_Guide_DP3",
    ])
    def test_hoaic_solar_text_is_availability_not_restriction(self, carrier):
        found = _guaranteed_lookup_chunks(carrier, _mentions_solar, keep=2)
        if not found:
            pytest.skip(f"{carrier} has no solar text at all -- nothing to over-trigger on")
        # Scope to the SOLAR lines only. Scanning the whole chunk gives false
        # positives: HOAIC's solar row sits in a large coverage table whose
        # unrelated rows contain words like "excluded" (e.g. "Scheduled
        # Personal Property ... Intentional acts are excluded"), which says
        # nothing about solar.
        solar_lines = [
            line.lower()
            for c in found for line in c.page_content.split("\n")
            if "solar" in line.lower()
        ]
        assert solar_lines, f"{carrier}: solar chunk retrieved but no line mentions solar."
        blob = " ".join(solar_lines)
        assert "available" in blob or "endorsement" in blob, (
            f"{carrier}: expected availability wording ('available'/'endorsement'); got {blob!r}"
        )
        # If any of these ever appear ON A SOLAR LINE, the carrier gained a
        # real solar restriction and the "nothing to clarify" reasoning must
        # be re-examined.
        for restrictive in ("ineligible", "not eligible", "prohibited", "excluded", "unacceptable"):
            assert restrictive not in blob, (
                f"{carrier}: a solar line now contains {restrictive!r} -- it may have gained a "
                f"genuine solar restriction, so treating it as optional-coverage-only is no "
                f"longer safe. Line(s): {blob!r}"
            )


@pytest.mark.retrieval
class TestRoofAgeRuleRetrieval:
    """Round 12 priority 6: Orion's "Roof Material Payment Schedule
    required for the specified roof ages: 16 years and older for
    architectural and composite shingles" appeared in one live run and was
    completely absent from the next. Root-caused by measurement, not
    assumption: the clause lives in FOUR separate chunks, and the roof
    guaranteed-lookup predicate matched NONE of them -- it only recognized
    the phrase "life expectancy", which Orion never uses. So the rule had
    no retrieval guarantee at all and rode entirely on the embedding-rank
    lottery, exactly like PPC/pool/solar did before their guarantees.

    The same measurement showed TWICO and all four Swyfft programs had
    zero coverage too -- which independently explains TWICO going silent
    on roof/tile in a real run earlier this round. Parametrized across
    carriers that phrase the same underlying roof-age rule three different
    ways (payment schedule / RCV-ACV-Excluded age bands / max age), per
    CLAUDE.md's 2+-phrasings requirement."""

    @pytest.mark.parametrize("carrier,must_contain", [
        # "payment schedule" + "years and older" phrasing
        ("Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3", "16 years and older"),
        # RCV / ACV / Excluded age-band table phrasing
        ("TWICO_HO3", "acv"),
        ("Swyfft_-_Lloyds_(Surplus)_HO3", "acv"),
        # the original "life expectancy" phrasing must still work
        ("Allied_Trust_HO3", "life expectancy"),
    ])
    def test_roof_age_rule_is_guaranteed_retrievable(self, carrier, must_contain):
        found = _guaranteed_lookup_chunks(
            carrier, _mentions_roof_life_expectancy, keep=3,
            priority_key=lambda c: "shingle" not in c.page_content.lower(),
        )
        assert found, f"{carrier}: roof-age rule has NO guaranteed-lookup coverage at all."
        blob = " ".join(c.page_content for c in found).lower()
        assert must_contain.lower() in blob, (
            f"{carrier}: expected roof-age rule text ({must_contain!r}) not among the "
            f"{len(found)} guaranteed-lookup chunk(s) -- this rule is back to riding the "
            f"embedding-rank lottery."
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
        # DP3, not HO3, since round 17: a claim about the document's own FPC
        # rows is only meaningful against the record that truly holds them,
        # and Sage_-_Occidental_HO3 holds the DP3 guide (DD-4).
        "Sage_-_Occidental_DP3",
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
        # Occidental checked on its DP3 record since round 17 -- the HO3 record
        # holds the DP3 guide (DD-4), so that is the Occidental text on file.
        for carrier in ["Sage_-_Auros_HO3", "Sage_-_Occidental_DP3", "Sage_-_Wilshire_HO3_-_12.02.2025"]:
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
        matches = _find_carrier(self.by_carrier, substr)
        assert matches, f"No carrier matching {substr!r} in output: {list(self.by_carrier)}"
        return matches[0]

    # test_mercury_roof_exactly_10_years_gets_rcv_not_endorsement was a hard
    # assert here until a 16-run sweep measured it at 75% (6/8) -- another
    # previously-unsuspected flaky assert, found the same way Swyfft/Orion/
    # Allied Trust were. Now tracked: see
    # test_mercury_exactly_10yr_roof_consistency below.

    @pytest.mark.xfail(reason="Foremost county/territory restriction table unflagged since round 3 (backlog, still open as of round 11)")
    def test_foremost_flags_county_restriction(self):
        r = self._find("Foremost")
        blob = " ".join(r.get("missing_info", [])).lower()
        assert "county" in blob

    @pytest.mark.xfail(
        reason="NOT DECIDABLE FROM THE CURRENT INTAKE -- reclassified round 17, not a model "
        "error. CHUBB's two clauses split on dwelling type / unit count (clause 1: <=2-unit "
        "dwelling; clause 2: a house, condo, ...), the intake collects neither, and BOTH make an "
        "owner-occupant eligible. Since 2026-09-28 an individual owner's prompt is main's again "
        "(the guarantee is Trust/LLC only), so clause 2 does not reach this profile at all. This "
        "test presumes single-family. A dwelling-type field is Liam's call.",
        strict=False,
    )
    def test_chubb_cites_correct_eligible_persons_clause(self):
        """Backlog since rounds 9-11. Round 17 root-caused the RETRIEVAL half
        -- clause 2 never reached the prompt, so the model could only cite
        clause 1 (multiple-unit dwellings) for a single-family home. The
        guarantee that fixed it now runs for Trust / LLC only (Liam,
        2026-09-28), so for this individual-owner profile it is main's
        behaviour again; see the xfail reason.

        The old assertion was `"house" in citations`, which could PASS while
        the bug was fully present: CHUBB's clause-1 chunk opens "The term
        dwelling includes individually owned TOWNHOUSE units". This checks
        for clause 2's own distinctive text instead."""
        r = self._find("CHUBB")
        cites = " ".join(r.get("citations", [])).lower()
        assert re.search(r"a house, a condominium unit|owner-occupant or tenant", cites), cites

    @pytest.mark.xfail(
        reason="CONFIRMED ROUND 16, and it is a DATA problem, not a code one. The HO6 and HO3 "
        "records are byte-identical (same sha256 over 27 chunks each) -- the HO6 record holds "
        "the HO3 document, so the correct Condominium Unit-Owners PDF was never ingested. The "
        "only 'condominium' text in either is one row of a Minimum Coverage Requirements table. "
        "Measured 5/20 = 25% over the round 15 STANDARD sweep, and the passes are the model "
        "inferring from the FILENAME -- its own citation reads 'The document title and content "
        "indicate this is a Condominium Unit-Owners Program'. No code change can fix this; it "
        "needs the real HO6 PDF uploaded. See test_no_two_carriers_hold_the_same_document.",
        strict=False,
    )
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
        matches = _find_carrier(self.by_carrier, substr)
        assert matches, f"No carrier matching {substr!r} in output: {list(self.by_carrier)}"
        return matches[0]

    def test_mercury_no_spurious_ppc10_question(self):
        # Round 10 bug (fixed): asked about PPC 10 eligibility for a PPC-1 customer.
        r = self._find("Mercury")
        blob = " ".join(r.get("missing_info", [])).lower()
        assert "ppc 10" not in blob and "ppc-10" not in blob

    # CHANGED DELIBERATELY (Liam, 2026-09-30): this used to assert "not
    # INSUFFICIENT_INFORMATION". ALT has no County, and Auros and Wilshire
    # only write in specific counties, so the correct answer is now
    # INSUFFICIENT_INFORMATION -- held on County, NOT on the FPC table, which
    # is still the thing this test exists to guard. Occidental dropped: it
    # has been a wrong-guide row (GUIDE_UNAVAILABLE) since 2026-09-29, which
    # made this case pass without testing anything.
    @pytest.mark.parametrize("carrier_substr", ["Auros", "Wilshire"])
    def test_sage_family_ppc1_is_eligible_not_insufficient(self, carrier_substr):
        """Round 11: a full read of all six Sage documents' FPC tables
        confirms an FPC-1 risk is eligible under every row -- the
        ineligible row requires FPC>=9, which this customer can never
        reach. Missing distance data only determines which additional
        conditions apply, not whether the risk qualifies.

        xfail REMOVED (round 12): this was marked xfail(strict=False) at a
        measured 1/4 (25%) pass rate, when the fix in place was a prompt
        instruction. The real fix turned out to be structural -- routing
        the deterministic sage_family_fpc_eligibility() result into the
        verdict field (the _apply_structured_overrides wiring gap, where
        the model's own correct FPC conclusion was landing in `notes` and
        going unread). A full 16-run sweep after that fix measured 16/16
        (100%) for all three carriers, so the backlog item this marker
        guarded is resolved and the marker was hiding a real pass. Kept as
        a hard assert deliberately: at 16/16 it is not in the
        "flaky, track the rate" category that Swyfft/Orion/Allied Trust/
        Mercury are in."""
        r = self._find(carrier_substr)
        assert _held_only_on_county(r), (
            f"{carrier_substr}: PPC 1 can never fail the FPC>=9 exclusion clause; with no "
            f"County the only hold is the address rule. Got {r['status']}, "
            f"missing_info={r.get('missing_info')}."
        )


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

    def test_progressive_ho3_surfaces_solar_exclusion(self):
        """xfail REMOVED (round 12): marked xfail(strict=False) back when
        this measured 85% (17/20). A full 16-run sweep now measures 16/16
        (100%), so the marker was hiding a real pass. The rate is still
        tracked continuously by test_progressive_ho3_solar_consistency
        below, which is the right place for the running number -- this
        assert just stops a silent regression from being invisible."""
        r = self._find("Progressive HO3")
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
        matches = _find_carrier(by_carrier, "progressive", "ho3", exclude=("ho6",))
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
    """DD-4 (round 17): NOT HO3 EVIDENCE. Sage_-_Occidental_HO3 holds the
    08/06/2025 revision of Occidental's DWELLING FIRE PROGRAM (DP3) guide, so
    every measurement below -- including the 55% -- is of the DP3 pool rule
    read under an HO3 name in an owner-occupied run. It still guards how the
    pipeline handles the text on file; it says nothing about Occidental's HO3
    program. The pool-fence TEXT claim now lives on the DP3 record (see
    test_pool_spec_matches_each_carriers_own_source_clause).

    Was a hard, unconditional assert (test_sage_occidental_pool_fence_rule_is_found)
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
        matches = _find_carrier(by_carrier, "occidental")
        assert matches, "Occidental: not found in output"
        r = matches[0]
        blob = " ".join(r.get("reasons", []) + r.get("citations", []) + r.get("missing_info", [])).lower()
        outcomes.append("fenc" in blob or "gate" in blob)
    pass_rate = sum(outcomes) / len(outcomes)
    record_property("sage_occidental_pool_fence_pass_rate", pass_rate)
    print(f"\nSage Occidental pool-fence pass rate: {pass_rate:.0%} over {n_runs} runs ({outcomes})"
          f"  [DD-4: DP3 guide on file under the HO3 name -- not HO3 evidence]")
    assert pass_rate > 0.0, (
        f"Sage Occidental's pool-fence rule did not surface in ANY of {n_runs} runs -- "
        f"this has regressed from partial (55% measured over 20 runs) to total failure."
    )


@pytest.mark.baseline
def test_swyfft_lloyds_and_orion_ppc9_consistency(record_property):
    """Round 12: both test_swyfft_lloyds_excluded_for_ppc9 and
    test_orion_ppc9_is_eligible_not_ppc10 were hard, unconditional asserts
    that failed in the SAME pytest run this round -- unrelated to anything
    changed that round (neither carrier's logic was touched). A 5-run
    measurement confirmed both are genuinely flaky, not broken: Swyfft
    Lloyds 80% (4/5 INELIGIBLE, 1/5 INSUFFICIENT_INFORMATION), Orion 40%
    (2/5 ELIGIBLE, 3/5 INSUFFICIENT_INFORMATION) -- they had simply been
    getting lucky on every previous single-run pytest execution. Same
    lesson as Sage Occidental's pool-fence conversion above: a hard assert
    on a genuinely flaky case fails "randomly" in CI in a way that looks
    like a regression but isn't one -- tracked here instead.

    ROUND 13 -- RESOLVED, AND THE "DRIFT" WAS THIS TEST'S OWN BUG.

    Swyfft came back 0/3 here and was written up as an 80% -> 0% product
    regression, complete with a p-value (P(<=0 of 3 | p=.80) = 0.8%). It was
    not a regression. The needle used to find the carrier was "lloyds", and
    round 13's carrier-name normalisation (added to fix "Allied_Trust_HO3"
    vs "allied trust") strips apostrophes -- so "lloyds" started matching
    BOTH Swyfft_-_Lloyds_(Surplus)_HO3 and
    Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5. Sage Trium sorts first, so
    this test was reading SAGE TRIUM's status and reporting it as Swyfft's.
    The older naive substring match had excluded Sage Trium only by accident
    of that apostrophe. See _find_carrier, which now rejects an ambiguous
    needle outright instead of resolving it by dict order.

    Settled with real samples of the same profile rather than n=3:

      Swyfft Lloyds INELIGIBLE   pre-round-13 sweep  16/16 = 100%
                                 fresh sweep, n=25    25/25 = 100%
      Orion         ELIGIBLE     pre-round-13 sweep    4/16 =  25%
                                 fresh sweep, n=25     5/25 =  20%
                                 (the 40% recorded here previously was n=5)

    Orion is the genuinely flaky one and always was; its 1/3 is the single
    most likely outcome at that rate (P(<=1 of 3 | p=.40) = 65%) and must
    never be cited as evidence of regression. Swyfft has been stable at or
    near 100% throughout.

    The lesson worth keeping: a measurement is only as trustworthy as the
    lookup that produced it, and this one produced a confident p-value for a
    regression that never happened. Hence the hard failure in _find_carrier
    -- an ambiguous needle can no longer quietly measure the wrong carrier."""
    n_runs = 3
    swyfft_outcomes = []
    orion_outcomes = []
    for _ in range(n_runs):
        result = check_eligibility(STANDARD_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}
        swyfft = next((r["status"] for r in _find_carrier(by_carrier, "Swyfft Lloyds")), None)
        orion = next((r["status"] for r in _find_carrier(by_carrier, "orion")), None)
        assert swyfft is not None, "Swyfft Lloyds: not found in output"
        assert orion is not None, "Orion: not found in output"
        swyfft_outcomes.append(swyfft == "INELIGIBLE")
        orion_outcomes.append(orion == "ELIGIBLE")
        # PPC 9 is inside Orion's accepted range, so whatever else varies,
        # a DECLINE is never correct here. This is the assertion that
        # actually protects an agent; the rate below is only a tracked
        # number (see the calibration note in the docstring).
        assert orion != "INELIGIBLE", (
            "Orion declined a PPC 9 property. PPC 9 is within its accepted range -- "
            "this is a wrong verdict, not flakiness. (0 of 41 measured runs did this.)"
        )
    swyfft_rate = sum(swyfft_outcomes) / len(swyfft_outcomes)
    orion_rate = sum(orion_outcomes) / len(orion_outcomes)
    record_property("swyfft_lloyds_ppc9_ineligible_pass_rate", swyfft_rate)
    record_property("orion_ppc9_eligible_pass_rate", orion_rate)
    print(f"\nSwyfft Lloyds PPC9-ineligible pass rate: {swyfft_rate:.0%} over {n_runs} runs ({swyfft_outcomes})")
    print(f"Orion PPC9-eligible pass rate: {orion_rate:.0%} over {n_runs} runs ({orion_outcomes})")
    assert swyfft_rate > 0.0, (
        "Swyfft Lloyds' PPC9 exclusion did not hold in ANY run -- measured 25/25 and 16/16 "
        "across two sweeps, so 0/3 is not flakiness. Check the carrier lookup first: this "
        "exact symptom was once an ambiguous test needle, not a product change."
    )
    # NOT asserting orion_rate > 0.0. Orion's real rate is 20% (5/25), so at
    # n_runs=3 that guard fails P(0 of 3 | p=.20) = 51% of the time -- it
    # would be a coin flip dressed up as a regression detector, which is the
    # exact failure this file keeps rediscovering. The meaningful check
    # (never INELIGIBLE) is asserted per-run above; the rate is recorded.


@pytest.mark.baseline
@pytest.mark.xfail(
    reason="MEASURED 0% on STANDARD across 41 runs (0/16 pre-round-13, 0/25 fresh) -- the "
    "'regressed from 60%' premise came from a stale n=5 sample. Not a regression and not "
    "verdict-changing on this profile (home age 17 is UNDER the borrowed 0-20 cap, so the "
    "clause reads as corroboration; status was INSUFFICIENT_INFORMATION in 25/25). The same "
    "carrier measured 0/20 misattributed citations on COASTAL, where the clause WOULD be "
    "adverse. Tracked, not silently green. "
    "ROUND 15 MEASUREMENT (n=20, the sweep the round 14 XPASS asked for): 5/20 = 25% CLEAN, "
    "up from 0/41 pooled before round 14. That improvement is real -- P(>=5 clean in 20 | the "
    "old rate's 95% upper bound of 7%) = 1.1e-02 -- and the likely cause is round 14's "
    "authoritative-input rule, which forbids carrying a property fact in from another "
    "carrier's document. But 25% clean is NOT clean, so this STAYS xfail: the round 14 3/3 "
    "XPASS was luck sitting on top of a genuine partial improvement, which is exactly the "
    "trap this file keeps rediscovering. The contamination also CHANGED SHAPE: it was 25/25 "
    "citation-level before, and is now 5 citation / 10 prose / 5 clean -- so the citation "
    "form dropped sharply while a prose form took its place. Do not convert to a hard assert "
    "until a sweep shows it actually clean.",
    strict=False,
)
def test_ari_hoa_plus_no_age_cap_contamination_consistency(record_property):
    """Round 12's audit found ARI (HOA+) had stopped borrowing ARI (HOB)'s
    age-cap citation ("Homes 0-20 years old are eligible...") in a single
    observed run -- but a dedicated 5-run measurement (see
    experiment_round12_investigation.py) found it actually recurs 40% of
    the time (2/5), with one of those two producing an outright wrong
    INELIGIBLE verdict. The model sometimes even correctly labels the
    citation as belonging to "ARI (HOB)" in its own citations list while
    still applying it to HOA+'s eligibility -- confirmed this is cross-
    carrier bleed-through in a large combined completion (the same
    documented failure shape as the Sage family's "Classification A/B/C"
    contamination), not a retrieval bug: ARI (HOA+)'s own chunks never
    contain this text (see TestAriCrossContaminationRetrieval). Tracked
    here rather than asserted as resolved from one clean run.

    ROUND 13 -- NOT A REGRESSION. THIS ASSERT'S PREMISE WAS WRONG.

    The failure message below says this "regressed from partial (60%
    measured over 5 runs) to total failure". It never was partial. Measured
    on the STANDARD profile:

        pre-round-13 sweep (Aug 20, n=16)   0/16 clean =  0%
        fresh sweep, this commit (n=25)     0/25 clean =  0%

    So the contamination has been at 100% on this profile the entire time,
    across 41 measured runs, and the 60% figure came from an n=5 sample that
    the much larger sweep sitting in the same directory already contradicted.
    An earlier round 13 write-up called this drift on the strength of a
    pooled 0/6 versus that stale 60% -- comparing against the wrong baseline.
    Always check for an existing sweep before trusting a recorded rate.

    A `pass_rate > 0.0` assert on a metric that is flatly 0% is not a
    regression detector; it is a test that can never pass, duplicating the
    xfail in test_ari_hoa_plus_does_not_quote_hob_age_cap. Marked xfail so it
    stays named and visible per CLAUDE.md rather than sitting permanently red.

    Where it MATTERS, the round 12/13 work did land. STANDARD's home is 17
    years old, so HOB's "Homes 0-20 years old are eligible" clause reads as
    SUPPORTING eligibility -- the model quotes it as corroboration and it
    cannot flip a verdict (status was INSUFFICIENT_INFORMATION in 25/25).
    On COASTAL, where home age 22 makes the same clause ADVERSE, the round
    13 A/B measured this carrier at 0/20 misattributed citations post-fix
    (see verification/analyze_coastal_ab.py). Same borrowed text, opposite
    rhetorical use, opposite outcome -- which is why a rate measured on one
    profile says almost nothing about another."""
    n_runs = 3
    outcomes = []
    for _ in range(n_runs):
        result = check_eligibility(STANDARD_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}
        matches = _find_carrier(by_carrier, "ARI HOA+")
        assert matches, "ARI (HOA+): not found in output"
        r = matches[0]
        blob = " ".join(
            r.get("reasons", []) + r.get("citations", []) + r.get("missing_info", []) + [r.get("notes", "")]
        ).lower()
        contaminated = "0-20 years" in blob or "hoa plus" in blob or "hoa/hoa" in blob
        outcomes.append(not contaminated)
    pass_rate = sum(outcomes) / len(outcomes)
    record_property("ari_hoa_plus_no_contamination_pass_rate", pass_rate)
    print(f"\nARI (HOA+) no-contamination pass rate: {pass_rate:.0%} over {n_runs} runs ({outcomes})")
    assert pass_rate > 0.0, (
        f"ARI (HOA+) borrowed ARI (HOB)'s age-cap citation in EVERY run -- "
        f"this has regressed from partial (60% measured over 5 runs) to total failure."
    )


@pytest.mark.baseline
@pytest.mark.xfail(
    reason="BACKLOG (round 12, open): the citation-attribution validator only catches "
    "cross-carrier bleed that carries a carrier LABEL. Prose-only bleed -- another "
    "carrier's terminology written into reasons/notes with no citation to attribute -- "
    "is NOT covered, and is exactly the shape of the historical Sage 'Classification "
    "A/B/C' issue. Covered today only by a prompt instruction and a retrieval-level "
    "guard, both weaker than a mechanical check. Logged so 'cross-carrier contamination' "
    "is never treated as fully solved by the P1 validator alone.",
    strict=False,
)
def test_prose_only_cross_carrier_bleed_is_absent():
    """End-to-end counterpart to
    TestCitationAttributionValidator::test_DOCUMENTED_LIMITATION_prose_only_bleed_is_not_caught.
    Asserts no Sage-family carrier's prose borrows a sibling's
    'Classification A/B/C' terminology (which exists only in
    Trium/SURE/SafePort's own documents)."""
    result = check_eligibility(ALT_PROFILE)
    by_carrier = {r["carrier"]: r for r in result}
    # Occidental's prose here is generated from the DP3 guide filed under the
    # HO3 name (DD-4): a clean result for it is not evidence about HO3.
    for target in ["Auros", "Occidental", "Wilshire"]:
        matches = _find_carrier(by_carrier, target)
        assert matches, f"{target}: not found in output"
        r = matches[0]
        prose = " ".join(r.get("reasons", []) + [r.get("notes", "")]).lower()
        assert "classification" not in prose, (
            f"{target}: borrowed 'Classification' terminology from a sibling carrier's "
            f"document in prose (no citation label, so the attribution validator cannot see it)."
        )


@pytest.mark.baseline
def test_allied_trust_mounted_solar_not_declined_consistency(record_property):
    """Round 12 priority 5, end to end: ALT_PROFILE is exactly the failing
    scenario (mounted PV panels on a Composition Shingle roof). Allied
    Trust must not be declined over its integrated-solar-roofing exclusion
    ("solar roof system" / "solar panel tiles"), which cannot apply to a
    conventional roof covering. Tracked as a pass rate rather than a hard
    assert because the same input produced two different live behaviors --
    and retrieval was proven deterministic across those runs (see
    TestIntegratedSolarRoofingVsMountedPanels), so the variance is purely
    synthesis-layer."""
    n_runs = 3
    outcomes = []
    for _ in range(n_runs):
        result = check_eligibility(ALT_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}
        matches = _find_carrier(by_carrier, "allied trust")
        assert matches, "Allied Trust: not found in output"
        r = matches[0]
        declined_over_solar = (
            r.get("status") == "INELIGIBLE"
            and "solar" in " ".join(r.get("reasons", []) + r.get("citations", [])).lower()
        )
        outcomes.append(not declined_over_solar)
    pass_rate = sum(outcomes) / len(outcomes)
    record_property("allied_trust_mounted_solar_not_declined_pass_rate", pass_rate)
    print(f"\nAllied Trust mounted-solar-not-declined pass rate: {pass_rate:.0%} over {n_runs} runs ({outcomes})")
    assert pass_rate > 0.0, (
        "Allied Trust was declined over its integrated-solar-roofing exclusion in EVERY run -- "
        "the mounted-panel vs. solar-roofing distinction is not being applied at all."
    )


@pytest.mark.baseline
def test_mercury_exactly_10yr_roof_consistency(record_property):
    """Mercury's source says "older than 10 years old" -- exclusive, so a
    roof at exactly 10 keeps RCV and the carrier stays ELIGIBLE. Was a hard
    assert until a 16-run sweep measured it at 75% (6/8): a fourth
    previously-unsuspected flaky assert, none of which were found by
    suspicion -- all four surfaced only because the whole baseline tier was
    swept. Treat any remaining un-swept hard assert as unmeasured, not
    reliable.

    ROUND 13 -- re-measured, stable, still genuinely flaky:
        pre-round-13 sweep (n=16)  10/16 = 62% ELIGIBLE
        fresh sweep      (n=25)    13/25 = 52% ELIGIBLE
    A 0/3 here (which happened this round) is P(0 of 3 | p=.52) ~ 11%, i.e.
    ordinary bad luck at a known-flaky rate, NOT drift. The n=3 loop is too
    small to distinguish those; read the sweep before calling it either way."""
    n_runs = 3
    outcomes = []
    for _ in range(n_runs):
        result = check_eligibility(STANDARD_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}
        matches = _find_carrier(by_carrier, "mercury")
        assert matches, "Mercury: not found in output"
        r = matches[0]

        # THE ACTUAL SUBJECT OF THIS TEST. mercury_roof_eligibility() reads
        # the boundary deterministically and its conclusion is written to
        # notes on every run (measured 25/25 in the round 13 sweep), so
        # assert that directly instead of inferring it from overall status.
        assert "within the standard" in r.get("notes", "").lower(), (
            f"Mercury's deterministic roof-boundary note is missing -- the structured "
            f"check either did not run or no longer reads 'older than 10 years' as "
            f"exclusive. notes={r.get('notes')!r}"
        )
        assert r.get("status") != "INELIGIBLE", (
            "Mercury declined a 10-year roof. 'Older than 10 years' is exclusive, so a "
            "roof at exactly 10 keeps RCV -- this would be the boundary read as inclusive. "
            "(0 of 41 measured runs did this.)"
        )
        outcomes.append(r["status"] == "ELIGIBLE")

    pass_rate = sum(outcomes) / len(outcomes)
    record_property("mercury_exactly_10yr_roof_pass_rate", pass_rate)
    print(f"\nMercury exactly-10yr-roof ELIGIBLE pass rate: {pass_rate:.0%} over {n_runs} runs ({outcomes})")
    # NOT asserting pass_rate > 0.0. Mercury's real ELIGIBLE rate is 52%
    # (13/25), so that guard fails P(0 of 3 | p=.52) ~ 11% of runs -- and it
    # failed twice in one evening on exactly that. Worse, it was measuring
    # the wrong thing: all 12 non-ELIGIBLE runs in the sweep were held on a
    # POOL question, none mentioned the roof at all. The roof boundary is
    # asserted directly above; the rate stays as a tracked number.


@pytest.mark.baseline
@pytest.mark.xfail(
    reason="BACKLOG (round 12, open -- MEASURED, do not treat as solved): ARI (HOA+) still "
    "quotes ARI (HOB)'s age-cap rule in 7/8 STANDARD sweep runs. The P1 attribution "
    "validator FIRED in 0/8 because the model labels the borrowed citation with HOA+'s OWN "
    "name ('ARI_(HOA+): Homes 0-20 years old...') rather than HOB's -- no foreign label to "
    "detect. It targets a real but different variant (correctly-labeled-as-foreign, seen in "
    "earlier captures); a content-based check is what's actually needed. "
    "IMPORTANT -- HOME AGE DETERMINES WHETHER THIS BUG CAN EVEN MANIFEST: the borrowed rule "
    "is 'Homes 0-20 years old are eligible', so a home UNDER 20 satisfies it and the "
    "contamination cannot flip the verdict. STANDARD is age 17 (under) -- its 8/8 "
    "verdict-correct result measures a case where the bug is structurally unable to appear "
    "and must NOT be read as evidence of safety. Profiles that actually exercise it: "
    "COASTAL_PPC4 age 22 (pre-fix: 1/5 wrongly INELIGIBLE) and ALT age 32 (post-fix: 0/12 "
    "wrong verdicts AND 0/12 any contamination text -- encouraging, and again with the "
    "validator firing 0/12, so any gain is from the prompt rule, not the validator). "
    "Next step: re-measure COASTAL_PPC4 post-fix for a clean same-profile before/after.",
    strict=False,
)
def test_ari_hoa_plus_does_not_quote_hob_age_cap():
    result = check_eligibility(STANDARD_PROFILE)
    by_carrier = {r["carrier"]: r for r in result}
    matches = _find_carrier(by_carrier, "ARI HOA+")
    assert matches, "ARI (HOA+): not found in output"
    text = " ".join(
        matches[0].get("reasons", []) + matches[0].get("citations", [])
        + matches[0].get("missing_info", []) + [matches[0].get("notes", "")]
    ).lower()
    assert "0-20 years" not in text and "hoa/hoa" not in text


@pytest.mark.baseline
def test_allied_trust_14yr_roof_consistency(record_property):
    """Round 12: this was a hard, unconditional assert
    (21yr total life expectancy - 14yr age = 7yr remaining, vs 15.75yr
    required -- should fail the 3/4-remaining-life threshold) that failed
    in the same full-suite run as the Swyfft/Orion flakiness discovery,
    with a genuinely wrong ELIGIBLE verdict (not a JSON parse crash this
    time). Unrelated to anything changed this round -- Allied Trust's
    roof-life-expectancy logic wasn't touched. Converted to the same
    tracked pattern rather than left as a hard assert that fails
    unpredictably alongside the other newly-discovered flaky cases."""
    n_runs = 3
    outcomes = []
    for _ in range(n_runs):
        result = check_eligibility(ALT_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}
        matches = _find_carrier(by_carrier, "allied trust")
        assert matches, "Allied Trust: not found in output"
        outcomes.append(matches[0]["status"] != "ELIGIBLE")
    pass_rate = sum(outcomes) / len(outcomes)
    record_property("allied_trust_14yr_roof_correct_pass_rate", pass_rate)
    print(f"\nAllied Trust 14yr-roof correct-verdict pass rate: {pass_rate:.0%} over {n_runs} runs ({outcomes})")
    assert pass_rate > 0.0, (
        f"Allied Trust's 14yr roof passed as clean ELIGIBLE in EVERY run -- "
        f"the 3/4-remaining-life-expectancy rule is not being applied at all."
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
    # CHANGED DELIBERATELY (Liam, 2026-09-30): the outcome is "not held on
    # the FPC table" -- since the County hold, a County-only hold is the
    # correct answer for ALT (no County). Occidental dropped: a wrong-guide
    # row since 2026-09-29.
    target_carriers = ["Auros", "Wilshire"]
    per_carrier_outcomes = {c: [] for c in target_carriers}
    for _ in range(n_runs):
        result = check_eligibility(ALT_PROFILE)
        by_carrier = {r["carrier"]: r for r in result}
        for target in target_carriers:
            matches = _find_carrier(by_carrier, target)
            assert matches, f"{target}: not found in output"
            per_carrier_outcomes[target].append(_held_only_on_county(matches[0]))
    for carrier, outcomes in per_carrier_outcomes.items():
        rate = sum(outcomes) / len(outcomes)
        record_property(f"sage_{carrier.lower()}_ppc1_pass_rate", rate)
        print(f"\nSage {carrier} PPC-1 eligible-not-insufficient pass rate: {rate:.0%} over {n_runs} runs ({outcomes})")
    # Not a hard gate at any particular threshold yet -- this test's job is
    # to keep the real number visible on every run, not to silently pass or
    # fail. If it's reliably 0% going forward, that's a stronger signal to
    # invest in a structural fix (e.g. a dedicated per-branch check) rather
    # than another prompt instruction.


@pytest.mark.baseline
class TestBaselineCoastalPPC4Profile:
    """Round 12's audit profile: PPC 4, Tier 3 coastal, 2004-built (22yr),
    16yr Tile roof, Frame construction, Copper plumbing, no pool, no solar.
    A third, genuinely different profile (mid-range PPC, coastal, tile
    roof, copper plumbing) checking round 12's fixes hold outside the two
    profiles every prior round reused."""

    @classmethod
    def setup_class(cls):
        cls.result = check_eligibility(COASTAL_PPC4_PROFILE)
        cls.by_carrier = {r["carrier"]: r for r in cls.result}

    def _find(self, substr):
        matches = _find_carrier(self.by_carrier, substr)
        assert matches, f"No carrier matching {substr!r} in output: {list(self.by_carrier)}"
        return matches[0]

    def test_liberty_mutual_ho3_ppc4_no_spurious_fire_department_distance_question(self):
        """PPC 4 never reaches Liberty Mutual's Protection-Class-9/10-conditioned
        fire-department-distance rule, so it must not become an open QUESTION
        or an adverse ground for this profile.

        CHANGED (round 13): this used to forbid the phrase "15 miles"
        anywhere in reasons at all, and failed on a run whose reasons said

            "the carrier's guidelines for PPC 9 and 10 state specific
             requirements (dwelling within 15 miles of fire department...),
             but these conditions do not apply to PPC 4"

        which is the model explaining, correctly, why the rule is
        inapplicable. That is the SAME behavior round 13's P4 work went out
        of its way to ADD for solar -- an explicit dismissal is more useful
        to an agent than silence, and silence is what an auditor cannot tell
        apart from a retrieval miss. The assertion now targets the actual
        defect: the rule appearing as a missing_info question, or driving an
        adverse verdict.
        """
        r = self._find("Liberty Mutual HO3")

        missing = " ".join(r.get("missing_info", [])).lower()
        assert "15 miles" not in missing and "fire department" not in missing, (
            f"PPC 4 cannot reach the PPC-9/10 fire-department-distance rule, so it must "
            f"not be raised as something still to confirm. missing_info={r.get('missing_info')}"
        )

        reasons = " ".join(r.get("reasons", [])).lower()
        mentions_rule = "15 miles" in reasons or "fire department" in reasons
        if mentions_rule:
            # Mentioning it is fine ONLY as a dismissal.
            dismissed = any(
                k in reasons for k in
                ("do not apply", "does not apply", "not applicable", "only applies",
                 "apply to ppc 9", "n/a", "is eligible")
            )
            assert dismissed, (
                f"Liberty Mutual raised the PPC-9/10 fire-department-distance rule without "
                f"stating that it does not apply to PPC 4. reasons={r.get('reasons')}"
            )
            assert r.get("status") != "INELIGIBLE", (
                "the PPC-9/10 distance rule cannot make a PPC 4 property ineligible"
            )

    def test_allied_trust_ppc4_no_spurious_ppc10_age_exception_question(self):
        """PPC 4 never reaches Allied Trust's Protection-Class-10-conditioned
        3-year-age exception, so it must not become an open QUESTION or an
        adverse ground here.

        CHANGED (round 13): this forbade the phrase anywhere in reasons and
        failed once on a run that mentioned the rule while working through
        why it does not apply. Same narrowing as
        test_liberty_mutual_ho3_ppc4_no_spurious_fire_department_distance_question
        above, and for the same reason: an explicit dismissal is more useful
        to an agent than silence.

        Measured rarity, so the old form was an un-swept flaky hard assert:
        the phrase appeared in 0/20 COASTAL sweep runs and 0/4 further runs
        on this commit -- roughly 1 occurrence in 25. The failing run's exact
        wording was truncated in the pytest output and never reproduced, so
        whether that one was a dismissal or a genuine spurious question is
        unconfirmed; the assertion below would catch the latter."""
        r = self._find("Allied Trust")
        needles = ("protection class 10", "ppc 10", "ppc10")

        missing = " ".join(r.get("missing_info", [])).lower()
        assert not any(k in missing for k in needles), (
            f"PPC 4 cannot reach the PPC-10 age exception, so it must not be raised as "
            f"something still to confirm. missing_info={r.get('missing_info')}"
        )

        reasons = " ".join(r.get("reasons", [])).lower()
        if any(k in reasons for k in needles):
            dismissed = any(
                k in reasons for k in
                ("do not apply", "does not apply", "not applicable", "only applies",
                 "n/a", "is eligible", "1 - 9", "1-9")
            )
            assert dismissed, (
                f"Allied Trust raised the PPC-10 age exception without stating it does not "
                f"apply to PPC 4. reasons={r.get('reasons')}"
            )
            assert r.get("status") != "INELIGIBLE", (
                "the PPC-10 age exception cannot make a PPC 4 property ineligible"
            )

    def test_bucket_verdict_labels_are_not_swapped(self):
        # Live confirmation of the same invariant TestBucketAssignment
        # checks with synthetic data (rounds 9-11's bucket/label mismatch),
        # against a real profile's real output.
        buckets = assign_buckets(self.result)
        assert all(r["status"] == "INELIGIBLE" for r in buckets["not_eligible"])
        assert all(r["status"] == "INSUFFICIENT_INFORMATION" for r in buckets["insufficient_info"])
        assert all(
            (r["status"] == "INELIGIBLE" and r.get("flaw_count", 0) == 1) or r["status"] == "REFER"
            for r in buckets["one_issue"]
        )

    def test_twico_mentions_roof_or_tile_at_all(self):
        r = self._find("TWICO")
        blob = " ".join(r.get("reasons", []) + r.get("citations", []) + [r.get("notes", "")]).lower()
        assert "roof" in blob or "tile" in blob, (
            "TWICO's response must not be silently blank on roof/tile -- the round 12 "
            "regression was twico_roof_settlement() being gated out of production entirely "
            "rather than scoped to just the ambiguous Composition-Shingle case."
        )

    @pytest.mark.xfail(
        reason="Round 12: unconfirmed either way whether Coastal Tier 3 should trigger "
        "Progressive HO3's wind-pool-zone/base-flood-elevation provisions -- this tool has no "
        "ground-truth mapping from its own Tier 1/2/3 scheme to Progressive's geographic "
        "definitions. build_risk_factors() now widens the retrieval trigger to include Tier 3 "
        "(see TestCoastalTierRiskFactors), but retrieval firing doesn't guarantee the model's "
        "final synthesis actually surfaces it -- tracked here rather than asserted as resolved.",
        strict=False,
    )
    def test_progressive_ho3_surfaces_wind_pool_or_flood_elevation_for_tier_3(self):
        r = self._find("Progressive HO3")
        blob = " ".join(
            r.get("reasons", []) + r.get("citations", []) + r.get("missing_info", []) + [r.get("notes", "")]
        ).lower()
        assert "wind pool" in blob or "flood elevation" in blob or "base flood" in blob


# ---------------------------------------------------------------------------
# ROUND 13 -- P2: a structured check that reports genuine AMBIGUITY must
# reach the STATUS field, not just the prose.
#
# Audit finding: TWICO_HO3's notes said, correctly, "at 21 years, 3-tab
# resolves to EXCLUDED and architectural resolves to ACV. Any single bracket
# stated above without that confirmation is an assumption, not a
# determination" -- while its status was a flat INELIGIBLE. Same shape as
# round 12's Sage FPC wiring gap: the override computed the right answer and
# then never wired it to the field an agent acts on.
# ---------------------------------------------------------------------------

def _twico_result(status="INELIGIBLE", reasons=None, flaw_count=1, notes=""):
    return {
        "carrier": "TWICO_HO3",
        "status": status,
        "reasons": reasons if reasons is not None else [
            "Roof age 21 years exceeds TWICO's 20-year composition shingle band -- "
            "roof coverage is excluded."
        ],
        "citations": [],
        "missing_info": [],
        "notes": notes,
        "flaw_count": flaw_count,
    }


@pytest.mark.retrieval
class TestRound13AmbiguityReachesStatus:
    """Pure logic -- no retrieval, no LLM."""

    def test_twico_21yr_composition_shingle_is_not_confident_ineligible(self):
        """The EXACT scenario from the round 13 audit, not a simplified
        version: composition shingle, sub-type unspecified, age 21 -- the
        age where TWICO's two sub-type bands genuinely disagree (3-tab is
        EXCLUDED, architectural is ACV)."""
        profile = dict(AUDIT_R13_PROFILE)
        assert profile["roof_age"] == 21 and profile["roof_type"] == "Composition Shingle"
        # Sanity-check the premise itself rather than trusting the audit note.
        assert twico_roof_settlement("Composition (3-tab)", 21)[0] == "EXCLUDED"
        assert twico_roof_settlement("Composition (Architectural)", 21)[0] == "ACV"

        result = _twico_result()
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)

        assert result["status"] != "INELIGIBLE", (
            "TWICO committed to the pessimistic branch of an ambiguity its own notes "
            "field had just described as 'an assumption, not a determination'."
        )
        assert result["status"] == "INSUFFICIENT_INFORMATION"
        assert result["flaw_count"] == 0

    @pytest.mark.parametrize("roof_type", [
        "Composition Shingle",
        "Composite Shingle",
        "asphalt shingle",
    ])
    def test_ambiguity_hold_generalizes_across_roofing_terminology(self, roof_type):
        """CLAUDE.md rule 2: a general rule needs more than the one phrasing
        that happened to appear in the bug report. These three name the SAME
        roofing family per SYSTEM_INSTRUCTIONS' ROOFING MATERIAL TERMINOLOGY
        rule. Before round 13 only the literal word "composition" was
        recognized -- "Composite Shingle" and "asphalt shingle" fell through
        to twico_roof_settlement()'s generic "not found in this table"
        branch, so the P2 hold would not have fired for them at all."""
        profile = dict(AUDIT_R13_PROFILE, roof_type=roof_type)
        result = _twico_result(reasons=[f"Roof age 21 exceeds TWICO's band for {roof_type}."])
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        assert result["status"] == "INSUFFICIENT_INFORMATION", (
            f"{roof_type!r} is the same roofing family as 'Composition Shingle' and must "
            f"be held for sub-type confirmation identically."
        )

    def test_ambiguity_hold_at_a_second_divergent_age(self):
        """A different age band with a different pair of divergent outcomes
        (at 12 years: 3-tab -> ACV, architectural -> RCV), so this can't pass
        by hard-coding anything about age 21 or about EXCLUDED specifically."""
        assert twico_roof_settlement("Composition (3-tab)", 12)[0] == "ACV"
        assert twico_roof_settlement("Composition (Architectural)", 12)[0] == "RCV"
        profile = dict(AUDIT_R13_PROFILE, roof_age=12)
        result = _twico_result(reasons=["Roof age 12 puts settlement on an ACV basis."])
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        assert result["status"] == "INSUFFICIENT_INFORMATION"

    @pytest.mark.parametrize("roof_type,age", [
        ("Architectural Shingle", 21),   # sub-type stated -> decidable (ACV)
        ("3-tab shingle", 21),           # sub-type stated -> decidable (EXCLUDED)
        ("Tile", 21),                    # unambiguous material -> decidable (RCV)
    ])
    def test_subtype_qualified_roof_stays_decidable(self, roof_type, age):
        """The hold must fire ONLY on genuine ambiguity. A roof type that
        names its sub-type resolves cleanly, and its verdict must stand --
        otherwise this "fix" would just suppress every TWICO determination."""
        profile = dict(AUDIT_R13_PROFILE, roof_type=roof_type, roof_age=age)
        result = _twico_result(reasons=[f"Roof age {age} for {roof_type}."])
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        assert result["status"] == "INELIGIBLE"

    @pytest.mark.parametrize("age", [8, 30])
    def test_agreeing_subtypes_do_not_trigger_a_hold(self, age):
        """At 8 years BOTH sub-types resolve to RCV; at 30 BOTH resolve to
        EXCLUDED. The fact is still unconfirmed, but it changes nothing, so
        there is nothing to hold for -- the same principle as
        SYSTEM_INSTRUCTIONS' "do not downgrade when every applicable branch
        agrees" rule."""
        three_tab = twico_roof_settlement("Composition (3-tab)", age)[0]
        architectural = twico_roof_settlement("Composition (Architectural)", age)[0]
        assert three_tab == architectural, "premise: the two sub-types agree at this age"
        profile = dict(AUDIT_R13_PROFILE, roof_age=age)
        result = _twico_result(reasons=[f"Roof age {age}."])
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        assert result["status"] == "INELIGIBLE"

    def test_ineligible_on_an_independent_ground_is_not_downgraded(self):
        """TWICO also flatly excludes homes with solar panels. An INELIGIBLE
        resting on THAT must survive untouched -- the roof sub-type being
        unconfirmed says nothing about it.

        This case caught a real defect in the first draft of the fix: the
        relevance check read `notes` live, by which point the override had
        already written its own "3-tab vs architectural" caveat there, so
        the check matched text it had just written itself and downgraded a
        verdict whose only ground was solar."""
        profile = dict(AUDIT_R13_PROFILE)
        result = _twico_result(reasons=["TWICO excludes homes with solar panels."])
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        assert result["status"] == "INELIGIBLE", (
            "an adverse verdict the model grounded in solar, not roof, was downgraded by "
            "the roof-ambiguity hold"
        )

    def test_multi_flaw_ineligible_stands_but_records_the_caveat(self):
        """flaw_count > 1 means other independent grounds exist, so the
        verdict does not rest solely on the unresolved fact."""
        profile = dict(AUDIT_R13_PROFILE)
        result = _twico_result(
            reasons=["Roof age 21 exceeds the composition band.", "TWICO excludes solar panels."],
            flaw_count=2,
        )
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        assert result["status"] == "INELIGIBLE"
        assert "independent grounds" in result["notes"].lower(), (
            "the caveat must still be recorded even when the status stands"
        )

    def test_material_absent_from_the_table_gets_no_fictional_subtype_caveat(self):
        """twico_roof_settlement() also returns INSUFFICIENT_INFORMATION for
        a material simply not in TWICO's table. Before round 13 the sub-type
        comparison ran unconditionally, so such a roof got a confident and
        entirely invented "at 21 years, 3-tab resolves to EXCLUDED and
        architectural resolves to ACV" note attached to it."""
        profile = dict(AUDIT_R13_PROFILE, roof_type="Foam")
        result = _twico_result(status="INSUFFICIENT_INFORMATION", flaw_count=0,
                               reasons=["Roof material not addressed by this carrier."])
        _apply_structured_overrides([result], ["TWICO_HO3"], profile)
        assert "3-tab" not in result["notes"], result["notes"]
        assert "does not appear in" in result["notes"]

    # -- same helper, a different carrier and a different topic ------------

    def test_sage_fpc9_unresolved_distance_is_not_confident_ineligible(self):
        """The identical wiring gap on the Sage FPC branch: FPC 9+ is
        ELIGIBLE within 5 driving miles of the fire station and INELIGIBLE
        beyond it, and the intake collects no distance. A second carrier and
        a second topic going through the same shared helper -- this is what
        makes the round 13 fix a general rule rather than a TWICO patch."""
        assert sage_family_fpc_eligibility("9")[0] == "INSUFFICIENT_INFORMATION"
        profile = dict(STANDARD_PROFILE, ppc="9")
        result = {
            "carrier": "Sage - Auros HO3", "status": "INELIGIBLE",
            "reasons": ["FPC 9 is ineligible under this carrier's fire protection class table."],
            "citations": [], "missing_info": [], "notes": "", "flaw_count": 1,
        }
        _apply_structured_overrides([result], ["Sage_-_Auros_HO3"], profile)
        assert result["status"] == "INSUFFICIENT_INFORMATION"
        assert result["flaw_count"] == 0

    def test_sage_fpc9_ineligible_on_an_independent_ground_stands(self):
        profile = dict(STANDARD_PROFILE, ppc="9")
        result = {
            "carrier": "Sage - Auros HO3", "status": "INELIGIBLE",
            "reasons": ["The dwelling exceeds this carrier's maximum acreage."],
            "citations": [], "missing_info": [], "notes": "", "flaw_count": 1,
        }
        _apply_structured_overrides([result], ["Sage_-_Auros_HO3"], profile)
        assert result["status"] == "INELIGIBLE"

    def test_sage_fpc_that_resolves_is_untouched(self):
        """PPC 4 resolves to ELIGIBLE for every applicable row, so there is
        no ambiguity to hold for."""
        assert sage_family_fpc_eligibility("4")[0] == "ELIGIBLE"
        profile = dict(STANDARD_PROFILE, ppc="4")
        result = {
            "carrier": "Sage - Auros HO3", "status": "ELIGIBLE",
            "reasons": ["FPC 4 is acceptable."], "citations": [],
            "missing_info": [], "notes": "", "flaw_count": 0,
        }
        _apply_structured_overrides([result], ["Sage_-_Auros_HO3"], profile)
        assert result["status"] == "ELIGIBLE"


# ---------------------------------------------------------------------------
# ROUND 13 -- P3: a carrier may not assert that a SPECIFIC pool requirement
# is met when the intake only says "In Ground - Fenced".
#
# Audit finding: ARI (HOA+)'s rule is "a 6' high fence with locked or self
# locking gates"; its Analysis said the property "meets the requirement".
# Nothing in the intake confirms a height or a gate type.
#
# Not ARI-specific: twenty owner-occupied carriers state a specific fence
# height and/or gate mechanism (18 a height, 18 a gate). The corpus holds
# exactly TWO heights: ARI (HOA+) and ARI (HOB) at 6', every other
# height-stating carrier at 4'.
# ---------------------------------------------------------------------------

def _real_pool_spec(carrier):
    """Build the spec the way production does -- same guaranteed lookup, same
    extractor -- rather than hand-feeding the test a string."""
    vs = get_vectorstore()
    found = guaranteed_carrier_lookup(
        vs._collection, carrier, predicate=_mentions_pool_rule, keep=3,
        priority_key=lambda c: not (
            "fenc" in c.page_content.lower() or "gate" in c.page_content.lower()
        ),
    )
    spec = {"heights": set(), "gates": set()}
    for chunk in found:
        got = _extract_pool_spec(normalize_chunk_text(chunk.page_content))
        spec["heights"] |= got["heights"]
        spec["gates"] |= got["gates"]
    return spec


@pytest.mark.retrieval
class TestRound13PoolSpecNotAssumedMet:

    def test_ari_hoa_plus_does_not_assume_its_6ft_rule_is_satisfied(self):
        """The exact audit scenario."""
        carrier = "ARI_(HOA+)"
        spec = _real_pool_spec(carrier)
        assert "6" in spec["heights"], (
            f"premise: ARI (HOA+)'s own document states a 6' pool fence. Got {spec}"
        )
        result = {
            "carrier": "ARI (HOA+)", "status": "ELIGIBLE",
            "reasons": ["The in-ground pool is fenced, which meets the requirement."],
            "citations": ["ARI (HOA+): 'a 6' high fence with locked or self locking gates'"],
            "missing_info": [], "notes": "", "flaw_count": 0,
        }
        _enforce_pool_spec_support([result], [carrier], AUDIT_R13_PROFILE, {carrier: spec})

        blob = " ".join(result["missing_info"]).lower()
        assert "pool enclosure specifics" in blob
        assert "fence height" in blob and "6'" in " ".join(result["missing_info"])
        assert "gate mechanism" in blob
        assert "unconfirmed, not satisfied" in result["notes"]

    # Every expected value here was read off the carrier's own source clause
    # (printed and checked by eye), NOT taken from _extract_pool_spec's
    # output -- that circularity is exactly what let a wrong Foremost figure
    # be reported as "verified 16/16".
    @pytest.mark.parametrize("carrier,expected_height,source_phrase", [
        ("ARI_(HOA+)", "6", "6' high fence"),
        ("ARI_(HOB)", "6", "6' high fence"),
        # The DP3 record since round 17: this clause is the DP3 guide's, and
        # Sage_-_Occidental_HO3 holds that same guide (DD-4).
        ("Sage_-_Occidental_DP3", "4", "minimum height of 4 feet"),
        ("Foremost_DP3_and_HO3_-_07.01.2026", "4", "fence minimum four feet high"),
        ("Sage_-_Markel_HO3", "4", "approved fence (at least four feet high)"),
        ("Allied_Trust_HO3", "4", "fence at least 4-foot-high"),
        ("Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3", "4", "at least a four-foot fence"),
        ("Swyfft_-_Lloyds_(Surplus)_HO3", "4", "4' permanent fence"),
    ])
    def test_pool_spec_matches_each_carriers_own_source_clause(
        self, carrier, expected_height, source_phrase
    ):
        """CLAUDE.md rule 2, and a guard against the cross-carrier number
        borrowing SYSTEM_INSTRUCTIONS already warns about. Also anchors each
        expectation to the literal phrase in the carrier's document, so a
        future extractor change that produces a plausible-but-wrong number
        fails here instead of being confirmed by its own output."""
        text = " ".join(
            normalize_chunk_text(c.page_content).lower()
            for c in _all_chunks(carrier)
        )
        assert source_phrase.lower() in text, (
            f"{carrier}: the source phrase this expectation is anchored to is no longer in "
            f"the document -- re-read the source before changing the expected height."
        )

        spec = _real_pool_spec(carrier)
        assert spec["heights"] == {expected_height}, (
            f"{carrier}: source says {source_phrase!r} -> {expected_height}', "
            f"extractor produced {sorted(spec['heights'])}"
        )

        result = {
            "carrier": carrier, "status": "ELIGIBLE", "reasons": [], "citations": [],
            "missing_info": [], "notes": "", "flaw_count": 0,
        }
        _enforce_pool_spec_support([result], [carrier], AUDIT_R13_PROFILE, {carrier: spec})
        item = " ".join(result["missing_info"])
        assert f"{expected_height}'" in item, item
        for other in {"4", "5", "6"} - {expected_height}:
            assert f"{other}'" not in item, (
                f"{carrier} surfaced another carrier's fence height {other}': {item}"
            )

    def test_no_carrier_in_the_corpus_states_a_5ft_pool_fence(self):
        """Round 13 reported Foremost as the corpus's only 5' carrier. It is
        not: its rule is "a fence minimum four feet high", stated five times.
        The 5 came from "(over 2.5 feet deep)" -- a pool DEPTH threshold that
        a sentence splitter cut at the decimal point, leaving "5 feet deep)"
        to be harvested as a height. Nothing in this corpus is 5'."""
        collection = get_vectorstore()._collection
        offenders = {}
        for carrier in get_carriers_for_occupancy("Owner Occupied"):
            spec = _real_pool_spec(carrier)
            if "5" in spec["heights"]:
                offenders[carrier] = sorted(spec["heights"])
        assert not offenders, (
            f"a 5' pool fence height was extracted for {offenders} -- no carrier in this "
            f"corpus states one; check for a depth figure or another structure's dimension."
        )

    @pytest.mark.parametrize("text,expected,why", [
        ("Properties with pools (over 2.5 feet deep) must have a fence minimum "
         "four feet high (fully enclosing the pool) AND a self-locking gate.",
         {"4"}, "Foremost: decimal depth must not be split into a height"),
        ("Approved fence (at least four feet high). Lockable gate. Pool slide where "
         "the top of the slide is no higher than five feet above the pool deck.",
         {"4"}, "Markel: a slide's height is not the fence's height"),
        ("No swimming pools unless they are adequately fenced. A height of at least "
         "four feet and locking gates are required.",
         {"4"}, "NatGen Premier: the figure sits in the sentence AFTER the pool mention"),
        ("Pool water over 4 feet deep requires a diving board endorsement.",
         set(), "a depth figure alone is not a fence height"),
        ("The dwelling must be within 100 feet of a fire hydrant.",
         set(), "an unrelated distance is not a fence height"),
    ])
    def test_height_extraction_rejects_figures_that_are_not_fence_heights(
        self, text, expected, why
    ):
        """Three real corpus sentences that the first version of
        _extract_pool_spec got wrong, plus two negatives. Every failure mode
        here is the same shape: a number that IS in the pool rule, but
        describes the water, a slide, or something else entirely."""
        assert _extract_pool_spec(text)["heights"] == expected, why

    def test_generic_fence_language_creates_no_pool_question(self):
        """A carrier whose rule only says "fenced", with no height or gate
        menu, is already satisfied by "In Ground - Fenced" -- manufacturing
        a specificity question the document never asks is the opposite bug,
        and SYSTEM_INSTRUCTIONS explicitly forbids it."""
        spec = _extract_pool_spec("Swimming pools must be fenced or otherwise secured.")
        assert not spec["heights"] and not spec["gates"]
        result = {
            "carrier": "Generic HO3", "status": "ELIGIBLE", "reasons": [], "citations": [],
            "missing_info": [], "notes": "", "flaw_count": 0,
        }
        _enforce_pool_spec_support([result], ["Generic HO3"], AUDIT_R13_PROFILE,
                                   {"Generic HO3": spec})
        assert result["missing_info"] == []
        assert result["notes"] == ""

    def test_no_pool_profile_adds_nothing(self):
        carrier = "ARI_(HOA+)"
        result = {
            "carrier": carrier, "status": "ELIGIBLE", "reasons": [], "citations": [],
            "missing_info": [], "notes": "", "flaw_count": 0,
        }
        _enforce_pool_spec_support(
            [result], [carrier], dict(AUDIT_R13_PROFILE, swimming_pool="No Pool"),
            {carrier: _real_pool_spec(carrier)},
        )
        assert result["missing_info"] == [] and result["notes"] == ""

    def test_intake_that_states_the_specifics_adds_nothing(self):
        """The rule is "don't assert what the input doesn't support", not
        "always add a pool caveat" -- if the form ever collects height and
        gate type, the question disappears."""
        carrier = "ARI_(HOA+)"
        profile = dict(AUDIT_R13_PROFILE, swimming_pool="In Ground - 6' fence, self-latching gate")
        assert _intake_states_pool_specifics(profile["swimming_pool"])
        result = {
            "carrier": carrier, "status": "ELIGIBLE", "reasons": [], "citations": [],
            "missing_info": [], "notes": "", "flaw_count": 0,
        }
        _enforce_pool_spec_support([result], [carrier], profile,
                                   {carrier: _real_pool_spec(carrier)})
        assert result["missing_info"] == []

    @pytest.mark.parametrize("text,heights,gates", [
        ("Swimming pools must have a 6' high fence with locked or self locking gates.", {"6"}, True),
        ("Pool must be enclosed by a 4 foot fence with a self-latching gate.", {"4"}, True),
        ("Swimming pool requires a 5 ft fence and self-locking gate.", {"5"}, True),
        # must NOT pick up figures from sentences that aren't about a pool fence
        ("The dwelling must be within 100 feet of a fire hydrant.", set(), False),
        ("Trampolines must be enclosed by a 6 foot fence.", set(), False),
    ])
    def test_pool_spec_extractor_is_scoped_to_pool_enclosure_sentences(self, text, heights, gates):
        spec = _extract_pool_spec(text)
        assert spec["heights"] == heights, spec
        assert bool(spec["gates"]) is gates, spec

    # -- the mirror case: a question the document never asks ---------------

    def _mercury_result(self, status, missing_info, flaw_count=0):
        return {
            "carrier": "Mercury_HO3_-_01.01.2026", "status": status, "reasons": [],
            "citations": [], "missing_info": list(missing_info), "notes": "",
            "flaw_count": flaw_count,
        }

    def test_mercury_states_no_specific_pool_requirement(self):
        """Premise check, read off Mercury's own document rather than
        assumed: its ONLY pool language is "unfenced in-ground swimming
        pools" in a hazard list. No height, no gate mechanism -- so
        "In Ground - Fenced" satisfies it outright."""
        spec = _real_pool_spec("Mercury_HO3_-_01.01.2026")
        assert not spec["heights"] and not spec["gates"], (
            f"Mercury now states a specific pool requirement ({spec}) -- if so, a "
            f"fence-height question IS legitimate for it and these tests need revisiting."
        )
        text = " ".join(
            normalize_chunk_text(c.page_content).lower() for c in _all_chunks("Mercury_HO3_-_01.01.2026")
        )
        assert "unfenced in-ground swimming pools" in text

    def test_manufactured_pool_question_is_removed_and_verdict_corrected(self):
        """Round 13, found in the closing sweep and verdict-level.

        Mercury was held at INSUFFICIENT_INFORMATION in 12 of 25 STANDARD
        runs, and in all 12 the sole missing_info item was a pool
        fence/gate question its document never asks -- none of the 12
        mentioned the roof. That moves a carrier out of the Eligible bucket
        ~48% of the time over an invented blocker."""
        carrier = "Mercury_HO3_-_01.01.2026"
        r = self._mercury_result(
            "INSUFFICIENT_INFORMATION",
            ["Swimming pool requirements (fence height, gate mechanism)"],
        )
        _enforce_pool_spec_support([r], [carrier], STANDARD_PROFILE, {})
        assert r["missing_info"] == []
        assert r["status"] == "ELIGIBLE", "the only stated blocker was removed as invalid"
        assert "never states" in r["notes"].lower()

    def test_manufactured_question_removal_leaves_other_blockers_alone(self):
        """The status correction must be narrow: absence of THIS blocker is
        not evidence there was no other."""
        carrier = "Mercury_HO3_-_01.01.2026"
        r = self._mercury_result(
            "INSUFFICIENT_INFORMATION",
            ["Swimming pool fencing requirements", "Year of last electrical update"],
        )
        _enforce_pool_spec_support([r], [carrier], STANDARD_PROFILE, {})
        assert r["missing_info"] == ["Year of last electrical update"]
        assert r["status"] == "INSUFFICIENT_INFORMATION"

    def test_manufactured_question_removal_never_upgrades_a_decline(self):
        carrier = "Mercury_HO3_-_01.01.2026"
        r = self._mercury_result("INELIGIBLE", ["Swimming pool fence height"], flaw_count=1)
        _enforce_pool_spec_support([r], [carrier], STANDARD_PROFILE, {})
        assert r["status"] == "INELIGIBLE"

    def test_carrier_that_does_state_specifics_keeps_its_question(self):
        """ARI states 6' + locking gates, so the question is real and must
        survive -- this is the line between the two halves of the check."""
        carrier = "ARI_(HOA+)"
        spec = _real_pool_spec(carrier)
        r = {
            "carrier": carrier, "status": "INSUFFICIENT_INFORMATION", "reasons": [],
            "citations": [], "missing_info": ["Swimming pool fence height (must be 6 feet)"],
            "notes": "", "flaw_count": 0,
        }
        _enforce_pool_spec_support([r], [carrier], STANDARD_PROFILE, {carrier: spec})
        assert any("fence height" in m.lower() for m in r["missing_info"])
        assert r["status"] == "INSUFFICIENT_INFORMATION"

    @pytest.mark.parametrize("pool_value,should_remove", [
        ("In Ground - Fenced", True),
        ("In Ground - Unfenced", False),   # "unfenced" CONTAINS "fenc"
        ("Above Ground - Not Fenced", False),
        ("No Pool", False),
    ])
    def test_removal_respects_whether_the_intake_says_enclosed(self, pool_value, should_remove):
        """The negation has to be checked before the positive: an earlier
        draft tested `"fenc" in value` and happily stripped the question for
        "In Ground - Unfenced", where it is entirely legitimate."""
        carrier = "Mercury_HO3_-_01.01.2026"
        r = self._mercury_result("INSUFFICIENT_INFORMATION", ["Swimming pool fence height"])
        _enforce_pool_spec_support(
            [r], [carrier], dict(STANDARD_PROFILE, swimming_pool=pool_value), {}
        )
        removed = r["missing_info"] == []
        assert removed is should_remove, (
            f"pool_value={pool_value!r}: removed={removed}, expected {should_remove}"
        )

    @pytest.mark.parametrize("item,expected", [
        ("Swimming pool requirements (fence height, gate mechanism)", True),
        ("Pool fence height", True),
        ("Confirm the pool enclosure barrier", True),
        ("Year of last electrical update", False),
        ("Roof covering material", False),
        ("Distance to the nearest fire hydrant", False),
    ])
    def test_only_pool_specificity_items_are_treated_as_manufactured(self, item, expected):
        assert _is_manufactured_pool_question(item) is expected

    @pytest.mark.xfail(
        reason="Round 13 P3 deferred: the carrier still reports ELIGIBLE while carrying a "
        "missing_info item saying its own specific pool requirement is unconfirmed. Strictly, "
        "SYSTEM_INSTRUCTIONS' status rule 3 (INSUFFICIENT_INFORMATION when a fact required to "
        "reach ELIGIBLE is not known) says that should be INSUFFICIENT_INFORMATION. Not changed "
        "this round because the audit finding was about the Analysis text asserting compliance, "
        "was not flagged verdict-changing, and flipping all sixteen affected carriers is a much "
        "larger behavioral change than the evidence so far supports. Tracked here so it stays "
        "visible instead of living only in a code comment.",
        strict=False,
    )
    def test_unconfirmed_specific_pool_requirement_should_block_eligible(self):
        carrier = "ARI_(HOA+)"
        result = {
            "carrier": carrier, "status": "ELIGIBLE", "reasons": [], "citations": [],
            "missing_info": [], "notes": "", "flaw_count": 0,
        }
        _enforce_pool_spec_support([result], [carrier], AUDIT_R13_PROFILE,
                                   {carrier: _real_pool_spec(carrier)})
        assert result["status"] == "INSUFFICIENT_INFORMATION"


# ---------------------------------------------------------------------------
# ROUND 13 -- P4: is Allied Trust's solar retrieval firing?
#
# Answer: yes, deterministically. This is the same check run on Orion /
# TWICO / Swyfft for the roof topic in round 12's P6. The guaranteed lookup
# is an exact keyword scan over the carrier's full chunk set, so unlike an
# embedding-rank lookup it has no run-to-run variance to measure -- but the
# round 12 lesson was that a "guarantee" can still return nothing if the
# eligibility-content filter drops the chunk, so assert the count, not just
# the mechanism.
# ---------------------------------------------------------------------------

_CARRIERS_WITH_SOLAR_TEXT = [
    "ARI_(HOA+)",
    "ARI_(HOB)",
    "Allied_Trust_HO3",
    "Foremost_DP3_and_HO3_-_07.01.2026",
    "HOAIC_-_TX-HOMEOWNERS-0326_HO3",
    "NatGen_Premier_OneChoice_HO3_-_02.26.2025",
    "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3",
    "Progressive_HO3_-_04.01.2026",
    "Progressive_HO6_-_10.01.2025",
    "Swyfft_-_Benchmark_(Admitted)_HO3",
    "Swyfft_-_Benchmark_(Surplus)_HO3",
    "Swyfft_-_Lloyds_(Surplus)_HO3",
    "Swyfft_-_Topa_(Surplus)_HO3",
    "TWICO_HO3",
    "Travelers_HO3_-_06.12.2026",
]


@pytest.mark.retrieval
class TestRound13SolarRetrievalGuarantee:

    def test_allied_trust_solar_retrieval_is_deterministic(self):
        """Round 13 P4 asked whether Allied Trust's solar retrieval fires
        "consistently". Repeat it and assert the SAME non-empty result every
        time, rather than reporting a single sample as if it settled the
        question."""
        counts = {len(_guaranteed_lookup_chunks("Allied_Trust_HO3", _mentions_solar, keep=2))
                  for _ in range(5)}
        assert counts == {2}, (
            f"Allied Trust solar retrieval was not stable across 5 calls: saw counts {counts}"
        )

    @pytest.mark.parametrize("carrier", _CARRIERS_WITH_SOLAR_TEXT)
    def test_every_carrier_with_solar_text_actually_retrieves_it(self, carrier):
        """Generalizes P4 past the one carrier in the bug report: every
        carrier whose document mentions solar at all must have that text
        reach the prompt."""
        raw = [c for c in _all_chunks(carrier) if _mentions_solar(c.page_content)]
        assert raw, f"premise: {carrier} has solar text in its document"
        kept = _guaranteed_lookup_chunks(carrier, _mentions_solar, keep=2)
        assert kept, (
            f"{carrier} has {len(raw)} chunk(s) mentioning solar but the guaranteed lookup "
            f"returned none -- the eligibility-content filter is dropping them."
        )

    def test_allied_trust_solar_text_is_roofing_material_not_mounted_panels(self):
        """Documents WHY Allied Trust's silence on a mounted-panel property
        is defensible rather than a retrieval miss: both of its solar
        references are roof COVERING materials ("solar roof system", "Solar
        panel tiles"), which per SYSTEM_INSTRUCTIONS' SOLAR TERMINOLOGY rule
        do not apply to panels mounted on an ordinary shingle roof. If this
        ever fails, Allied Trust has gained a genuine mounted-panel rule and
        its silence WOULD then be a real defect."""
        blob = " ".join(
            c.page_content.lower()
            for c in _guaranteed_lookup_chunks("Allied_Trust_HO3", _mentions_solar, keep=3)
        )
        assert "solar roof system" in blob or "solar panel tiles" in blob
        for mounted_panel_signal in ("mounted", "attached to the roof", "photovoltaic"):
            assert mounted_panel_signal not in blob, (
                f"Allied Trust's solar text now contains {mounted_panel_signal!r} -- it may "
                f"have gained a mounted-panel rule, so silence is no longer defensible."
            )


@pytest.mark.baseline
def test_allied_trust_explicitly_addresses_solar_for_a_solar_property():
    """Round 13 P4. Retrieval was never the problem -- it fires 2/2 chunks,
    stable across 5 calls (TestRound13SolarRetrievalGuarantee). The problem
    was that Allied Trust's solar text is integrated solar ROOFING, which
    correctly does NOT apply to mounted panels, and the model therefore said
    nothing at all -- measured at 1 of 3 runs mentioning solar. From outside,
    that silence is indistinguishable from a retrieval miss. The
    deterministic [Solar check] note now makes the dismissal explicit on
    every run, so this is a hard assert rather than a tracked rate."""
    result = check_eligibility(AUDIT_R13_PROFILE)
    matches = _find_carrier({r.get("carrier", ""): r for r in result}, "allied")
    assert matches, "Allied Trust missing from the response entirely"
    r = matches[0]
    blob = " ".join(
        r.get("reasons", []) + r.get("citations", []) + r.get("missing_info", [])
        + [r.get("notes", "")]
    ).lower()
    assert "solar" in blob


# ---------------------------------------------------------------------------
# ROUND 13 -- MINOR: bucket label sanity check.
# ---------------------------------------------------------------------------

@pytest.mark.retrieval
def test_insufficient_information_bucket_label_is_not_truncated():
    """The round 13 audit narrative rendered this bucket as just
    "Information". The app's own label is the full string -- the four
    headers sit in st.columns(4), so a narrow column wraps the label onto
    two lines and copying it can pick up only the second. Asserted here so
    that stays a rendering artifact rather than something anyone has to
    re-check by eye."""
    app_src = open(
        os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8"
    ).read()
    assert 'st.markdown("### Insufficient Information")' in app_src
    for label in ("### Eligible", "### One Issue", "### Not Eligible", "### Could Not Be Checked"):
        assert f'st.markdown("{label}")' in app_src, f"bucket header {label!r} missing"
    # Step 2 (2026-09-29): two pipeline-written buckets, rendered together
    # under "Could Not Be Checked".
    assert set(assign_buckets([]).keys()) == {
        "eligible", "one_issue", "insufficient_info", "not_eligible",
        "guide_unavailable", "not_evaluated", "unrecognised",
    }
    for bucket in ("unrecognised", "guide_unavailable", "not_evaluated"):
        assert f'buckets["{bucket}"]' in app_src


# ---------------------------------------------------------------------------
# ROUND 13 -- P4 (continued): integrated solar ROOFING vs. MOUNTED panels.
#
# Retrieval was confirmed firing (see TestRound13SolarRetrievalGuarantee).
# The remaining gap was that a carrier whose solar rule correctly does not
# apply said nothing at all, which from outside is indistinguishable from a
# retrieval miss -- measured at 1 of 3 runs mentioning solar for Allied
# Trust. The Mercury and TWICO roof branches already settled that a silent
# "unremarkable" outcome is itself a bug; this applies the same remedy.
# ---------------------------------------------------------------------------

@pytest.mark.retrieval
class TestRound13SolarRoofingVsMountedPanels:

    @pytest.mark.parametrize("text,expected", [
        # integrated solar ROOFING -- the roof covering IS solar material
        ("solar roof system and roofs with any type of wood shingles", "roofing_only"),
        ("Solar panel tiles, slate, unique/uncommon roof material", "roofing_only"),
        ("j. Solar shingles k. Woodruf and T-Lock shingles", "roofing_only"),
        ("no tesla solar roofs, seasonal or secondary homes", "roofing_only"),
        # MOUNTED panels -- conventional PV on an ordinary roof
        ("Coverage for roof-mounted solar panels requires an endorsement", "addresses_panels"),
        ("Homes with photovoltaic systems are ineligible", "addresses_panels"),
        ("wind or hail that results in marring of ... solar panels", "addresses_panels"),
        ("no mention of the topic at all", "none"),
    ])
    def test_solar_text_classification(self, text, expected):
        """'Solar panel tiles' contains the substring 'solar panel' -- the
        exact confusion SYSTEM_INSTRUCTIONS' SOLAR TERMINOLOGY rule exists to
        prevent -- so integrated phrases must be consumed before any
        mounted-panel signal is looked for."""
        assert classify_solar_text(text) == expected

    def test_photovoltaic_only_text_is_not_missed(self):
        """The mounted-panel check runs before the "no solar at all" exit, so
        a rule written purely as "photovoltaic" still classifies. (No carrier
        currently in the database does this -- checked -- but the classifier
        must not depend on that staying true.)"""
        assert classify_solar_text("Homes with photovoltaic arrays require approval") == "addresses_panels"

    def test_foremost_is_classified_over_its_whole_document(self):
        """Regression for a bug in this round's own first draft. The
        guaranteed lookup keeps at most 2 chunks; Foremost has 4 mentioning
        solar. The two that rank first are both "Solar shingles" in a list of
        ineligible roof COVERINGS, but a later chunk covers "wind or hail
        that results in marring of ... solar panels" -- a real mounted-panel
        rule. Classifying only the kept chunks returned roofing_only and
        would have had the note assert Foremost states no mounted-panel rule."""
        collection = get_vectorstore()._collection
        carrier = "Foremost_DP3_and_HO3_-_07.01.2026"
        all_solar = [c for c in _all_chunks(carrier) if _mentions_solar(c.page_content)]
        kept = _guaranteed_lookup_chunks(carrier, _mentions_solar, keep=2)
        assert len(all_solar) > len(kept), "premise: Foremost has more solar chunks than are kept"
        assert classify_carrier_solar_text(collection, carrier) == "addresses_panels"

    def test_roofing_only_carriers_really_have_no_bare_solar_mention(self):
        """The note asserts the ABSENCE of a mounted-panel rule, so verify
        that claim against every carrier it will be attached to: after every
        integrated-roofing phrase is removed, no "solar" mention may remain
        anywhere in that carrier's document."""
        collection = get_vectorstore()._collection
        checked = 0
        for carrier in get_carriers_for_occupancy("Owner Occupied"):
            if classify_carrier_solar_text(collection, carrier) != "roofing_only":
                continue
            checked += 1
            blob = " ".join(
                normalize_chunk_text(c.page_content) for c in _all_chunks(carrier)
                if _mentions_solar(c.page_content)
            ).lower()
            for phrase in _INTEGRATED_SOLAR_ROOFING_PHRASES:
                blob = blob.replace(phrase, " ")
            assert "solar" not in blob, (
                f"{carrier} is classified roofing_only but still mentions solar outside an "
                f"integrated-roofing phrase -- the dismissal note would be asserting something "
                f"this document does not support."
            )
        assert checked, "expected at least one roofing_only carrier to check"

    def test_note_is_added_for_a_mounted_panel_property(self):
        carrier = "Allied_Trust_HO3"
        collection = get_vectorstore()._collection
        assert classify_carrier_solar_text(collection, carrier) == "roofing_only"
        result = {"carrier": carrier, "status": "ELIGIBLE", "reasons": [], "citations": [],
                  "missing_info": [], "notes": "", "flaw_count": 0}
        _note_solar_roofing_does_not_apply(
            [result], [carrier], AUDIT_R13_PROFILE, {carrier: "roofing_only"}
        )
        assert "[Solar check]" in result["notes"]
        assert "does not apply" in result["notes"].lower()
        # note-only: it must never move a verdict
        assert result["status"] == "ELIGIBLE"
        assert result["missing_info"] == [] and result["reasons"] == []

    def test_no_note_when_the_carrier_addresses_mounted_panels(self):
        """TWICO genuinely excludes homes with solar panels -- it must be
        left to say so itself, not handed a dismissal."""
        carrier = "TWICO_HO3"
        result = {"carrier": carrier, "status": "INELIGIBLE", "reasons": [], "citations": [],
                  "missing_info": [], "notes": "", "flaw_count": 1}
        _note_solar_roofing_does_not_apply(
            [result], [carrier], AUDIT_R13_PROFILE, {carrier: "addresses_panels"}
        )
        assert result["notes"] == ""

    def test_no_note_when_the_property_has_no_solar_panels(self):
        carrier = "Allied_Trust_HO3"
        result = {"carrier": carrier, "status": "ELIGIBLE", "reasons": [], "citations": [],
                  "missing_info": [], "notes": "", "flaw_count": 0}
        _note_solar_roofing_does_not_apply(
            [result], [carrier], dict(AUDIT_R13_PROFILE, solar_panels="No"),
            {carrier: "roofing_only"},
        )
        assert result["notes"] == ""


# ---------------------------------------------------------------------------
# ROUND 13 -- JSON parse failures: unescaped inner double quotes.
#
# Found while running this round's baseline tier, which lost three separate
# multi-run STANDARD_PROFILE tests to a single malformed response. This is
# the THIRD distinct cause behind "JSON PARSE ERROR" in this project:
#   * round 11/12 blamed ARI's curly apostrophes and embedded newlines
#     (a real cleanup, but not what was failing most runs)
#   * round 12 found output-token TRUNCATION and raised max_tokens
#   * round 13 (this) -- a COMPLETE response (stop_reason "end_turn",
#     ~50k chars) whose Mercury citation contains raw inner double quotes:
#         "The "Roof Surfacing" Loss Settlement Payment Schedule"
#
# Every prior round diagnosed this class from partial output, so these tests
# work from the actual captured bytes rather than a paraphrase.
# ---------------------------------------------------------------------------

@pytest.mark.retrieval
class TestRound13JsonQuoteRepair:

    @pytest.mark.parametrize("payload,expected_repairs", [
        (r'[{"a": "the \"x\" thing"}]', 0),        # correctly escaped -> untouched
        ('[{"a": "the "x" thing"}]', 2),           # the Mercury shape
        ('[{"a": "plain"}]', 0),
        ('[{"a": "x", "b": ["y", "z"]}]', 0),      # commas/arrays not misread
        ('[{"a": "He said "hi", then left"}]', 2), # inner quote FOLLOWED BY A COMMA
    ])
    def test_repair_escapes_only_inner_quotes(self, payload, expected_repairs):
        """The comma case is the subtle one. A closing quote is usually
        followed by a comma -- so is the inner quote in
        'says "X", which means Y', a shape this domain's citations produce
        constantly. Treating any quote-then-comma as a close ends the string
        early and turns the rest of the sentence into garbage, so the
        lookahead also requires what follows the comma to actually begin a
        JSON value or key."""
        repaired, n = repair_unescaped_quotes(payload)
        assert n == expected_repairs
        json.loads(repaired)  # must be valid JSON afterwards

    def test_repair_preserves_the_original_string_content(self):
        payload = '[{"a": "the "x" thing"}]'
        parsed, n = parse_carrier_json(payload)
        assert n == 2
        assert parsed[0]["a"] == 'the "x" thing'

    def test_unrepairable_json_still_raises_the_original_error(self):
        """A genuinely truncated response must NOT be silently swallowed by
        the repair -- round 12's truncation bug has to stay diagnosable."""
        with pytest.raises(json.JSONDecodeError):
            parse_carrier_json('[{"carrier": "X", "reasons": ["a"')

    def test_repairs_the_real_captured_failure(self):
        """The actual bytes from the failing run, kept as a fixture. A
        synthetic reproduction is what let round 11 'fix' this class twice
        without fixing it."""
        path = os.path.join(os.path.dirname(__file__), "fixtures",
                            "json_parse_failure_unescaped_quotes.txt")
        raw = open(path, encoding="utf-8").read()
        payload = raw[raw.find("["):raw.rfind("]") + 1]

        with pytest.raises(json.JSONDecodeError):
            json.loads(payload)  # premise: this really is malformed

        parsed, n = parse_carrier_json(payload)
        assert n == 2
        assert len(parsed) == 28, (
            f"the whole response -- all 28 carriers -- used to be discarded; "
            f"recovered {len(parsed)}"
        )
        mercury = [p for p in parsed if "Mercury" in p.get("carrier", "")]
        assert mercury, "Mercury (the carrier whose citation broke the parse) must survive"
        assert any(
            "Roof Surfacing" in r for r in mercury[0].get("reasons", [])
        ), "the repaired citation must keep its text"


# ---------------------------------------------------------------------------
# ROUND 14 -- P1: the tool must never assert a property feature the intake
# says is absent.
#
# Audit: on a DP3 profile whose intake reads "Solar Panels: No", 7 of 12
# carriers reasoned from solar being present, and NatGen Premier OneChoice
# DP3 was marked INELIGIBLE solely on it -- "The carrier's flat exclusion of
# solar panels makes this property ineligible regardless of other factors."
#
# Root cause found in SYSTEM_INSTRUCTIONS, which is CACHED and sent
# identically on every call: it contained the sentence
#     The customer's "Solar Panels: Yes" in PROPERTY DETAILS means ...
# stating a customer fact as though it were true of every run, and the whole
# surrounding section was written on the premise that panels are present
# ("does NOT apply to this customer"). That is now a two-branch conditional
# keyed on the actual value, plus a general authoritative-input rule.
# ---------------------------------------------------------------------------

@pytest.mark.retrieval
class TestRound14SystemPromptStatesNoCustomerFacts:

    def _system_instructions(self):
        import eligibility_check
        return eligibility_check.SYSTEM_INSTRUCTIONS

    def test_prompt_never_asserts_the_customers_solar_value(self):
        """The exact sentence that caused it. Guarded by substring rather
        than by intent, because the failure mode is a literal value being
        stated as fact."""
        sysinst = self._system_instructions()
        assert 'The customer\'s "Solar Panels: Yes"' not in sysinst, (
            "the cached system prompt again asserts the customer's solar value; it must "
            "describe both branches conditionally instead"
        )

    def test_prompt_covers_the_solar_no_branch_explicitly(self):
        sysinst = self._system_instructions()
        assert "Solar Panels: No" in sysinst, (
            "the solar section must tell the model what to do when the value is No -- "
            "previously it only ever described the Yes case"
        )

    def test_prompt_carries_the_authoritative_input_rule(self):
        sysinst = self._system_instructions()
        assert "PROPERTY DETAILS IS THE ONLY SOURCE OF FACTS" in sysinst

    @pytest.mark.parametrize("field_value_phrase", [
        'Swimming Pool is "In Ground - Fenced"',   # marked e.g., acceptable
    ])
    def test_remaining_literal_examples_are_marked_as_examples(self, field_value_phrase):
        """A literal intake value in the prompt is only safe when it reads as
        an example. This one is introduced by "e.g."; the solar one was not,
        which is precisely why it was taken as fact."""
        sysinst = self._system_instructions()
        idx = sysinst.find(field_value_phrase)
        assert idx != -1
        preceding = sysinst[max(0, idx - 90):idx]
        assert "e.g." in preceding, (
            f"{field_value_phrase!r} is stated without an 'e.g.' marker, so it reads as a "
            f"fact about the current customer"
        )


def _contradiction_result(carrier, status, reasons, flaw_count=0, missing_info=None, notes=""):
    return {
        "carrier": carrier, "status": status, "reasons": list(reasons), "citations": [],
        "missing_info": list(missing_info or []), "notes": notes, "flaw_count": flaw_count,
    }


@pytest.mark.retrieval
class TestRound14ContradictedPropertyFacts:
    """Deterministic half of P1. CLAUDE.md's premise is that a prompt rule is
    not a guarantee; unlike most rules here this one is mechanically
    decidable, because the intake value is known."""

    def test_the_exact_audit_sentence_undoes_the_verdict(self):
        r = _contradiction_result(
            "NatGen_Premier_OneChoice_DP3_-_02.26.2025", "INELIGIBLE",
            ["The carrier's flat exclusion of solar panels makes this property ineligible "
             "regardless of other factors."],
            flaw_count=1,
        )
        _strip_contradicted_property_claims([r], AUDIT_R14_DP3_PROFILE)
        assert r["status"] == "ELIGIBLE", (
            "an adverse verdict resting on a feature the intake says is absent is not a verdict"
        )
        assert r["reasons"] == []
        assert "intake contradiction" in r["notes"].lower()

    @pytest.mark.parametrize("phrasing", [
        "Solar panels are present, which this carrier excludes.",
        "The property has solar panels, making it ineligible under the carrier's exclusion.",
        "Solar Panels: Yes -- the carrier does not write risks with solar, so it is ineligible.",
        "The carrier's flat exclusion of solar panels makes this property ineligible.",
    ])
    def test_multiple_phrasings_of_the_same_fabrication(self, phrasing):
        """CLAUDE.md rule 2. The audit reported two distinct shapes ('solar
        panels are present' and 'Solar Panels: Yes'), and the one that
        actually moved a verdict asserted nothing at all -- it just applied
        the exclusion. All must be caught."""
        r = _contradiction_result("X", "INELIGIBLE", [phrasing], flaw_count=1)
        _strip_contradicted_property_claims([r], AUDIT_R14_DP3_PROFILE)
        assert r["status"] == "ELIGIBLE", f"not caught: {phrasing!r}"

    def test_an_independent_ground_keeps_the_verdict(self):
        r = _contradiction_result(
            "X", "INELIGIBLE",
            ["Solar panels are present, which the carrier excludes.",
             "Roof age 25 exceeds the carrier's 20-year maximum."],
            flaw_count=2,
        )
        _strip_contradicted_property_claims([r], AUDIT_R14_DP3_PROFILE)
        assert r["status"] == "INELIGIBLE"
        assert any("Roof age" in x for x in r["reasons"])
        assert not any("solar" in x.lower() for x in r["reasons"])

    @pytest.mark.parametrize("safe_reason", [
        "No solar panels are present, so the exclusion does not apply.",
        "The carrier's solar exclusion does not apply to this property.",
        "Solar panel coverage is available by endorsement.",
    ])
    def test_correct_or_neutral_solar_statements_survive(self, safe_reason):
        """Round 13 spent effort making carriers explicitly DISMISS
        inapplicable rules. This check must not delete those."""
        r = _contradiction_result("X", "ELIGIBLE", [safe_reason])
        _strip_contradicted_property_claims([r], AUDIT_R14_DP3_PROFILE)
        assert r["reasons"] == [safe_reason]
        assert r["status"] == "ELIGIBLE"

    def test_does_not_fire_when_the_feature_is_actually_present(self):
        r = _contradiction_result(
            "X", "INELIGIBLE", ["Solar panels are present, which the carrier excludes."],
            flaw_count=1,
        )
        _strip_contradicted_property_claims([r], ALT_PROFILE)  # ALT has solar=Yes
        assert r["status"] == "INELIGIBLE"
        assert r["reasons"]

    def test_generalises_to_other_absent_features(self):
        """Not a solar patch. The same check covers any field whose value
        positively states absence."""
        r = _contradiction_result(
            "X", "INELIGIBLE",
            ["The property has a swimming pool that is unfenced and therefore ineligible."],
            flaw_count=1,
        )
        _strip_contradicted_property_claims([r], AUDIT_R14_DP3_PROFILE)  # No Pool
        assert r["status"] == "ELIGIBLE"

    def test_remaining_missing_info_blocks_the_upgrade(self):
        r = _contradiction_result(
            "X", "INELIGIBLE", ["Solar panels are present, which the carrier excludes."],
            flaw_count=1, missing_info=["Year of last roof replacement"],
        )
        _strip_contradicted_property_claims([r], AUDIT_R14_DP3_PROFILE)
        assert r["status"] == "INELIGIBLE", "something is still genuinely unresolved"


# ---------------------------------------------------------------------------
# ROUND 14 -- P2: Sage's own shingle-subtype ambiguity.
# ---------------------------------------------------------------------------

@pytest.mark.retrieval
class TestRound14SageRooferStatementSubtype:

    def test_source_text_really_has_two_thresholds(self):
        """Anchored to the carriers' own words, not to the rule module."""
        text = " ".join(
            normalize_chunk_text(c.page_content).lower()
            for c in _all_chunks("Sage_-_Occidental_DP3")
        )
        assert "roofer's statement" in text
        assert "over 25 years of age" in text and "architectural" in text
        assert "over 15 years of age" in text and "3-tab" in text

    @pytest.mark.parametrize("roof_type", [
        "Composition Shingle", "Composite Shingle", "asphalt shingle",
    ])
    def test_generic_shingle_at_25_is_ambiguous_across_phrasings(self, roof_type):
        """CLAUDE.md rule 2 -- the same family named three ways."""
        status, reasons = sage_roofer_statement_required(roof_type, 25)
        assert status == "INSUFFICIENT_INFORMATION"
        assert "15" in reasons[0] and "25" in reasons[0]

    @pytest.mark.parametrize("roof_type,age,expected", [
        ("Architectural Shingle", 25, "NOT_REQUIRED"),   # 25 is not "over 25"
        ("Architectural Shingle", 26, "REQUIRED"),
        ("3-tab shingle", 25, "REQUIRED"),               # 10 years past ITS threshold
        ("3-tab shingle", 15, "NOT_REQUIRED"),           # 15 is not "over 15"
        ("Tile", 25, "NOT_REQUIRED"),
    ])
    def test_stated_subtypes_resolve_cleanly(self, roof_type, age, expected):
        assert sage_roofer_statement_required(roof_type, age)[0] == expected

    @pytest.mark.parametrize("age", [10, 30])
    def test_ages_where_both_readings_agree_are_not_ambiguous(self, age):
        """The sub-type is still unknown, but it changes nothing -- the same
        principle as SYSTEM_INSTRUCTIONS' 'do not downgrade when every
        applicable branch agrees'."""
        assert sage_roofer_statement_required("Composition Shingle", age)[0] != \
            "INSUFFICIENT_INFORMATION"

    def test_all_nine_siblings_disclose_both_readings(self):
        """The audit saw three siblings silently pick the favourable
        sub-type. All nine carrying the rule must disclose both."""
        assert len(_SAGE_ROOFER_STATEMENT_CARRIERS) == 9
        carriers = sorted(_SAGE_ROOFER_STATEMENT_CARRIERS)
        for carrier in carriers:
            r = {
                "carrier": carrier, "status": "ELIGIBLE",
                "reasons": ["Architectural shingles at 25 are not over 25, so no statement."],
                "citations": [], "missing_info": [], "notes": "", "flaw_count": 0,
            }
            _apply_structured_overrides([r], carriers, AUDIT_R14_DP3_PROFILE)
            assert "3-tab" in r["notes"], f"{carrier}: 3-tab reading not disclosed"
            assert "Architectural" in r["notes"], f"{carrier}: architectural reading not disclosed"
            assert any("sub-type" in m.lower() for m in r["missing_info"]), carrier

    def test_rule_still_applies_to_carriers_that_also_match_the_fpc_branch(self):
        """Six of the nine are also in _SAGE_FPC_CARRIERS. The roof check is
        deliberately NOT part of that elif chain -- an elif would skip it for
        exactly the carriers the audit flagged, which is the same wiring
        mistake round 12 made with the FPC check itself."""
        overlap = _SAGE_ROOFER_STATEMENT_CARRIERS & _SAGE_FPC_CARRIERS
        assert overlap, "premise: these sets overlap"
        for carrier in sorted(overlap):
            r = {
                "carrier": carrier, "status": "ELIGIBLE", "reasons": [], "citations": [],
                "missing_info": [], "notes": "", "flaw_count": 0,
            }
            _apply_structured_overrides([r], sorted(_SAGE_ROOFER_STATEMENT_CARRIERS),
                                        AUDIT_R14_DP3_PROFILE)
            assert "3-tab" in r["notes"], (
                f"{carrier} matched an earlier branch and never reached the roof rule"
            )

    def test_a_documentation_requirement_never_becomes_a_decline(self):
        """A roofer's statement is a condition to satisfy, not an exclusion."""
        carriers = sorted(_SAGE_ROOFER_STATEMENT_CARRIERS)
        r = {
            "carrier": carriers[0], "status": "ELIGIBLE", "reasons": [], "citations": [],
            "missing_info": [], "notes": "", "flaw_count": 0,
        }
        _apply_structured_overrides([r], carriers, dict(AUDIT_R14_DP3_PROFILE, roof_age=30))
        assert sage_roofer_statement_required("Composition Shingle", 30)[0] == "REQUIRED"
        assert r["status"] != "INELIGIBLE"


# ---------------------------------------------------------------------------
# ROUND 14 -- P3: roof SHAPE had no retrieval guarantee at all.
# ---------------------------------------------------------------------------

_FLAT_ROOF_RE = re.compile(r"(?i)flat\s+roof|roof.{0,25}\bflat\b|\bflat\b\s*\(unless")


@pytest.mark.retrieval
class TestRound14RoofShapeRetrievalGuarantee:

    def test_centauri_dp3_really_does_exclude_flat_roofs(self):
        """The audit run said Centauri's DP3 excerpt 'does not explicitly
        exclude flat roofs'. Its document says the opposite, under a heading
        that reads ROOFS/SIDING - Ineligible."""
        text = " ".join(
            normalize_chunk_text(c.page_content)
            for c in _all_chunks("Centauri_-_DP3_-_11.16.2022")
        )
        assert "Flat (unless poured concrete)" in text
        assert "Ineligible" in text

    def test_flat_roof_rules_reach_the_prompt_for_every_carrier_that_has_one(self):
        """Before the guarantee, 5 of 14 never did -- Centauri, CHUBB,
        NatGen Premier OneChoice DP3, Progressive DP3 and Steadily."""
        collection = get_vectorstore()._collection
        shape_keywords = _RESTRICTED_ROOF_SHAPES["flat"]
        tenant_carriers = get_carriers_for_occupancy("Tenant Occupied")
        checked = 0
        for carrier in tenant_carriers:
            raw = _all_chunks(carrier)
            has_rule = [c for c in raw if _FLAT_ROOF_RE.search(normalize_chunk_text(c.page_content))]
            if not has_rule:
                continue
            checked += 1
            kept = guaranteed_carrier_lookup(
                collection, carrier,
                predicate=lambda doc: _mentions_roof_shape_rule(doc, shape_keywords),
                keep=2,
            )
            assert kept, (
                f"{carrier} states a flat-roof rule but the roof-shape guarantee returned "
                f"nothing for it"
            )
        # Tied to the carrier list, not a magic number. Round 16's occupancy
        # fix legitimately shrank the tenant list from 18 to 13 (five
        # homeowners documents removed, which happened to carry flat-roof
        # rules too) and a hardcoded ">= 10" failed on a correct change.
        # The real invariant is the per-carrier assertion above; this is only
        # a guard against the predicate silently matching nothing.
        assert checked >= len(tenant_carriers) // 2, (
            f"only {checked} of {len(tenant_carriers)} tenant carriers matched a flat-roof "
            f"rule -- the predicate may have stopped matching"
        )

    @pytest.mark.parametrize("text,expected", [
        ("ROOFS/SIDING - Ineligible: g. Flat (unless poured concrete)", True),
        ("Flat roofs are ineligible for coverage.", True),
        ("Dwellings with flat roof sections require inspection.", True),
        ("A flat fee of $250 applies to each endorsement.", False),
        ("Premium is calculated on a flat basis for this program.", False),
    ])
    def test_shape_word_must_sit_near_roof_language(self, text, expected):
        """A bare 'flat' is common in insurance prose ('flat fee', 'flat
        deductible'); only a roof-adjacent one counts."""
        assert _mentions_roof_shape_rule(text, ("flat",)) is expected

    def test_unrestricted_shapes_do_not_trigger_the_lookup(self):
        """Gable and Hip appear in almost no ineligibility list, so they get
        no guarantee and cost no prompt tokens."""
        assert "gable" not in _RESTRICTED_ROOF_SHAPES
        assert "hip" not in _RESTRICTED_ROOF_SHAPES
        assert set(_RESTRICTED_ROOF_SHAPES) == {"flat", "gambrel", "mansard"}

    def test_centauri_dp3_shingle_brackets_are_NOT_ambiguous(self):
        """Round 14 P3.2, and the answer is 'no change needed'. Centauri's
        HO3 document groups "Architectural or Composition Shingle" as one
        bracket, which would make plain "Composition Shingle" ambiguous. Its
        DP3 document does NOT: it gives composition and architectural
        SEPARATE thresholds (16 and 25), so "Composition Shingle" maps to
        the composition bracket unambiguously and must not get the
        Sage/TWICO ambiguity treatment.

        Per SYSTEM_INSTRUCTIONS' own terminology rule, two of these terms are
        genuinely different categories exactly when the SAME document gives
        them different numeric thresholds -- which this one does."""
        text = " ".join(
            normalize_chunk_text(c.page_content).lower()
            for c in _all_chunks("Centauri_-_DP3_-_11.16.2022")
        )
        assert "composition shingles age 16 and greater" in text
        assert "architectural shingles age 25 and greater" in text
        # and it is not wired into either ambiguity path
        assert "Centauri_-_DP3_-_11.16.2022" not in _SAGE_ROOFER_STATEMENT_CARRIERS
        assert "Centauri_-_DP3_-_11.16.2022" not in _TWICO_CARRIERS


@pytest.mark.retrieval
class TestOccupancyFilterProductDetection:
    """Round 16: the deferred "one deliberate pass over the whole occupancy
    filter". Previously an xfail.

    Three separate places re-derived which product a carrier document is,
    with slightly different substring checks -- which is exactly how a gap
    survived in two of them while the third handled it. `"DP3" in name or
    "DP-3" in name` caught the hyphenated dwelling-fire form, but the
    homeowners side was only `"HO3" in name`, so Sage_-_SURE_HO-3 and
    Sage_-_SafePort_HO-3 were offered for tenant-occupied risks. All three
    now call carrier_programs().

    Measured impact before the fix, over 44 tenant-occupied executions: the
    five wrongly-included homeowners documents reached the OUTPUT 14-32
    times each. Never as ELIGIBLE (ARI was INELIGIBLE 32/32), so this was
    scope noise and wasted prompt tokens rather than a wrong-decline risk.
    """

    @pytest.mark.parametrize("carrier,expected", [
        # the punctuation variants that started this -- same program, two spellings
        ("Sage_-_SURE_HO-3_-_01.31.2026", (True, False)),
        ("Sage_-_SafePort_HO-3_-_01.31.2026", (True, False)),
        ("Sage_-_Auros_HO3", (True, False)),
        ("Sage_-_SURE_DP-3_-_01.31.2026", (False, True)),
        ("Sage_-_Markel_DP3", (False, True)),
        # other homeowners forms
        ("Liberty_Mutual_HO6_-_02.21.2026", (True, False)),
        ("Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026", (True, False)),
        ("HOAIC_-_TX-HOMEOWNERS-0326_HO3", (True, False)),
        # bundles both
        ("Foremost_DP3_and_HO3_-_07.01.2026", (True, True)),
    ])
    def test_product_detection_is_punctuation_insensitive(self, carrier, expected):
        """CLAUDE.md rule 2: the same program spelled two ways must classify
        the same way. HO3/HO-3 and DP3/DP-3 are the pairs that matter."""
        assert carrier_programs(carrier) == expected

    def test_hyphen_and_unhyphenated_forms_agree(self):
        """Stated directly rather than only via the table above, because the
        whole defect was these two disagreeing."""
        assert carrier_programs("Sage_-_SURE_HO-3_-_01.31.2026") == \
               carrier_programs("Sage_-_SURE_HO3_-_01.31.2026")
        assert carrier_programs("Sage_-_SURE_DP-3_-_01.31.2026") == \
               carrier_programs("Sage_-_SURE_DP3_-_01.31.2026")

    @pytest.mark.parametrize("carrier,quote", [
        ("ARI_(HOA+)", "owner occupied by owner"),
        ("ARI_(HOB)", "owner occupied by owner"),
        ("CHUBB_HO_-_05.22.2026", "homeowners insurance"),
    ])
    def test_tokenless_carriers_are_classified_from_their_own_documents(self, carrier, quote):
        """These three filenames carry no product token, so they were kept
        for EVERY occupancy. They are classified by an explicit map -- and
        the map's justification is checked against the source text here, so
        it cannot rot into folklore."""
        text = " ".join(
            normalize_chunk_text(c.page_content).lower() for c in _all_chunks(carrier)
        )
        assert quote in text, (
            f"{carrier}: the source line justifying its homeowners classification is gone"
        )
        assert carrier_programs(carrier) == (True, False)

    def test_hoaic_dwelling_guide_is_not_swallowed_by_an_hoa_substring(self):
        """Why the token regex deliberately does NOT match a bare "HOA":
        HOAIC is a different company, and HOAIC_-_DP_Guide_DP3 is a
        dwelling-fire document. Matching "HOA" to catch ARI would have
        misclassified it as combined-program."""
        assert carrier_programs("HOAIC_-_DP_Guide_DP3") == (False, True)
        assert "HOAIC_-_DP_Guide_DP3" not in get_combined_program_carriers()

    def test_no_homeowners_document_is_offered_for_a_tenant_risk(self):
        leaked = [
            c for c in get_carriers_for_occupancy("Tenant Occupied")
            if carrier_programs(c)[0] and not carrier_programs(c)[1]
        ]
        assert not leaked, f"homeowners programs selected for a tenant-occupied run: {leaked}"

    def test_no_dwelling_fire_document_is_offered_for_an_owner_risk(self):
        leaked = [
            c for c in get_carriers_for_occupancy("Owner Occupied")
            if carrier_programs(c)[1] and not carrier_programs(c)[0]
        ]
        assert not leaked, f"dwelling-fire programs selected for an owner-occupied run: {leaked}"

    def test_only_genuinely_combined_documents_appear_in_both_lists(self):
        owner = set(get_carriers_for_occupancy("Owner Occupied"))
        tenant = set(get_carriers_for_occupancy("Tenant Occupied"))
        both = owner & tenant
        assert both == get_combined_program_carriers(), (
            f"carriers in both occupancy lists that are not combined-program: "
            f"{sorted(both - get_combined_program_carriers())}"
        )

    def test_every_carrier_is_classified_as_something(self):
        """A document with no recognised product token is kept for every
        occupancy, which is how ARI and CHUBB slipped through unnoticed. If
        a new carrier lands with an unrecognised name, fail loudly here
        rather than silently offering it to everyone."""
        unclassified = [
            c for c in get_all_carriers() if carrier_programs(c) == (False, False)
        ]
        assert not unclassified, (
            f"these carriers match no product token and would be offered for EVERY "
            f"occupancy type -- add them to _PRODUCT_BY_DOCUMENT with a source quote: "
            f"{unclassified}"
        )


@pytest.mark.retrieval
class TestRound14CentauriFlatRoof:
    """Round 14 P3.1. Surfacing the clause was necessary but not sufficient:
    measured over 12 DP3 runs, adding the retrieval guarantee alone moved
    Centauri from 12/12 INELIGIBLE to 5/12, because the model began treating
    "is it poured concrete?" as an open question. Roof Type already answers
    it, so the rule is a lookup and belongs in code."""

    CARRIER = "Centauri_-_DP3_-_11.16.2022"

    @pytest.mark.parametrize("roof_type", [
        "Composition Shingle", "Architectural Shingle", "Metal",
        "Tile", "Slate", "Wood Shake", "Flat/Built-Up",
    ])
    def test_every_intake_roof_type_on_a_flat_roof_is_ineligible(self, roof_type):
        """None of the intake's Roof Type options is a poured concrete deck
        -- "Built-Up" is tar and gravel -- so a flat roof is ineligible for
        all of them."""
        assert centauri_dp3_flat_roof("Flat", roof_type)[0] == "INELIGIBLE"

    def test_unknown_material_is_not_forced_either_way(self):
        """"Other" genuinely could be a poured deck; claiming ineligible
        would be asserting a fact the intake does not supply."""
        assert centauri_dp3_flat_roof("Flat", "Other")[0] == "INSUFFICIENT_INFORMATION"

    @pytest.mark.parametrize("roof_type", ["Poured Concrete", "Concrete"])
    def test_the_documented_exception_is_honoured(self, roof_type):
        assert centauri_dp3_flat_roof("Flat", roof_type)[0] == "ELIGIBLE"

    def test_concrete_tile_is_not_a_poured_deck(self):
        """A discrete covering that happens to be made of concrete is not
        the poured deck the exception describes."""
        assert centauri_dp3_flat_roof("Flat", "Concrete Tile")[0] == "INELIGIBLE"

    @pytest.mark.parametrize("shape", ["Gable", "Hip", "Gambrel", "Mansard"])
    def test_non_flat_shapes_are_untouched(self, shape):
        assert centauri_dp3_flat_roof(shape, "Composition Shingle")[0] == "NOT_APPLICABLE"

    def test_override_forces_the_verdict_regardless_of_what_the_model_said(self):
        for model_status in ("ELIGIBLE", "INSUFFICIENT_INFORMATION", "REFER"):
            r = {
                "carrier": self.CARRIER, "status": model_status, "reasons": [],
                "citations": [], "missing_info": [], "notes": "", "flaw_count": 0,
            }
            _apply_structured_overrides([r], [self.CARRIER], AUDIT_R14_DP3_PROFILE)
            assert r["status"] == "INELIGIBLE", (
                f"model said {model_status}; the flat-roof exclusion is not optional"
            )
            assert any("poured concrete" in x.lower() for x in r["reasons"])


@pytest.mark.retrieval
def test_only_the_mixed_status_buckets_carry_a_status_suffix():
    """Which buckets render a "| STATUS" suffix on each carrier, and which
    render the bare carrier name.

    Asked twice by manual audits. Round 13's question was about the bucket
    HEADER ("Insufficient Information" arriving as just "Information") --
    that header is complete in the source and the truncation was a
    column-wrap copy artifact. Round 15's question is a DIFFERENT element:
    the per-carrier suffix. Ten carriers landed in Insufficient Information
    with no "| STATUS" tag while One Issue and Not Eligible carriers all had
    one. That is real, it is by design, and the copy-paste was faithful.

    The reason is that One Issue is the only bucket that can hold more than
    one status -- assign_buckets() puts both INELIGIBLE-with-flaw_count-1 and
    REFER in it, so the tag is doing real work there. Eligible and
    Insufficient Information each map to exactly one status, so a tag would
    only restate the column header.

    Locked in so a third audit doesn't have to ask. If someone deliberately
    makes the tagging uniform, this test should be updated, not deleted --
    the point is that the choice is explicit rather than accidental.
    """
    app_src = open(
        os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8"
    ).read()
    section = app_src[app_src.find("col_yes, col_one, col_info, col_no"):]
    section = section[:section.find("# ===")] if "# ===" in section else section

    def bucket_body(name):
        start = section.find(f'st.markdown("### {name}")')
        assert start != -1, f"bucket header {name!r} not found"
        rest = section[start:]
        nxt = rest.find("with col_", 1)
        return rest[:nxt] if nxt != -1 else rest

    # Buckets holding exactly one status -> bare carrier name.
    for name in ("Eligible", "Insufficient Information"):
        body = bucket_body(name)
        assert 'st.expander(carrier["carrier"])' in body, (
            f"{name!r} bucket no longer renders the bare carrier name"
        )
        assert '+ "  |  " +' not in body, (
            f"{name!r} bucket gained a status suffix; every carrier in it has the same "
            f"status, so the suffix would only restate the column header"
        )

    # One Issue genuinely mixes INELIGIBLE(flaw_count==1) and REFER.
    one_issue = bucket_body("One Issue")
    assert 'carrier.get("status", "").replace("_", " ")' in one_issue
    assert '+ "  |  " +' in one_issue, (
        "One Issue is the only bucket that can hold two different statuses -- dropping "
        "its suffix would make INELIGIBLE and REFER indistinguishable in the UI"
    )

    # Sanity: that mixing claim is a property of assign_buckets, not folklore.
    mixed = assign_buckets([
        {"carrier": "a", "status": "INELIGIBLE", "flaw_count": 1},
        {"carrier": "b", "status": "REFER", "flaw_count": 0},
    ])
    assert {r["status"] for r in mixed["one_issue"]} == {"INELIGIBLE", "REFER"}
    single = assign_buckets([
        {"carrier": "c", "status": "INSUFFICIENT_INFORMATION", "flaw_count": 0},
    ])
    assert {r["status"] for r in single["insufficient_info"]} == {"INSUFFICIENT_INFORMATION"}


@pytest.mark.retrieval
@pytest.mark.xfail(
    reason="TWO KNOWN DATA DEFECTS, both confirmed round 16, both needing a corrected PDF "
    "upload rather than a code change:\n"
    "  Liberty_Mutual_HO6 holds the Liberty_Mutual_HO3 document (27 chunks, identical "
    "sha256) -- the Condominium Unit-Owners guide was never ingested.\n"
    "  NatGen_Custom360_HO3 holds the NatGen_Custom360_DP3 document (112 chunks, identical "
    "sha256). The shared file is titled 'Texas Landlord - Custom360' with 31 'landlord' "
    "mentions and zero homeowners signals, so the DP3 record is the correct one and the HO3 "
    "record is wrong. Measured over the round 15 STANDARD (owner-occupied) sweep: it appears "
    "in 20/20 runs, is INELIGIBLE in 18/20, and all 20 outputs correctly say it is a landlord "
    "program that does not apply -- which means every owner-occupied query reports a carrier "
    "as not applicable when the truth is that we never ingested its homeowners guide.\n"
    "This will XPASS once both PDFs are re-uploaded.",
    strict=False,
)
def test_no_two_carriers_hold_the_same_document():
    """Two carrier records holding byte-identical content means one of them
    is the wrong PDF.

    Worth a standing check rather than a one-off: this is invisible from the
    output. The model reads whatever document it is given and reasons about
    it correctly, so a mis-filed PDF produces confident, well-cited, wrong-
    program answers instead of an error. Both known cases were found only
    because a manual audit asked an unrelated question about one of them.

    Related but NOT the same as the round 12 dedup fix: that one was about
    two carriers legitimately sharing text and the retrieval key collapsing
    them. This is about a record holding the wrong file entirely.
    """
    import hashlib
    collection = get_vectorstore()._collection
    by_hash = {}
    for carrier in get_all_carriers():
        docs = collection.get(where={"carrier": carrier}, include=["documents"])["documents"]
        digest = hashlib.sha256("".join(sorted(docs)).encode("utf-8", "replace")).hexdigest()
        by_hash.setdefault(digest, []).append(carrier)

    duplicates = {h: sorted(v) for h, v in by_hash.items() if len(v) > 1}
    assert not duplicates, (
        "carrier records holding identical document content -- one of each pair is the "
        "wrong PDF: " + "; ".join(" == ".join(v) for v in duplicates.values())
    )


# Product words as a document describes ITSELF, counted over the whole
# document. This is the WORD rule, and it is what catches NatGen Custom360
# HO3 (DD-1: 34 landlord/dwelling-fire hits against 2).
#
# CORRECTION (DD-4, round 17). This comment used to say "a header-based
# version was tried and is worse, tripping on Sage Occidental HO3 (1 vs 2)".
# That trip was CORRECT: Sage_-_Occidental_HO3 holds Occidental's DWELLING
# FIRE PROGRAM (DP3) guide, and the header version saw it. It was treated as
# a false positive and tuned away, and the defect went unseen until round 17.
# The word rule on its own misses it for a specific reason: 5 of the record's
# 6 "homeowners" hits are "owner occupied", which dwelling-fire guides use
# constantly ("Dwellings (DP 00 03) must be: ... Owner or Tenant occupied").
#
# "owner occupied" is deliberately KEPT in the word rule anyway, because
# dropping it was measured and makes the rule worse: Travelers HO3 goes from
# 3 vs 8 (ratio 2.7, safe) to 1 vs 8 (ratio 8), protected only by the 10-hit
# floor. The fix for DD-4 is a SECOND signal below, not a weaker first one.
_SELF_DESCRIBED_HOMEOWNERS_RE = re.compile(
    r"(?i)\bhomeowners?\b|\bHO-?[356]\b|owner[- ]occupied")
_SELF_DESCRIBED_DWELLING_FIRE_RE = re.compile(
    r"(?i)\blandlord\b|dwelling fire|\bDP-?[13]\b|tenant[- ]occupied|"
    r"rented to others|rental dwelling")

# A document must read overwhelmingly like the OTHER product before the word
# rule calls it a mismatch: at least this many opposite-product hits, AND that
# many times its own-product hits. Travelers' HO3 guide legitimately contains
# a "LANDLORD DWELLING/LANDLORD CONDOMINIUM ONLY" ineligibility section (ho=3,
# dp=8, ratio 2.7) and must not trip; NatGen Custom360's mis-filed record is
# ho=2, dp=34, ratio 17.
_OPPOSITE_PRODUCT_FLOOR = 10
_OPPOSITE_PRODUCT_RATIO = 4

# The REFERENCE rule: what policy FORM and PRODUCT the guide says it writes.
# Endorsement numbers are deliberately excluded -- DP guides cite HO 04 70
# (the Texas wind/hail exclusion) and HO guides cite dwelling endorsements --
# so only the policy forms themselves (HO 00 0x, DP 00 0x), bare product names
# (HO-3, DP3) and program titles count. "owner occupied" is not a signal here.
#
# Measured over every single-product record: Sage_-_Occidental_HO3 is the ONLY
# one with zero references to its own product and any to the other -- 0 HO vs
# 5 DP, every one of them the document describing itself: its title "TEXAS
# OCCIDENTAL DWELLING FIRE PROGRAM (DP3)", its footer "TX Occidental DP3
# Revised 08/06/2025", and twice "Dwellings: DP 00 03" under Forms. The close
# call is Liberty Mutual DP3: 0 DP vs 1 HO, and that one HO hit is a
# cross-reference ("the maintenance standards that apply to Safeco's
# homeowners program are consistent with those for Landlord Protection").
# Floor 3 leaves a two-hit margin on each side. Travelers is 0 vs 0 and
# cannot trip a reference-based rule at all.
_HO_PRODUCT_REF_RE = re.compile(
    r"(?i)\bHO[- ]?00[- ]?0[2-8]\b|\bHO[- ]?[3568]\b(?![- ]?\d)|homeowners? program")
_DP_PRODUCT_REF_RE = re.compile(
    r"(?i)\bDP[- ]?00[- ]?0[1-3]\b|\bDP[- ]?[13]\b(?![- ]?\d)|dwelling fire program|landlord program")
_PRODUCT_REF_FLOOR = 3


def _product_mismatches():
    """{carrier: reason} for every single-product record whose document
    describes the other product, by EITHER rule. Shared by the standing check
    and its calibration test, so the two cannot drift apart."""
    collection = get_vectorstore()._collection
    found = {}
    for carrier in get_all_carriers():
        is_ho, is_dp = carrier_programs(carrier)
        if is_ho == is_dp:
            continue  # bundles both (Foremost), or no product token to check
        blob = " ".join(
            normalize_chunk_text(d)
            for d in collection.get(where={"carrier": carrier}, include=["documents"])["documents"]
        )
        ho_words = len(_SELF_DESCRIBED_HOMEOWNERS_RE.findall(blob))
        dp_words = len(_SELF_DESCRIBED_DWELLING_FIRE_RE.findall(blob))
        ho_refs = len(_HO_PRODUCT_REF_RE.findall(blob))
        dp_refs = len(_DP_PRODUCT_REF_RE.findall(blob))
        if is_ho:
            own_w, opp_w, own_r, opp_r, reads = ho_words, dp_words, ho_refs, dp_refs, "dwelling-fire/landlord"
        else:
            own_w, opp_w, own_r, opp_r, reads = dp_words, ho_words, dp_refs, ho_refs, "homeowners"
        why = []
        if opp_w >= _OPPOSITE_PRODUCT_FLOOR and opp_w >= _OPPOSITE_PRODUCT_RATIO * max(own_w, 1):
            why.append(f"word rule {opp_w} vs {own_w}")
        if own_r == 0 and opp_r >= _PRODUCT_REF_FLOOR:
            why.append(f"reference rule {opp_r} vs {own_r}")
        if why:
            found[carrier] = (f"filename says {'HO' if is_ho else 'DP'}, document reads {reads}: "
                              + "; ".join(why))
    return found


@pytest.mark.retrieval
@pytest.mark.xfail(
    reason="KNOWN DATA DEFECTS, both needing a corrected PDF, not a code change. "
    "DD-1 (round 16): NatGen_Custom360_HO3 holds the DP3 document -- caught by the WORD rule, "
    "landlord/dwelling-fire 34 times against 2 homeowners hits. "
    "DD-4 (round 17): Sage_-_Occidental_HO3 holds the 08/06/2025 revision of Occidental's "
    "DWELLING FIRE PROGRAM (DP3) guide -- caught by the REFERENCE rule, 5 references to DP3 / "
    "DP 00 03 against 0 to any HO product. Neither the duplicate-hash check (the two Occidental "
    "revisions differ byte-for-byte) nor the word rule (as tuned) saw DD-4. REMOVE THIS XFAIL "
    "MARKER once both PDFs are corrected: after that it should be a hard assert, so a future "
    "mis-ingest fails the build.",
    strict=False,
)
def test_each_document_reads_like_the_product_its_filename_claims():
    """Catches a carrier slot holding the wrong PRODUCT's document.

    Complements test_no_two_carriers_hold_the_same_document rather than
    replacing it -- the two cover different failure modes and neither
    subsumes the other:

      duplicate-hash  catches a record holding a copy of ANOTHER TRACKED
                      record's file, whatever product that file is. It is
                      the only one of the two that catches Liberty Mutual
                      HO6 (which holds the HO3 document -- still a
                      homeowners document, so its product signals agree
                      with its filename and this test is silent on it).

      this test       catches a record whose document is the wrong PRODUCT,
                      even if that file appears nowhere else in the corpus
                      -- by word counts (DD-1) or by the policy forms and
                      program name the document gives itself (DD-4, whose
                      file is a different REVISION of its sibling's guide, so
                      no hash check could ever see it).

    What NEITHER catches: a record holding the wrong document of the RIGHT
    product that is also unique -- e.g. one homeowners carrier's guide filed
    under a different homeowners carrier's name. Detecting that needs the
    carrier's own name to appear in its text, which these documents do not
    reliably do.
    """
    mismatched = _product_mismatches()
    assert not mismatched, (
        "carrier records whose document describes a different product than their filename "
        "claims -- the wrong PDF is almost certainly in that slot: "
        + "; ".join(f"{c} ({why})" for c, why in sorted(mismatched.items()))
    )


# ---------------------------------------------------------------------------
# ROUND 17 -- occupancy / ownership eligibility had no retrieval guarantee.
#
# The CHUBB backlog item ("cites the multi-unit clause instead of the
# single-family 'a house' clause", open since rounds 9-11) was a RETRIEVAL
# miss, not a reasoning one: CHUBB's Eligible Persons section spans two
# chunks and clause 2 never reached the prompt, so the model cited clause 1
# because it was the only one it was shown (16/20 recorded STANDARD runs;
# 0/20 cited clause 2). The family survey found the same silent miss on ~9
# carriers, and on Allied Trust it is verdict-bearing: its unconditional
# "Properties owned by a business, corporation, LLC ... are NOT eligible"
# did not reach the prompt for an LLC-owned property.
#
# General-rule fix, so every assertion below spans several phrasings of the
# same concept -- per CLAUDE.md, the Allied Trust "Composition Shingle" fix
# generalized to nothing because its test only knew one wording.
# ---------------------------------------------------------------------------

class _PromptCaptured(Exception):
    pass


def _captured_prompt(profile):
    """The exact user prompt check_eligibility() would send -- real retrieval,
    with the model call intercepted, so zero API cost.

    The original client method is restored in `finally`. Without that, every
    baseline test that runs after this one in the same session would hit the
    fake and fail with _PromptCaptured, which would read as a pipeline
    regression rather than a test-harness leak.
    """
    import eligibility_check as ec
    captured = {}
    original = ec.client.messages.create

    def fake(**kwargs):
        captured.update(kwargs)
        raise _PromptCaptured()

    ec.client.messages.create = fake
    try:
        check_eligibility(profile)
    except _PromptCaptured:
        pass
    finally:
        ec.client.messages.create = original
    content = captured["messages"][0]["content"]
    if not isinstance(content, str):
        content = "".join(b.get("text", "") for b in content)
    return re.sub(r"\s+", " ", content).lower()


def _norm(text):
    return re.sub(r"\s+", " ", normalize_chunk_text(text)).lower()


# (carrier, probe) -- each probe is text that exists in that carrier's own
# guide and states who or what dwelling it will insure. Several distinct
# phrasings of the one concept, which is the point.
# Occupancy rules: who lives there, what kind of dwelling. These reach EVERY
# property's prompt -- they are the CHUBB clause-2 fix for ordinary customers.
_OCCUPANCY_RULES = [
    ("CHUBB_HO_-_05.22.2026", "a house, a condominium unit"),            # dwelling-type list
    ("CHUBB_HO_-_05.22.2026", "multiple unit dwelling"),                 # multi-unit clause
    ("Allied_Trust_HO3", "owner-occupied at least nine months"),         # occupancy duration
    ("Allied_Trust_HO3", "not occupied by the named insured"),           # occupant identity
    ("Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3", "deeded to the named insured"),  # title
    ("Progressive_HO3_-_04.01.2026", "occupied by the owner and owner"),  # family occupancy
    ("Sage_-_Auros_HO3", "dwellings must be owner occupied"),            # bare requirement
    ("Sage_-_Wilshire_HO3_-_12.02.2025", "dwellings must be owner occupied"),
]

# Entity-ownership rules: reach only a Trust / LLC property's prompt (Liam's
# decision, round 17) -- such a rule cannot change an individual's verdict.
_ENTITY_OWNERSHIP_RULES = [
    ("Allied_Trust_HO3", "owned by a business, corporation, llc"),       # entity ownership
    ("Allied_Trust_HO3", "trust may not be listed as a named insured"),  # trust as insured
]


@pytest.mark.retrieval
class TestRound17OccupancyEligibilityGuarantee:

    @pytest.mark.parametrize("carrier,probe", _OCCUPANCY_RULES + _ENTITY_OWNERSHIP_RULES)
    def test_predicate_matches_every_phrasing_of_the_rule(self, carrier, probe):
        chunks = [c for c in _all_chunks(carrier) if probe in _norm(c.page_content)]
        assert chunks, f"premise: {probe!r} is in {carrier}'s guide"
        assert any(_mentions_occupancy_eligibility(c.page_content) for c in chunks)

    @pytest.mark.parametrize("carrier,probe", _OCCUPANCY_RULES)
    def test_every_occupancy_rule_matches_the_occupancy_only_predicate(self, carrier, probe):
        """The OCCUPANCY half on its own. No property uses it alone today --
        individual owners no longer get the guarantee (2026-09-28) -- but
        second homes will, once they are routed to HO carriers."""
        chunks = [c for c in _all_chunks(carrier) if probe in _norm(c.page_content)]
        assert any(_mentions_occupancy_rule(c.page_content) for c in chunks)

    @pytest.mark.parametrize("text", [
        "Dwellings must be owner occupied.",
        "Primary residences must be deeded to the named insured and owner occupied.",
        "Properties owned by an LLC are not eligible for coverage.",
        "The Trust may NOT be listed as a named insured.",
        "Residence must be occupied by the owner and owner's immediate family.",
        "I. Eligible Persons",
        "OCCUPANCY AND USE - Primary residences only.",
    ])
    def test_predicate_matches_synthetic_phrasings(self, text):
        assert _mentions_occupancy_eligibility(text)

    @pytest.mark.parametrize("text", [
        "Occupation of each Named Insured. Do they travel frequently?",
        "A credit-based insurance score of the named insured will be used in rating.",
        "The contractor is not the named insured.",
        "Prior to binding coverage, the applicant/named insured must sign the form.",
        # Allied Trust's MORTGAGE rule. An early version of the predicate
        # matched this on "trust ... not acceptable" and it won a slot over a
        # genuine occupancy rule -- caught by the whole-family test below.
        "If there is a mortgage on the property, applicants must have a mortgage through "
        "an acceptable financial institution. Private mortgages, land contracts, trust "
        "and/or bond for deeds are not acceptable.",
    ])
    def test_predicate_ignores_named_insured_noise(self, text):
        """Bare 'named insured' is mostly noise across this corpus. Matching
        it would spend the per-carrier cap on jewelry-schedule questions,
        credit-score text and financing rules instead of the rule that
        decides eligibility."""
        assert not _mentions_occupancy_eligibility(text)

    @pytest.mark.parametrize("ownership,carrier,probe", [
        ("LLC", "Allied_Trust_HO3", "owned by a business, corporation, llc"),
        ("Trust", "Allied_Trust_HO3", "trust may not be listed as a named insured"),
        ("Individual Owner", "CHUBB_HO_-_05.22.2026", "a house, a condominium unit"),
        ("Individual Owner", "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3", "deeded to the named insured"),
    ])
    def test_the_decisive_rule_survives_the_cap_for_this_ownership_type(self, ownership, carrier, probe):
        """Uses the production predicate AND cap for each ownership type, not a
        copy of either. Without an ownership-aware priority, an LLC property
        can fill the cap with owner-occupancy chunks and drop the
        business-ownership exclusion -- the one rule actually in question."""
        kept = guaranteed_carrier_lookup(
            get_vectorstore()._collection, carrier,
            predicate=_occupancy_predicate_for(ownership),
            keep=_occupancy_cap_for(ownership),
            priority_key=_occupancy_priority_key(ownership),
        )
        assert any(probe in _norm(c.page_content) for c in kept), (
            f"{carrier}'s {probe!r} did not survive the cap for ownership={ownership}"
        )

    def test_a_table_of_contents_line_sorts_last(self):
        """CHUBB's index ("I. Eligible Person 2-3 II. Physical Conditions
        4-5 ...") matches on the heading alone and carries no rule."""
        toc = Document(page_content=(
            "Index Page I. Eligible Person 2-3 II. Physical Conditions 4-5 "
            "III. Underwriting 5 IV. Claim History 5-6"))
        rule = Document(page_content="2. A person who is the owner-occupant of a house is eligible.")
        key = _occupancy_priority_key("Individual Owner")
        assert key(rule) < key(toc)

    @pytest.mark.parametrize("ownership", ["Trust", "LLC"])
    def test_chubb_clause_2_reaches_the_prompt_where_the_guarantee_runs(self, ownership):
        """THE ORIGINAL AUDIT SCENARIO, on the properties the guarantee still
        runs for. Before it, clause 2 was absent from the STANDARD prompt on
        every run, so no model could cite it."""
        assert "a house, a condominium unit" in _captured_prompt(
            dict(STANDARD_PROFILE, ownership_type=ownership))

    def test_chubb_clause_2_is_back_to_mains_behaviour_for_an_individual_owner(self):
        """Liam, 2026-09-28: an individual owner's prompt is exactly main's,
        where clause 2 did not reach STANDARD. Pinned so a change that quietly
        re-enables the guarantee for individuals shows up here by name."""
        assert "a house, a condominium unit" not in _captured_prompt(STANDARD_PROFILE)

    @pytest.mark.parametrize("ownership", ["Trust", "LLC"])
    def test_the_whole_family_reaches_the_prompt_for_every_ownership_type(self, ownership):
        """Every project profile is "Individual Owner", so before round 17 no
        baseline, sweep or audit had ever exercised the Trust or LLC intake
        options. Measured before the fix: 2 of 21 (rule x ownership) checks
        reached the prompt.

        No carve-outs, deliberately. At a cap of 3 this test needed an LLC
        exception for Allied Trust's nine-month rule, and it was a trap: the
        exception hid that the cap was also truncating the entire Sage family
        and CHUBB, which only surfaced once the cap was swept properly (see
        MAX_OCCUPANCY_CHUNKS_PER_CARRIER). Every rule, every ownership type.

        Individual Owner is no longer a case: since 2026-09-28 the guarantee
        runs for Trust and LLC only, and the individual-owner prompt is pinned
        to main's by test_the_guarantee_adds_nothing_for_an_individual_owner."""
        prompt = _captured_prompt(dict(STANDARD_PROFILE, ownership_type=ownership))
        expected = _OCCUPANCY_RULES + _ENTITY_OWNERSHIP_RULES
        missing = [f"{c}: {p!r}" for c, p in expected if p not in prompt]
        assert not missing, "occupancy rules missing from the prompt:\n  " + "\n  ".join(missing)

    def test_allied_trust_llc_exclusion_reaches_the_prompt_for_an_llc_property(self):
        """The verdict-bearing case, on its own so it is named in the output.
        The chunk says "LLC" VERBATIM and embedding retrieval still missed it
        for an LLC query -- the strongest evidence that this topic needs a
        keyword guarantee rather than a better query."""
        prompt = _captured_prompt(dict(STANDARD_PROFILE, ownership_type="LLC"))
        assert "owned by a business, corporation, llc" in prompt


class _CallRecorder:
    """Record every model call made during a pipeline run -- test-side only,
    no product change. Per call: wall-clock seconds (INCLUDING any SDK retries,
    since that is what an agent waits through), input / output / cache
    tokens, stop reason, and the RAW model text before any post-generation
    backstop rewrites it. The raw text is what makes a future OQ-1 recurrence
    diagnosable -- the round-17 Travelers one was caught by the backstop and
    nothing of it was kept."""

    def __init__(self):
        self.calls = []

    def __enter__(self):
        import time
        import eligibility_check as ec
        self._ec, self._real = ec, ec.client.messages.create

        def recorded(**kwargs):
            t0 = time.perf_counter()
            resp = self._real(**kwargs)
            u = resp.usage
            self.calls.append({
                "api_seconds": round(time.perf_counter() - t0, 2),
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
                "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
                "stop_reason": resp.stop_reason,
                "raw_text": "".join(b.text for b in resp.content if getattr(b, "type", "") == "text"),
            })
            return resp

        ec.client.messages.create = recorded
        return self

    def __exit__(self, *exc):
        self._ec.client.messages.create = self._real


def _recorded_run(profile):
    """One full check_eligibility() run: (results, record). The record holds
    the pipeline's end-to-end seconds and every model call's usage."""
    import time
    with _CallRecorder() as rec:
        t0 = time.perf_counter()
        results = check_eligibility(profile)
        total = round(time.perf_counter() - t0, 2)
    return results, {"pipeline_seconds": total, "calls": rec.calls}


def _dump_runs(path, profile, runs):
    import json, subprocess
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, cwd=os.path.dirname(__file__)).stdout.strip()
    except Exception:
        commit = "unknown"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"commit": commit, "profile": profile, "runs": runs}, fh, indent=1,
                  ensure_ascii=False)


def _dump_path(name):
    # verification/*_results.json is git-ignored, so none of this is committed.
    return os.path.join(os.path.dirname(__file__), f"{name}_results.json")


# ---- CHUBB eligible persons: three separate questions, scored separately ----

_CHUBB_CLAUSE_1_RE = re.compile(r"multiple[- ]unit|multi-unit|two residential units|clause 1\b", re.I)
_CHUBB_CLAUSE_2_CITE_RE = re.compile(r"a house, a condominium unit|owner-occupant or tenant", re.I)
# "Clause 1 does not apply" must NOT read as "clause 1 is satisfied". The
# old check (multiple[- ]unit dwelling ... satisf|meet|qualif|eligible) fired
# on exactly that contrast -- a correct answer the fix itself made likely.
_SETS_ASIDE_RE = re.compile(
    r"\b(?:does not|doesn't|do not|not)\s+(?:apply|applicable|relevant|a multiple|multi)"
    r"|\bn/a\b|\binapplicable\b|\bnot applicable\b|\brather than\b|\binstead\b"
    r"|\bonly (?:applies|covers)\b|\bapplies only\b|\bnot a multiple\b|\birrelevant\b", re.I)
_SATISFIED_RE = re.compile(r"satisf|\bmeets?\b|qualif|complies|is eligible|are eligible", re.I)


def _chubb_clause_1_stance(r):
    """Per reason item (and per notes sentence): "claims satisfied" if one
    mentions clause 1 and concludes it is met WITHOUT setting it aside;
    "sets aside" if one mentions clause 1 and says it does not apply; else
    "not discussed". A claim anywhere outranks a set-aside elsewhere."""
    units = list(r.get("reasons", [])) + re.split(r"(?<=[.!?])\s+", r.get("notes", "") or "")
    stance = "not discussed"
    for u in units:
        if not _CHUBB_CLAUSE_1_RE.search(u):
            continue
        if _SETS_ASIDE_RE.search(u):
            stance = "sets aside" if stance == "not discussed" else stance
        elif _SATISFIED_RE.search(u):
            return "claims satisfied"
    return stance


def _score_chubb_runs(runs):
    """Pure: one row per run answering (a) status, (b) clause 2 cited, (c) the
    stance on clause 1. (a) passes unless CHUBB is declined ON the eligible-
    persons rule -- its status on STANDARD also depends on unrelated rules."""
    rows = []
    for run in runs:
        matches = [x for x in run["results"] if "CHUBB" in x.get("carrier", "").upper()]
        if len(matches) != 1:
            rows.append({"resolved": False})
            continue
        r = matches[0]
        cites = " ".join(r.get("citations", []))
        declined_on_persons = r.get("status") == "INELIGIBLE" and bool(re.search(
            r"eligible persons|owner-occupant|multiple[- ]unit", " ".join(r.get("reasons", [])), re.I))
        rows.append({
            "resolved": True,
            "status": r.get("status"),
            "a_status_ok": not declined_on_persons,
            "b_clause_2_cited": bool(_CHUBB_CLAUSE_2_CITE_RE.search(cites)),
            "b_clause_1_cited": bool(_CHUBB_CLAUSE_1_RE.search(cites)),
            "c_clause_1_stance": _chubb_clause_1_stance(r),
        })
    return rows


@pytest.mark.retrieval
@pytest.mark.parametrize("reason,expected", [
    # Round 15's recorded failure shape: clause 1 applied as if met.
    ("The carrier states a person who is the owner-occupant of a multiple unit dwelling of not "
     "more than two residential units is eligible. This property is owner-occupied, which "
     "satisfies this requirement.", "claims satisfied"),
    # The contrast a CORRECT answer makes -- the old regex failed this.
    ("The multiple unit dwelling clause does not apply; the home is eligible under clause 2.",
     "sets aside"),
    ("Clause 1 covers multi-unit dwellings and is not applicable here; the owner-occupant of a "
     "house is eligible under clause 2.", "sets aside"),
    ("An owner-occupant of a house is eligible for home insurance.", "not discussed"),
])
def test_chubb_clause_1_stance_tells_satisfied_from_set_aside(reason, expected):
    """Pins the reasoning classifier. A check that cannot tell "satisfies
    clause 1" from "clause 1 does not apply" would fail the fix for doing
    exactly what it should."""
    assert _chubb_clause_1_stance({"reasons": [reason], "notes": ""}) == expected


_CHUBB_ELIGIBLE_PERSONS_FRAGMENTS = (
    "owner-occupant of a multiple unit dwelling",            # clause 1
    "owner-occupant or tenant of a dwelling",                # clause 2
)
_DWELLING_TYPE_ASSERTED_RE = re.compile(
    r"\b(?:this|the)\s+(?:property|home|dwelling|house|residence|risk)\s+(?:is|is a|being)\s+"
    r"(?:an?\s+)?(?:single[- ]family|one[- ]unit|two[- ]unit|two[- ]family|duplex|multi[- ]?(?:unit|family))",
    re.I)


def _invents_dwelling_type(r):
    """True if the reasoning states a dwelling type or unit count as a fact
    about THIS property. The intake never gives one, so any such statement is
    invented -- the round-15 shape ("this single-family home satisfies the
    multiple-unit clause") is the case that matters."""
    units = list(r.get("reasons", [])) + re.split(r"(?<=[.!?])\s+", r.get("notes", "") or "")
    return any(_DWELLING_TYPE_ASSERTED_RE.search(u) for u in units)


@pytest.fixture(scope="module")
def chubb_standard_runs():
    """Three recorded STANDARD runs, made ONCE and scored by every CHUBB test
    below -- so one set of calls answers (a), (b) and (c). Dumped first.

    REUSE_DUMPS=1 re-scores the existing dump instead of paying for new runs
    -- the point of dumping. Its commit is printed, so a stale dump is visible."""
    import json
    path = _dump_path("chubb_consistency")
    if os.environ.get("REUSE_DUMPS") and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            dumped = json.load(fh)
        print(f"\nCHUBB: re-scoring dump from commit {dumped['commit']} ({len(dumped['runs'])} runs)")
        return dumped["runs"]
    runs = []
    for _ in range(3):
        results, rec = _recorded_run(STANDARD_PROFILE)
        runs.append({"results": results, **rec})
        _dump_runs(_dump_path("chubb_consistency"), STANDARD_PROFILE, runs)
    rows = _score_chubb_runs(runs)
    print(f"\nCHUBB over {len(runs)} STANDARD runs (raw: {_dump_path('chubb_consistency')}):")
    for i, row in enumerate(rows, 1):
        print(f"   run {i}: {row}")
    return runs


def _chubb(run):
    matches = [x for x in run["results"] if "CHUBB" in x.get("carrier", "").upper()]
    assert len(matches) == 1, f"CHUBB not uniquely resolved: {[x.get('carrier') for x in matches]}"
    return matches[0]


# CHUBB's eligible-persons question, reclassified in round 17. The intake has
# no dwelling-type or unit-count field, and CHUBB's two clauses split exactly
# on that fact: clause 1 an owner-occupant of a dwelling of <=2 units, clause
# 2 an owner-occupant of a house, condo, etc. BOTH make an owner-occupant
# eligible. Citing clause 1 is one of two valid answers to what the model is
# actually told, so it is recorded, not failed. What IS a defect is the model
# inventing the missing fact -- the round-15 shape.

@pytest.mark.baseline
def test_chubb_eligible_persons_never_decides_a_decline(chubb_standard_runs):
    """(a), as far as eligible persons determines it: an owner-occupant
    satisfies either clause, so CHUBB must never be declined on this rule."""
    for run in chubb_standard_runs:
        r = _chubb(run)
        assert not (r.get("status") == "INELIGIBLE" and re.search(
            r"eligible persons|owner-occupant|multiple[- ]unit", " ".join(r.get("reasons", [])), re.I)), r


@pytest.mark.baseline
@pytest.mark.xfail(
    reason="ACCEPTED WITH LIAM'S 2026-09-28 DECISION, not a new regression: the guarantee now runs "
    "for Trust/LLC only, so this individual-owner STANDARD prompt is main's again, without clause 2. "
    "Measured rates: main's prompt invented a dwelling type in 3/20 round-15 runs; with clause 2 "
    "present, 0/3. Non-strict: a 3-run fixture at ~15%/run passes most of the time.",
    strict=False,
)
def test_chubb_reasoning_never_invents_a_dwelling_type(chubb_standard_runs):
    """(c) -- the only part of the old backlog item that is a real reasoning
    error. Round 15's recorded runs did it 3/20."""
    for run in chubb_standard_runs:
        r = _chubb(run)
        assert _chubb_clause_1_stance(r) != "claims satisfied", r.get("reasons")
        assert not _invents_dwelling_type(r), r.get("reasons")


@pytest.mark.baseline
def test_chubb_eligible_persons_citations_come_from_that_section(chubb_standard_runs, record_property):
    """(b), as a correctness check rather than a clause preference: WHEN the
    model cites an eligible-persons rule, it must be one of CHUBB's two
    clauses, verbatim. Which one -- and whether it cites one at all -- is
    recorded for information only."""
    cited = []
    for run in chubb_standard_runs:
        r = _chubb(run)
        persons = [c for c in r.get("citations", []) if re.search(r"owner-occupant|eligible person", c, re.I)]
        for c in persons:
            assert any(_compare_key(f) in _compare_key(c) for f in _CHUBB_ELIGIBLE_PERSONS_FRAGMENTS), c
        cited.append("clause 2" if any(_compare_key(_CHUBB_ELIGIBLE_PERSONS_FRAGMENTS[1]) in _compare_key(c) for c in persons)
                     else "clause 1" if persons else "none")
    print(f"\n   CHUBB eligible-persons citation per run (informational): {cited}")
    record_property("chubb_eligible_persons_citation", ",".join(cited))


@pytest.mark.baseline
@pytest.mark.xfail(
    reason="NOT DECIDABLE FROM THE CURRENT INTAKE, not a model error. CHUBB's clause 1 (owner-"
    "occupant of a dwelling of <=2 units) and clause 2 (owner-occupant of a house, condo, ...) "
    "split on dwelling type / unit count, and the intake collects neither. This asserts clause "
    "2, which presumes single-family -- a fact the model is never given. Whether to add a "
    "dwelling-type field is a product decision for Liam; no prompt text should push the model "
    "to assume single-family.",
    strict=False,
)
def test_chubb_cites_the_clause_matching_the_dwelling_type(chubb_standard_runs):
    for run in chubb_standard_runs:
        assert _CHUBB_CLAUSE_2_CITE_RE.search(" ".join(_chubb(run).get("citations", [])))


@pytest.mark.baseline
def test_chubb_without_coverage_a_is_insufficient_and_says_why(chubb_standard_runs):
    """CHANGED DELIBERATELY (Liam, 2026-09-30). This was an xfail asserting
    CHUBB should NOT be INSUFFICIENT_INFORMATION on STANDARD, on the reading
    that its tiers only set pricing. That reading was incomplete: for a
    primary house the Standard Tier's minimum-coverages row reads "Subject to
    pre-approval" below the $1,000,000 minimum of the discounted tiers, and
    wildfire class, Flood Zone and loss history also decide placement -- none
    of which the form asks for. With Dwelling amount blank, INSUFFICIENT
    with Coverage A named is now the pipeline's deterministic answer
    (_apply_chubb_hold). Under REUSE_DUMPS the recorded pre-hold runs are
    re-scored, so this checks the status only there."""
    import os as _os
    for run in chubb_standard_runs:
        r = _chubb(run)
        assert r.get("status") == "INSUFFICIENT_INFORMATION", r.get("status")
        if not _os.environ.get("REUSE_DUMPS"):
            assert _CHUBB_COVERAGE_A_ITEM in r.get("missing_info", [])


@pytest.mark.retrieval
@pytest.mark.parametrize("topic,pattern", [
    ("PPC / protection class", r"protection class|\bppc\b|\bfpc\b"),
    ("roof age", r"roof[^.]{0,40}(?:age|years? old)|age of (?:the )?roof"),
    ("swimming pool", r"swimming|\bpool"),
])
def test_chubb_guide_has_no_ppc_roof_age_or_pool_rule(topic, pattern):
    """Pins the premise of the xfail above. If CHUBB's guide is re-uploaded
    with one of these rules, this fails and that xfail must be revisited --
    its reasons would then be legitimate rather than silence."""
    text = " ".join(normalize_chunk_text(c.page_content) for c in _all_chunks("CHUBB_HO_-_05.22.2026"))
    assert not re.search(pattern, text, re.I), f"CHUBB's guide now states a {topic} rule"




def _score_allied_llc_runs(runs):
    """Pure: INELIGIBLE, on Allied Trust's OWN verbatim entity exclusion."""
    frag = _compare_key("owned by a business, corporation, llc")
    out = []
    for run in runs:
        found, _ = _resolve_results(run["results"], ["Allied_Trust_HO3"])
        r = found.get("Allied_Trust_HO3")
        if r is None:
            out.append({"resolved": False})
            continue
        out.append({"resolved": True, "status": r.get("status"),
                    "own_rule_cited": any(frag in _compare_key(c) for c in r.get("citations", []))})
    return out


@pytest.mark.baseline
def test_allied_trust_llc_is_ineligible_on_its_own_rule_consistency(record_property):
    """An LLC-owned property must be INELIGIBLE at Allied Trust, on Allied
    Trust's OWN verbatim business-ownership exclusion -- not merely on
    SYSTEM_INSTRUCTIONS' general "most HO3 carriers do not accept LLC" line.
    The verbatim fragment replaced a keyword match, which Allied Trust's own
    unrelated "BUSINESS EXPOSURE" rule could satisfy."""
    n_runs = 3
    profile = dict(STANDARD_PROFILE, ownership_type="LLC")
    runs = []
    for _ in range(n_runs):
        results, rec = _recorded_run(profile)
        runs.append({"results": results, **rec})
        _dump_runs(_dump_path("allied_llc_consistency"), profile, runs)
    rows = _score_allied_llc_runs(runs)
    print(f"\nAllied Trust LLC over {n_runs} runs (raw: {_dump_path('allied_llc_consistency')}): {rows}")
    ok = [r["resolved"] and r["status"] == "INELIGIBLE" and r["own_rule_cited"] for r in rows]
    record_property("allied_trust_llc_pass_rate", sum(ok) / n_runs)
    assert all(ok), rows


# ---------------------------------------------------------------------------
# ROUND 17 (cont.) -- Trust and LLC ownership: real profile coverage.
#
# The occupancy guarantee above proved the rules REACH the model. It did not
# prove the model reasons to the right verdict once they do -- and before this
# no profile in the project had ever used ownership_type "Trust" or "LLC", so
# there was no evidence either way.
#
# Every expectation below was read from the carrier's own text AND the heading
# it sits under (the Mercury flat-roof lesson: a phrase means what its heading
# says). The family does NOT share one rule, which is why assuming Allied
# Trust's shape everywhere would have been wrong:
#
#   LLC, flat exclusion -> INELIGIBLE on the carrier's own rule
#     Allied Trust ("...LLC, partnership, estates or land trusts etc., are NOT
#     eligible"), Progressive HO3, Sage Auros / SURE / SafePort / Trium /
#     Wilshire ("non-individual owned properties are ineligible"), Mercury
#     (item x under "The following risks are ineligible"), Orion ("f.
#     Ownership" under "INELGIBLE RISKS"), Liberty Mutual HO3 (under
#     "Ineligible Risks", before "Refer to Underwriting").
#
#   LLC, permitted / conditional / referral -> must NOT be declined on it
#     Sage Markel ("Residence held by corporations, including LLCs, is
#     eligible"), Sage Vave (tax/real-estate holding entities), Foremost ("the
#     only eligible business ... is an LLC" if no business in the name),
#     NatGen Premier (ineligible only when owning more than 10 dwellings),
#     Travelers (only with business/commercial exposure), Swyfft Benchmark x2
#     and Topa and Lloyds ("Check with us first ... underwriting approval"),
#     Progressive HO6 (condo LLC exception with prior approval).
#
#   Trust -> no carrier here flatly excludes a family/living trust
#     Who must LIVE there differs: Allied Trust the grantor; Foremost the
#     grantor and/or trustee; the Sage family trustee, grantor OR beneficiary.
#     Progressive and the Swyfft programs REFER any trust to underwriting.
#     Mercury excludes only a "Corporate Trust". Land trusts are excluded by
#     Allied Trust, Progressive and Foremost -- a different thing.
#
# EXCLUDED, wrong document on file: Sage_-_Occidental_HO3 holds an older
# revision of Occidental's DP3 dwelling-fire guide (header "DWELLING FIRE
# PROGRAM (DP3)", policy form DP 00 03, 84% text overlap with the DP3 record);
# Liberty_Mutual_HO6 and NatGen_Custom360_HO3 are the round-16 DD-2 / DD-1
# records. An expectation built on the wrong document would test nothing.
# ---------------------------------------------------------------------------

from profiles import OWNERSHIP_BASE_PROFILE

_LLC_FLAT_EXCLUSION = [
    "Allied_Trust_HO3",
    "Progressive_HO3_-_04.01.2026",
    "Sage_-_Auros_HO3",
    "Sage_-_SURE_HO-3_-_01.31.2026",
    "Sage_-_SafePort_HO-3_-_01.31.2026",
    "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026",
    "Sage_-_Wilshire_HO3_-_12.02.2025",
    "Mercury_HO3_-_01.01.2026",
    "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3",
    "Liberty_Mutual_HO3_-_02.21.2026",
]
_LLC_NOT_A_FLAT_DECLINE = [
    "Sage_-_Markel_HO3",
    "Sage_-_Vave_HO3_-_07.01.2026",
    "Foremost_DP3_and_HO3_-_07.01.2026",
    "NatGen_Premier_OneChoice_HO3_-_02.26.2025",
    "Travelers_HO3_-_06.12.2026",
    "Swyfft_-_Benchmark_(Admitted)_HO3",
    "Swyfft_-_Benchmark_(Surplus)_HO3",
    "Swyfft_-_Topa_(Surplus)_HO3",
    "Swyfft_-_Lloyds_(Surplus)_HO3",
    "Progressive_HO6_-_10.01.2025",
]
_TRUST_NOT_A_DECLINE = [
    "Allied_Trust_HO3",
    "Progressive_HO3_-_04.01.2026",
    "Progressive_HO6_-_10.01.2025",
    "Sage_-_Auros_HO3",
    "Sage_-_SURE_HO-3_-_01.31.2026",
    "Sage_-_SafePort_HO-3_-_01.31.2026",
    "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026",
    "Sage_-_Wilshire_HO3_-_12.02.2025",
    "Sage_-_Vave_HO3_-_07.01.2026",
    "Sage_-_Markel_HO3",
    "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3",
    "Foremost_DP3_and_HO3_-_07.01.2026",
    "TWICO_HO3",
    "Travelers_HO3_-_06.12.2026",
    "Swyfft_-_Benchmark_(Admitted)_HO3",
    "Swyfft_-_Benchmark_(Surplus)_HO3",
    "Swyfft_-_Topa_(Surplus)_HO3",
    "Swyfft_-_Lloyds_(Surplus)_HO3",
    "Mercury_HO3_-_01.01.2026",
]
# The carrier's own text explicitly routes a trust to underwriting.
_TRUST_REFERRAL = [
    "Allied_Trust_HO3",               # "Residence Held in Trust | Submit for Approval with Trust documents"
    "Progressive_HO3_-_04.01.2026",   # "must be referred to Underwriting for prior Underwriting approval"
    "Progressive_HO6_-_10.01.2025",
    "Swyfft_-_Benchmark_(Admitted)_HO3",  # "Check with us first. You'll need underwriting approval"
    "Swyfft_-_Benchmark_(Surplus)_HO3",
    "Swyfft_-_Topa_(Surplus)_HO3",
    "Swyfft_-_Lloyds_(Surplus)_HO3",
]

# (carrier or None, verbatim source fragment). None = fragment is unique to
# one guide, so matching the whole prompt is enough; a carrier is named where
# several guides share the wording (the Sage and Swyfft families).
_LLC_RULE_PROBES = {
    "Allied Trust": (None, "owned by a business, corporation, llc"),
    "Progressive HO3": (None, "in the name of a business, limited liability corporation"),
    "Sage Auros": ("Sage_-_Auros_HO3", "non-individual owned properties are ineligible"),
    "Sage SURE": ("Sage_-_SURE_HO-3_-_01.31.2026", "non-individual owned properties are ineligible"),
    "Sage SafePort": ("Sage_-_SafePort_HO-3_-_01.31.2026", "non-individual owned properties are ineligible"),
    "Sage Trium": ("Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026", "non-individual owned properties are ineligible"),
    "Sage Wilshire": ("Sage_-_Wilshire_HO3_-_12.02.2025", "non-individual owned properties are ineligible"),
    "Mercury": (None, "properties owned by an llc, corporation"),
    "Orion": (None, "deeded to or owned by a corporation, limited liability company"),
    "Liberty Mutual HO3": (None, "buildings owned by a corporation, company, llc"),
    "Sage Markel": (None, "including llcs, is eligible"),
    "Sage Vave": (None, "in the name of an llc, llp, or corporation are only eligible"),
    "Foremost": (None, "the only eligible business"),
    "NatGen Premier": (None, "llcs owning more than 10 dwellings"),
    "Travelers": (None, "any type of non-personal entity"),
    "Swyfft Benchmark A": ("Swyfft_-_Benchmark_(Admitted)_HO3", "homes in the name of a trust or llc"),
    "Swyfft Benchmark S": ("Swyfft_-_Benchmark_(Surplus)_HO3", "homes in the name of a trust or llc"),
    "Swyfft Topa": ("Swyfft_-_Topa_(Surplus)_HO3", "homes in the name of a trust or llc"),
    "Swyfft Lloyds": (None, "if home is in the name of a corp, llc or llp"),
    "Progressive HO6": (None, "exceptions may be granted to condominium units written in the name of an llc"),
}
_TRUST_RULE_PROBES = {
    "Allied Trust, conditional clause": (None, "owned in the name of a trust are eligible if the grantor"),
    "Allied Trust, approval table": (None, "submit for approval with trust documents"),
    "Progressive HO3": (None, "owned in the name of a trust or ira must be referred"),
    "Progressive HO6": (None, "must be referred to underwriting for prior approval"),
    "Sage Auros": ("Sage_-_Auros_HO3", "residence held in trust if the residence is occupied by the trustee"),
    "Sage SURE": ("Sage_-_SURE_HO-3_-_01.31.2026", "residence held in trust if the residence is occupied by the trustee"),
    "Sage SafePort": ("Sage_-_SafePort_HO-3_-_01.31.2026", "residence held in trust if the residence is occupied by the trustee"),
    "Sage Trium": ("Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026", "residence held in trust if the residence is occupied by the trustee"),
    "Sage Wilshire": ("Sage_-_Wilshire_HO3_-_12.02.2025", "residence held in trust if the residence is occupied by the trustee"),
    "Sage Vave": (None, "in the name of a trust are eligible only when"),
    "Sage Markel": (None, "residence held in trust is eligible"),
    "Orion": (None, "titled in the name of a revocable living trust"),
    "Foremost": (None, "residing in the home must be the grantor"),
    "TWICO": (None, "trusts must be in the name of the trustee"),
    "Travelers": (None, "any type of non-personal entity"),
    "Swyfft Benchmark A": ("Swyfft_-_Benchmark_(Admitted)_HO3", "homes in the name of a trust or llc"),
    "Swyfft Benchmark S": ("Swyfft_-_Benchmark_(Surplus)_HO3", "homes in the name of a trust or llc"),
    "Swyfft Topa": ("Swyfft_-_Topa_(Surplus)_HO3", "homes in the name of a trust or llc"),
    "Swyfft Lloyds": ("Swyfft_-_Lloyds_(Surplus)_HO3", "homes in the name of a trust"),
    "Mercury": (None, "and/or corporate trust"),
}

_SECTIONS_CACHE = {}


def _captured_sections(profile):
    """({carrier: normalized text of its prompt sections}, whole prompt), with
    the model call intercepted -- zero API cost. Cached per profile, since
    retrieval is deterministic and several tests read the same prompt."""
    key = tuple(sorted(profile.items()))
    if key not in _SECTIONS_CACHE:
        import eligibility_check as ec
        captured = {}
        original = ec.client.messages.create

        def fake(**kwargs):
            captured.update(kwargs)
            raise _PromptCaptured()

        ec.client.messages.create = fake
        try:
            check_eligibility(profile)
        except _PromptCaptured:
            pass
        finally:
            ec.client.messages.create = original
        content = captured["messages"][0]["content"]
        if not isinstance(content, str):
            content = "".join(b.get("text", "") for b in content)
        per = {}
        for name, body in re.findall(
                r"\n--- (.+?) \(page [^)]*\) ---\n(.*?)(?=\n--- |\nCARRIERS WITH NO|\Z)", content, re.S):
            per[name] = per.get(name, "") + " " + re.sub(r"[\s|]+", " ", body).lower()
        _SECTIONS_CACHE[key] = (per, re.sub(r"[\s|]+", " ", content).lower())
    return _SECTIONS_CACHE[key]


_SECTIONS_WITHOUT_CACHE = {}


def _captured_sections_patched(profile, **patches):
    """_captured_sections with pipeline attributes temporarily replaced, to
    tell what one mechanism adds from what other retrieval paths bring.
    Cached per (profile, patch names); never pollutes the unpatched cache;
    restored in finally."""
    key = (tuple(sorted(profile.items())), tuple(sorted(patches)))
    if key not in _SECTIONS_WITHOUT_CACHE:
        import eligibility_check as ec
        plain = tuple(sorted(profile.items()))
        real = {name: getattr(ec, name) for name in patches}
        saved = _SECTIONS_CACHE.pop(plain, None)
        for name, value in patches.items():
            setattr(ec, name, value)
        try:
            _SECTIONS_WITHOUT_CACHE[key] = _captured_sections(profile)
        finally:
            for name, value in real.items():
                setattr(ec, name, value)
            _SECTIONS_CACHE.pop(plain, None)   # never let a patched capture be reused
            if saved is not None:
                _SECTIONS_CACHE[plain] = saved
    return _SECTIONS_WITHOUT_CACHE[key]


def _captured_sections_without_occupancy_guarantee(profile):
    """The same capture with the occupancy guarantee switched off entirely."""
    return _captured_sections_patched(profile, _occupancy_guarantee_applies=lambda details: False)


def _unreached(ownership, probes):
    per, whole = _captured_sections(dict(OWNERSHIP_BASE_PROFILE, ownership_type=ownership))
    return [label for label, (carrier, text) in probes.items()
            if text not in (per.get(carrier, "") if carrier else whole)]


@pytest.mark.retrieval
class TestRound17OwnershipRuleRetrieval:

    @pytest.mark.parametrize("text", [
        "Residence held in trust is eligible.",
        "Residence held by corporations, including LLCs, is eligible.",
        "Properties owned in the name of a trust are eligible if the grantor(s) are still residing in the dwelling.",
        "Homes in the name of a Trust or LLC",
        "Risks written in the name of an LLC, LLP, or corporation are only eligible when the following criteria are met.",
        "Dwellings titled in the name of a Revocable Living Trust are eligible.",
        "Individuals, corporations, LLCs, trusts, or estates allowed on title.",
        "Any type of non-personal entity (e.g. Trust, LLC, etc.) with any business exposure.",
    ])
    def test_permissive_and_conditional_ownership_rules_match(self, text):
        """The first cut of the predicate was built from EXCLUSION language
        only, so rules that permit or condition ownership never matched -- and
        for an LLC or trust property those are the rules that prevent a wrong
        decline. Eight phrasings, one concept."""
        assert _mentions_occupancy_eligibility(text)

    @pytest.mark.parametrize("text", [
        # financing, not ownership -- Allied Trust's mortgage rule, second wording
        "Individuals as mortgagees, deeds of trust and/or bond for deeds are not acceptable.",
        # how the home was bought, not who owns it -- and "trustee" is not "trust"
        "Dwellings purchased at, from or through foreclosure, bank or trustee sale are only acceptable if the insured provides an appraisal.",
        # an endorsement NAME in a list, no rule
        "Trust Endorsement Scheduled Personal Property Service Line Enhancement",
        # the program manager's own corporate name
        "SAGESURE INSURANCE MANAGERS LLC A Licensed Property Casualty Insurance Agency",
        "SageSure Insurance Managers LLC does not guarantee the completeness and accuracy of its contents.",
        "MIC General Insurance Corporation Edition Date: 08/01/2016 Form Number: 13942",
    ])
    def test_entity_words_in_other_roles_do_not_match(self, text):
        """Widening the predicate to permissive language is only safe if an
        entity word in some OTHER role stays out."""
        assert not _mentions_occupancy_eligibility(text)

    def test_a_carriers_own_brand_is_not_an_ownership_signal(self):
        """Every Allied Trust chunk says "Allied Trust". Before brand stripping,
        a Trust profile boosted all of that carrier's chunks equally, so the
        ownership-aware ranking did nothing for the one carrier whose trust
        rule it most needed to surface."""
        key = _occupancy_priority_key("Trust")
        brand_only = Document(
            page_content="Allied Trust does NOT accept galvanized plumbing. Homes not occupied by the named insured are ineligible.",
            metadata={"carrier": "Allied_Trust_HO3"})
        real_trust = Document(
            page_content="Properties owned in the name of a trust are eligible if the grantor(s) are still residing in the dwelling.",
            metadata={"carrier": "Allied_Trust_HO3"})
        assert key(real_trust) < key(brand_only)

    @pytest.mark.parametrize("text,is_ownership", [
        ("Properties owned by a business, corporation, LLC are NOT eligible.", True),
        ("Homes in the name of a Business are ineligible.", True),
        ("Scheduled property used in any insured's business or profession is not eligible for this coverage.", False),
        ("Business Exposures other than Permitted Incidental Office Occupancy are ineligible.", False),
    ])
    def test_business_counts_as_ownership_only_when_it_is_the_owner(self, text, is_ownership):
        """Bare "business" boosted Allied Trust's scheduled-personal-property
        rule over its genuine occupancy rules for an LLC profile."""
        key = _occupancy_priority_key("LLC")
        boosted = key(Document(page_content=text, metadata={"carrier": "X"}))[0] is False
        assert boosted is is_ownership

    # ---- the gate (Liam's decisions, round 17 and 2026-09-28), both ways ----

    @pytest.mark.parametrize("ownership,applies", [
        ("Individual Owner", False), ("Trust", True), ("LLC", True), ("", False),
    ])
    def test_the_guarantee_runs_for_trust_and_llc_only(self, ownership, applies):
        assert _occupancy_guarantee_applies(dict(STANDARD_PROFILE, ownership_type=ownership)) is applies

    @pytest.mark.parametrize("profile", [STANDARD_PROFILE, ALT_PROFILE, COASTAL_PPC4_PROFILE,
                                         OWNERSHIP_BASE_PROFILE],
                             ids=["STANDARD", "ALT", "COASTAL_PPC4", "OWNERSHIP_BASE"])
    def test_the_guarantee_adds_nothing_for_an_individual_owner(self, profile):
        """Liam, 2026-09-28: individual-owner checks go back to exactly what
        main does. Measured once against 72e34db itself -- the whole captured
        request, every field, byte-identical on all four profiles. This is the
        DB-independent form of that claim, so it survives a re-upload: with
        the guarantee switched off entirely, nothing in the prompt changes."""
        prof = dict(profile, ownership_type="Individual Owner")
        assert _captured_sections(prof) == _captured_sections_without_occupancy_guarantee(prof)

    @pytest.mark.parametrize("ownership", ["Trust", "LLC"])
    def test_the_guarantee_still_adds_rules_for_trust_and_llc(self, ownership):
        """The other half, so the gate cannot be satisfied by switching the
        guarantee off for everyone."""
        prof = dict(OWNERSHIP_BASE_PROFILE, ownership_type=ownership)
        assert _captured_sections(prof) != _captured_sections_without_occupancy_guarantee(prof)

    def test_each_ownership_type_gets_its_own_predicate_and_cap(self):
        assert _occupancy_predicate_for("Individual Owner") is _mentions_occupancy_rule
        assert _occupancy_cap_for("Individual Owner") == MAX_OCCUPANCY_CHUNKS_PER_CARRIER
        for own in ("Trust", "LLC"):
            assert _occupancy_predicate_for(own) is _mentions_occupancy_eligibility
            assert _occupancy_cap_for(own) == MAX_OWNERSHIP_CHUNKS_PER_CARRIER
        assert MAX_OCCUPANCY_CHUNKS_PER_CARRIER < MAX_OWNERSHIP_CHUNKS_PER_CARRIER

    @pytest.mark.parametrize("text", [
        "Properties owned by a business, corporation, LLC are NOT eligible for coverage.",
        "Residence held in trust is eligible.",
        "Properties deeded to or owned by a corporation, limited liability company (LLC).",
    ])
    def test_entity_rules_are_not_occupancy_rules(self, text):
        """The split has to be clean in both halves: an entity rule must match
        the entity half and NOT the occupancy half, or it rides into a prompt
        that only asked for occupancy rules (second homes, once routed).
        Orion's is the case that needed "deeded to" narrowed to "deeded to
        the named insured"."""
        assert _mentions_ownership_entity_rule(text)
        assert not _mentions_occupancy_rule(text)

    def test_every_llc_rule_reaches_the_prompt_for_an_llc_property(self):
        """Flat exclusions, permissions, conditions and referrals alike -- 20
        rules across the family. Measured before the permissive widening:
        15/20, with every miss a rule that allows or conditions an LLC."""
        missing = _unreached("LLC", _LLC_RULE_PROBES)
        assert not missing, f"LLC rules missing from an LLC property's prompt: {missing}"

    def test_every_trust_rule_reaches_the_prompt_for_a_trust_property(self):
        """Measured before: 14/20. The miss that mattered most was Allied
        Trust's own conditional clause -- split across a chunk boundary exactly
        the way CHUBB's clause 2 was, with the continuation ("The Trust may
        NOT be listed...") matching and the head, which carries the grantor
        condition, matching nothing."""
        missing = _unreached("Trust", _TRUST_RULE_PROBES)
        assert not missing, f"trust rules missing from a Trust property's prompt: {missing}"


def _resolve_results(results, canonical, universe=()):
    """{canonical carrier: result record}. Exact-one match or it is left out
    and reported (and the test fails on it) -- never a coin flip, per
    _find_carrier.

    Matches in BOTH directions. The model restates carrier names freely and
    often drops the date ("Mercury HO3" for Mercury_HO3_-_01.01.2026). The
    first version only accepted an output name CONTAINING the full canonical
    one, and on the round-17 run it silently dropped 13 expected carriers per
    Trust/LLC run -- eight of the ten flat-exclusion carriers among them --
    while the check still printed 6/6. A floor of 6 characters keeps a bare
    "Sage" from matching everything; a multi-match is left unresolved.

    Containment still misses a name whose dropped part sits in the MIDDLE:
    "Orion HO3" (Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3), "HOAIC HO3"
    (HOAIC_-_TX-HOMEOWNERS-0326_HO3). The model wrote "Orion HO3" in all 3
    round-17 Individual Owner controls, so Orion's LLC and Trust checks never
    ran. Only when containment finds NOTHING, a record whose words are a
    subset of the canonical name's words is accepted -- and only if those
    words fit exactly one carrier in `universe`, the FULL carrier list, not
    the caller's subset (otherwise "Sage HO3" would resolve to whichever Sage
    program the caller happened to ask for). No universe, no fallback."""
    out, missing = {}, []
    universe_words = {u: _carrier_words(u) for u in universe}
    for c in canonical:
        want = normalize_carrier_name(c)

        def related(r):
            got = normalize_carrier_name(r.get("carrier", ""))
            return bool(got) and (got == want or want in got or (len(got) >= 6 and got in want))

        hits = [r for r in results if related(r)]
        if not hits and c in universe_words:
            for drop in (False, True):      # "NatGen Custom360 (Landlord)" needs the second pass
                def fits_only_c(r):
                    w = _carrier_words(r.get("carrier", ""), drop)
                    return bool(w) and [u for u, uw in universe_words.items() if w <= uw] == [c]
                hits = [r for r in results if fits_only_c(r)]
                if hits:
                    break
        if len(hits) == 1:
            out[c] = hits[0]
        else:
            missing.append((c, len(hits)))
    return out, missing


def _compare_key(text):
    """Alphanumerics only, lowercased: a verbatim fragment still matches when
    the model's quote differs in spacing or punctuation, and nothing else."""
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


# The carrier's OWN verbatim entity-exclusion text. Matching this -- not a
# keyword -- is what makes an LLC pass prove the carrier's rule was used: a
# bare "llc|business|corporation" search passes on Sage's page header
# ("SAGESURE INSURANCE MANAGERS LLC") or Allied Trust's unrelated "BUSINESS
# EXPOSURE" rule.
_LLC_FLAT_FRAGMENTS = {
    "Allied_Trust_HO3": "owned by a business, corporation, llc",
    "Progressive_HO3_-_04.01.2026": "in the name of a business, limited liability corporation",
    "Sage_-_Auros_HO3": "non-individual owned properties are ineligible",
    "Sage_-_SURE_HO-3_-_01.31.2026": "non-individual owned properties are ineligible",
    "Sage_-_SafePort_HO-3_-_01.31.2026": "non-individual owned properties are ineligible",
    "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026": "non-individual owned properties are ineligible",
    "Sage_-_Wilshire_HO3_-_12.02.2025": "non-individual owned properties are ineligible",
    "Mercury_HO3_-_01.01.2026": "properties owned by an llc, corporation",
    "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3": "owned by a corporation, limited liability company",
    "Liberty_Mutual_HO3_-_02.21.2026": "buildings owned by a corporation, company, llc",
}
assert set(_LLC_FLAT_FRAGMENTS) == set(_LLC_FLAT_EXCLUSION)

# A referral must be ABOUT the trust. Bare "underwrit|approval|refer" over the
# whole record passed on Allied Trust's page footer ("UNDERWRITING
# GUIDELINES") and on unrelated rules ("125 amps may be acceptable with
# underwriting approval") -- the old "townhouse units" shape again. So one
# single unit (a reason, a citation, a missing_info item, or one sentence of
# the notes) has to carry BOTH a trust word and referral language.
_TRUST_WORD_RE = re.compile(r"\btrusts?\b", re.I)
_REFERRAL_LANGUAGE_RE = re.compile(
    r"\brefer(?:red|ral|ring)?\b|underwriting approval|prior approval|submit for approval"
    r"|approval before binding|check with us|underwriter", re.I)


def _record_units(r):
    notes = re.split(r"(?<=[.!?])\s+", r.get("notes", "") or "")
    return [u for u in (r.get("reasons", []) + r.get("citations", [])
                        + r.get("missing_info", []) + notes) if u]


def _trust_referral_surfaced(r, carrier):
    brand = _carrier_brand(carrier)
    for unit in _record_units(r):
        scan = unit.lower().replace(brand, " ") if brand else unit.lower()
        if _TRUST_WORD_RE.search(scan) and _REFERRAL_LANGUAGE_RE.search(scan):
            return True
    return False


# (group, carrier) checks read by eye and held out of the aggregate, each with
# its own named xfail below carrying its measured rate -- so it stays visible
# on every run instead of failing the aggregate and hiding any NEW miss behind
# a failure everyone already expects. Both vary on byte-identical evidence
# (the only prompt change between the 3caeb64 and 1b446e2 runs was CHUBB's
# tiering chunk), so they are rates, not fixes or regressions.
_HELD_OUT_CHECKS = {
    ("Trust: REFER, with the referral about the trust", "Allied_Trust_HO3"):
        "test_allied_trust_trust_is_refer_on_its_approval_row",
    ("Trust: not declined", "Mercury_HO3_-_01.01.2026"):
        "test_mercury_trust_is_not_declined_on_its_corporate_trust_rule",
}


def _omitted_carriers(results, universe):
    """Carriers the model left out of its output altogether -- as opposed to
    ones it named in a way the resolver cannot match. Only when the record
    count is short by EXACTLY the number of unmatched carriers, and none is
    ambiguous; any other unmatched carrier is a resolution failure, which is
    what once hid 13 dropped carriers per run and must still fail."""
    if not universe:
        return set()
    _, missing = _resolve_results(results, universe, universe)
    shortfall = len(universe) - len(results)
    if missing and all(n == 0 for _, n in missing) and len(missing) == shortfall:
        return {c for c, _ in missing}
    return set()


def _score_ownership_runs(reps, universe=()):
    """Pure scoring over recorded runs -- no API calls -- so a changed
    assertion can be re-scored from the JSON dump instead of re-paid for.

    reps: [{"Individual Owner": [records], "Trust": [...], "LLC": [...]}, ...]
    universe: the full carrier list, for _resolve_results' fallback.
    Returns (checks, coverage): checks[(group, carrier)] = [bool per run];
    coverage[group] = {"expected", "ran", "skipped": [(carrier, why)],
    "unresolved": [(ownership, carrier, n_matches)], "omitted": [(ownership,
    carrier)], "held_out": [carrier]}. Omitted and held-out checks are
    reported, and tested by their own named xfails; unresolved ones fail.
    """
    groups = {
        "LLC: INELIGIBLE on its own verbatim entity rule": ("LLC", _LLC_FLAT_EXCLUSION),
        "LLC: not declined (permitted/conditional/referral)": ("LLC", _LLC_NOT_A_FLAT_DECLINE),
        "Trust: not declined": ("Trust", _TRUST_NOT_A_DECLINE),
        "Trust: REFER, with the referral about the trust": ("Trust", _TRUST_REFERRAL),
        "Trust: Allied Trust surfaces the grantor condition": ("Trust", ["Allied_Trust_HO3"]),
    }
    groups = {g: (own, [c for c in cs if (g, c) not in _HELD_OUT_CHECKS]) for g, (own, cs) in groups.items()}
    checks = {}
    coverage = {g: {"expected": len(cs) * len(reps), "ran": 0, "skipped": [], "unresolved": [],
                    "omitted": [], "held_out": sorted(c for (hg, c) in _HELD_OUT_CHECKS if hg == g)}
                for g, (_, cs) in groups.items()}
    every = sorted({c for _, cs in groups.values() for c in cs})

    for rep in reps:
        by = {}
        for own, res in rep.items():
            by[own], missing = _resolve_results(res, every, universe)
            omitted = _omitted_carriers(res, universe)
            for g, (g_own, cs) in groups.items():
                for c, n in missing:
                    if c in cs and own in (g_own, "Individual Owner"):
                        if c in omitted:
                            coverage[g]["omitted"].append((own, c))
                        else:
                            coverage[g]["unresolved"].append((own, c, n))
        control = by["Individual Owner"]
        for g, (own, cs) in groups.items():
            for c in cs:
                r, ctl = by[own].get(c), control.get(c)
                if r is None or ctl is None:
                    continue  # already counted as unresolved or omitted
                # The control rule applies to EVERY group, the flat-exclusion
                # one included: a pass must prove OWNERSHIP moved the verdict,
                # so a carrier the control already declined proves nothing.
                if ctl.get("status") == "INELIGIBLE":
                    coverage[g]["skipped"].append((c, "control INELIGIBLE"))
                    continue
                coverage[g]["ran"] += 1
                if g.startswith("LLC: INELIGIBLE"):
                    frag = _compare_key(_LLC_FLAT_FRAGMENTS[c])
                    ok = (r.get("status") == "INELIGIBLE"
                          and any(frag in _compare_key(x) for x in r.get("citations", [])))
                elif g.startswith("Trust: REFER"):
                    # The status, not only the wording: REFER is its own UI
                    # bucket (One Issue), and SYSTEM_INSTRUCTIONS ranks it
                    # above INSUFFICIENT_INFORMATION when the carrier's own
                    # text offers a referral path for this situation.
                    ok = r.get("status") == "REFER" and _trust_referral_surfaced(r, c)
                elif g.startswith("Trust: Allied Trust"):
                    ok = "grantor" in " ".join(_record_units(r)).lower()
                else:
                    ok = r.get("status") != "INELIGIBLE"
                checks.setdefault((g, c), []).append(bool(ok))
    return checks, coverage


_OWNERSHIP_DUMP = os.environ.get(
    "OWNERSHIP_VERDICT_DUMP",
    os.path.join(os.path.dirname(__file__), "ownership_verdicts_results.json"))


@pytest.mark.baseline
def test_trust_and_llc_verdicts_follow_each_carriers_own_rule(record_property):
    """The claim the retrieval tests cannot make: once each carrier's
    ownership rule reaches the model, the VERDICT follows that carrier's rule.

    Each repetition runs the clean base profile three times -- Individual
    Owner (the control), Trust, LLC -- so ownership is the only variable.
    EVERY check, the flat-exclusion one included, skips a carrier the control
    already declined, so a pass proves ownership moved the verdict. Skips and
    unresolved names are counted and reported, never silently dropped, and an
    expected carrier that cannot be resolved fails the test -- unless the
    model left it out of that run altogether (see _omitted_carriers), which
    is reported here and asserted by its own xfail.

    Every run's raw per-carrier output is written to _OWNERSHIP_DUMP (git-
    ignored, verification/*_results.json) before scoring, so an assertion
    change can be re-scored with _score_ownership_runs() for free --
    REUSE_DUMPS=1 does exactly that, with the dump's commit printed.
    """
    import json
    n_runs = 3
    recorded = []   # [{ownership: {"results", "pipeline_seconds", "calls"}}]
    if os.environ.get("REUSE_DUMPS") and os.path.exists(_OWNERSHIP_DUMP):
        with open(_OWNERSHIP_DUMP, encoding="utf-8") as fh:
            dumped = json.load(fh)
        recorded = dumped["runs"]
        print(f"\nOwnership: re-scoring dump from commit {dumped['commit']} ({len(recorded)} reps)")
    for _ in range(n_runs - len(recorded)):
        rep = {}
        for own in ("Individual Owner", "Trust", "LLC"):
            results, rec = _recorded_run(dict(OWNERSHIP_BASE_PROFILE, ownership_type=own))
            rep[own] = {"results": results, **rec}
        recorded.append(rep)
        _dump_runs(_OWNERSHIP_DUMP, OWNERSHIP_BASE_PROFILE, recorded)   # after every rep

    reps = [{own: v["results"] for own, v in rep.items()} for rep in recorded]
    universe = get_carriers_for_occupancy("Owner Occupied")
    checks, coverage = _score_ownership_runs(reps, universe)

    # Not asserted -- reported. The eligibility pipeline does not consult the
    # data-defect list, so these carriers get ordinary verdicts from the wrong
    # document. What they actually say is the input to a product decision.
    print("\nKnown-defective records in the Individual Owner results (not asserted):")
    for rep_i, rep in enumerate(reps, 1):
        found, _ = _resolve_results(rep["Individual Owner"], [
            "NatGen_Custom360_HO3_-_06.25.2026", "Sage_-_Occidental_HO3",
            "Liberty_Mutual_HO6_-_02.21.2026", "Centauri_-_HO3_-_05.01.2026"], universe)
        for c in ("NatGen_Custom360_HO3_-_06.25.2026", "Sage_-_Occidental_HO3",
                  "Liberty_Mutual_HO6_-_02.21.2026", "Centauri_-_HO3_-_05.01.2026"):
            r = found.get(c)
            print(f"   rep {rep_i} {c[:34]:34s} " + ("NOT IN OUTPUT" if r is None else r.get("status")))

    print(f"\nTrust/LLC verdict checks over {n_runs} runs (raw results: {_OWNERSHIP_DUMP}):")
    failures = []
    for g, cov in coverage.items():
        results = [ok for (grp, _), oks in checks.items() if grp == g for ok in oks]
        passed = sum(results)
        print(f"   {g}")
        print(f"      passed {passed}/{len(results)}   ran {cov['ran']}/{cov['expected']}"
              f"   skipped {len(cov['skipped'])}   unresolved {len(cov['unresolved'])}"
              f"   omitted {len(cov['omitted'])}   held out {len(cov['held_out'])}")
        for c, why in sorted(set(cov["skipped"])):
            print(f"      skipped: {c} ({why})")
        for own_c in sorted(set(cov["omitted"])):
            print(f"      omitted by the model: {own_c} (see test_every_carrier_appears_in_every_recorded_run)")
        for c in cov["held_out"]:
            print(f"      held out: {c} (see {_HELD_OUT_CHECKS[(g, c)]})")
        for u in sorted(set(cov["unresolved"])):
            print(f"      UNRESOLVED: {u}")
            failures.append(f"unresolved carrier {u} in group {g!r}")
        record_property(g, f"{passed}/{len(results)} ran {cov['ran']}/{cov['expected']}")
    for (g, c), oks in sorted(checks.items()):
        if not all(oks):
            failures.append(f"{g} | {c} | {sum(oks)}/{len(oks)}")
    assert any(cov["ran"] for cov in coverage.values()), "no check ran at all"
    assert not failures, "ownership verdict checks failed:\n  " + "\n  ".join(failures)


def _ownership_dump_reps():
    """The runs test_trust_and_llc_verdicts_follow_each_carriers_own_rule
    recorded (it runs first in file order), so the tests below cost no calls."""
    import json
    if not os.path.exists(_OWNERSHIP_DUMP):
        pytest.skip(f"no ownership dump at {_OWNERSHIP_DUMP}")
    with open(_OWNERSHIP_DUMP, encoding="utf-8") as fh:
        return json.load(fh)["runs"]


def _dumped_record(rep, ownership, carrier, universe):
    found, missing = _resolve_results(rep[ownership]["results"], [carrier], universe)
    if missing:
        return None
    return found[carrier]


@pytest.mark.baseline
@pytest.mark.xfail(
    reason="VERDICT-CHANGING, INTERMITTENT (round 17, read by eye): Allied Trust/Trust is REFER "
    "in 3/6 recorded runs -- 0/3 at 3caeb64, 3/3 at 1b446e2 on BYTE-IDENTICAL Allied evidence. "
    "The misses follow the grantor clause and drop the 'Residence Held in Trust | Submit for "
    "Approval with Trust documents' row, which is in the prompt. The other five "
    "trust-referral carriers are REFER 6/6.",
    strict=False,
)
def test_allied_trust_trust_is_refer_on_its_approval_row():
    """The exact finding: status REFER (the One Issue bucket), with the
    referral stated about the trust -- the grantor condition alone is not
    enough."""
    universe = get_carriers_for_occupancy("Owner Occupied")
    rows = []
    for rep in _ownership_dump_reps():
        r = _dumped_record(rep, "Trust", "Allied_Trust_HO3", universe)
        rows.append(None if r is None else (r.get("status"), _trust_referral_surfaced(r, "Allied_Trust_HO3")))
    assert all(row and row[0] == "REFER" and row[1] for row in rows), \
        f"(status, referral surfaced) per run: {rows}"


@pytest.mark.baseline
@pytest.mark.xfail(
    reason="VERDICT-CHANGING, INTERMITTENT (round 17, read by eye): Mercury excludes 'Properties "
    "owned by an LLC, Corporation, and/or Corporate Trust'. The intake's 'Trust' does not say "
    "corporate, so a decline over-reads the rule. Declined in 1/6 recorded Trust runs (0/3 at "
    "3caeb64, 1/3 at 1b446e2) on byte-identical Mercury evidence; the rest were not declined. "
    "A trust-type intake field is Liam's call, like the grantor field.",
    strict=False,
)
def test_mercury_trust_is_not_declined_on_its_corporate_trust_rule():
    universe = get_carriers_for_occupancy("Owner Occupied")
    statuses = []
    for rep in _ownership_dump_reps():
        r = _dumped_record(rep, "Trust", "Mercury_HO3_-_01.01.2026", universe)
        statuses.append(None if r is None else r.get("status"))
    assert all(s not in (None, "INELIGIBLE") for s in statuses), f"Mercury/Trust per run: {statuses}"


@pytest.mark.baseline
@pytest.mark.xfail(
    reason="SILENT, INTERMITTENT (round 17): rep 3 Trust at 1b446e2 returned 26 of 28 carriers -- "
    "Foremost and NatGen Custom360 left out entirely, stop_reason end_turn, not a truncation. 1 of "
    "48 recorded calls. Nothing in the pipeline notices, so an agent would never know; the fix is "
    "a fixed 'not evaluated' row, the same machinery as the data-defect warning row.",
    strict=False,
)
def test_every_carrier_appears_in_every_recorded_run():
    universe = get_carriers_for_occupancy("Owner Occupied")
    gaps = []
    for i, rep in enumerate(_ownership_dump_reps(), 1):
        for own, run in rep.items():
            _, missing = _resolve_results(run["results"], universe, universe)
            if missing:
                gaps.append((i, own, sorted(c for c, _ in missing)))
    assert not gaps, f"carriers absent from the output: {gaps}"


# The names the model actually wrote in round 17's recorded runs, where
# containment alone fails because the dropped part sits in the middle.
_NAMES_MISSING_THEIR_MIDDLE = [
    ("Orion HO3", "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3"),
    ("HOAIC HO3", "HOAIC_-_TX-HOMEOWNERS-0326_HO3"),
    ("HOAIC TX Homeowners HO3", "HOAIC_-_TX-HOMEOWNERS-0326_HO3"),
    ("NatGen Custom360 (Landlord)", "NatGen_Custom360_HO3_-_06.25.2026"),
]
_RESOLVER_UNIVERSE = [
    "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3", "HOAIC_-_TX-HOMEOWNERS-0326_HO3",
    "NatGen_Custom360_HO3_-_06.25.2026", "NatGen_Premier_OneChoice_HO3_-_02.26.2025",
    "Sage_-_Auros_HO3", "Sage_-_Markel_HO3", "Sage_-_Vave_HO3_-_07.01.2026",
    "Sage_-_SURE_HO-3_-_01.31.2026", "Swyfft_-_Benchmark_(Admitted)_HO3",
    "Swyfft_-_Benchmark_(Surplus)_HO3",
]


@pytest.mark.retrieval
def test_an_omission_is_only_a_short_output_with_exactly_those_carriers_missing():
    """_omitted_carriers must never absorb a resolution failure -- the
    round-17 bug that hid 13 carriers per run was a FULL-length output whose
    names the resolver could not match."""
    universe = ["Sage_-_Auros_HO3", "Sage_-_Markel_HO3", "Mercury_HO3_-_01.01.2026",
                "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3"]
    short = [{"carrier": "Sage_-_Auros_HO3"}, {"carrier": "Mercury HO3"}]
    assert _omitted_carriers(short, universe) == {
        "Sage_-_Markel_HO3", "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3"}
    full_but_unmatched = short + [{"carrier": "Sage HO3"}, {"carrier": "Orion UW"}]
    assert _omitted_carriers(full_but_unmatched, universe) == set()
    one_short_two_unmatched = short + [{"carrier": "Sage HO3"}]
    assert _omitted_carriers(one_short_two_unmatched, universe) == set()


@pytest.mark.retrieval
@pytest.mark.parametrize("written, canonical", _NAMES_MISSING_THEIR_MIDDLE)
def test_verdict_resolver_accepts_a_name_missing_its_middle(written, canonical):
    found, missing = _resolve_results([{"carrier": written}], [canonical], _RESOLVER_UNIVERSE)
    assert found.get(canonical) == {"carrier": written}, missing


@pytest.mark.retrieval
@pytest.mark.parametrize("written, asked", [
    ("Sage HO3", "Sage_-_Markel_HO3"),                                # four Sage programs fit
    ("Swyfft Benchmark HO3", "Swyfft_-_Benchmark_(Surplus)_HO3"),     # Admitted and Surplus fit
    ("NatGen HO3", "NatGen_Custom360_HO3_-_06.25.2026"),              # Custom360 and Premier fit
])
def test_verdict_resolver_never_picks_among_several_carriers(written, asked):
    """Even when the caller asks for ONE of them -- uniqueness is judged
    against the full list, not the caller's subset."""
    found, _ = _resolve_results([{"carrier": written}], [asked], _RESOLVER_UNIVERSE)
    assert asked not in found


@pytest.mark.retrieval
def test_verdict_resolver_fallback_needs_the_full_carrier_list():
    found, _ = _resolve_results([{"carrier": "Orion HO3"}],
                                ["Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3"])
    assert not found


@pytest.mark.retrieval
def test_verdict_resolver_prefers_containment_over_the_fallback():
    orion = "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3"
    recs = [{"carrier": orion, "status": "full name"}, {"carrier": "Orion HO3", "status": "short"}]
    found, _ = _resolve_results(recs, [orion], _RESOLVER_UNIVERSE)
    assert found[orion]["status"] == "full name"


@pytest.mark.retrieval
def test_names_missing_their_middle_are_real_owner_occupied_carriers():
    """Keeps the pipeline xfail below failing for its stated reason, not a
    renamed carrier."""
    carriers = set(get_carriers_for_occupancy("Owner Occupied"))
    assert {c for _, c in _NAMES_MISSING_THEIR_MIDDLE} <= carriers


@pytest.mark.retrieval
@pytest.mark.parametrize("written, canonical", [
    (w, c) for w, c in _NAMES_MISSING_THEIR_MIDDLE if "(" not in w
])
def test_pipeline_resolves_the_carrier_names_the_model_actually_writes(written, canonical):
    """Fixed 2026-09-28. Containment alone resolved these to None, and every
    post-parse guard skipped the record -- 14 of 420 recorded round-17
    records, in 6 of 15 calls. ("NatGen Custom360 (Landlord)" is deliberately
    not resolved by the pipeline -- see the next test.)"""
    carriers = get_carriers_for_occupancy("Owner Occupied")
    assert _resolve_structured_carrier(written, carriers) == canonical


@pytest.mark.retrieval
@pytest.mark.parametrize("label, carrier", [
    ("ARI (HOB)", "ARI_(HOA+)"),
    ("ARI (HOA+)", "ARI_(HOB)"),
    ("Swyfft Benchmark (Surplus)", "Swyfft_-_Benchmark_(Admitted)_HO3"),
])
def test_pipeline_resolver_never_drops_a_carriers_own_parenthetical(label, carrier):
    """_citation_attributed_carrier asks one carrier at a time. A first cut
    of the fallback dropped parentheticals, so "ARI (HOB)" became "ARI" and
    fitted ARI (HOA+) -- and HOB's rule in HOA+'s record stopped being
    recognised as foreign."""
    assert _resolve_structured_carrier(label, [carrier]) is None


@pytest.mark.retrieval
@pytest.mark.parametrize("written", [
    "Sage HO3",                  # fits every Sage HO3 program
    "Swyfft Benchmark HO3",      # fits Admitted and Surplus
    "NatGen HO3",                # fits Custom360 and Premier
])
def test_pipeline_resolver_never_picks_among_several_carriers(written):
    carriers = get_carriers_for_occupancy("Owner Occupied")
    assert _resolve_structured_carrier(written, carriers) is None


@pytest.mark.retrieval
def test_pipeline_resolver_fallback_runs_only_when_containment_finds_nothing(monkeypatch):
    """Every name containment already resolved resolves exactly as before:
    with the fallback made to blow up, canonical names and the usual
    date-dropped spellings still resolve."""
    import eligibility_check as ec
    carriers = get_carriers_for_occupancy("Owner Occupied")

    def boom(*a, **k):
        raise AssertionError("fallback reached for a name containment resolves")
    monkeypatch.setattr(ec, "_carrier_words", boom)
    for name in list(carriers) + ["Mercury HO3", "Allied Trust HO3", "Sage - SURE HO-3"]:
        assert ec._resolve_structured_carrier(name, carriers) is not None, name


@pytest.mark.retrieval
@pytest.mark.parametrize("label, expected", [
    ("Orion HO3", "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3"),   # now attributable
    ("Sage HO3", None),                                               # still ambiguous
])
def test_citation_labels_resolve_by_the_same_rule(label, expected):
    carriers = get_carriers_for_occupancy("Owner Occupied")
    assert _citation_attributed_carrier(f"{label}: 'some quoted rule'", carriers) == expected


# Vave's roof age-band table, verbatim from its guide. Roof age is a
# guaranteed-lookup topic, but _mentions_roof_life_expectancy's age-band
# clause keys on the word "excluded" -- TWICO's and Swyfft's wording -- and
# Vave's header says "Exclusion for roofs over". Found round 17 when the
# model said "the table details are not fully provided in the retrieved
# excerpts": the table is in the guide and never reached a recorded prompt.
_VAVE = "Sage_-_Vave_HO3_-_07.01.2026"
_VAVE_ROOF_TABLE = (
    "| ROOF COVERAGE1 |  |  |  |\n| --- | --- | --- | --- |\n"
    "| Roof Type | RCV for roofs under | ACV for roofs between | Exclusion for roofs over |\n"
    "| Asphalt Shingles | < 15 years | 15–25 years | > 25 years |")
_VAVE_XFAIL = pytest.mark.xfail(
    reason="NOT FIXED (round 17): the roof age-band predicate needs the word 'excluded'; Vave's "
    "table says 'Exclusion for roofs over', so Vave's roof-age rule has no retrieval guarantee. "
    "A retrieval change; needs the baseline tier before merge.",
    strict=True,
    raises=AssertionError,
)


@pytest.mark.retrieval
@_VAVE_XFAIL
@pytest.mark.parametrize("text", [
    _VAVE_ROOF_TABLE,                                                   # Vave, verbatim
    "Roof loss settlement is RCV for roofs under 15 years and ACV from 15 to 20 years; "
    "a roof exclusion applies over 20 years.",                          # same rule, in prose
], ids=["vave-table", "prose"])
def test_roof_age_band_with_exclusion_wording_is_a_roof_age_rule(text):
    assert _mentions_roof_life_expectancy(text)


@pytest.mark.retrieval
@_VAVE_XFAIL
@pytest.mark.parametrize("profile", [STANDARD_PROFILE, OWNERSHIP_BASE_PROFILE],
                         ids=["STANDARD", "OWNERSHIP_BASE"])
def test_vave_roof_age_table_reaches_the_prompt(profile):
    per, _ = _captured_sections(profile)
    if not per.get(_VAVE):
        pytest.fail(f"{_VAVE} has no section in the prompt at all")   # not the xfail's reason
    assert "rcv for roofs under" in per[_VAVE].lower()


# ---------------------------------------------------------------------------
# Round 17 verdict diff (main 72e34db vs the gated guarantee, Individual
# Owner, 4 profiles x 3 runs). Three (profile, carrier) statuses changed in
# 3/3 runs on each side, all worse on the gated side: ALT CHUBB, ALT HOAIC,
# COASTAL ARI (HOA+). Liam's decision (2026-09-28) takes individual owners
# off the guarantee, so all three are main's behaviour again. What remains
# below is what outlives that decision: the tier exclusion, because the same
# CHUBB section would reach Trust / LLC prompts, and the ARI record, because
# a quote relabelled from a sibling carrier can come from ANY prompt.
# ---------------------------------------------------------------------------

# CHUBB's page-8 chunk as it reaches the prompt. Its heading, one chunk
# earlier, is "VIII. Tiering Guidelines -- Risks that qualify for homeowners
# insurance based on the criteria in sections I-III, become eligible for
# placement in our Standard Tier ... for risks that qualify for discounted
# pricing." Tier placement comes AFTER eligibility.
_CHUBB_TIER_CHUNK = (
    "• Risks in Flood Zone V are only acceptable for tenants and condominiums on the 3rd floor or "
    "higher. • Risks in Flood Zone A are subject to pre-approval. Minimum $3,000,000 Maximum "
    "$5,000,000 AND Year Built Ten Years Old - House: Coverage A OR $5,000,000 or greater Discount "
    "Tier Conditions • Must satisfy Standard Tier Conditions • Primary residence must be single "
    "family or two family home and owner-occupied")


@pytest.mark.retrieval
@pytest.mark.parametrize("text", [
    _CHUBB_TIER_CHUNK,                                                  # CHUBB, verbatim
    "Preferred Tier Conditions: all Standard Tier Conditions must be met, and the dwelling "
    "must be owner-occupied with no business conducted on premises.",   # same kind of rule
], ids=["chubb-verbatim", "second-phrasing"])
def test_tier_placement_conditions_are_not_occupancy_rules(text):
    assert _is_tier_placement(text)
    assert not _mentions_occupancy_rule(text)


@pytest.mark.retrieval
def test_tier_placement_conditions_are_not_ownership_rules_either():
    assert not _mentions_ownership_entity_rule(
        "Ultra Preferred Tier Conditions: the residence may not be held in a trust or LLC and is "
        "ineligible for this tier if it is.")


@pytest.mark.retrieval
@pytest.mark.parametrize("text", [
    "Dwellings in First Tier counties must be owner occupied.",   # coastal tier, not pricing
    "Tier 1 and Tier 2 coastal counties: dwellings must be owner occupied.",
])
def test_coastal_tiers_are_not_tier_placement(text):
    """Bare "tier" is Texas coastal geography in 58 chunks of this corpus."""
    assert not _is_tier_placement(text)
    assert _mentions_occupancy_rule(text)


@pytest.mark.retrieval
@pytest.mark.parametrize("ownership", ["Trust", "LLC"])
def test_chubb_tiering_chunk_stays_out_of_trust_and_llc_prompts(ownership):
    """The case the exclusion is kept for once individual owners are off the
    guarantee. The premise is checked too: with the exclusion switched off,
    the guarantee DOES add the chunk -- so a pass means the exclusion is
    doing the work, not that CHUBB's section simply never ranks."""
    chubb = "CHUBB_HO_-_05.22.2026"
    prof = dict(ALT_PROFILE, ownership_type=ownership)
    without_exclusion, _ = _captured_sections_patched(prof, _is_tier_placement=lambda content: False)
    assert "discount tier conditions" in without_exclusion.get(chubb, ""), \
        "premise: without the exclusion the guarantee adds CHUBB's tiering chunk"
    per, _ = _captured_sections(prof)
    assert per.get(chubb), "CHUBB has no section in the prompt at all"
    assert "discount tier conditions" not in per[chubb]


def _replayed_run(profile, raw_text):
    """check_eligibility() with the model call answered by recorded text --
    real retrieval and the real post-parse chain, zero API cost. Restored in
    finally, like _captured_prompt."""
    import types
    import eligibility_check as ec
    original = ec.client.messages.create

    def fake(**kwargs):
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text=raw_text)], stop_reason="end_turn",
            usage=types.SimpleNamespace(input_tokens=0, output_tokens=0,
                                        cache_read_input_tokens=0, cache_creation_input_tokens=0))

    ec.client.messages.create = fake
    try:
        return check_eligibility(dict(profile))
    finally:
        ec.client.messages.create = original


# ARI (HOA+)'s record from gated COASTAL_PPC4 run 1, verbatim as the model
# wrote it (identical reasoning in runs 2 and 3). The first citation is ARI
# (HOB)'s AGE rule -- it sits in the ARI_(HOB) section of the prompt, under
# an "HOB Underwriting Guidelines" page footer -- relabelled as HOA+'s own.
# ARI (HOA+)'s guide has no home-age limit at all ("An inspection is
# required on homes over 5 years old" is its only age line), and HOB's rule
# itself sends homes over 20 to HOA/HOA Plus. Main read it correctly 3/3.
_ARI_HOA_PLUS_COASTAL_RECORD = {
    "carrier": "ARI_(HOA+)",
    "reasons": [
        "Home Age is 22 years, which exceeds the 20-year maximum for HOA+ (homes over 20 years old "
        "can be considered for HOA/HOA Plus, but this is the HOA+ program specifically)",
        "Roof Age is 16 years. Roofs 15 years or older are covered on Actual Cash Value (ACV) basis "
        "rather than Replacement Cost Value (RCV)",
        "Tile roofs are not listed among the ineligible roof types (wood, flat, asbestos, tar/gravel, "
        "expensive metal), so the roof material itself is acceptable",
        "PPC 4 is within the eligible range (1-9 per the quick reference table)",
    ],
    "citations": [
        "ARI_(HOA+): 'Homes 0-20 years old are eligible for this program. Homes over 20years old can "
        "be considered for coverage under the HOA/HOA Plus.'",
        "ARI_(HOA+): 'Roofs that are 15 years or older will be covered on an Actual Cash Value (ACV) "
        "basis.'",
    ],
    "missing_info": [],
    "notes": "Roof coverage would be on ACV basis due to roof age of 16 years. The property exceeds "
             "the 20-year age limit for the HOA+ program specifically.",
    "status": "INELIGIBLE",
    "flaw_count": 1,
}


@pytest.mark.retrieval
@pytest.mark.xfail(
    reason="VERDICT-CHANGING, NOT FIXED: a real model record (COASTAL_PPC4 ARI (HOA+), 3/3 in the "
    "round-17 gated runs) declined on ARI (HOB)'s home-age rule quoted under HOA+'s own label. "
    "Individual owners are off the guarantee now, but nothing in the pipeline checks a quote "
    "against the cited carrier's own document, so any prompt can produce it. Step 3's "
    "quote-in-own-guide guard is the fix.",
    strict=True,
    raises=AssertionError,
)
def test_ari_hoa_plus_is_not_declined_on_ari_hob_age_rule():
    import json
    results = _replayed_run(COASTAL_PPC4_PROFILE, json.dumps([_ARI_HOA_PLUS_COASTAL_RECORD]))
    ari = [r for r in results if r.get("carrier") == "ARI_(HOA+)"]
    if len(ari) != 1:
        pytest.fail(f"replay returned {len(ari)} ARI (HOA+) records")    # not the xfail's reason
    assert ari[0]["status"] != "INELIGIBLE", ari[0]


@pytest.mark.retrieval
class TestProductCheckCalibration:
    """Pins the product check's behaviour in BOTH directions, as a hard assert
    that runs every commit. The standing check above is xfail while the
    defects exist, so on its own it could quietly start flagging -- or stop
    flagging -- anything without the suite noticing."""

    @pytest.mark.parametrize("carrier", [
        "Travelers_HO3_-_06.12.2026",        # real LANDLORD section; words 3 vs 8, refs 0 vs 0
        "Sage_-_Vave_HO3_-_07.01.2026",      # refs 19 HO vs 4 DP
        "Sage_-_Markel_HO3",                 # refs 32 HO vs 1 DP
        "Liberty_Mutual_DP3_-_02.21.2026",   # refs 0 DP vs 1 HO -- a cross-reference
        "Sage_-_Occidental_DP3",             # the CORRECT record of the DD-4 pair
    ])
    def test_the_known_close_calls_are_not_flagged(self, carrier):
        assert carrier not in _product_mismatches()

    def test_only_known_defects_are_flagged(self):
        """Anything flagged that is not a documented defect is either a new
        mis-ingest (investigate the PDF) or a false positive (fix the rule) --
        never something to add here without reading the document."""
        known = {"NatGen_Custom360_HO3_-_06.25.2026", "Sage_-_Occidental_HO3"}
        assert set(_product_mismatches()) <= known, set(_product_mismatches()) - known

    def test_occidental_ho3_is_flagged_while_it_holds_the_dp3_guide(self):
        """Premise-guarded, so it clears itself: once the real HO3 PDF is
        uploaded the record stops calling itself a dwelling-fire program and
        this has nothing to assert."""
        text = " ".join(c.page_content for c in _all_chunks("Sage_-_Occidental_HO3")).upper()
        if "DWELLING FIRE PROGRAM" not in text:
            pytest.skip("Sage_-_Occidental_HO3 no longer self-describes as DP3 -- DD-4 fixed?")
        assert "Sage_-_Occidental_HO3" in _product_mismatches()
        assert "reference rule" in _product_mismatches()["Sage_-_Occidental_HO3"]

    def test_the_runtime_detector_agrees_with_this_check(self):
        """data_defects.py runs the same product rule for the live app. Two
        copies of one rule drift apart, so pin them together: every record
        this check flags is a runtime defect too (possibly under another
        kind -- NatGen Custom360 is DUPLICATE_DOCUMENT first), and every
        runtime WRONG_PRODUCT record is flagged here."""
        import data_defects
        runtime = data_defects.defective_programs()
        mismatched = set(_product_mismatches())
        assert mismatched <= set(runtime), mismatched - set(runtime)
        wrong_product = {p for p, d in runtime.items() if d["kind"] == data_defects.WRONG_PRODUCT}
        assert wrong_product <= mismatched, wrong_product - mismatched


# ---------------------------------------------------------------------------
# Step 2 (Liam, 2026-09-28/29): rows the PIPELINE writes for carriers it
# could not check. A carrier whose guide on file is unusable is left out of
# the prompt and shown as a GUIDE_UNAVAILABLE row; a carrier the model left
# out of its answer gets a NOT_EVALUATED row. No carrier silently vanishes.
# All zero-API: the model call is intercepted or answered from a fixture.
# ---------------------------------------------------------------------------

_DEFECTIVE_HO = {
    "NatGen_Custom360_HO3_-_06.25.2026": "wrong document",   # DD-1, holds the DP3 guide
    "Liberty_Mutual_HO6_-_02.21.2026": "wrong document",     # DD-2, holds the HO3 guide
    "Centauri_-_HO3_-_05.01.2026": "no readable text",       # DD-3, never in the store
    "Sage_-_Occidental_HO3": "wrong document",               # DD-4, holds the DP3 guide
}


def _answer_for(carriers, **extra_records):
    """A model answer with one plain record per carrier, plus any extra
    records (a replayed defective carrier, a misnamed one) by name."""
    import json
    recs = [{"carrier": c, "status": "ELIGIBLE", "flaw_count": 0, "reasons": ["fixture"],
             "citations": [], "missing_info": [], "notes": ""} for c in carriers]
    recs += [dict(recs[0] if recs else {}, carrier=name, **fields)
             for name, fields in extra_records.items()]
    return json.dumps(recs)


def _usable(occupancy):
    import data_defects
    defects = data_defects.defective_programs()
    return [c for c in get_carriers_for_occupancy(occupancy) if c not in defects]


@pytest.mark.retrieval
class TestFixedRows:

    @pytest.mark.parametrize("carrier", [c for c in _DEFECTIVE_HO if c != "Centauri_-_HO3_-_05.01.2026"])
    def test_a_defective_carrier_is_left_out_of_the_prompt(self, carrier):
        per, whole = _captured_sections(OWNERSHIP_BASE_PROFILE)
        assert carrier not in per
        assert _norm(carrier) not in whole

    def test_its_usable_sibling_stays_in_the_prompt(self):
        """DD-2's bad record is the HO6; the Liberty Mutual HO3 guide is fine."""
        per, _ = _captured_sections(OWNERSHIP_BASE_PROFILE)
        assert "Liberty_Mutual_HO3_-_02.21.2026" in per

    def test_each_of_the_four_gets_the_row_and_nothing_else_does(self):
        results = _replayed_run(OWNERSHIP_BASE_PROFILE, _answer_for(_usable("Owner Occupied")))
        rows = {r["carrier"]: r for r in results if r["status"] == GUIDE_UNAVAILABLE}
        assert set(rows) == set(_DEFECTIVE_HO)
        for carrier, kind in _DEFECTIVE_HO.items():
            assert kind in rows[carrier]["reasons"][0], rows[carrier]["reasons"]
            assert "check with the carrier directly" in rows[carrier]["reasons"][0]
        assert not [r for r in results if r["status"] == NOT_EVALUATED]
        assert sorted(r["carrier"] for r in results) == sorted(
            _usable("Owner Occupied") + list(_DEFECTIVE_HO))

    def test_a_replayed_record_for_a_defective_carrier_is_replaced_not_duplicated(self):
        """Recorded outputs from before Step 2 still hold model records for
        these carriers -- in round 17's own spelling, "(Landlord)" included."""
        answer = _answer_for(_usable("Owner Occupied"), **{
            "NatGen Custom360 (Landlord)": {"status": "INELIGIBLE", "flaw_count": 1},
            "Sage - Occidental HO3": {"status": "ELIGIBLE"},
            "Liberty Mutual HO6": {"status": "INELIGIBLE", "flaw_count": 1},
        })
        results = _replayed_run(OWNERSHIP_BASE_PROFILE, answer)
        for carrier in _DEFECTIVE_HO:
            assert [r["status"] for r in results if r["carrier"] == carrier] == [GUIDE_UNAVAILABLE]
        assert not [r for r in results if r["carrier"] in (
            "NatGen Custom360 (Landlord)", "Sage - Occidental HO3", "Liberty Mutual HO6")]

    def test_a_tenant_property_gets_no_warning_rows(self):
        """All four defects are homeowners records; their dwelling-fire
        siblings are sound and stay."""
        tenant = dict(OWNERSHIP_BASE_PROFILE, occupancy_type="Tenant Occupied")
        results = _replayed_run(tenant, _answer_for(_usable("Tenant Occupied")))
        assert not [r for r in results if r["status"] in (GUIDE_UNAVAILABLE, NOT_EVALUATED)]

    @pytest.mark.parametrize("cleared", list(_DEFECTIVE_HO))
    def test_the_row_disappears_once_the_defect_clears(self, cleared, monkeypatch):
        """Presence and defects come from the store, so fixing a PDF needs no
        code or list edit. Simulated by the detector no longer reporting it."""
        import data_defects
        real = data_defects.defective_programs()
        monkeypatch.setattr(data_defects, "defective_programs",
                            lambda: {p: d for p, d in real.items() if p != cleared})
        results = _replayed_run(OWNERSHIP_BASE_PROFILE, _answer_for(_usable("Owner Occupied")))
        assert cleared not in {r["carrier"] for r in results if r["status"] == GUIDE_UNAVAILABLE}
        if cleared in get_all_carriers():
            assert _norm(cleared) in _captured_prompt(OWNERSHIP_BASE_PROFILE)

    def test_a_carrier_the_model_skips_gets_a_not_evaluated_row(self):
        """THE EXACT ROUND-17 SHAPE: rep 3 Trust at 1b446e2 returned 26 of 28
        carriers, leaving out Foremost and NatGen Custom360. NatGen Custom360
        is now a warning row either way; Foremost must not vanish."""
        trust = dict(OWNERSHIP_BASE_PROFILE, ownership_type="Trust")
        answered = [c for c in _usable("Owner Occupied") if c != "Foremost_DP3_and_HO3_-_07.01.2026"]
        results = _replayed_run(trust, _answer_for(answered))
        assert [r["carrier"] for r in results if r["status"] == NOT_EVALUATED] == [
            "Foremost_DP3_and_HO3_-_07.01.2026"]
        assert "run the check again" in [r for r in results if r["status"] == NOT_EVALUATED][0]["reasons"][0]

    @pytest.mark.parametrize("dropped", ["Allied_Trust_HO3", "Sage_-_SURE_HO-3_-_01.31.2026"])
    def test_any_skipped_carrier_gets_the_row(self, dropped):
        results = _replayed_run(OWNERSHIP_BASE_PROFILE,
                                _answer_for([c for c in _usable("Owner Occupied") if c != dropped]))
        assert [r["carrier"] for r in results if r["status"] == NOT_EVALUATED] == [dropped]

    def test_an_abbreviated_name_still_counts_as_an_answer(self):
        """"Orion HO3" is Orion's record (round-17 spelling), not an omission."""
        orion = "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3"
        answer = _answer_for([c for c in _usable("Owner Occupied") if c != orion],
                             **{"Orion HO3": {"status": "ELIGIBLE"}})
        results = _replayed_run(OWNERSHIP_BASE_PROFILE, answer)
        assert not [r for r in results if r["status"] == NOT_EVALUATED]

    def test_a_parse_failure_still_shows_the_warning_rows(self):
        results = _replayed_run(OWNERSHIP_BASE_PROFILE, "this is not json [ {")
        assert results[0]["carrier"] == "Parse Error"
        assert {r["carrier"] for r in results if r["status"] == GUIDE_UNAVAILABLE} == set(_DEFECTIVE_HO)
        assert not [r for r in results if r["status"] == NOT_EVALUATED]


# ---------------------------------------------------------------------------
# Step "now" (Liam, 2026-09-29): the pipeline's model call behind the same
# provider switch chat.py uses. This suite itself is pinned to Sonnet in
# conftest.py regardless of ELIGIBILITY_MODEL's default, so every test above
# this point still exercises what it was calibrated against -- these are the
# only tests that touch the switch itself.
# ---------------------------------------------------------------------------

@pytest.mark.retrieval
@pytest.mark.parametrize("model, is_openai", [
    ("gpt-6-luna", True),
    ("gpt-4o", True),
    ("o3-mini", True),
    ("o1", True),
    ("claude-sonnet-4-5", False),
    ("claude-opus-5-5", False),
])
def test_is_openai_model_matches_by_prefix(model, is_openai):
    assert _is_openai_model(model) is is_openai


@pytest.mark.retrieval
def test_the_suite_itself_is_pinned_to_sonnet():
    """Pins conftest.py's setdefault, so a change there that lets the
    default (gpt-6-luna) leak into the suite fails loudly here instead of
    as a real API call inside a 'retrieval' test."""
    import eligibility_check as ec
    assert ec.ELIGIBILITY_MODEL == "claude-sonnet-4-5"
    assert not _is_openai_model(ec.ELIGIBILITY_MODEL)


@pytest.mark.retrieval
def test_complete_dispatches_on_the_model_name(monkeypatch):
    """The one thing this suite can check without an OpenAI key: _complete
    routes to the Anthropic branch (which the rest of the suite mocks via
    client.messages.create) when ELIGIBILITY_MODEL is not an OpenAI model,
    and to the OpenAI branch when it is -- without touching client at all."""
    import eligibility_check as ec

    def boom_openai(*a, **k):
        raise AssertionError("OpenAI branch reached for a Sonnet model")
    monkeypatch.setattr(ec, "_complete_openai", boom_openai)
    monkeypatch.setattr(ec, "_complete_anthropic", lambda *a, **k: ("[]", {}))
    assert ec._complete("sys", "user", 100) == ("[]", {})

    def boom_anthropic(*a, **k):
        raise AssertionError("Anthropic branch reached for an OpenAI model")
    monkeypatch.setattr(ec, "ELIGIBILITY_MODEL", "gpt-6-luna")
    monkeypatch.setattr(ec, "_complete_anthropic", boom_anthropic)
    monkeypatch.setattr(ec, "_complete_openai", lambda *a, **k: ("[]", {}))
    assert ec._complete("sys", "user", 100) == ("[]", {})


@pytest.mark.retrieval
def test_complete_anthropic_shape_is_unchanged():
    """THE REVERT PATH: with ELIGIBILITY_MODEL back on Sonnet, the request
    _complete_anthropic sends is identical in every field the rest of the
    suite (and the real pipeline pre-Luna) depends on -- model, system cache
    control, and the single-user-message shape client.messages.create() is
    mocked against everywhere else in this file."""
    import eligibility_check as ec
    captured = {}
    monkeypatch_original = ec.client.messages.create

    def fake(**kwargs):
        captured.update(kwargs)
        raise _PromptCaptured()

    ec.client.messages.create = fake
    try:
        ec._complete_anthropic("SYS TEXT", "USER TEXT", 999)
    except _PromptCaptured:
        pass
    finally:
        ec.client.messages.create = monkeypatch_original
    assert captured["model"] == "claude-sonnet-4-5"
    assert captured["max_tokens"] == 999
    assert captured["system"] == [{"type": "text", "text": "SYS TEXT",
                                   "cache_control": {"type": "ephemeral"}}]
    assert captured["messages"] == [{"role": "user", "content": "USER TEXT"}]
    assert captured["temperature"] == 0


# ---------------------------------------------------------------------------
# 2026-09-30 LIVE BUG: all four result columns empty on an ordinary profile.
# Captured, one real gpt-6-luna call: finish_reason "stop", 23 well-formed
# records, and NOT ONE had a "status" or "flaw_count" key (the verdict words
# appear 0 times in 28,561 characters). assign_buckets placed none of them;
# _add_fixed_rows counted coverage by NAME, so no NOT_EVALUATED row appeared
# either. All zero-API: the model call is answered from a fixture.
# ---------------------------------------------------------------------------

_LIVE_BUG_PROFILE = {
    "year_built": 2000, "roof_age": 10, "roof_type": "Composition Shingle",
    "roof_shape": "Gable", "construction_type": "Frame", "plumbing_type": "Copper",
    "occupancy_type": "Owner Occupied", "ownership_type": "Individual Owner",
    "coastal_tier": "Not Coastal", "swimming_pool": "Above Ground - Fenced",
    "pool_accessories": "None", "has_dogs": "No", "aggressive_breed": "No",
    "solar_panels": "Yes", "ppc": "2"}

# Two records from the live capture, verbatim apart from trimming -- no
# status, no flaw_count.
_LIVE_STATUSLESS_RECORDS = [
    {"carrier": "ARI_(HOA+)",
     "reasons": ["This HOA+ program requires an owner-occupied residence, and the property is owner occupied."],
     "citations": ["ARI_(HOA+): “An inspection is required on homes over 5 years old.”"],
     "missing_info": ["Whether the pool fence is at least 6 feet high and has a locked or self-locking gate."],
     "notes": "HOA Coverage A is ACV by default; replacement cost on Coverage A or B, or both, may be purchased."},
    {"carrier": "ARI_(HOB)",
     "reasons": ["This HOB program requires an owner-occupied residence, and the property is owner occupied."],
     "citations": ["ARI_(HOB): “Homes 0-20 years old are eligible for this program.”"],
     "missing_info": ["Whether the pool fence is at least 6 feet high and has a locked or self-locking gate."],
     "notes": "The excerpt states that roofs 15 years or older are covered on an ACV basis."},
]


def _replay_live(raw):
    return _replayed_run(_LIVE_BUG_PROFILE, raw)


def _all_placed_once(results):
    buckets = assign_buckets(results)
    placed = [id(r) for b in buckets.values() for r in b]
    return len(placed) == len(results) == len(set(placed))


def _with_status(status, flaw="0"):
    """A full answer with every record's status and flaw_count replaced."""
    import json
    recs = json.loads(_answer_for(_usable("Owner Occupied")))
    raw = json.dumps(recs)
    return raw.replace('"status": "ELIGIBLE", "flaw_count": 0',
                       '"status": %s, "flaw_count": %s' % (json.dumps(status), flaw))


@pytest.mark.retrieval
class TestNoSilentlyEmptyResult:

    def test_the_exact_live_shape_now_shows_a_row_for_every_carrier(self):
        """THE LIVE BUG: status-less records must not vanish."""
        import json
        results = _replay_live(json.dumps(_LIVE_STATUSLESS_RECORDS))
        b = assign_buckets(results)
        unrec = {r["carrier"] for r in b["unrecognised"]}
        assert unrec == {"ARI_(HOA+)", "ARI_(HOB)"}
        assert all("('no status given')" in r["reasons"][0] for r in b["unrecognised"])
        # the carriers the model did not answer at all still get a row
        assert {r["carrier"] for r in b["not_evaluated"]} == set(_usable("Owner Occupied")) - unrec
        assert usable_answer_count(results) == 0
        assert _all_placed_once(results)

    @pytest.mark.parametrize("raw", ["[]", "", "I'm sorry, but I can't help with that request.",
                                     '{"note": "no list here"}'],
                             ids=["empty-list", "empty-string", "refusal", "wrapper-without-list"])
    def test_no_usable_answer_is_reported_as_such(self, raw):
        results = _replay_live(raw)
        assert usable_answer_count(results) == 0
        assert _all_placed_once(results)
        if raw in ("[]", '{"note": "no list here"}'):
            assert len(assign_buckets(results)["not_evaluated"]) == len(_usable("Owner Occupied"))

    @pytest.mark.parametrize("written, expected", [
        ("eligible", "ELIGIBLE"), (" Ineligible ", "INELIGIBLE"), ("refer", "REFER"),
        ("insufficient information", "INSUFFICIENT_INFORMATION"),
        ("Insufficient-Information", "INSUFFICIENT_INFORMATION"),
    ])
    def test_status_is_normalised_by_case_space_and_hyphen_only(self, written, expected):
        results = _replay_live(_with_status(written))
        usable = set(_usable("Owner Occupied"))          # once, not once per record
        statuses = {r["status"] for r in results if r["carrier"] in usable}
        assert expected in statuses
        assert not assign_buckets(results)["unrecognised"]

    @pytest.mark.parametrize("made_up", ["NOT_ELIGIBLE", "APPROVED", "Maybe", "PASS"])
    def test_a_made_up_status_is_never_mapped_to_a_real_one(self, made_up):
        """No synonyms: 'NOT_ELIGIBLE' is not 'INELIGIBLE'."""
        results = _replay_live(_with_status(made_up))
        b = assign_buckets(results)
        assert len(b["unrecognised"]) == len(_usable("Owner Occupied"))
        assert all(made_up in r["reasons"][0] and repr(made_up) in r["notes"] for r in b["unrecognised"])
        assert usable_answer_count(results) == 0
        assert _all_placed_once(results)

    @pytest.mark.parametrize("flaw, one_issue", [('"1"', True), ('"2"', False), ('"one"', False),
                                                 ("null", False), ("1.0", True)])
    def test_flaw_count_is_coerced_to_an_int(self, flaw, one_issue):
        results = _replay_live(_with_status("INELIGIBLE", flaw))
        model = [r for r in results if r["status"] == "INELIGIBLE"]
        assert model and all(isinstance(r["flaw_count"], int) for r in model)
        assert (len(assign_buckets(results)["one_issue"]) == len(model)) is one_issue
        assert _all_placed_once(results)

    def test_an_unrecognised_record_does_not_cover_a_real_carrier(self):
        """It shares its name with a real carrier: that carrier gets exactly
        one row, the unrecognised-verdict one -- never nothing, never two."""
        import json
        answered = [c for c in _usable("Owner Occupied") if c != "Allied_Trust_HO3"]
        recs = json.loads(_answer_for(answered))
        recs.append(dict(recs[0], carrier="Allied_Trust_HO3", status="SOMETHING_ELSE"))
        results = _replay_live(json.dumps(recs))
        allied = [r for r in results if r["carrier"] == "Allied_Trust_HO3"]
        assert [r["status"] for r in allied] == [UNRECOGNISED_VERDICT]
        assert not assign_buckets(results)["not_evaluated"]
        assert usable_answer_count(results) == len(answered)

    def test_the_diagnostics_are_printed_when_the_answer_is_unusable(self, capsys):
        import json
        _replay_live(json.dumps(_LIVE_STATUSLESS_RECORDS))
        out = capsys.readouterr().out
        assert "UNUSABLE MODEL ANSWER" in out
        assert "RAW RESPONSE HEAD:" in out and "RAW RESPONSE TAIL:" in out

    def test_app_shows_the_error_banner_and_the_new_bucket(self):
        app_src = open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8").read()
        assert "The check did not return usable answers. Run it again; if it repeats, tell Liam." in app_src
        assert "usable_answer_count(results) == 0" in app_src
        assert 'buckets["unrecognised"]' in app_src


@pytest.mark.retrieval
@pytest.mark.parametrize("seed", range(20))
def test_every_record_lands_in_exactly_one_bucket_whatever_its_status(seed):
    """The invariant, on random and garbage statuses and flaw counts."""
    import random
    rng = random.Random(seed)
    pool = ["ELIGIBLE", "INELIGIBLE", "REFER", "INSUFFICIENT_INFORMATION", GUIDE_UNAVAILABLE,
            NOT_EVALUATED, UNRECOGNISED_VERDICT, "eligible", "NOT_ELIGIBLE", "", None, 7,
            "Insufficient Information", "—", ["ELIGIBLE"]]
    results = [{"carrier": "c%d" % i, "status": rng.choice(pool),
                "flaw_count": rng.choice([0, 1, 2, "1", None, "x"])} for i in range(rng.randint(0, 40))]
    buckets = assign_buckets(results)
    placed = [id(r) for b in buckets.values() for r in b]
    assert sorted(placed) == sorted(id(r) for r in results)


# ---------------------------------------------------------------------------
# Round 19, Step 1 (Liam, 2026-09-30): three OPTIONAL intake fields -- County,
# Dwelling amount (Coverage A), Dwelling type. Blank = unknown, and a blank
# field must leave the prompt byte-identical (proved once against 31abddc
# itself on STANDARD, ALT, COASTAL_PPC4 and OWNERSHIP_BASE; pinned here in a
# DB-independent form). All zero-API.
# ---------------------------------------------------------------------------

import intake_fields

_BLANK_OPTIONALS = {"county": "", "dwelling_amount": None, "dwelling_type": ""}


@pytest.mark.retrieval
class TestOptionalIntakeFields:

    def test_texas_has_254_counties_in_the_committed_list(self):
        assert len(intake_fields.TEXAS_COUNTIES) == 254
        assert len(set(intake_fields.TEXAS_COUNTIES)) == 254
        for name in ("Harris", "Bexar", "Travis", "Hidalgo", "Dallas", "Nueces", "Polk"):
            assert name in intake_fields.TEXAS_COUNTIES

    @pytest.mark.parametrize("written, expected", [
        ("Harris", "Harris"), ("harris county", "Harris"), ("  BEXAR ", "Bexar"),
        ("", ""), (None, ""), ("Atlantis", ""), ("Harris, TX", ""),
    ])
    def test_county_is_one_of_the_254_or_unknown(self, written, expected):
        assert intake_fields.normalize_county(written) == expected

    @pytest.mark.parametrize("written, expected", [
        ("450000", 450000), ("450,000", 450000), ("$450,000", 450000), ("$450,000.00", 450000),
        ("450k", 450000), ("1.2m", 1200000), (" 1,000,000 ", 1000000), (325000, 325000),
        ("", None), (None, None), ("   ", None), ("four hundred", None), ("-5000", None),
        ("0", None), ("45O,000", None),
    ])
    def test_dwelling_amount_parses_or_is_unknown(self, written, expected):
        assert intake_fields.parse_dwelling_amount(written) == expected

    def test_app_offers_blank_first_and_never_a_default_answer(self):
        src = open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8").read()
        assert '[""] + intake_fields.TEXAS_COUNTIES' in src
        assert 'list(intake_fields.DWELLING_TYPES)' in src and intake_fields.DWELLING_TYPES[0] == ""
        assert '"Dwelling amount (Coverage A, $)", value=""' in src
        for key in ('"county": county', '"dwelling_amount": dwelling_amount', '"dwelling_type": dwelling_type'):
            assert key in src

    @pytest.mark.parametrize("profile", [STANDARD_PROFILE, ALT_PROFILE, COASTAL_PPC4_PROFILE,
                                         OWNERSHIP_BASE_PROFILE],
                             ids=["STANDARD", "ALT", "COASTAL_PPC4", "OWNERSHIP_BASE"])
    def test_blank_optional_fields_leave_the_prompt_byte_identical(self, profile):
        assert _captured_prompt(dict(profile, **_BLANK_OPTIONALS)) == _captured_prompt(dict(profile))

    def test_each_filled_field_is_stated_once_and_only_when_filled(self):
        blank = _captured_prompt(dict(STANDARD_PROFILE, **_BLANK_OPTIONALS))
        for absent in ("county:", "dwelling amount (coverage a):", "dwelling type:"):
            assert absent not in blank
        filled = _captured_prompt(dict(STANDARD_PROFILE, county="harris county",
                                       dwelling_amount="$450,000", dwelling_type="Townhome"))
        for line in ("county: harris", "dwelling amount (coverage a): $450,000", "dwelling type: townhome"):
            assert filled.count(line) == 1, line

    def test_house_routes_the_condo_programs_out(self):
        house = dict(OWNERSHIP_BASE_PROFILE, dwelling_type="House")
        per, _ = _captured_sections(house)
        assert "Progressive_HO6_-_10.01.2025" not in per
        # the defective Liberty Mutual HO6 record gets no warning row either
        results = _replayed_run(house, _answer_for([c for c in _usable("Owner Occupied")
                                                    if "HO6" not in c]))
        assert not [r for r in results if "HO6" in r["carrier"]]

    @pytest.mark.parametrize("dtype", ["Townhome", "Condo", ""])
    def test_townhome_and_condo_change_no_routing(self, dtype):
        per, _ = _captured_sections(dict(OWNERSHIP_BASE_PROFILE, dwelling_type=dtype))
        assert "Progressive_HO6_-_10.01.2025" in per

    @pytest.mark.parametrize("carrier, rule", [
        ("Progressive_HO3_-_04.01.2026", "maximum coverage a – dwelling binding authority is $1,500,000"),
        ("Mercury_HO3_-_01.01.2026", "homeowners (coverage a) n/a $ 1,500,000"),
    ])
    def test_the_coverage_a_guarantee_runs_only_when_the_amount_is_filled(self, carrier, rule):
        """Measured 2026-09-30: with an amount filled, 19 of 25 carriers gain
        a chunk; these two only get their limit rule through the guarantee
        (Allied Trust's already arrives by ordinary retrieval)."""
        blank, _ = _captured_sections(dict(OWNERSHIP_BASE_PROFILE, **_BLANK_OPTIONALS))
        filled, _ = _captured_sections(dict(OWNERSHIP_BASE_PROFILE, dwelling_amount=450000))
        assert rule not in blank.get(carrier, "")
        assert rule in filled[carrier]

    @pytest.mark.parametrize("text", [
        "Coverage A Limit | $200,000 to $1,250,000 (Over $1,250,000 submit to underwriting.)",
        "For all eligible risks, the maximum Coverage A – Dwelling Binding Authority is $1,500,000.",
        "Dwelling Coverage | | $150,000 minimum, up to $2,000,000.",
        "Coverage A: Maximum $2 million",
        "| Minimum | $100,000 Coverage A |",
    ], ids=["allied", "progressive", "hoaic", "twico", "vave-table"])
    def test_coverage_a_limit_phrasings_match(self, text):
        assert _mentions_coverage_a_limit(text)

    @pytest.mark.parametrize("text", [
        "The base policy automatically provides up to 10% of the Coverage A Limit.",
        "A renovation is having a total budget of 10% or more of the current coverage A limit.",
        "Personal Injury - Optional $10K, $25K and $50K",
    ])
    def test_coverage_a_noise_does_not_rank_first(self, text):
        """Percent-of references may match, but must rank below a real limit."""
        real = Document(page_content="Coverage A Limit | $200,000 to $1,250,000 maximum")
        noise = Document(page_content=text)
        assert _coverage_a_priority_key(real) < _coverage_a_priority_key(noise)


# ---------------------------------------------------------------------------
# Round 19, Step 2 (Liam, 2026-09-30): the Sage ADDRESS rule. County blank ->
# INSUFFICIENT_INFORMATION with County named; in territory -> the model's
# verdict stands; outside -> INELIGIBLE quoting the guide. Keyed on carrier
# identity and the County field only. All zero-API: the model answer is a
# fixture, and the real FPC upgrade runs on it first.
# ---------------------------------------------------------------------------

import chat as _chat
import guides as _guides
from structured_rules import sage_county_in_territory, SAGE_EAST_TEXAS_COUNTIES
from eligibility_check import _SAGE_LOCATION_RULE

_SAGE_WITH_ADDRESS_RULE_HO = [
    "Sage_-_Auros_HO3", "Sage_-_SURE_HO-3_-_01.31.2026", "Sage_-_SafePort_HO-3_-_01.31.2026",
    "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026", "Sage_-_Wilshire_HO3_-_12.02.2025",
]
_SAGE_UNRESTRICTED = ["Sage_-_Markel_HO3", "Sage_-_Vave_HO3_-_07.01.2026"]

# Liam's live profile: PPC 3, so the Sage FPC table resolves ELIGIBLE and the
# upgrade fires.
_LIAM_PPC3 = dict(_LIVE_BUG_PROFILE, ppc="3", swimming_pool="No Pool", solar_panels="No")


def _sage_answer(status="INSUFFICIENT_INFORMATION", notes="FPC 3 is eligible regardless of driving distance."):
    """Every usable carrier answered; the Sage ones in the exact live shape --
    the model holds on something, and its text mentions FPC, so the Sage FPC
    upgrade flips it to ELIGIBLE."""
    import json
    recs = json.loads(_answer_for(_usable("Owner Occupied")))
    for r in recs:
        if r["carrier"] in _SAGE_WITH_ADDRESS_RULE_HO + _SAGE_UNRESTRICTED:
            r.update(status=status, notes=notes,
                     missing_info=["Whether the property's county is within the eligible area"])
    return json.dumps(recs)


def _by_carrier(results):
    return {r["carrier"]: r for r in results}


@pytest.mark.retrieval
class TestSageCountyHold:

    def test_the_guides_carry_the_rule_exactly_where_the_table_says(self):
        """Read from every Sage guide 2026-09-30. Markel and Vave only require
        Texas; everyone in the table carries the county sentence verbatim."""
        for carrier, (_, sentence) in _SAGE_LOCATION_RULE.items():
            text = _guides.guide_text(carrier)
            assert _chat._compare_key(sentence) in _chat._compare_key(text), carrier
            assert _chat._appears_in(sentence, text), carrier
        for carrier in _SAGE_UNRESTRICTED:
            text = _guides.guide_text(carrier).lower()
            assert "31 degrees" not in text and "state of texas" in text

    def test_the_trium_sentence_has_no_nueces_exception_and_the_others_do(self):
        assert _SAGE_LOCATION_RULE["Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026"][0] is False
        assert "Nueces" not in _SAGE_LOCATION_RULE["Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026"][1]
        for c in _SAGE_WITH_ADDRESS_RULE_HO:
            if "Trium" not in c:
                assert _SAGE_LOCATION_RULE[c][0] is True

    @pytest.mark.parametrize("county, expected", [
        ("Harris", "IN"), ("Bexar", "IN"), ("Travis", "IN"), ("Hidalgo", "IN"),
        ("Dallas", "OUT"), ("Tarrant", "OUT"), ("Lubbock", "OUT"),
        ("Nueces", "OUT"),                          # the guide's own exception
        ("", "UNKNOWN"), ("Atlantis", "UNKNOWN"),
    ])
    def test_territory_sanity_table(self, county, expected):
        assert sage_county_in_territory(county, intake_fields.COUNTY_MAX_LATITUDE) == expected

    @pytest.mark.parametrize("county", SAGE_EAST_TEXAS_COUNTIES)
    def test_the_eight_east_texas_counties_are_in_by_name(self, county):
        """All eight reach north of 31 degrees -- in only because the guide names them."""
        assert intake_fields.COUNTY_MAX_LATITUDE[county] >= 31.0
        assert sage_county_in_territory(county, intake_fields.COUNTY_MAX_LATITUDE) == "IN"

    def test_nueces_is_in_for_trium_only(self):
        assert sage_county_in_territory("Nueces", intake_fields.COUNTY_MAX_LATITUDE, False) == "IN"

    def test_county_blank_holds_all_five_even_after_the_fpc_upgrade(self):
        """THE LIVE BUG."""
        by = _by_carrier(_replayed_run(_LIAM_PPC3, _sage_answer()))
        for c in _SAGE_WITH_ADDRESS_RULE_HO:
            r = by[c]
            assert r["status"] == "INSUFFICIENT_INFORMATION", (c, r["status"])
            assert "Structured FPC check" in r["notes"], "premise: the FPC upgrade fired first"
            assert r["missing_info"][0].startswith("County -- this guide only writes in specific counties")

    @pytest.mark.parametrize("status", ["ELIGIBLE", "REFER"])
    def test_county_blank_holds_a_model_eligible_or_refer_too(self, status):
        by = _by_carrier(_replayed_run(_LIAM_PPC3, _sage_answer(status=status, notes="x")))
        for c in _SAGE_WITH_ADDRESS_RULE_HO:
            assert by[c]["status"] == "INSUFFICIENT_INFORMATION", c

    def test_the_hold_does_not_depend_on_any_model_wording(self):
        """No location, county, FPC or PPC words anywhere in the record."""
        import json
        recs = json.loads(_answer_for(_usable("Owner Occupied")))
        for r in recs:
            r.update(reasons=["Looks fine."], notes="", missing_info=[], citations=[])
        by = _by_carrier(_replayed_run(_LIAM_PPC3, json.dumps(recs)))
        for c in _SAGE_WITH_ADDRESS_RULE_HO:
            assert by[c]["status"] == "INSUFFICIENT_INFORMATION", c
            assert _county_item_present(by[c]["missing_info"])

    def test_county_harris_leaves_the_verdict_alone(self):
        by = _by_carrier(_replayed_run(dict(_LIAM_PPC3, county="Harris"), _sage_answer()))
        for c in _SAGE_WITH_ADDRESS_RULE_HO:
            assert by[c]["status"] == "ELIGIBLE", c        # the FPC upgrade's verdict stands
            assert not _county_item_present(by[c]["missing_info"])

    def test_county_dallas_is_ineligible_quoting_the_guide(self):
        by = _by_carrier(_replayed_run(dict(_LIAM_PPC3, county="Dallas"), _sage_answer()))
        for c in _SAGE_WITH_ADDRESS_RULE_HO:
            r = by[c]
            sentence = _SAGE_LOCATION_RULE[c][1]
            assert r["status"] == "INELIGIBLE" and r["flaw_count"] == 1, c
            assert f"{c}: '{sentence}'" in r["citations"]
            assert _chat._appears_in(sentence, _guides.guide_text(c)), c   # quote-in-own-guide

    def test_nueces_splits_the_family(self):
        by = _by_carrier(_replayed_run(dict(_LIAM_PPC3, county="Nueces"), _sage_answer()))
        assert by["Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026"]["status"] == "ELIGIBLE"
        assert by["Sage_-_Auros_HO3"]["status"] == "INELIGIBLE"

    @pytest.mark.parametrize("county", ["", "Dallas", "Nueces"])
    @pytest.mark.parametrize("status", ["ELIGIBLE", "INSUFFICIENT_INFORMATION"])
    def test_markel_and_vave_are_untouched(self, county, status):
        """The County field has no effect on them at all: same record as
        with a county that every rule accepts."""
        answer = _sage_answer(status=status)
        got = _by_carrier(_replayed_run(dict(_LIAM_PPC3, county=county), answer))
        ref = _by_carrier(_replayed_run(dict(_LIAM_PPC3, county="Harris"), answer))
        for c in _SAGE_UNRESTRICTED:
            assert got[c] == ref[c], (c, county)
            assert not _county_item_present(got[c]["missing_info"])
            assert "County hold" not in got[c]["notes"]

    def test_an_already_ineligible_record_keeps_its_verdict(self):
        by = _by_carrier(_replayed_run(_LIAM_PPC3, _sage_answer(status="INELIGIBLE", notes="x")))
        for c in _SAGE_WITH_ADDRESS_RULE_HO:
            assert by[c]["status"] == "INELIGIBLE", c


def _held_only_on_county(r):
    """An ALT (PPC 1, no County) Sage record the FPC table did not hold: either
    not INSUFFICIENT at all, or INSUFFICIENT with the County hold applied and
    no fire-station distance question (the FPC hold's own item)."""
    if r.get("status") != "INSUFFICIENT_INFORMATION":
        return True
    mi = r.get("missing_info", [])
    return (_county_item_present(mi) and "County hold" in (r.get("notes") or "")
            and not any("fire station" in m.lower() and "fpc 9" in m.lower() for m in mi))


@pytest.mark.retrieval
@pytest.mark.parametrize("carrier", ["Sage_-_Auros_HO3", "Sage_-_Wilshire_HO3_-_12.02.2025"])
def test_the_updated_alt_baseline_check_accepts_a_county_hold(carrier):
    """Pins _held_only_on_county, the zero-API half of the ALT baseline
    change above, on the exact shape the pipeline now produces for PPC 1."""
    by = _by_carrier(_replayed_run(ALT_PROFILE, _sage_answer(notes="FPC 1 is eligible regardless.")))
    assert by[carrier]["status"] == "INSUFFICIENT_INFORMATION"
    assert _held_only_on_county(by[carrier])
    assert not _held_only_on_county(dict(by[carrier], notes="", missing_info=[
        "Driving distance to the responding fire station (needed to determine FPC 9+ eligibility)."]))


# ---------------------------------------------------------------------------
# Round 19, Step 3 (Liam, 2026-09-30): the CHUBB Coverage A hold. Dwelling
# amount blank -> ELIGIBLE / REFER become INSUFFICIENT_INFORMATION with
# Coverage A named; filled -> the model's verdict stands, with a note of what
# the guide says for that amount. Keyed on carrier identity and the field
# only. All zero-API.
# ---------------------------------------------------------------------------

from eligibility_check import _CHUBB, _CHUBB_COVERAGE_A_ITEM, _chubb_amount_note


def _chubb_answer(status="ELIGIBLE", reasons=None, notes=""):
    """The live 2026-09-30 shape: Eligible from one sentence."""
    import json
    recs = json.loads(_answer_for(_usable("Owner Occupied")))
    for r in recs:
        if r["carrier"] == _CHUBB:
            r.update(status=status, notes=notes, reasons=reasons or [
                "The owner-occupant of a house is an eligible person."], missing_info=[])
    return json.dumps(recs)


@pytest.mark.retrieval
class TestChubbCoverageAHold:

    @pytest.mark.parametrize("status", ["ELIGIBLE", "REFER"])
    def test_amount_blank_holds_eligible_and_refer(self, status):
        r = _by_carrier(_replayed_run(_LIAM_PPC3, _chubb_answer(status)))[_CHUBB]
        assert r["status"] == "INSUFFICIENT_INFORMATION"
        assert r["missing_info"][0] == _CHUBB_COVERAGE_A_ITEM
        assert "$1,000,000" in r["missing_info"][0] and "pre-approval" in r["missing_info"][0]

    def test_amount_blank_names_coverage_a_on_an_already_insufficient_record(self):
        r = _by_carrier(_replayed_run(_LIAM_PPC3, _chubb_answer("INSUFFICIENT_INFORMATION")))[_CHUBB]
        assert r["status"] == "INSUFFICIENT_INFORMATION"
        assert _CHUBB_COVERAGE_A_ITEM in r["missing_info"]

    def test_amount_blank_leaves_ineligible_alone(self):
        r = _by_carrier(_replayed_run(_LIAM_PPC3, _chubb_answer("INELIGIBLE")))[_CHUBB]
        assert r["status"] == "INELIGIBLE"

    def test_the_hold_does_not_depend_on_any_model_wording(self):
        r = _by_carrier(_replayed_run(_LIAM_PPC3, _chubb_answer(reasons=["Looks fine."])))[_CHUBB]
        assert r["status"] == "INSUFFICIENT_INFORMATION"

    # Changed deliberately 2026-10-01 (round 20, Liam): below $1,000,000 an
    # ELIGIBLE now becomes REFER (TestChubbBelowMinimumRefer); the note stays.
    @pytest.mark.parametrize("amount, phrase, status", [
        (450000, "Subject to pre-approval", "REFER"),
        (999999, "Subject to pre-approval", "REFER"),
        (1000000, "Preferred Tier", "ELIGIBLE"),
        (2500000, "Preferred Tier", "ELIGIBLE"),
    ])
    def test_amount_filled_notes_the_guide(self, amount, phrase, status):
        r = _by_carrier(_replayed_run(dict(_LIAM_PPC3, dwelling_amount=amount), _chubb_answer()))[_CHUBB]
        assert r["status"] == status
        assert phrase in r["notes"] and f"${amount:,}" in r["notes"]
        assert _CHUBB_COVERAGE_A_ITEM not in r["missing_info"]

    @pytest.mark.parametrize("fragment", [
        "Subject to pre-approval",
        "Coverage will not be declined solely based on the minimum of value of the property",
        "Minimum: $1,000,000",
        "risks are unacceptable in any Tier",
        "Risks in Flood Zone A are subject to pre-approval",
        "Risks or applicants with a loss history will require underwriter approval",
        "become eligible for placement in our Standard Tier",
    ])
    def test_every_guide_phrase_the_hold_quotes_is_in_chubbs_guide(self, fragment):
        assert _chat._compare_key(fragment) in _chat._compare_key(_guides.guide_text(_CHUBB))

    def test_the_notes_quote_only_what_the_guide_says(self):
        for amount in (450000, 1500000):
            note = _chubb_amount_note(amount)
            for quoted in re.findall(r'"([^"]+)"', note):
                assert _chat._compare_key(quoted) in _chat._compare_key(_guides.guide_text(_CHUBB)), quoted

    def test_no_other_carrier_is_touched(self):
        blank = _by_carrier(_replayed_run(_LIAM_PPC3, _chubb_answer()))
        filled = _by_carrier(_replayed_run(dict(_LIAM_PPC3, dwelling_amount=450000), _chubb_answer()))
        for c in blank:
            if c != _CHUBB:
                assert blank[c] == filled[c], c


# ---------------------------------------------------------------------------
# Round 20, Step 1 (Liam, 2026-10-01): CHUBB below $1,000,000 Coverage A is a
# referral. Keyed on carrier identity and the parsed amount only.
# ---------------------------------------------------------------------------

from eligibility_check import _CHUBB_BELOW_MINIMUM_REFER_NOTE


def _chubb_record(status, missing_info=(), amount=None, reasons=None):
    import json
    answer = json.loads(_chubb_answer(status, reasons=reasons))
    for rec in answer:
        if rec["carrier"] == _CHUBB:
            rec["missing_info"] = list(missing_info)
            if status == "INELIGIBLE":
                rec["flaw_count"] = 1
    profile = dict(_LIAM_PPC3) if amount is None else dict(_LIAM_PPC3, dwelling_amount=amount)
    return _by_carrier(_replayed_run(profile, json.dumps(answer)))


@pytest.mark.retrieval
class TestChubbBelowMinimumRefer:

    @pytest.mark.parametrize("amount", [999999, "$950,000", "950000", "450k", "$999,999.00"])
    def test_eligible_below_one_million_becomes_refer(self, amount):
        r = _chubb_record("ELIGIBLE", amount=amount)[_CHUBB]
        assert r["status"] == "REFER" and r["flaw_count"] == 0
        assert _CHUBB_BELOW_MINIMUM_REFER_NOTE in r["notes"]

    @pytest.mark.parametrize("amount", [1000000, "1,000,000", "$1,000,000", "1m", "$2.5m"])
    def test_one_million_and_up_is_unchanged(self, amount):
        r = _chubb_record("ELIGIBLE", amount=amount)[_CHUBB]
        assert r["status"] == "ELIGIBLE"
        assert _CHUBB_BELOW_MINIMUM_REFER_NOTE not in r["notes"]

    def test_ineligible_below_one_million_is_untouched(self):
        r = _chubb_record("INELIGIBLE", amount=450000,
                          reasons=["Wildfire classification 24-50 is unacceptable in any Tier."])[_CHUBB]
        assert r["status"] == "INELIGIBLE"
        assert _CHUBB_BELOW_MINIMUM_REFER_NOTE not in r["notes"]

    def test_insufficient_open_for_another_fact_is_untouched(self):
        r = _chubb_record("INSUFFICIENT_INFORMATION", amount=450000,
                          missing_info=["Flood Zone -- Zone A is subject to pre-approval."])[_CHUBB]
        assert r["status"] == "INSUFFICIENT_INFORMATION"
        assert r["missing_info"] == ["Flood Zone -- Zone A is subject to pre-approval."]
        assert _CHUBB_BELOW_MINIMUM_REFER_NOTE not in r["notes"]

    def test_refer_from_the_model_stays_refer(self):
        r = _chubb_record("REFER", amount=450000)[_CHUBB]
        assert r["status"] == "REFER"

    @pytest.mark.parametrize("amount", [None, "", "abc", "0", "-5"])
    def test_blank_or_unparseable_stays_insufficient(self, amount):
        r = _chubb_record("ELIGIBLE", amount=amount)[_CHUBB]
        assert r["status"] == "INSUFFICIENT_INFORMATION"
        assert r["missing_info"][0] == _CHUBB_COVERAGE_A_ITEM

    def test_no_other_carrier_is_touched_by_a_low_amount(self):
        low = _chubb_record("ELIGIBLE", amount=450000)
        high = _chubb_record("ELIGIBLE", amount=2500000)
        others = [c for c in low if c != _CHUBB]
        assert others
        for c in others:
            assert low[c] == high[c], c
        assert any(low[c]["status"] == "ELIGIBLE" for c in others)

    def test_the_refer_note_quotes_pass_the_quote_check_in_chubbs_guide(self):
        quotes = re.findall(r'"([^"]+)"', _CHUBB_BELOW_MINIMUM_REFER_NOTE)
        assert quotes == ["Subject to pre-approval*",
                          "Coverage will not be declined solely based on the minimum of value of the property."]
        text = _guides.guide_text(_CHUBB)
        for q in quotes:
            assert _chat._appears_in(_chat._compare_key(q), _chat._compare_key(text)), q
            assert q in text, q                                # exact, not just after folding


# ---------------------------------------------------------------------------
# Round 19, Step 4 (Liam, 2026-09-30): enforced output structure on the
# OpenAI path. Zero-API: the OpenAI client is replaced by a recorder.
# ---------------------------------------------------------------------------

from eligibility_check import CARRIER_RESULTS_SCHEMA, MODEL_STATUSES


def _fake_openai_response(content, refusal=None, finish="stop"):
    import types
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=content, refusal=refusal), finish_reason=finish)],
        usage=types.SimpleNamespace(prompt_tokens=10, completion_tokens=5,
                                    prompt_tokens_details=None, completion_tokens_details=None))


@pytest.mark.retrieval
class TestStructuredOutput:

    def test_schema_fields_are_in_order_all_required_no_extras(self):
        item = CARRIER_RESULTS_SCHEMA["properties"]["carriers"]["items"]
        order = ["carrier", "reasons", "citations", "missing_info", "notes", "status", "flaw_count"]
        assert list(item["properties"]) == order            # verdict LAST
        assert item["required"] == order
        assert item["additionalProperties"] is False
        assert CARRIER_RESULTS_SCHEMA["additionalProperties"] is False
        assert CARRIER_RESULTS_SCHEMA["required"] == ["carriers"]
        assert item["properties"]["status"]["enum"] == list(MODEL_STATUSES)
        assert item["properties"]["flaw_count"]["type"] == "integer"

    @pytest.mark.parametrize("on", [True, False])
    def test_response_format_is_sent_only_when_the_flag_is_on(self, on, monkeypatch):
        import eligibility_check as ec
        sent = {}

        class Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        sent.update(kw)
                        return _fake_openai_response('{"carriers": []}')
        monkeypatch.setattr(ec, "ELIGIBILITY_MODEL", "gpt-6-luna")
        monkeypatch.setattr(ec, "ELIGIBILITY_STRUCTURED", on)
        monkeypatch.setattr(ec, "_get_openai_client", lambda: Client)
        ec._complete("sys", "user", 100)
        if on:
            rf = sent["response_format"]
            assert rf["type"] == "json_schema"
            assert rf["json_schema"]["strict"] is True
            assert rf["json_schema"]["schema"] is CARRIER_RESULTS_SCHEMA
            assert sent["reasoning_effort"]            # still sent alongside
        else:
            assert "response_format" not in sent

    def test_a_refusal_is_reported_in_the_stop_reason(self, monkeypatch):
        import eligibility_check as ec

        class Client:
            class chat:
                class completions:
                    @staticmethod
                    def create(**kw):
                        return _fake_openai_response(None, refusal="I can't help with that.")
        monkeypatch.setattr(ec, "ELIGIBILITY_MODEL", "gpt-6-luna")
        monkeypatch.setattr(ec, "_get_openai_client", lambda: Client)
        text, usage = ec._complete("sys", "user", 100)
        assert text == "" and usage["stop_reason"].startswith("refusal:")

    def test_the_wrapped_answer_parses_through_the_real_pipeline(self):
        """{"carriers": [...]} is what strict json_schema returns; the
        existing extraction must place every record."""
        import json
        wrapped = json.dumps({"carriers": json.loads(_answer_for(_usable("Owner Occupied")))})
        results = _replayed_run(OWNERSHIP_BASE_PROFILE, wrapped)
        assert usable_answer_count(results) == len(_usable("Owner Occupied"))
        assert not assign_buckets(results)["unrecognised"]
        assert not assign_buckets(results)["not_evaluated"]


@pytest.mark.retrieval
def test_structured_output_defaults_on():
    """Liam, 2026-09-30: ON by default because 10 of 10 real structured Luna
    checks returned a valid status and integer flaw_count on every record."""
    import eligibility_check as ec
    if os.environ.get("ELIGIBILITY_STRUCTURED") is None:
        assert ec.ELIGIBILITY_STRUCTURED is True


# ---------------------------------------------------------------------------
# Round 20, Step 2 (Liam, 2026-10-01): pool fence-height and gate checkboxes.
# Unchecked means UNKNOWN. Zero API throughout.
# ---------------------------------------------------------------------------

from eligibility_check import _POOL_GATE_RULE, _enforce_pool_spec_support

_FENCED_ALT = dict(ALT_PROFILE, swimming_pool="Above Ground - Fenced")
_BOX_KEYS = ("pool_fence_4ft", "pool_gate_locking")


def _raw_prompt(profile):
    """The exact system + user text sent to the model, byte for byte."""
    import eligibility_check as ec
    captured = {}
    real = ec._complete

    def fake(system_text, user_content, max_tokens):
        captured["text"] = (system_text if isinstance(system_text, str) else repr(system_text)) + \
            "\x00" + (user_content if isinstance(user_content, str) else repr(user_content))
        raise _PromptCaptured()

    ec._complete = fake
    try:
        check_eligibility(dict(profile))
    except _PromptCaptured:
        pass
    finally:
        ec._complete = real
    return captured["text"]


def _boxes(profile, fence, gate):
    return dict(profile, pool_fence_4ft=fence, pool_gate_locking=gate)


def _pool_answer(carrier, status="INSUFFICIENT_INFORMATION", missing_info=()):
    import json
    recs = json.loads(_answer_for(_usable("Owner Occupied")))
    for r in recs:
        if r["carrier"] == carrier:
            r.update(status=status, missing_info=list(missing_info))
    return json.dumps(recs)


_ALLIED = "Allied_Trust_HO3"                    # 4 ft, "locking gate"
_FOREMOST = "Foremost_DP3_and_HO3_-_07.01.2026"  # 4 ft, "self-locking gate"
_ARI = "ARI_(HOA+)"                              # 6 ft
_MODEL_POOL_ITEM = "Confirm the pool fence is at least 4 feet high with a locking gate."


@pytest.mark.retrieval
class TestPoolBoxes:

    @pytest.mark.parametrize("profile", [STANDARD_PROFILE, ALT_PROFILE, COASTAL_PPC4_PROFILE,
                                         OWNERSHIP_BASE_PROFILE, _FENCED_ALT],
                             ids=["STANDARD", "ALT", "COASTAL_PPC4", "OWNERSHIP_BASE", "fenced-ALT"])
    def test_unticked_boxes_leave_the_prompt_byte_identical(self, profile):
        plain = _raw_prompt(profile)
        assert _raw_prompt(_boxes(profile, False, False)) == plain
        assert "Pool Fence Height:" not in plain and "Pool Gate:" not in plain

    @pytest.mark.parametrize("fence, gate", [(True, False), (False, True), (True, True)])
    def test_a_ticked_box_enters_property_details_as_a_stated_fact(self, fence, gate):
        plain = _raw_prompt(STANDARD_PROFILE)
        ticked = _raw_prompt(_boxes(STANDARD_PROFILE, fence, gate))
        added = [l for l in ticked.splitlines() if l not in plain.splitlines()]
        expect = (["Pool Fence Height: confirmed 4 feet or higher"] if fence else []) + \
                 (["Pool Gate: confirmed self-latching and can be locked"] if gate else [])
        assert added == expect
        accessories = STANDARD_PROFILE["pool_accessories"]
        assert f"Pool Accessories: {accessories}\n" + "\n".join(expect) + "\n" in ticked

    @pytest.mark.parametrize("pool", ["No Pool", "Above Ground - Unfenced", "In Ground - Unfenced"])
    def test_boxes_are_ignored_unless_the_pool_is_fenced(self, pool):
        """A stale tick (the boxes are hidden for these answers) never reaches
        the prompt or the checks."""
        base = dict(STANDARD_PROFILE, swimming_pool=pool)
        assert _raw_prompt(_boxes(base, True, True)) == _raw_prompt(base)
        assert _by_carrier(_replayed_run(_boxes(base, True, True), _pool_answer(_ALLIED))) == \
            _by_carrier(_replayed_run(base, _pool_answer(_ALLIED)))

    @pytest.mark.parametrize("truthy", ["yes", "True", 1])
    def test_only_a_real_tick_counts(self, truthy):
        assert _raw_prompt(_boxes(STANDARD_PROFILE, truthy, truthy)) == _raw_prompt(STANDARD_PROFILE)

    # -- each combination against a 4-ft, locking-gate carrier ---------------
    @pytest.mark.parametrize("fence, gate, wants", [
        (False, False, ["fence height", "gate mechanism"]),
        (True, False, ["gate mechanism"]),
        (False, True, ["fence height"]),
        (True, True, []),
    ])
    def test_each_combination_against_a_4ft_carrier(self, fence, gate, wants):
        r = _by_carrier(_replayed_run(_boxes(STANDARD_PROFILE, fence, gate), _pool_answer(_ALLIED)))[_ALLIED]
        ours = [m for m in r["missing_info"] if m.startswith("Pool enclosure specifics")]
        if not wants:
            assert ours == []
        else:
            assert len(ours) == 1
            for w in ("fence height", "gate mechanism"):
                assert (w in ours[0]) == (w in wants), (w, ours[0])

    def test_both_ticked_removes_the_models_own_question_and_frees_the_verdict(self):
        answer = _pool_answer(_ALLIED, missing_info=[_MODEL_POOL_ITEM])
        before = _by_carrier(_replayed_run(STANDARD_PROFILE, answer))[_ALLIED]
        after = _by_carrier(_replayed_run(_boxes(STANDARD_PROFILE, True, True), answer))[_ALLIED]
        assert _MODEL_POOL_ITEM in before["missing_info"] and before["status"] == "INSUFFICIENT_INFORMATION"
        assert after["missing_info"] == [] and after["status"] == "ELIGIBLE"

    def test_one_box_does_not_remove_a_question_about_both(self):
        answer = _pool_answer(_ALLIED, missing_info=[_MODEL_POOL_ITEM])
        r = _by_carrier(_replayed_run(_boxes(STANDARD_PROFILE, True, False), answer))[_ALLIED]
        assert _MODEL_POOL_ITEM in r["missing_info"] and r["status"] == "INSUFFICIENT_INFORMATION"

    def test_a_second_phrasing_of_the_height_question_is_answered_too(self):
        item = "Pool fence height not stated (Allied requires 4-foot-high)."
        r = _by_carrier(_replayed_run(_boxes(STANDARD_PROFILE, True, False),
                                      _pool_answer(_ALLIED, missing_info=[item])))[_ALLIED]
        assert item not in r["missing_info"]

    def test_an_unrelated_open_fact_keeps_the_record_insufficient(self):
        other = "Roof condition -- 5+ years of remaining life must be confirmed."
        r = _by_carrier(_replayed_run(_boxes(STANDARD_PROFILE, True, True),
                                      _pool_answer(_ALLIED, missing_info=[_MODEL_POOL_ITEM, other])))[_ALLIED]
        assert r["missing_info"] == [other] and r["status"] == "INSUFFICIENT_INFORMATION"

    # -- carriers the boxes cannot settle -------------------------------------
    def test_a_stated_height_above_4_stays_open(self):
        """Synthetic spec: a 6-ft carrier with a locking gate."""
        recs = [{"carrier": "Allied_Trust_HO3", "status": "INSUFFICIENT_INFORMATION", "flaw_count": 0,
                 "reasons": [], "citations": [], "missing_info": [_MODEL_POOL_ITEM], "notes": ""}]
        _enforce_pool_spec_support(recs, ["Allied_Trust_HO3"], _boxes(STANDARD_PROFILE, True, True),
                                   {"Allied_Trust_HO3": {"heights": {"6"}, "gates": {"locking"}}})
        ours = [m for m in recs[0]["missing_info"] if m.startswith("Pool enclosure specifics")]
        assert len(ours) == 1 and "fence height" in ours[0] and "6'" in ours[0]
        assert "gate mechanism" not in ours[0]
        assert _MODEL_POOL_ITEM in recs[0]["missing_info"]      # asks about height too
        assert recs[0]["status"] == "INSUFFICIENT_INFORMATION"

    def test_ari_states_6ft_so_a_4ft_box_does_not_settle_it(self):
        r = _by_carrier(_replayed_run(_boxes(STANDARD_PROFILE, True, True), _pool_answer(_ARI)))[_ARI]
        ours = [m for m in r["missing_info"] if m.startswith("Pool enclosure specifics")]
        assert len(ours) == 1 and "6'" in ours[0] and "gate mechanism" not in ours[0]

    # Round 21 (Liam, 2026-10-02): the one strict box settles every wording
    # family. One test per family, each with the carrier's own gate wording.
    @pytest.mark.parametrize("carrier, family", [
        ("Allied_Trust_HO3", "locking gate"),
        ("Foremost_DP3_and_HO3_-_07.01.2026", "self-locking gate"),
        ("Swyfft_-_Benchmark_(Admitted)_HO3", "self-latching gate"),
        ("Sage_-_Auros_HO3", "combination or padlocked gate or self-locking or self-latching mechanism"),
        ("Sage_-_Markel_HO3", "Lockable gate"),
    ])
    def test_the_strict_gate_box_settles_each_wording_family(self, carrier, family):
        assert family.lower() in _POOL_GATE_RULE[carrier][1].lower()
        item = f"Confirm the pool gate meets the carrier's requirement ({family})."
        gate_only = _pool_answer(carrier, missing_info=[item])
        unticked = _by_carrier(_replayed_run(_boxes(STANDARD_PROFILE, True, False), gate_only))[carrier]
        ticked = _by_carrier(_replayed_run(_boxes(STANDARD_PROFILE, True, True), gate_only))[carrier]
        assert item in unticked["missing_info"]
        assert item not in ticked["missing_info"]
        assert not any(m.startswith("Pool enclosure specifics") for m in ticked["missing_info"])

    def test_travelers_ladder_lock_is_not_settled_by_the_gate_box(self):
        tr = "Travelers_HO3_-_06.12.2026"
        assert tr not in _POOL_GATE_RULE
        r = _by_carrier(_replayed_run(_boxes(STANDARD_PROFILE, True, True), _pool_answer(tr)))[tr]
        ours = [m for m in r["missing_info"] if m.startswith("Pool enclosure specifics")]
        assert len(ours) == 1 and "gate mechanism" in ours[0]

    def test_nothing_here_makes_a_carrier_ineligible(self):
        for fence, gate in [(False, False), (True, False), (False, True), (True, True)]:
            for r in _replayed_run(_boxes(STANDARD_PROFILE, fence, gate), _answer_for(_usable("Owner Occupied"))):
                assert r["status"] != "INELIGIBLE", (r["carrier"], fence, gate)

    def test_the_gate_table_quotes_each_carriers_own_guide(self):
        for carrier, (_, phrase) in _POOL_GATE_RULE.items():
            text = _guides.guide_text(carrier)
            assert _chat._appears_in(_chat._compare_key(phrase), _chat._compare_key(text)), carrier

    def test_the_strict_box_settles_every_listed_carrier(self):
        assert all(settles for settles, _ in _POOL_GATE_RULE.values())


@pytest.mark.retrieval
class TestPoolBoxesInTheApp:
    """Streamlit keeps widget state: a box ticked under one pool answer must
    not reach the check after the pool answer changes."""

    def _run(self, monkeypatch, steps):
        import eligibility_check as ec
        seen = []
        monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: seen.append(dict(pd)) or [])
        at = self._app()
        for step in steps:
            step(at)
            at.run()
        at.selectbox(key="dwelling_type").select("House").run()     # required since round 21
        at.button(key="submit").click().run()
        return at, seen[-1]

    @staticmethod
    def _app():
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(os.path.dirname(__file__), "..", "app.py"), default_timeout=60)
        at.session_state["authenticated"] = True        # past the password page
        at.run()
        assert not at.exception
        return at

    @staticmethod
    def _boxes_of(at):
        return [c for c in at.checkbox if str(c.key).startswith(("pool_fence_4ft", "pool_gate_locking"))]

    def test_boxes_appear_only_for_a_fenced_pool(self, monkeypatch):
        at = self._app()
        for pool, n in [("No Pool", 0), ("Above Ground - Unfenced", 0), ("In Ground - Unfenced", 0),
                        ("Above Ground - Fenced", 2), ("In Ground - Fenced", 2)]:
            at.selectbox(key="pool").select(pool).run()
            boxes = self._boxes_of(at)
            assert len(boxes) == n, pool
            for b in boxes:
                assert b.value is False and "UNKNOWN" in (b.help or "")

    def test_ticked_boxes_reach_the_check(self, monkeypatch):
        def tick(at):
            for b in self._boxes_of(at):
                b.check()
        _, pd = self._run(monkeypatch, [lambda at: at.selectbox(key="pool").select("In Ground - Fenced"), tick])
        assert pd["pool_fence_4ft"] is True and pd["pool_gate_locking"] is True

    @pytest.mark.parametrize("then", ["No Pool", "In Ground - Unfenced", "Above Ground - Fenced"])
    def test_a_stale_tick_does_not_survive_a_pool_change(self, monkeypatch, then):
        def tick(at):
            for b in self._boxes_of(at):
                b.check()
        _, pd = self._run(monkeypatch, [
            lambda at: at.selectbox(key="pool").select("In Ground - Fenced"), tick,
            lambda at: at.selectbox(key="pool").select(then)])
        assert pd["pool_fence_4ft"] is False and pd["pool_gate_locking"] is False
        assert pd["swimming_pool"] == then


# ---------------------------------------------------------------------------
# Round 20, Step 3 (Liam, 2026-10-01): inspection requirements are not
# checked. Three layers; zero API.
# ---------------------------------------------------------------------------

from eligibility_check import (SYSTEM_INSTRUCTIONS, INSPECTION_NOT_CHECKED_NOTE,
                               _is_inspection_request, _strip_inspection_requests)

_INSPECTION_ASKS = [
    # recorded Sonnet wording
    "Whether the property will pass the required inspection within 30 days of the policy effective date",
    "Exterior and interior inspection photos as required for homes over 40 years old",
    "Inspection from agency including exterior pictures of front and back, and interior pictures of all rooms",
    "Whether a Roof Condition Questionnaire and photos have been or can be provided",
    # other phrasings of the same requirement
    "Interior inspection required for homes 10+ years old",
    "Exterior inspection (required for all homes)",
    "Photos of each side of the dwelling",
    "4-point inspection report",
    "Wind mitigation report",
    "A current survey of the property",
    "Photographs of the roof",
]
_PROPERTY_RULES = [
    "Plumbing type -- no galvanized plumbing is permitted (verified at inspection)",
    "Roof in good condition with no visible damage (confirmed by inspection)",
    "No more than one overlay on the roof (inspection will verify)",
    "4-point inspection confirming all updates (electrical, plumbing, HVAC, roof) completed in past 20 years",
    "Inspection photos showing completely renovated kitchens and bathrooms with updated plumbing, cabinetry, appliances and floors",
    "Whether the furnace or burner has been replaced within the past 30 years (required unless inspected by licensed HVAC contractor)",
    "Coverage A amount to determine applicable water damage minimum coverage requirements and inspection requirements",
]
_ROOFER = [
    "Letter from a licensed roofer stating the roof has 5+ years of useful life remaining",
    "Roofer's statement attesting the roof is in good condition and does not require replacement",
    "Roof certification from a licensed roofer, with photos",
]


def _rec(status, missing_info, reasons=("fixture",)):
    return {"carrier": "X", "status": status, "flaw_count": 1 if status == "INELIGIBLE" else 0,
            "reasons": list(reasons), "citations": [], "missing_info": list(missing_info), "notes": ""}


@pytest.mark.retrieval
class TestInspectionNotChecked:

    # -- layer 1 -------------------------------------------------------------
    def test_the_instruction_is_in_the_system_prompt_with_its_scope(self):
        s = SYSTEM_INSTRUCTIONS
        assert "INSPECTION REQUIREMENTS ARE NOT CHECKED BY THIS TOOL." in s
        for kept in ("no galvanized plumbing", "roof in good condition", "no more than one overlay",
                     "roofer letters and roof certifications"):
            assert kept in s

    def test_the_instruction_reaches_the_model(self):
        assert "inspection requirements are not checked by this tool." in _captured_prompt_system(STANDARD_PROFILE)

    # -- layer 2 -------------------------------------------------------------
    @pytest.mark.parametrize("item", _INSPECTION_ASKS)
    def test_an_inspection_request_is_recognised(self, item):
        assert _is_inspection_request(item)

    @pytest.mark.parametrize("item", _PROPERTY_RULES + _ROOFER)
    def test_property_rules_and_roofer_letters_are_kept(self, item):
        assert not _is_inspection_request(item)

    def test_the_strip_counts_and_notes_what_it_removed(self):
        recs = [_rec("ELIGIBLE", [_INSPECTION_ASKS[0], _PROPERTY_RULES[0]]),
                _rec("REFER", [_INSPECTION_ASKS[1], _INSPECTION_ASKS[2]])]
        assert _strip_inspection_requests(recs) == 3
        assert recs[0]["missing_info"] == [_PROPERTY_RULES[0]]
        assert recs[1]["missing_info"] == []
        assert INSPECTION_NOT_CHECKED_NOTE in recs[0]["notes"]

    # -- layer 3 -------------------------------------------------------------
    def test_insufficient_only_for_an_inspection_becomes_eligible(self):
        recs = [_rec("INSUFFICIENT_INFORMATION", [_INSPECTION_ASKS[0]])]
        _strip_inspection_requests(recs)
        assert recs[0]["status"] == "ELIGIBLE" and recs[0]["flaw_count"] == 0
        assert INSPECTION_NOT_CHECKED_NOTE in recs[0]["notes"]

    def test_insufficient_with_anything_else_open_stays(self):
        recs = [_rec("INSUFFICIENT_INFORMATION", [_INSPECTION_ASKS[0], _ROOFER[0]])]
        _strip_inspection_requests(recs)
        assert recs[0]["status"] == "INSUFFICIENT_INFORMATION" and recs[0]["missing_info"] == [_ROOFER[0]]

    def test_insufficient_with_no_inspection_item_is_not_freed(self):
        """Only the strip can free a record -- an INSUFFICIENT that already
        had nothing open is not this layer's business."""
        recs = [_rec("INSUFFICIENT_INFORMATION", [])]
        _strip_inspection_requests(recs)
        assert recs[0]["status"] == "INSUFFICIENT_INFORMATION"

    @pytest.mark.parametrize("status", ["INELIGIBLE", "REFER"])
    def test_ineligible_and_refer_keep_their_status_and_reasons(self, status):
        reasons = ["Exterior and interior inspection photos are required and were not provided."]
        recs = [_rec(status, [_INSPECTION_ASKS[1]], reasons=reasons)]
        _strip_inspection_requests(recs)
        assert recs[0]["status"] == status and recs[0]["reasons"] == reasons

    def test_through_the_real_pipeline_and_the_county_hold_still_applies(self):
        import json
        recs = json.loads(_answer_for(_usable("Owner Occupied")))
        for r in recs:
            r.update(status="INSUFFICIENT_INFORMATION", missing_info=[_INSPECTION_ASKS[0]])
        out = _by_carrier(_replayed_run(_LIAM_PPC3, json.dumps(recs)))
        assert out["Allied_Trust_HO3"]["status"] == "ELIGIBLE"
        assert out["TWICO_HO3"]["status"] == "INSUFFICIENT_INFORMATION"             # its own sub-type hold
        assert out["Sage_-_Auros_HO3"]["status"] == "INSUFFICIENT_INFORMATION"      # County hold
        assert out[_CHUBB]["status"] == "INSUFFICIENT_INFORMATION"                  # Coverage A hold
        for r in out.values():
            assert _INSPECTION_ASKS[0] not in r.get("missing_info", [])

    # -- the caption ---------------------------------------------------------
    def test_the_results_carry_the_caption(self, monkeypatch):
        import eligibility_check as ec
        monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: [])
        at = TestPoolBoxesInTheApp._app()
        at.selectbox(key="dwelling_type").select("House").run()
        at.button(key="submit").click().run()
        assert "Inspection requirements are not checked." in [c.value for c in at.caption]


def _captured_prompt_system(profile):
    return _raw_prompt(profile).split("\x00")[0].lower()


# ---------------------------------------------------------------------------
# Round 21, Step 1 (Liam, 2026-10-02): one registry of checkable topics.
# These tests keep it honest: every input key is owned once, and every
# guarantee / override / check carries a topic tag -- a new one added
# without a tag fails here.
# ---------------------------------------------------------------------------

import ast as _ast
import inspect as _inspect
import topics as _topics


def _src_of(fn):
    import textwrap
    return _ast.parse(textwrap.dedent(_inspect.getsource(fn)))


def _on_calls(node):
    """The step names of every _on("...") call under node."""
    return {c.args[0].value for c in _ast.walk(node)
            if isinstance(c, _ast.Call) and getattr(c.func, "id", None) == "_on"
            and c.args and isinstance(c.args[0], _ast.Constant)}


def _parents(tree):
    par = {}
    for n in _ast.walk(tree):
        for ch in _ast.iter_child_nodes(n):
            par[ch] = n
    return par


def _gating_tags(node, par):
    """Tags of the _on() calls in every enclosing if / for / comprehension /
    and-expression test, walking up from node."""
    tags = set()
    while node in par:
        p = par[node]
        if isinstance(p, (_ast.If, _ast.IfExp)) and node is not p.test:
            tags |= _on_calls(p.test)
        if isinstance(p, _ast.For) and node is not p.iter:
            tags |= _on_calls(p.iter)
        node = p
    return tags


def _ungated_lookups(tree):
    par = _parents(tree)
    return [c.lineno for c in _ast.walk(tree)
            if isinstance(c, _ast.Call) and getattr(c.func, "id", None) == "guaranteed_carrier_lookup"
            and not any(t.startswith("guarantee:") for t in _gating_tags(c, par))]


def _untagged_override_branches(tree):
    """`canon in _SET` tests not paired with _on("override:_SET")."""
    bad = []
    for n in _ast.walk(tree):
        if isinstance(n, (_ast.If,)):
            test = n.test
            members = [c for c in _ast.walk(test) if isinstance(c, _ast.Compare)
                       and isinstance(c.ops[0], _ast.In) and getattr(c.left, "id", None) == "canon"]
            for m in members:
                name = getattr(m.comparators[0], "id", None)
                if f"override:{name}" not in _on_calls(test):
                    bad.append(name)
    return bad


_CHECK_NAME = re.compile(r"^_(apply|strip|enforce|note|drop|hold|add)_")


def _untagged_checks(tree):
    par = _parents(tree)
    bad = []
    for c in _ast.walk(tree):
        name = getattr(getattr(c, "func", None), "id", None) if isinstance(c, _ast.Call) else None
        if not name or not _CHECK_NAME.match(name) or name in _topics.CORE_STEPS:
            continue
        if f"check:{name}" not in _gating_tags(c, par):
            bad.append(name)
    return bad


@pytest.mark.retrieval
class TestTopicRegistry:

    def test_every_input_key_is_owned_exactly_once(self):
        owners = {}
        for t in _topics.TOPICS + _topics.ALWAYS_ON:
            for k in t.owns:
                owners.setdefault(k, []).append(t.key)
        assert all(len(v) == 1 for v in owners.values()), owners
        keys = set()
        for p in (STANDARD_PROFILE, ALT_PROFILE, COASTAL_PPC4_PROFILE, OWNERSHIP_BASE_PROFILE,
                  AUDIT_R13_PROFILE, AUDIT_R14_DP3_PROFILE):
            keys |= set(p)
        keys |= {"county", "dwelling_amount", "dwelling_type", "pool_fence_4ft", "pool_gate_locking"}
        assert keys - set(owners) == set(), keys - set(owners)

    def test_the_app_sends_only_owned_keys(self, monkeypatch):
        import eligibility_check as ec
        seen = []
        monkeypatch.setattr(ec, "check_eligibility", lambda pd, **kw: seen.append(dict(pd)) or [])
        at = TestPoolBoxesInTheApp._app()
        at.selectbox(key="dwelling_type").select("House").run()
        at.button(key="submit").click().run()
        owned = {k for t in _topics.TOPICS + _topics.ALWAYS_ON for k in t.owns}
        assert set(seen[-1]) - owned == set()

    def test_steps_name_only_known_topics_and_modes(self):
        known = set(_topics.TOPIC_KEYS)
        for step, (needed, mode) in _topics.STEPS.items():
            assert set(needed) <= known and needed, step
            assert mode in ("all", "any"), step
        for t in _topics.TOPICS:
            assert t.strip and _topics.STRIP_RES[t.key].pattern

    def test_every_tag_used_in_code_is_registered(self):
        import eligibility_check as ec
        tree = _ast.parse(_inspect.getsource(ec))
        used = _on_calls(tree) | {n.value for n in _ast.walk(tree) if isinstance(n, _ast.Constant)
                                  and isinstance(n.value, str)
                                  and re.match(r"^(fact|query|risk|guarantee|guard|override|check):.", n.value)}
        assert used and used - set(_topics.STEPS) - set(_topics.ALWAYS_ON_STEPS) == set()
        for check in ec._CONTRADICTION_CHECKS:
            assert "guard:" + check["field"] in _topics.STEPS, check["field"]

    def test_every_guaranteed_lookup_is_gated_by_a_guarantee_tag(self):
        import eligibility_check as ec
        assert _ungated_lookups(_src_of(ec.check_eligibility)) == []

    def test_every_structured_override_branch_is_tagged(self):
        import eligibility_check as ec
        tree = _src_of(ec._apply_structured_overrides)
        assert _untagged_override_branches(tree) == []
        names = {getattr(c.comparators[0], "id", None) for c in _ast.walk(tree)
                 if isinstance(c, _ast.Compare) and getattr(c.left, "id", None) == "canon"
                 and isinstance(c.ops[0], _ast.In)}
        assert len(names) == 7, names

    def test_every_post_parse_check_is_tagged_or_core(self):
        import eligibility_check as ec
        assert _untagged_checks(_src_of(ec.check_eligibility)) == []

    def test_an_untagged_override_added_later_fails_these_checks(self):
        """The guards themselves, on a synthetic function."""
        src = _ast.parse(
            "def f(results, checked):\n"
            "    for r in results:\n"
            "        if canon in _NEW_CARRIERS:\n"
            "            pass\n"
            "    guaranteed_carrier_lookup(c, x, predicate=p, keep=1)\n"
            "    _apply_new_hold(results)\n")
        assert _untagged_override_branches(src) == ["_NEW_CARRIERS"]
        assert _ungated_lookups(src) == [5]
        assert _untagged_checks(src) == ["_apply_new_hold"]

    def test_the_elif_chain_carrier_sets_are_disjoint(self):
        import eligibility_check as ec
        sets = [ec._SAGE_FPC_CARRIERS, ec._MERCURY_CARRIERS, ec._SAGE_MARKEL_CARRIERS,
                ec._SWYFFT_MAX30_CARRIERS, ec._TWICO_CARRIERS]
        for i, a in enumerate(sets):
            for b in sets[i + 1:]:
                assert not (set(a) & set(b))

    def test_rules_needing_two_topics_are_all_mode(self):
        """Liam: a rule needing an unchecked topic is skipped."""
        two = {s: v for s, v in _topics.STEPS.items() if len(v[0]) > 1}
        for step, (_, mode) in two.items():
            assert mode == ("any" if step.split(":")[0] in ("guarantee", "risk", "query") else "all"), step


# ---------------------------------------------------------------------------
# Round 21, Step 2 (Liam, 2026-10-01/02): the check honours checked_topics.
# Zero API.
# ---------------------------------------------------------------------------

from collections import Counter
from eligibility_check import (UNCHECKED_NOT_CONSIDERED_NOTE, _strip_unchecked_topics,
                               _is_about_unchecked_only)

_THREE = ["roof_age", "home_age", "solar"]


def _raw_prompt_kw(profile, **kw):
    import eligibility_check as ec
    got = {}
    real = ec._complete

    def fake(s, u, m):
        got["s"], got["u"] = s, u
        raise _PromptCaptured()
    ec._complete = fake
    try:
        check_eligibility(dict(profile), **kw)
    except _PromptCaptured:
        pass
    finally:
        ec._complete = real
    return got["s"], got["u"]


def _lookups(profile, **kw):
    """The predicate of every guaranteed lookup the check makes."""
    import eligibility_check as ec
    seen = []
    real = ec.guaranteed_carrier_lookup

    def spy(collection, carrier, predicate, keep, priority_key=None):
        name = getattr(predicate, "__name__", "")
        if name == "<lambda>":
            name = "+".join(predicate.__code__.co_names)
        seen.append(name)
        return real(collection, carrier, predicate, keep, priority_key)
    ec.guaranteed_carrier_lookup = spy
    try:
        _raw_prompt_kw(profile, **kw)
    finally:
        ec.guaranteed_carrier_lookup = real
    return Counter(seen)


def _replayed_run_kw(profile, raw_text, **kw):
    import types
    import eligibility_check as ec
    original = ec.client.messages.create

    def fake(**kwargs):
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text=raw_text)], stop_reason="end_turn",
            usage=types.SimpleNamespace(input_tokens=0, output_tokens=0,
                                        cache_read_input_tokens=0, cache_creation_input_tokens=0))
    ec.client.messages.create = fake
    try:
        return check_eligibility(dict(profile), **kw)
    finally:
        ec.client.messages.create = original


def _answer_with(carrier, **fields):
    import json
    recs = json.loads(_answer_for(_usable("Owner Occupied")))
    for r in recs:
        if r["carrier"] == carrier:
            r.update(fields)
    return json.dumps(recs)


@pytest.mark.retrieval
class TestCheckedTopics:

    @pytest.mark.parametrize("profile", [STANDARD_PROFILE, ALT_PROFILE, COASTAL_PPC4_PROFILE,
                                         OWNERSHIP_BASE_PROFILE],
                             ids=["STANDARD", "ALT", "COASTAL_PPC4", "OWNERSHIP_BASE"])
    def test_select_all_is_byte_identical_to_no_selection(self, profile):
        assert _raw_prompt_kw(profile, checked_topics=list(_topics.TOPIC_KEYS)) == _raw_prompt_kw(profile)

    def test_the_system_prompt_never_changes(self):
        assert _raw_prompt_kw(STANDARD_PROFILE, checked_topics=_THREE)[0] == _raw_prompt_kw(STANDARD_PROFILE)[0]

    def test_partial_lists_only_checked_and_always_on_facts(self):
        _, u = _raw_prompt_kw(dict(STANDARD_PROFILE, county="Harris", dwelling_amount=450000,
                                   dwelling_type="House"), checked_topics=_THREE)
        facts = u.split("\n\n")[0].splitlines()
        assert facts == ["PROPERTY DETAILS:", "State: TX", f"Year Built: {STANDARD_PROFILE['year_built']}",
                         facts[3], f"Roof Age: {STANDARD_PROFILE['roof_age']} years",
                         "Occupancy Type: Owner Occupied", "Ownership Structure: Individual Owner",
                         f"Solar Panels: {STANDARD_PROFILE['solar_panels']}", "Dwelling Type: House"]
        assert facts[3].startswith("Home Age: ")

    def test_the_instruction_appears_only_when_partial_and_names_the_unchecked(self):
        _, full = _raw_prompt_kw(STANDARD_PROFILE)
        _, part = _raw_prompt_kw(STANDARD_PROFILE, checked_topics=_THREE)
        assert "PARTIAL CHECK" not in full
        line = [l for l in part.splitlines() if l.startswith("PARTIAL CHECK")][0]
        for label in ("PPC", "Swimming pool", "Plumbing", "Roof type", "County"):
            assert label in line
        for label in ("Roof age", "Solar panels", "Year built"):
            assert label not in line
        assert "missing_info" in line

    def test_unchecked_topics_skip_their_guaranteed_lookups(self):
        full = _lookups(STANDARD_PROFILE)
        part = _lookups(STANDARD_PROFILE, checked_topics=["roof_age"])
        assert any("_mentions_protection_class" in k for k in full)
        assert not any("_mentions_protection_class" in k for k in part)      # PPC unchecked
        assert full["_mentions_pool_rule"] and not part["_mentions_pool_rule"]
        assert part["_mentions_roof_life_expectancy"] == full["_mentions_roof_life_expectancy"]  # "any"
        none = _lookups(STANDARD_PROFILE, checked_topics=["solar"])
        assert not none["_mentions_roof_life_expectancy"]                     # neither roof topic

    def test_unchecked_topics_leave_the_query_and_risk_terms(self):
        from eligibility_check import build_retrieval_query, build_risk_factors
        q = build_retrieval_query(STANDARD_PROFILE, 10, _topics.normalize(["roof_age"]))
        assert "roof age" in q and "protection class" not in q and "swimming pool" not in q
        assert "occupancy Owner Occupied" in q
        rf = build_risk_factors(dict(STANDARD_PROFILE, plumbing_type="Galvanized"), "Owner Occupied",
                                _topics.normalize(["roof_age"]))
        assert not any("plumbing" in t or "PPC" in t for t in rf)
        assert any("roof" in t and "years old" in t for t in rf)
        assert all(STANDARD_PROFILE["roof_type"] not in t for t in rf)

    # -- overrides and holds run only for checked topics ---------------------
    def test_no_sage_county_hold_with_county_unchecked(self):
        auros = "Sage_-_Auros_HO3"
        ans = _answer_for(_usable("Owner Occupied"))
        held = _by_carrier(_replayed_run_kw(_LIAM_PPC3, ans))[auros]
        free = _by_carrier(_replayed_run_kw(_LIAM_PPC3, ans, checked_topics=["ppc"]))[auros]
        assert held["status"] == "INSUFFICIENT_INFORMATION" and free["status"] == "ELIGIBLE"

    def test_no_chubb_hold_or_refer_with_dwelling_amount_unchecked(self):
        prof = dict(_LIAM_PPC3, dwelling_amount=450000)
        on = _by_carrier(_replayed_run_kw(prof, _chubb_answer()))[_CHUBB]
        off = _by_carrier(_replayed_run_kw(prof, _chubb_answer(), checked_topics=["ppc"]))[_CHUBB]
        blank_off = _by_carrier(_replayed_run_kw(_LIAM_PPC3, _chubb_answer(), checked_topics=["ppc"]))[_CHUBB]
        assert on["status"] == "REFER" and off["status"] == "ELIGIBLE" and blank_off["status"] == "ELIGIBLE"

    def test_no_fpc_override_with_ppc_unchecked(self):
        sure = "Sage_-_SURE_HO-3_-_01.31.2026"
        ans = _answer_with(sure, status="INSUFFICIENT_INFORMATION",
                           reasons=["FPC 3 is within the acceptable range."], missing_info=[])
        prof = dict(_LIAM_PPC3, county="Harris")
        on = _by_carrier(_replayed_run_kw(prof, ans))[sure]
        off = _by_carrier(_replayed_run_kw(prof, ans, checked_topics=["county"]))[sure]
        assert "Structured FPC check" in on["notes"] and "Structured FPC check" not in off["notes"]

    def test_a_rule_needing_two_topics_runs_only_when_both_are_checked(self):
        twico, swyfft = "TWICO_HO3", "Swyfft_-_Topa_(Surplus)_HO3"
        ans = _answer_for(_usable("Owner Occupied"))
        both = _by_carrier(_replayed_run_kw(STANDARD_PROFILE, ans, checked_topics=["roof_age", "roof_type"]))
        age = _by_carrier(_replayed_run_kw(STANDARD_PROFILE, ans, checked_topics=["roof_age"]))
        tw = lambda r: any("TWICO distinguishes" in m for m in r[twico]["missing_info"])
        assert tw(both) and not tw(age)                                 # TWICO table needs both
        assert "30-year maximum" in age[swyfft]["notes"]                # Swyfft needs roof age only

    def test_no_pool_checks_and_no_pool_box_with_pool_unchecked(self):
        allied = "Allied_Trust_HO3"
        prof = dict(STANDARD_PROFILE, pool_fence_4ft=True)
        r = _by_carrier(_replayed_run_kw(prof, _pool_answer(allied), checked_topics=["roof_age"]))[allied]
        assert not any(m.startswith("Pool enclosure specifics") for m in r["missing_info"])
        _, u = _raw_prompt_kw(prof, checked_topics=["roof_age"])
        assert "Pool Fence Height" not in u and "Swimming Pool:" not in u

    def test_no_contradiction_guard_for_an_unchecked_field(self):
        claim = "The property has solar panels installed, which this carrier excludes."
        ans = _answer_with("Allied_Trust_HO3", status="INELIGIBLE", flaw_count=1, reasons=[claim])
        prof = dict(STANDARD_PROFILE, solar_panels="No")
        on = _by_carrier(_replayed_run_kw(prof, ans))["Allied_Trust_HO3"]
        off = _by_carrier(_replayed_run_kw(prof, ans, checked_topics=["roof_age"]))["Allied_Trust_HO3"]
        assert claim not in on["reasons"] and claim in off["reasons"]   # off: not hidden, see Step 4

    # -- the strip -----------------------------------------------------------
    @pytest.mark.parametrize("topic, item", [
        ("ppc", "Driving distance to the responding fire station (FPC 9+)"),
        ("ppc", "Whether PPC 8A falls within the acceptable protection class range"),
        ("pool", "Swimming pool fence height (must be minimum 4 feet)"),
        ("pool", "Lockable gate confirmation"),
        ("plumbing", "Whether galvanized or polybutylene plumbing is present"),
        ("plumbing", "Whether the pipes have been replaced"),
        ("county", "County (to determine if in Hidalgo or Webb county)"),
        ("county", "Property location in Texas territory south of 31 degrees"),
        ("dwelling_amount", "Coverage A dwelling limit"),
        ("dwelling_amount", "Dwelling coverage amount to confirm it does not exceed $300,000"),
        ("roof_type", "Whether the composition shingle is architectural or 3-tab type"),
        ("roof_type", "Roof covering material"),
        ("coastal", "Coastal Tier 2 eligibility and any associated restrictions"),
        ("coastal", "Whether the property is in the TWIA wind pool"),
        ("home_age", "Proof of updates for home older than 50 years"),
        ("home_age", "Year built requirement for homes over 40 years"),
        ("solar", "Whether the solar panels are roof-mounted"),
        ("solar", "Photovoltaic system details"),
        ("dogs", "Whether any dogs on premises are a prohibited breed"),
        ("dogs", "Animal liability exposure"),
    ])
    def test_each_topics_keywords_catch_two_phrasings(self, topic, item):
        assert topic in _topics.item_topics(item)
        assert _is_about_unchecked_only(item, frozenset(_topics.TOPIC_KEYS) - _topics.item_topics(item))

    def test_an_item_also_about_a_checked_topic_is_kept(self):
        item = "Roof age requirements for composition shingle roofs"
        assert not _is_about_unchecked_only(item, frozenset({"roof_age"}))
        assert _is_about_unchecked_only(item, frozenset({"solar"}))

    def test_proof_is_not_roof(self):
        assert "roof_age" not in _topics.item_topics("Proof of updates for dwelling over 50 years old")

    def test_wind_pool_is_coastal_not_pool(self):
        assert _topics.item_topics("Whether the property is in the wind pool") == {"coastal"}

    def test_strip_frees_only_insufficient_and_says_so(self):
        recs = [{"carrier": "X", "status": s, "flaw_count": 0, "reasons": ["r"], "citations": [],
                 "missing_info": ["Swimming pool fence height (must be minimum 4 feet)"], "notes": ""}
                for s in ("INSUFFICIENT_INFORMATION", "INELIGIBLE", "REFER", "ELIGIBLE")]
        assert _strip_unchecked_topics(recs, frozenset({"roof_age"})) == 4
        assert [r["status"] for r in recs] == ["ELIGIBLE", "INELIGIBLE", "REFER", "ELIGIBLE"]
        assert UNCHECKED_NOT_CONSIDERED_NOTE in recs[0]["notes"]
        assert all(r["missing_info"] == [] for r in recs)

    def test_strip_does_nothing_when_everything_is_checked(self):
        recs = [{"carrier": "X", "status": "INSUFFICIENT_INFORMATION", "flaw_count": 0, "reasons": [],
                 "citations": [], "missing_info": ["Swimming pool fence height"], "notes": ""}]
        assert _strip_unchecked_topics(recs, _topics.normalize(None)) == 0
        assert recs[0]["status"] == "INSUFFICIENT_INFORMATION"

    def test_strip_through_the_pipeline(self):
        allied = "Allied_Trust_HO3"
        ans = _answer_with(allied, status="INSUFFICIENT_INFORMATION",
                           missing_info=["Distance to the responding fire station"])
        r = _by_carrier(_replayed_run_kw(STANDARD_PROFILE, ans, checked_topics=_THREE))[allied]
        assert r["status"] == "ELIGIBLE" and UNCHECKED_NOT_CONSIDERED_NOTE in r["notes"]

    def test_unknown_topic_is_an_error(self):
        with pytest.raises(ValueError):
            _topics.normalize(["ppc", "zipcode"])

    def test_every_registered_step_is_used_in_code(self):
        import eligibility_check as ec
        consts = {n.value for n in _ast.walk(_ast.parse(_inspect.getsource(ec)))
                  if isinstance(n, _ast.Constant) and isinstance(n.value, str)}
        consts |= {"guard:" + c["field"] for c in ec._CONTRADICTION_CHECKS}
        assert set(_topics.STEPS) - consts == set()


# ---------------------------------------------------------------------------
# Round 21, Step 3 (Liam, 2026-10-02): the form. AppTest, no browser, zero API.
# ---------------------------------------------------------------------------

def _form(monkeypatch):
    """The app past the password page, with check_eligibility recorded."""
    import eligibility_check as ec
    calls = []
    monkeypatch.setattr(ec, "check_eligibility",
                        lambda pd, **kw: calls.append((dict(pd), kw.get("checked_topics"))) or [])
    return TestPoolBoxesInTheApp._app(), calls


def _boxes_state(at):
    return {t: at.session_state[f"chk_{t}"] for t in _topics.TOPIC_KEYS}


def _submit(at, dwelling="House"):
    if dwelling is not None:
        at.selectbox(key="dwelling_type").select(dwelling).run()
    at.button(key="submit").click().run()


@pytest.mark.retrieval
class TestTopicForm:

    def test_default_state_everything_unchecked_and_dwelling_type_blank(self, monkeypatch):
        at, _ = _form(monkeypatch)
        assert not any(_boxes_state(at).values())
        assert at.selectbox(key="dwelling_type").value == ""
        labels = [c.label for c in at.checkbox if str(c.key).startswith("chk_")]
        assert len(labels) == len(_topics.TOPIC_KEYS) and set(labels) == {"Check this"}

    @pytest.mark.parametrize("widget, value, topic", [
        ("ppc", "3", "ppc"), ("coastal", "Tier 2 - Moderate coastal area", "coastal"),
        ("rooftype", "Metal", "roof_type"), ("roofshape", "Hip", "roof_shape"),
        ("construction", "Masonry", "construction"), ("plumbing", "PEX", "plumbing"),
        ("pool", "In Ground - Fenced", "pool"), ("county", "Harris", "county"),
    ])
    def test_changing_a_selectbox_ticks_only_its_box(self, monkeypatch, widget, value, topic):
        at, _ = _form(monkeypatch)
        at.selectbox(key=widget).select(value).run()
        state = _boxes_state(at)
        assert state[topic] is True
        assert [t for t, v in state.items() if v] == [topic]

    def test_number_text_and_toggle_inputs_tick_their_boxes(self, monkeypatch):
        at, _ = _form(monkeypatch)
        at.number_input(key="year").set_value(1985).run()
        at.number_input(key="roofage").set_value(22).run()
        at.text_input(key="dwelling_amount").input("450,000").run()
        at.toggle(key="solar").set_value(True).run()
        at.toggle(key="dogs").set_value(True).run()
        state = _boxes_state(at)
        for t in ("home_age", "roof_age", "dwelling_amount", "solar", "dogs"):
            assert state[t] is True, t

    def test_changing_back_to_default_does_not_untick(self, monkeypatch):
        at, _ = _form(monkeypatch)
        at.selectbox(key="ppc").select("3").run()
        at.selectbox(key="ppc").select("N/A").run()
        assert _boxes_state(at)["ppc"] is True

    def test_untick_by_hand_then_change_again_reticks(self, monkeypatch):
        at, _ = _form(monkeypatch)
        at.selectbox(key="ppc").select("3").run()
        at.checkbox(key="chk_ppc").uncheck().run()
        assert _boxes_state(at)["ppc"] is False
        at.selectbox(key="ppc").select("4").run()
        assert _boxes_state(at)["ppc"] is True

    def test_a_default_answer_is_checked_by_ticking_by_hand(self, monkeypatch):
        at, calls = _form(monkeypatch)
        at.checkbox(key="chk_pool").check().run()
        _submit(at)
        assert calls[-1][0]["swimming_pool"] == "No Pool" and "pool" in calls[-1][1]

    def test_select_all_and_clear(self, monkeypatch):
        at, _ = _form(monkeypatch)
        at.button(key="select_all").click().run()
        assert all(_boxes_state(at).values())
        at.button(key="clear_all").click().run()
        assert not any(_boxes_state(at).values())
        assert at.selectbox(key="occupancy").value == "Owner Occupied"     # always-on untouched

    def test_values_survive_unticking_and_reticking(self, monkeypatch):
        at, _ = _form(monkeypatch)
        at.selectbox(key="ppc").select("7").run()
        at.button(key="clear_all").click().run()
        assert at.selectbox(key="ppc").value == "7"
        at.checkbox(key="chk_ppc").check().run()
        assert at.selectbox(key="ppc").value == "7"

    def test_blank_dwelling_type_blocks_the_run(self, monkeypatch):
        at, calls = _form(monkeypatch)
        _submit(at, dwelling=None)
        assert calls == []
        assert any("Dwelling type" in e.value for e in at.error)

    def test_the_selection_reaches_the_check(self, monkeypatch):
        at, calls = _form(monkeypatch)
        at.number_input(key="roofage").set_value(22).run()
        _submit(at)
        pd, checked = calls[-1]
        assert checked == ["roof_age"] and pd["roof_age"] == 22 and pd["dwelling_type"] == "House"

    def test_partial_check_line_and_eligible_caption(self, monkeypatch):
        at, _ = _form(monkeypatch)
        at.number_input(key="roofage").set_value(22).run()
        at.toggle(key="solar").set_value(True).run()
        _submit(at)
        info = [i.value for i in at.info if str(i.value).startswith("Partial check:")]
        assert info == ["Partial check: Roof age, Solar panels, Occupancy, Ownership, Dwelling type"]
        assert "No problem found on the checked items." in [c.value for c in at.caption]
        assert "Inspection requirements are not checked." in [c.value for c in at.caption]

    def test_everything_checked_shows_neither_line(self, monkeypatch):
        at, _ = _form(monkeypatch)
        at.button(key="select_all").click().run()
        _submit(at)
        assert not [i for i in at.info if str(i.value).startswith("Partial check:")]
        assert "No problem found on the checked items." not in [c.value for c in at.caption]

    def test_a_stale_pool_box_under_no_pool_does_not_reach_the_prompt(self, monkeypatch):
        at, calls = _form(monkeypatch)
        at.selectbox(key="pool").select("In Ground - Fenced").run()
        for b in TestPoolBoxesInTheApp._boxes_of(at):
            b.check()
        at.run()
        at.selectbox(key="pool").select("No Pool").run()
        _submit(at)
        pd, checked = calls[-1]
        assert "pool" in checked
        _, u = _raw_prompt_kw(dict(STANDARD_PROFILE, **{k: pd[k] for k in (
            "swimming_pool", "pool_accessories", "pool_fence_4ft", "pool_gate_locking")}),
            checked_topics=checked)
        assert "Pool Fence Height" not in u and "Pool Gate:" not in u
        assert "Swimming Pool: No Pool" in u


# ---------------------------------------------------------------------------
# Round 21, Step 5 (Liam, 2026-10-02): ZIP -> County, table in code. Zero API.
# ---------------------------------------------------------------------------

@pytest.mark.retrieval
class TestZipLookup:

    @pytest.mark.parametrize("zip_, county", [
        ("77002", "Harris"), ("75201", "Dallas"), ("78701", "Travis"),
        ("78501", "Hidalgo"), ("78401", "Nueces"),
        ("76801", "Brown"),        # genuinely split: Brown 95%, Coleman 3%, Mills 2%
    ])
    def test_sanity_values(self, zip_, county):
        assert intake_fields.county_for_zip(zip_)[0] == county

    def test_a_split_zip_names_every_county_with_its_share(self):
        county, msg = intake_fields.county_for_zip("76801")
        assert county == "Brown"
        assert msg == ("ZIP 76801 spans Brown (95%), Coleman (3%) and Mills (2%). Checked as Brown; "
                       "change the county below if you know it.")

    def test_a_single_county_zip_says_what_was_used(self):
        assert intake_fields.county_for_zip("77002") == ("Harris", "Checked as Harris County (from ZIP 77002).")

    def test_a_tie_goes_alphabetical(self, monkeypatch):
        """The real table has no exact tie (checked 2026-10-02); synthetic."""
        monkeypatch.setitem(intake_fields.ZIP_COUNTIES, "79999", [("Zavala", 0.5), ("Andrews", 0.5)])
        assert intake_fields.county_for_zip("79999")[0] == "Andrews"

    def test_the_pick_is_deterministic(self):
        multi = [z for z, v in intake_fields.ZIP_COUNTIES.items() if len(v) > 1][:50]
        first = {z: intake_fields.county_for_zip(z)[0] for z in multi}
        for _ in range(1000 // len(multi) + 1):
            assert {z: intake_fields.county_for_zip(z)[0] for z in multi} == first

    def test_a_fresh_interpreter_gives_the_same_answers(self):
        import subprocess, json
        multi = [z for z, v in intake_fields.ZIP_COUNTIES.items() if len(v) > 1][:50]
        code = ("import json,sys,intake_fields as f;"
                "print(json.dumps({z: f.county_for_zip(z)[0] for z in json.loads(sys.argv[1])}))")
        root = os.path.join(os.path.dirname(__file__), "..")
        out = subprocess.run([sys.executable, "-c", code, json.dumps(multi)], cwd=root,
                             capture_output=True, text=True, check=True).stdout
        assert json.loads(out.strip().splitlines()[-1]) == {z: intake_fields.county_for_zip(z)[0] for z in multi}

    @pytest.mark.parametrize("raw, zip_", [(" 77002 ", "77002"), ("77002-1234", "77002"),
                                           ("770021234", "77002"), ("7 7 0 0 2", "77002")])
    def test_input_handling_accepts(self, raw, zip_):
        assert intake_fields.parse_zip(raw) == (zip_, None)

    @pytest.mark.parametrize("raw", ["7700", "770022", "abcde", "77002-12", "77-002"])
    def test_input_handling_rejects_with_one_line(self, raw):
        z, msg = intake_fields.parse_zip(raw)
        assert z is None and msg and "\n" not in msg
        assert intake_fields.county_for_zip(raw)[0] == ""

    def test_blank_is_unknown_and_silent(self):
        assert intake_fields.county_for_zip("") == ("", None)

    def test_a_texas_zip_missing_from_the_table_is_blank_and_said(self):
        county, msg = intake_fields.county_for_zip("77001")      # Houston PO boxes: no ZCTA
        assert county == "" and "not in the ZIP-to-county table" in msg

    def test_a_non_texas_zip_is_blank_and_said(self):
        assert intake_fields.county_for_zip("90210") == ("", "ZIP 90210 is not a Texas ZIP, so County is left blank.")

    def test_every_county_in_the_table_is_one_of_texas_254(self):
        counties = {c for v in intake_fields.ZIP_COUNTIES.values() for c, _ in v}
        assert counties <= set(intake_fields.TEXAS_COUNTIES)
        assert len(intake_fields.TEXAS_COUNTIES) == 254

    def test_the_table_header_names_source_date_and_share(self):
        h = " ".join(intake_fields.ZIP_TABLE_HEADER)
        assert "source:" in h and "built:" in h and "share:" in h
        assert "Census 2020 ZCTA" in h and "AREALAND_PART" in h          # source B, not mixed with A

    def test_shares_are_fractions_and_sorted(self):
        for z, v in intake_fields.ZIP_COUNTIES.items():
            assert all(0 < s <= 1.000001 for _, s in v), z
            assert sum(s for _, s in v) <= 1 + 1e-5, z      # six-decimal rounding


# ---------------------------------------------------------------------------
# Round 21, Step 6 (Liam, 2026-10-02): the ZIP box. Zero API.
# ---------------------------------------------------------------------------

@pytest.mark.retrieval
class TestZipBox:

    # -- the prompt ------------------------------------------------------------
    def test_zip_and_county_blank_change_nothing(self):
        assert _raw_prompt_kw(dict(STANDARD_PROFILE, zip="", county="")) == _raw_prompt_kw(STANDARD_PROFILE)

    @pytest.mark.parametrize("zip_, county", [("77002", "Harris"), ("75201", "Dallas")])
    def test_a_zip_gives_the_same_prompt_as_the_county_typed_by_hand(self, zip_, county):
        by_zip = _raw_prompt_kw(dict(_LIAM_PPC3, zip=zip_, county=intake_fields.county_for_zip(zip_)[0]))
        by_hand = _raw_prompt_kw(dict(_LIAM_PPC3, county=county))
        assert by_zip == by_hand
        assert zip_ not in by_zip[1] and f"County: {county}" in by_zip[1]

    def test_the_zip_never_appears_in_any_prompt(self):
        for checked in (None, ["county"], ["ppc"]):
            _, u = _raw_prompt_kw(dict(_LIAM_PPC3, zip="77002", county="Harris"), checked_topics=checked)
            assert "77002" not in u

    # -- the form --------------------------------------------------------------
    def test_a_zip_fills_county_and_ticks_the_box(self, monkeypatch):
        at, _ = _form(monkeypatch)
        at.text_input(key="zip").input("77002").run()
        assert at.selectbox(key="county").value == "Harris"
        assert _boxes_state(at)["county"] is True
        assert "Checked as Harris County (from ZIP 77002)." in [c.value for c in at.caption]

    def test_a_split_zip_shows_the_two_county_line(self, monkeypatch):
        at, _ = _form(monkeypatch)
        at.text_input(key="zip").input("76801").run()
        assert at.selectbox(key="county").value == "Brown"
        assert any(c.value.startswith("ZIP 76801 spans Brown (95%)") for c in at.caption)

    def test_a_manual_pick_survives_a_rerun_and_a_zip_change_resets_it(self, monkeypatch):
        at, _ = _form(monkeypatch)
        at.text_input(key="zip").input("76801").run()
        at.selectbox(key="county").select("Coleman").run()
        at.run()
        assert at.selectbox(key="county").value == "Coleman"
        at.text_input(key="zip").input("77002").run()
        assert at.selectbox(key="county").value == "Harris"

    @pytest.mark.parametrize("zip_, says", [("7700", "five digits"), ("90210", "not a Texas ZIP"),
                                            ("77001", "not in the ZIP-to-county table")])
    def test_invalid_non_texas_and_missing_zips_leave_county_blank(self, monkeypatch, zip_, says):
        at, _ = _form(monkeypatch)
        at.text_input(key="zip").input(zip_).run()
        assert at.selectbox(key="county").value == ""
        assert any(says in c.value for c in at.caption)

    def test_county_unchecked_means_the_zip_does_nothing(self, monkeypatch):
        at, calls = _form(monkeypatch)
        at.text_input(key="zip").input("75201").run()
        at.checkbox(key="chk_county").uncheck().run()
        _submit(at)
        pd, checked = calls[-1]
        assert "county" not in checked and pd["county"] == "Dallas" and pd["zip"] == "75201"
        auros = "Sage_-_Auros_HO3"
        r = _by_carrier(_replayed_run_kw(dict(_LIAM_PPC3, county=pd["county"], zip=pd["zip"]),
                                         _answer_for(_usable("Owner Occupied")),
                                         checked_topics=checked + ["ppc"]))[auros]
        assert r["status"] == "ELIGIBLE"            # no Sage hold, no out-of-territory decline

    def test_county_checked_by_zip_runs_the_sage_rule(self, monkeypatch):
        at, calls = _form(monkeypatch)
        at.text_input(key="zip").input("75201").run()
        _submit(at)
        pd, checked = calls[-1]
        r = _by_carrier(_replayed_run_kw(dict(_LIAM_PPC3, county=pd["county"], zip=pd["zip"]),
                                         _answer_for(_usable("Owner Occupied")),
                                         checked_topics=checked + ["ppc"]))["Sage_-_Auros_HO3"]
        assert r["status"] == "INELIGIBLE"          # Dallas is north of 31 degrees


# ---------------------------------------------------------------------------
# Round 22, Step 1 (Liam, 2026-10-02): state the Sage territory result in the
# prompt, and undo a wrong location decline in code. Zero API.
# ---------------------------------------------------------------------------

from eligibility_check import LOCATION_DECLINE_NOTE, _territory_fact_line
from structured_rules import SAGE_EAST_TEXAS_COUNTIES as _EAST_TX

# Real gpt-6-luna, round 21 step 8, ZIP 77002 (Harris), verbatim.
_LUNA_HARRIS_DECLINE = ("Harris County is not among the listed eligible East Texas counties, and the "
                        "South Texas definition is limited to counties entirely south of 31 degrees North; "
                        "the stated location requirement is not met.")
_NON_LOCATION_OK = "The property is owner occupied and individually owned, consistent with the named-insured rule."
_SECOND_FLAW = "The roof is a wood shake roof, which this carrier lists as ineligible."
_AUROS, _TRIUM = "Sage_-_Auros_HO3", "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026"


def _decline(carrier, county, reasons=(_LUNA_HARRIS_DECLINE, _NON_LOCATION_OK), flaws=1,
             status="INELIGIBLE", citations=None):
    cites = citations if citations is not None else [
        f"{carrier}: “One of the following counties in East Texas: Bell, Falls, Robertson, Leon, "
        f"Madison, Houston, Trinity, and Polk.”"]
    ans = _answer_with(carrier, status=status, flaw_count=flaws, reasons=list(reasons),
                       citations=cites, missing_info=[])
    prof = dict(_LIAM_PPC3, county=county) if county else dict(_LIAM_PPC3)
    return _by_carrier(_replayed_run_kw(prof, ans))[carrier]


@pytest.mark.retrieval
class TestSageTerritoryGuard:

    # -- layer 1: the prompt line ----------------------------------------------
    @pytest.mark.parametrize("county, path", [("Harris", "South Texas (entirely south of 31 N)"),
                                              ("Bexar", "South Texas (entirely south of 31 N)"),
                                              ("Bell", "named East Texas county"),
                                              ("Polk", "named East Texas county")])
    def test_an_inside_county_gets_one_computed_line(self, county, path):
        _, u = _raw_prompt_kw(dict(_LIAM_PPC3, county=county))
        lines = [l for l in u.splitlines() if l.startswith("Territory (computed):")]
        assert len(lines) == 1
        assert lines[0].startswith(f"Territory (computed): {county} County is inside this guide's territory -- {path}")
        assert u.index(f"County: {county}\n") < u.index(lines[0])
        for c in (_AUROS, _TRIUM, "Sage_-_Wilshire_HO3_-_12.02.2025"):
            assert c in lines[0]
        for c in ("Sage_-_Markel_HO3", "Sage_-_Vave_HO3_-_07.01.2026", "Sage_-_Occidental_HO3"):
            assert c not in lines[0]                                   # no rule / not in the prompt

    @pytest.mark.parametrize("county", ["Dallas", "Tarrant", ""])
    def test_outside_or_blank_gets_no_line(self, county):
        _, u = _raw_prompt_kw(dict(_LIAM_PPC3, county=county))
        assert "Territory (computed)" not in u

    def test_nueces_is_inside_only_for_trium(self):
        line = _territory_fact_line("Nueces", [_AUROS, _TRIUM])
        assert _TRIUM in line and _AUROS not in line

    def test_no_line_when_county_is_unchecked(self):
        _, u = _raw_prompt_kw(dict(_LIAM_PPC3, county="Harris"), checked_topics=["ppc"])
        assert "Territory (computed)" not in u and "County: Harris" not in u

    def test_county_blank_prompt_is_unchanged_by_the_line_code(self):
        assert _territory_fact_line("", [_AUROS]) == ""

    # -- layer 2: the guard ------------------------------------------------------
    def test_harris_luna_decline_becomes_refer_with_the_note(self):
        r = _decline(_AUROS, "Harris")
        assert r["status"] == "REFER" and r["flaw_count"] == 0
        assert LOCATION_DECLINE_NOTE in r["notes"]
        assert _LUNA_HARRIS_DECLINE not in r["reasons"] and _NON_LOCATION_OK in r["reasons"]
        assert not any("East Texas" in c for c in r["citations"])

    def test_a_second_non_location_flaw_keeps_it_ineligible(self):
        r = _decline(_AUROS, "Harris", reasons=(_LUNA_HARRIS_DECLINE, _SECOND_FLAW), flaws=2)
        assert r["status"] == "INELIGIBLE" and r["flaw_count"] == 1
        assert r["reasons"] == [_SECOND_FLAW]
        assert LOCATION_DECLINE_NOTE not in r["notes"]

    def test_never_eligible(self):
        r = _decline(_AUROS, "Harris", reasons=(_LUNA_HARRIS_DECLINE,), flaws=1)
        assert r["status"] == "REFER"

    def test_dallas_outside_is_unchanged(self):
        r = _decline(_AUROS, "Dallas", reasons=("Dallas County is north of 31 degrees.",))
        assert r["status"] == "INELIGIBLE" and r["flaw_count"] == 2
        assert any("Property must be located in" in c for c in r["citations"])
        assert LOCATION_DECLINE_NOTE not in r["notes"]

    def test_nueces_excluded_by_name_stays_outside(self):
        nueces = "The property is in Nueces County, which the carrier expressly excludes."
        r = _decline(_AUROS, "Nueces", reasons=(nueces,))
        assert r["status"] == "INELIGIBLE" and nueces in r["reasons"]

    def test_nueces_is_inside_for_trium_so_its_location_decline_is_undone(self):
        r = _decline(_TRIUM, "Nueces", reasons=("Nueces County is outside the South Texas territory.",))
        assert r["status"] == "REFER"

    @pytest.mark.parametrize("county", list(_EAST_TX))
    def test_the_eight_named_east_texas_counties_are_inside(self, county):
        assert sorted(_EAST_TX) == sorted(["Bell", "Falls", "Robertson", "Leon", "Madison", "Houston",
                                           "Trinity", "Polk"])
        r = _decline(_AUROS, county, reasons=(f"{county} County is north of 31 degrees North.",))
        assert r["status"] == "REFER"

    def test_county_blank_is_untouched(self):
        r = _decline(_AUROS, "", reasons=(_LUNA_HARRIS_DECLINE,))
        assert r["status"] == "INELIGIBLE" and _LUNA_HARRIS_DECLINE in r["reasons"]

    @pytest.mark.parametrize("carrier", ["Sage_-_Markel_HO3", "Sage_-_Vave_HO3_-_07.01.2026"])
    def test_markel_and_vave_are_untouched(self, carrier):
        r = _decline(carrier, "Harris", reasons=(_LUNA_HARRIS_DECLINE,))
        assert r["status"] == "INELIGIBLE" and _LUNA_HARRIS_DECLINE in r["reasons"]

    @pytest.mark.parametrize("status", ["ELIGIBLE", "REFER", "INSUFFICIENT_INFORMATION"])
    def test_other_statuses_are_untouched(self, status):
        r = _decline(_AUROS, "Harris", reasons=(_LUNA_HARRIS_DECLINE,), status=status, flaws=0)
        assert r["status"] == status and LOCATION_DECLINE_NOTE not in r["notes"]

    def test_a_decline_on_something_else_is_untouched(self):
        r = _decline(_AUROS, "Harris", reasons=(_SECOND_FLAW,), citations=[])
        assert r["status"] == "INELIGIBLE" and r["reasons"] == [_SECOND_FLAW]

    def test_the_territory_decision_does_not_read_the_model(self):
        """A reason that falsely claims Harris is north of 31 is still undone:
        the territory comes from the county table, not the model's words."""
        r = _decline(_AUROS, "Harris", reasons=("Harris County lies north of 31 degrees North.",))
        assert r["status"] == "REFER"

    def test_keyword_set_on_real_outputs(self):
        from eligibility_check import _LOCATION_FLAW_RE as rx
        caught = [_LUNA_HARRIS_DECLINE,
                  "The property is in Nueces County, which the carrier expressly excludes from its South Texas location category."]
        not_caught = [_NON_LOCATION_OK,
                      "HO-3 policies are not appropriate for rental or tenant-occupied properties regardless of other property characteristics.",
                      "Property is Tenant Occupied, which makes it ineligible for HO3 (Homeowners 3) coverage."]
        assert all(rx.search(s) for s in caught) and not any(rx.search(s) for s in not_caught)

    def test_the_real_round21_luna_output_is_corrected(self):
        """The recorded failure itself: Luna declined Auros and Trium for
        Harris on location. Replayed now, both are REFER with the note."""
        import json
        path = os.path.join(os.path.dirname(__file__), "fixtures", "luna_r21_harris_location_decline.json")
        raw = json.load(open(path, encoding="utf-8"))["raw"]
        out = _by_carrier(_replayed_run_kw(dict(STANDARD_PROFILE, county="Harris", zip="77002",
                                                dwelling_type="House"), raw))
        for c in (_AUROS, _TRIUM):
            assert out[c]["status"] == "REFER" and LOCATION_DECLINE_NOTE in out[c]["notes"], c
        assert not any(out[c]["status"] == "INELIGIBLE" for c in out if c.startswith("Sage_-_")
                       and "Markel" not in c and "Vave" not in c)
