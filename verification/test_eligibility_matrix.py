"""Regression test for check_eligibility() against the standard test
profile used across every audit round to date.

Why this exists: across six audit rounds, at least four issues were
independently fixed, then regressed, then re-fixed at different points
(Swyfft Lloyd's PPC 9/10 exclusion, Liberty Mutual's Coverage-A tiering,
HOAIC's "3 years or newer" scoping, the Swyfft pool-fence question). Each
carrier's reasoning is regenerated fresh by the LLM on every run rather
than building on a previously-verified conclusion, so a fix made once can
silently disappear later. This script runs the real check_eligibility()
call (a real Claude API call -- costs a few cents) and diffs each
carrier's status against the last-known-correct baseline below, so a
regression shows up here before it reaches an external audit.

This is NOT a substitute for the full audits -- it only checks the ONE
standard profile, and only status (plus a few targeted keyword checks for
carriers whose specific citation content, not just the bucket, has
historically flipped). A carrier passing here can still have a wrong or
weak citation the audits would catch.

Usage:
    python verification/test_eligibility_matrix.py

When a real audit finds a NEW confirmed-correct state for a carrier,
update that carrier's entry in EXPECTED below so this script keeps
tracking the current target, not last round's target.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eligibility_check import check_eligibility, get_all_carriers
from profiles import STANDARD_PROFILE

# Baseline as of the round 6 audit (2026-08-15) + same-day fixes:
# - status: best-known-correct verdict, verified against a direct read of
#   each carrier's document (not just "whatever the tool last returned").
# - must_mention: lowercase substrings that must appear somewhere across
#   reasons + citations + notes for this carrier. Only set for carriers
#   where a SPECIFIC fact (not just the status bucket) has been the
#   recurring bug -- an empty list means only the status is checked. Each
#   entry is either a plain string, or a tuple of alternative phrasings
#   (any ONE satisfies it) -- the model expresses the same substantive
#   fact in different words run to run (e.g. "FPC" vs "Fire Protection
#   Class"), so a single rigid phrase is too brittle.
# - fragile: True for carriers with a documented history of flipping
#   across rounds. A PASS here is still worth a second look.
# - known_issue: a currently-unresolved, previously-documented gap that
#   this test does NOT enforce (so it doesn't block the suite on
#   something not yet fixed) -- surfaced in the report as a reminder.
EXPECTED = {
    "ARI_(HOA+)": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": False,
        "known_issue": None,
        "note": "PPC 9 carries no restriction in this carrier's classification table -- only PPC 10 does. Fixed round 6 (round 4 misread this as a distance-gated rule).",
    },
    "ARI_(HOB)": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": False,
        "known_issue": None,
        "note": "Stable/clean since round 4.",
    },
    "Allied_Trust_HO3": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": False,
        "known_issue": "4-ft pool-fence-with-locking-gate requirement confirmed present in the document, never mentioned across 3+ rounds.",
        "note": "Status itself has been stable; the pool-fence gap is a separate, still-open issue.",
    },
    "CHUBB_HO_-_05.22.2026": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": True,
        "known_issue": "Persistently cites the wrong 'Eligible Persons' clause (multi-unit/boarding-house) instead of the correct single-family clause 2 lines below it. Diagnosed: the correct clause exists and ranks #2/40 under a targeted query, but isn't reachable via the main blended query. Not yet fixed at retrieval level.",
        "note": "True correct answer given a direct document read: owner-occupied single-family clause applies, Standard tier by default, no PPC restriction. Actual output has been unstable (Eligible / Insufficient Information) across recent runs.",
    },
    "Foremost_DP3_and_HO3_-_07.01.2026": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": True,
        "known_issue": "~35-county territory eligibility table never flagged, 6 consecutive rounds. PPC 9 conclusion rests on a marketing sentence, not a quantified rule -- should be flagged as inference.",
        "note": "Also vanished entirely from round 5's output with no explanation -- watch for carrier-list instability.",
    },
    "HOAIC_-_TX-HOMEOWNERS-0326_HO3": {
        "status": "ELIGIBLE",
        "must_mention": ["3 years"],
        "fragile": True,
        "known_issue": None,
        "note": "The '3 years old or newer' PPC-review trigger doesn't apply to this 17-year-old home. Correct in rounds 3, 4, 6; wrong in rounds 1, 2, 5 -- specifically flag if this reverts to Refer/Ineligible.",
    },
    "Liberty_Mutual_HO3_-_02.21.2026": {
        "status": "INSUFFICIENT_INFORMATION",
        "must_mention": [],
        "fragile": True,
        "known_issue": "Analysis still describes the 15-mile-fire-department rule as applying broadly to 'PPC 9 and 10 homes' when the document limits it to the $1.5M-$3M Coverage A band; a separate 'Refer to Underwriting' trigger for PPC 9 + Coverage A >= $1.5M is never mentioned.",
        "note": "Bucket confirmed correct round 6. Do not accept INELIGIBLE here -- that was round 5's self-contradiction bug (notes said 'cannot determine' but verdict said Ineligible).",
    },
    "Liberty_Mutual_HO6_-_02.21.2026": {
        "status": "INELIGIBLE",
        "must_mention": [],
        "fragile": False,
        "known_issue": None,
        "note": "Condo-only program vs. this single-family home. Was mislabeled INSUFFICIENT_INFORMATION for rounds (falsely claiming no documents retrieved, actually a carrier-dedup collision with byte-identical HO3 PDF) -- now correctly confident INELIGIBLE.",
    },
    "Mercury_HO3_-_01.01.2026": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": True,
        "known_issue": None,
        "note": "Round 5 had a verdict-tag self-contradiction (fixed round 6). Round 6 introduced a boundary bug: treating a roof at EXACTLY 10 years as satisfying 'older than 10 years' (fixed same day -- 'older than' is exclusive). Watch this one specifically for the boundary case recurring.",
    },
    "NatGen_Custom360_HO3_-_06.25.2026": {
        "status": "INELIGIBLE",
        "must_mention": [],
        "fragile": False,
        "known_issue": None,
        "note": "Landlord/rental-only program, no owner-occupied section. Stable since round 3.",
    },
    "NatGen_Premier_OneChoice_HO3_-_02.26.2025": {
        "status": "INELIGIBLE",
        "must_mention": [("closed", "not eligible for new business", "no longer accepting")],
        "fragile": False,
        "known_issue": None,
        "note": "Program closed to new business. The single most stable, verbatim-correct carrier across all 6 rounds -- a regression here would be a strong signal something broke broadly.",
    },
    "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": True,
        "known_issue": "Pool-fence rule (4-ft fence, no diving board/slide) inconsistently surfaced -- sometimes flagged, sometimes silently dropped, across different runs of the identical input.",
        "note": "Round 5's verdict-tag self-contradiction (analysis said PPC 9 fine, verdict said Ineligible) is confirmed fixed round 6.",
    },
    "Progressive_HO3_-_04.01.2026": {
        "status": "INSUFFICIENT_INFORMATION",
        "must_mention": ["paved"],
        "fragile": True,
        "known_issue": None,
        "note": "PPC 9/10 requires paved road + visible to neighbors, neither given in intake. Round 4 correctly Refer, round 5 wrongly Eligible despite unresolved items, round 6 correctly Insufficient Information (better bucket than Refer -- no underwriting discretion path exists for this specific rule).",
    },
    "Progressive_HO6_-_10.01.2025": {
        "status": "INELIGIBLE",
        "must_mention": [],
        "fragile": False,
        "known_issue": None,
        "note": "Condo-only program vs. this single-family home. Same mislabel history as Liberty Mutual HO6.",
    },
    "Sage_-_Auros_HO3": {
        "status": "INSUFFICIENT_INFORMATION",
        "must_mention": [("fire protection class", "fpc"), ("driving distance", "fire station")],
        "fragile": True,
        "known_issue": None,
        "note": "Shares the identical Fire Protection Class table with its 5 siblings. Round 6 audit found Auros alone dropped this rule (kept only an unrelated county question) while all 5 siblings cited it correctly -- re-verified fixed same day, but flag specifically if this drops again.",
    },
    "Sage_-_Markel_HO3": {
        "status": "ELIGIBLE",
        "must_mention": ["protection class"],
        "fragile": False,
        "known_issue": "$100,000 minimum Coverage A requirement never mentioned across 4+ rounds.",
        "note": "Own favorable 'Protection Classes 1-10 are eligible' line correctly cited since round 4/5.",
    },
    "Sage_-_Occidental_HO3": {
        "status": "INSUFFICIENT_INFORMATION",
        "must_mention": [("fire protection class", "fpc"), ("driving distance", "fire station")],
        "fragile": False,
        "known_issue": None,
        "note": "Part of the Sage six -- see Sage_-_Auros_HO3 note.",
    },
    "Sage_-_SURE_HO-3_-_01.31.2026": {
        "status": "INSUFFICIENT_INFORMATION",
        "must_mention": [("fire protection class", "fpc"), ("driving distance", "fire station")],
        "fragile": False,
        "known_issue": None,
        "note": "Part of the Sage six -- see Sage_-_Auros_HO3 note.",
    },
    "Sage_-_SafePort_HO-3_-_01.31.2026": {
        "status": "INSUFFICIENT_INFORMATION",
        "must_mention": [("fire protection class", "fpc"), ("driving distance", "fire station")],
        "fragile": True,
        "known_issue": None,
        "note": "Had a fabricated 'PPC 9 eligible under 25 years' rule in rounds 1 and 3 (that age exception only applies to the FPC 4-8 band). Fixed since round 4 -- watch for this specific fabrication recurring.",
    },
    "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026": {
        "status": "INSUFFICIENT_INFORMATION",
        "must_mention": [("fire protection class", "fpc"), ("driving distance", "fire station")],
        "fragile": False,
        "known_issue": None,
        "note": "Part of the Sage six -- see Sage_-_Auros_HO3 note.",
    },
    "Sage_-_Vave_HO3_-_07.01.2026": {
        "status": "ELIGIBLE",
        "must_mention": ["protection class"],
        "fragile": True,
        "known_issue": "Roof-age table (asphalt shingles under 15 years = RCV), correctly cited in round 1, dropped as of round 4-5.",
        "note": "Own favorable 'ISO Protection Classes 1-10 are eligible' line correctly cited since round 4. Sometimes lands on INSUFFICIENT_INFORMATION instead over acreage/pool-liability details this carrier's document genuinely requires and the current intake form doesn't collect -- that's a real intake gap, not a hallucination, if it recurs.",
    },
    "Sage_-_Wilshire_HO3_-_12.02.2025": {
        "status": "INSUFFICIENT_INFORMATION",
        "must_mention": [("fire protection class", "fpc"), ("driving distance", "fire station")],
        "fragile": False,
        "known_issue": None,
        "note": "Part of the Sage six -- see Sage_-_Auros_HO3 note.",
    },
    "Swyfft_-_Benchmark_(Admitted)_HO3": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": True,
        "known_issue": "Pool-fence rule (4-ft permanent fence + self-latching gate) confirmed present, inconsistently flagged as missing across rounds -- sometimes correct, sometimes silently dropped.",
        "note": None,
    },
    "Swyfft_-_Benchmark_(Surplus)_HO3": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": True,
        "known_issue": "Same pool-fence instability as Benchmark (Admitted).",
        "note": None,
    },
    "Swyfft_-_Lloyds_(Surplus)_HO3": {
        "status": "INELIGIBLE",
        "must_mention": ["protection class"],
        "fragile": True,
        "known_issue": None,
        "note": "THE headline regression-test case: this carrier's unconditional 'ISO Protection Class 9 or 10' decline has flipped wrong/right FOUR times across 6 rounds (wrong-wrong-wrong-right-wrong-right). Root-caused to context assembly grouping chunks by retrieval pass instead of by carrier, scattering this carrier's guaranteed PPC chunk far from its main content block in a 25k+ token prompt. Fixed by grouping context by carrier. If this fails, check that fix hasn't regressed first.",
    },
    "Swyfft_-_Topa_(Surplus)_HO3": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": True,
        "known_issue": "Pool-fence rule inconsistently flagged -- correct in round 5, dropped in round 6.",
        "note": None,
    },
    "TWICO_HO3": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": False,
        "known_issue": "Pool disqualifier clause (diving board/slide/unfenced = ineligible) never checked, 5 consecutive rounds -- this customer's actual pool would pass it, but the tool has never verified that.",
        "note": None,
    },
    "Travelers_HO3_-_06.12.2026": {
        "status": "ELIGIBLE",
        "must_mention": [],
        "fragile": True,
        "known_issue": "Roof-age table (10/15/25-year thresholds by Wind/Hail/Tornado classification) never correctly found/cited across 6 rounds, despite the conclusion (Eligible) being substantively correct for this customer's actual roof.",
        "note": None,
    },
}

# Not in EXPECTED at all: Centauri HO3 (scanned/image PDF, 0 extracted
# pages -- a separate, known, by-design gap pending OCR conversion, not a
# retrieval or reasoning bug this suite can catch).


def _tokens(s):
    return set(t for t in re.split(r"[^A-Za-z0-9]+", s.upper()) if t)


def _best_match(model_name, candidate_keys):
    """The model restates carrier names in its own words -- sometimes
    verbose ("Orion Underwriting Guide TX HO3"), sometimes terse ("Orion
    HO3") -- so a plain substring check fails whenever the metadata key is
    longer and less predictable than the model's own short name (e.g.
    "Orion HO3" is NOT a contiguous substring of
    "Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3"). Token-overlap with a
    clear-winner requirement handles both directions."""
    model_tokens = _tokens(model_name)
    scores = {key: len(model_tokens & _tokens(key)) for key in candidate_keys}
    best_key = max(scores, key=scores.get)
    best_score = scores[best_key]
    if best_score == 0:
        return None
    runner_up = max((s for k, s in scores.items() if k != best_key), default=0)
    if best_score <= runner_up:
        return None  # ambiguous -- more than one candidate ties for best
    return best_key


def _text_blob(result):
    parts = result.get("reasons", []) + result.get("citations", [])
    if result.get("notes"):
        parts.append(result["notes"])
    return " ".join(parts).lower()


def _clause_satisfied(blob, clause):
    if isinstance(clause, (list, tuple)):
        return any(alt in blob for alt in clause)
    return clause in blob


def _clause_label(clause):
    return "/".join(clause) if isinstance(clause, (list, tuple)) else clause


def main():
    if "ANTHROPIC_API_KEY" not in os.environ and not os.path.exists(
        os.path.join(os.path.dirname(__file__), "..", ".env")
    ):
        print("WARNING: no ANTHROPIC_API_KEY / .env found -- this will likely fail to call the real API.")

    print("Running check_eligibility() against the standard test profile...")
    results = check_eligibility(STANDARD_PROFILE)
    all_carriers = get_all_carriers()

    by_expected_key = {}
    for r in results:
        match = _best_match(r.get("carrier", ""), list(EXPECTED.keys()))
        if match:
            by_expected_key[match] = r

    passed, failed, missing = [], [], []

    for carrier_key, expected in EXPECTED.items():
        result = by_expected_key.get(carrier_key)
        if result is None:
            missing.append(carrier_key)
            continue

        actual_status = result.get("status")
        blob = _text_blob(result)
        missing_mentions = [
            _clause_label(m) for m in expected["must_mention"] if not _clause_satisfied(blob, m)
        ]

        ok = actual_status == expected["status"] and not missing_mentions
        entry = {
            "carrier": carrier_key,
            "expected_status": expected["status"],
            "actual_status": actual_status,
            "missing_mentions": missing_mentions,
            "fragile": expected["fragile"],
        }
        (passed if ok else failed).append(entry)

    print(f"\n{'=' * 70}")
    print(f"PASS: {len(passed)}   FAIL: {len(failed)}   MISSING FROM OUTPUT: {len(missing)}")
    print(f"{'=' * 70}\n")

    if failed:
        print("FAILURES (regressions or new bugs):")
        for e in failed:
            flag = " [FRAGILE -- known history of flipping]" if e["fragile"] else ""
            print(f"  - {e['carrier']}{flag}")
            print(f"      expected status: {e['expected_status']}, got: {e['actual_status']}")
            if e["missing_mentions"]:
                print(f"      missing required content: {e['missing_mentions']}")
        print()

    if missing:
        print("MISSING FROM OUTPUT (carrier expected but not found in results -- "
              "check carrier-list instability or a name-resolution mismatch):")
        for m in missing:
            print(f"  - {m}")
        print()

    fragile_passes = [e["carrier"] for e in passed if e["fragile"]]
    if fragile_passes:
        print("Passed, but historically fragile -- worth a second look, not just a green check:")
        for c in fragile_passes:
            print(f"  - {c}: {EXPECTED[c]['note']}")
        print()

    known_issues = [(k, v["known_issue"]) for k, v in EXPECTED.items() if v["known_issue"]]
    if known_issues:
        print(f"Known open issues NOT enforced by this test ({len(known_issues)}):")
        for carrier, issue in known_issues:
            print(f"  - {carrier}: {issue}")
        print()

    print("Centauri HO3 is intentionally excluded (scanned PDF, pending OCR decision).")

    sys.exit(1 if (failed or missing) else 0)


if __name__ == "__main__":
    main()
