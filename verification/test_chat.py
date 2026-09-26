"""Tests for the Ask the Guides chat tab.

Two tiers, the same split and the same markers the eligibility suite uses, so
these run under the same commands:

    pytest verification/ -m retrieval    fast, no model call, every commit
    pytest verification/ -m baseline     the golden set, real API cost

Kept in their own file rather than appended to test_eligibility_matrix.py
because nothing here touches the eligibility pipeline -- but the markers are
shared deliberately, so `-m retrieval` over verification/ still runs
everything fast that exists.

The golden answers below were each checked against the PDFs. Where a golden
case encodes a GENERAL rule rather than one carrier's exact wording, it is
parametrized over more than one phrasing, per CLAUDE.md: the Allied Trust
"Composition Shingle" fix passed for the literal bug wording and generalized
to nothing, and a single-phrasing test would have called that done.
"""

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import chat
import data_defects
import guides


# ---------------------------------------------------------------------------
# TIER 1 -- fast, deterministic, no model call
# ---------------------------------------------------------------------------

@pytest.mark.retrieval
class TestNameResolution:
    """Carrier-name matching must never resolve a coin flip.

    Same rule the eligibility suite's _find_carrier enforces, and it is here
    for the same measured reason: round 13 lost a week to "lloyds" silently
    matching Sage Trium Lloyd's as well as Swyfft Lloyds and reporting one
    carrier's status as the other's.
    """

    @pytest.mark.parametrize("question", [
        "does Progressive take galvanized plumbing?",
        "what are Progressive's roof requirements",
        "PROGRESSIVE pool rules",
    ])
    def test_progressive_resolves_to_all_three_programs(self, question):
        """One insurer's several programs are answered per program, not asked
        about. Phrased three ways: the rule is about the carrier, not about
        one sentence's wording."""
        result = chat.resolve(question)
        assert result["mode"] == "programs"
        assert len(result["programs"]) == 3
        assert {p.split("_")[1] for p in result["programs"]} == {"DP3", "HO3", "HO6"}

    @pytest.mark.parametrize("question", [
        "what does Lloyds say about roof age?",
        "Lloyds maximum roof age",
        "is there a roof age cap for lloyd's?",
    ])
    def test_lloyds_is_ambiguous_and_asks(self, question):
        """Two unrelated insurers, so the tab must ask instead of picking.
        Three phrasings including the apostrophe form, because normalising the
        apostrophe away is exactly what created the collision."""
        result = chat.resolve(question)
        assert result["mode"] == "ambiguous"
        brands = {chat._brand(c) for c in result["candidates"]}
        assert brands == {"SWYFFT", "SAGE"}

    def test_fully_qualified_swyfft_lloyds_is_not_ambiguous(self):
        """The ambiguity check must not fire on a name that IS specific --
        otherwise the clarification is unescapable."""
        result = chat.resolve("what is the max roof age for Swyfft Lloyds?")
        assert result["mode"] == "programs"
        assert result["programs"] == ["Swyfft_-_Lloyds_(Surplus)_HO3"]

    @pytest.mark.parametrize("question", [
        "does HOA+ allow pools?",
        "HOA+ roof requirements",
    ])
    def test_hoa_plus_does_not_silently_resolve_to_hoaic(self, question):
        """"HOA+" normalises to "HOA", which is a substring of HOAIC -- a
        different company. It must surface both, not pick whichever sorts
        first."""
        result = chat.resolve(question)
        assert result["mode"] == "ambiguous"
        candidates = set(result["candidates"])
        assert "ARI_(HOA+)" in candidates
        assert any("HOAIC" in c for c in candidates)

    def test_no_carrier_named_is_a_cross_carrier_question(self):
        assert chat.resolve("which carriers accept galvanized plumbing?")["mode"] == "cross_carrier"

    def test_followup_carries_the_conversation_forward(self):
        """"what about their roof rules?" names nobody and must not become a
        40-carrier sweep."""
        result = chat.resolve(
            "what about their roof rules?",
            carried_forward=["Progressive_HO3_-_04.01.2026"],
        )
        assert result["mode"] == "programs"
        assert result["programs"] == ["Progressive_HO3_-_04.01.2026"]

    def test_named_product_narrows_to_that_program(self):
        result = chat.resolve("Progressive HO6 roof rules")
        assert result["programs"] == ["Progressive_HO6_-_10.01.2025"]

    def test_centauri_ho3_resolves_to_itself_not_its_dp3_sibling(self):
        """The regression this file exists to prevent. Centauri HO3 has no
        chunks in the store, so building the name index from stored programs
        alone made "Centauri HO3 roof age" resolve to Centauri's DP3 landlord
        guide -- handing an agent the wrong product's rule with nothing
        flagged."""
        result = chat.resolve("Centauri HO3 roof age")
        assert result["programs"] == ["Centauri_-_HO3_-_05.01.2026"]


@pytest.mark.retrieval
class TestQuoteVerifier:
    """Every quote must appear in the guide it is attributed to."""

    def _texts(self, *programs):
        return {p: guides.guide_text(p) for p in programs}

    def test_real_quote_from_the_right_carrier_passes(self):
        texts = self._texts("Allied_Trust_HO3")
        source = texts["Allied_Trust_HO3"]
        sentence = next(
            s for s in re.split(r"(?<=[.!?])\s+", source)
            if 40 < len(s) < 200
        )
        answer = 'Yes.\n\nSOURCES\n- Allied_Trust_HO3: "{}"'.format(sentence)
        verified, problems = chat.verify_quotes(answer, texts)
        assert verified, problems

    @pytest.mark.parametrize("fabricated", [
        "Trampolines are permitted on all risks without restriction.",
        "This carrier accepts homes with galvanized plumbing of any age.",
    ])
    def test_fabricated_quote_fails(self, fabricated):
        """Two different fabrications, because a verifier that only rejects
        one remembered sentence is not a verifier."""
        texts = self._texts("Allied_Trust_HO3")
        answer = 'Yes.\n\nSOURCES\n- Allied_Trust_HO3: "{}"'.format(fabricated)
        verified, problems = chat.verify_quotes(answer, texts)
        assert not verified
        assert problems[0]["reason"] in ("not_in_guide", "not_in_any_guide")

    def test_real_quote_attributed_to_the_wrong_carrier_fails(self):
        """The failure the pipeline actually measured: not invention, but a
        genuine rule applied to a carrier it does not belong to."""
        texts = self._texts("Allied_Trust_HO3", "Mercury_HO3_-_01.01.2026")
        mercury = texts["Mercury_HO3_-_01.01.2026"]
        sentence = next(
            s for s in re.split(r"(?<=[.!?])\s+", mercury)
            if 40 < len(s) < 200 and chat._compare_key(s) not in chat._compare_key(texts["Allied_Trust_HO3"])
        )
        answer = 'Yes.\n\nSOURCES\n- Allied_Trust_HO3: "{}"'.format(sentence)
        verified, problems = chat.verify_quotes(answer, texts)
        assert not verified
        assert problems[0]["reason"] == "wrong_carrier"
        assert "Mercury_HO3_-_01.01.2026" in problems[0]["actually_from"]

    @pytest.mark.parametrize("quote", [
        "Trampolines are always acceptable\nregardless of fencing or netting.",
        "This carrier writes\nany roof age\nwith no restriction whatsoever.",
    ])
    def test_a_multiline_fabricated_quote_is_still_caught(self, quote):
        """Found while building this: the SOURCES pattern was line-anchored,
        so a quote that wrapped across lines matched NOTHING, produced no
        problems, and the answer came back reported as verified. Guide text is
        full of newlines (table rows especially), so this was reachable with
        an ordinary quote, not a contrived one. Two phrasings because the bug
        was in the parser, not in one sentence."""
        texts = self._texts("Allied_Trust_HO3")
        answer = 'Yes.\n\nSOURCES\n- Allied_Trust_HO3: "{}"'.format(quote)
        verified, problems = chat.verify_quotes(answer, texts)
        assert not verified, "a multi-line fabrication slipped past the verifier"

    def test_a_quote_split_by_a_pdf_page_footer_still_verifies(self):
        """Measured on a real answer, not imagined. Progressive HO3's
        ineligible-homes bullet list has a page footer ("3 Uploaded to system
        2026-04 Texas Homeowners HO H Program ASI Lloyds") sitting between its
        second and third bullet. The model read across it and quoted the rule
        faithfully; a contiguous-substring verifier called that fabrication.
        A verifier that flags correct quotes teaches agents to ignore it."""
        program = "Progressive_HO3_-_04.01.2026"
        texts = self._texts(program)
        quote = (
            "Homes with the following are ineligible for coverage: • Homes deemed "
            "by the company to have a lack of maintenance or upgrades. • Homes with "
            "fuses, aluminum wiring, knob and tube wiring, or Federal Pacific breakers. "
            "• Homes with polybutylene, PEX installed prior to 2011, or galvanized "
            "plumbing."
        )
        answer = 'No.\n\nSOURCES\n- {}: "{}"'.format(program, quote)
        verified, problems = chat.verify_quotes(answer, texts)
        assert verified, problems

    def test_a_quote_split_by_a_two_column_pdf_layout_still_verifies(self):
        """Swyfft's PDF is laid out in two columns, so its roof rule is stored
        as "No roofs [Full Time Annual Rentals] older than 25 years." -- a
        verbatim-correct quote interrupted by an unrelated column. This is the
        case that set the matcher's minimum segment length; see _appears_in."""
        program = "Swyfft_-_Lloyds_(Surplus)_HO3"
        texts = self._texts(program)
        answer = '25 years.\n\nSOURCES\n- {}: "No roofs older than 25 years."'.format(program)
        verified, problems = chat.verify_quotes(answer, texts)
        assert verified, problems

    @pytest.mark.parametrize("fabricated", [
        "No roofs older than 40 years.",
        "Roofs older than 25 years are eligible.",
        "No roofs older than 25 months.",
        "Roofs in good condition of any age are accepted.",
    ])
    def test_segment_matching_rejects_near_miss_edits_of_a_real_rule(self, fabricated):
        """The adversarial half of the two-column tolerance, and the reason the
        segment floor is 7 rather than lower. Each of these is a one-token edit
        of a rule that IS in the Swyfft guide -- a swapped number, a flipped
        polarity -- which is exactly what a subtly wrong answer looks like."""
        source = chat._compare_key(guides.guide_text("Swyfft_-_Lloyds_(Surplus)_HO3"))
        assert not chat._appears_in(chat._compare_key(fabricated), source)

    @pytest.mark.parametrize("fabricated", [
        "Homes with galvanized plumbing are eligible for coverage.",
        "Homes with trampolines are ineligible for coverage.",
        "Homes with PEX installed prior to 2011 are acceptable.",
    ])
    def test_segment_matching_rejects_recombined_real_vocabulary(self, fabricated):
        """Every content word below appears in the Progressive HO3 guide. The
        sentences do not. If gap tolerance ever loosens enough to assemble
        these, the verifier has stopped verifying."""
        source = chat._compare_key(
            guides.guide_text_with_pages("Progressive_HO3_-_04.01.2026")
        )
        assert not chat._appears_in(chat._compare_key(fabricated), source)

    @pytest.mark.parametrize("fabricated", [
        "Homes with trampolines are always acceptable regardless of fencing or safety netting requirements.",
        "This carrier accepts homes with galvanized plumbing of any age without restriction.",
        "Homes with polybutylene are eligible for coverage when the company deems maintenance adequate.",
    ])
    def test_gap_tolerance_does_not_let_fabrications_through(self, fabricated):
        """The other half of the page-footer tolerance. Skipping short gaps
        must not become 'assemble any sentence from scattered words' -- these
        three reuse real vocabulary from the same guide and must still fail."""
        source = chat._compare_key(
            guides.guide_text_with_pages("Progressive_HO3_-_04.01.2026")
        )
        assert not chat._appears_in(chat._compare_key(fabricated), source)

    def test_gap_tolerance_does_not_let_a_quote_cross_carriers(self):
        """Loosening the matcher must not loosen attribution."""
        quote = chat._compare_key(
            "Homes with polybutylene, PEX installed prior to 2011, or galvanized plumbing."
        )
        mercury = chat._compare_key(guides.guide_text("Mercury_HO3_-_01.01.2026"))
        assert not chat._appears_in(quote, mercury)

    def test_a_short_quoted_term_in_prose_does_not_fake_a_fabrication(self):
        """Regression for a FALSE POSITIVE in the verifier itself.

        An answer that quotes a short term inline and then lists sources is a
        completely ordinary shape. The old regex-based extractor started
        matching at that term's CLOSING quote and ran to the next OPENING
        quote, reporting the prose in between as a quote found in no guide.
        Measured on Orion: 3 of 3 Sonnet answers were marked unverified while
        every actual quote was genuine.

        A verifier's false positives cost more than its false negatives here
        -- agents who see it cry wolf will stop reading it."""
        program = "Allied_Trust_HO3"
        texts = self._texts(program)
        real = next(
            s for s in re.split(r"(?<=[.!?])\s+", texts[program]) if 60 < len(s) < 180
        )
        answer = (
            'Yes. The guide treats these as "Other Structures" under Coverage B, '
            'and there is no eligibility restriction.\n\n'
            'SOURCES\n- {}: "{}"'.format(program, real)
        )
        verified, problems = chat.verify_quotes(answer, texts)
        assert verified, problems

    def test_quotes_are_paired_positionally_not_greedily(self):
        """The property the regex lacked, asserted directly: with four
        delimiters, segments 1 and 3 are the quotes and segment 2 is prose."""
        quotes = chat._inline_quotes('a "first quote" b "second quote" c')
        assert quotes == ["first quote", "second quote"]

    def test_whitespace_and_punctuation_differences_still_verify(self):
        """The corpus's own extraction inserts spaces mid-word ("P ools") and
        replacement characters where smart quotes were. A verifier that
        demanded those back verbatim would reject correct quotes."""
        texts = {"X": "Pools must have a fence minimum four feet high"}
        answer = 'SOURCES\n- X: "Pools  must have a fence, minimum four feet high."'
        verified, problems = chat.verify_quotes(answer, texts)
        assert verified, problems


@pytest.mark.retrieval
class TestDataDefects:
    """The defect list must be derived, so it clears when the PDFs are fixed."""

    def test_the_two_mis_filed_programs_are_flagged(self):
        defects = data_defects.defective_programs()
        assert "Liberty_Mutual_HO6_-_02.21.2026" in defects
        assert "NatGen_Custom360_HO3_-_06.25.2026" in defects

    def test_the_correct_sibling_of_each_pair_is_NOT_flagged(self):
        """Flagging both halves of a duplicate pair would throw away a good
        guide with the bad one. DATA_DEFECTS.md establishes which is which:
        the Liberty Mutual file is the HO3 guide and the NatGen file is the
        DP3 landlord guide, so those two records are correct."""
        defects = data_defects.defective_programs()
        assert "Liberty_Mutual_HO3_-_02.21.2026" not in defects
        assert "NatGen_Custom360_DP3_-_06.25.2026" not in defects

    def test_centauri_ho3_is_flagged_as_having_no_readable_text(self):
        defect = data_defects.defective_programs().get("Centauri_-_HO3_-_05.01.2026")
        assert defect is not None
        assert defect["kind"] == data_defects.NO_TEXT

    def test_a_clean_program_is_not_flagged(self):
        """Guards against a detector that fires on everything."""
        defects = data_defects.defective_programs()
        assert "Allied_Trust_HO3" not in defects
        assert "Progressive_HO3_-_04.01.2026" not in defects

    @pytest.mark.parametrize("program", [
        "Liberty_Mutual_HO6_-_02.21.2026",
        "NatGen_Custom360_HO3_-_06.25.2026",
        "Centauri_-_HO3_-_05.01.2026",
    ])
    def test_asking_about_a_defective_program_refuses_instead_of_answering(self, program):
        """No model call happens at all -- the refusal is structural."""
        result = chat.answer_programs("what are the roof rules?", [program])
        assert result["mode"] == "blocked"
        assert result["answer"] is None
        assert [p for p, _ in result["blocked"]] == [program]

    def test_guide_date_comes_from_the_filename(self):
        assert data_defects.guide_date("Progressive_HO3_-_04.01.2026") == "04.01.2026"
        assert data_defects.guide_date("Allied_Trust_HO3") is None


@pytest.mark.retrieval
class TestGuideReconstruction:
    def test_document_order_is_page_monotonic(self):
        """Chroma does not return chunks in reading order. If this breaks,
        full-guide mode is silently feeding the model a shuffled document."""
        for program in guides.all_programs():
            pages = [m.get("page", 0) for m, _ in guides._sorted_chunks(program)]
            assert pages == sorted(pages), program

    def test_foremost_pool_fence_is_four_feet_in_the_reconstructed_text(self):
        """The old extractor bug reported five. Asserted on the text the model
        is actually handed, so a reconstruction regression fails here rather
        than surfacing as a wrong answer."""
        text = guides.guide_text("Foremost_DP3_and_HO3_-_07.01.2026").lower()
        assert "fence minimum four feet high" in text

    def test_whole_corpus_stays_within_its_measured_size(self):
        """Full-guide mode is affordable only while this holds. If a much
        larger guide is ingested, this fails and the mode needs rethinking
        rather than silently becoming expensive."""
        largest = max(
            guides.estimate_tokens(guides.guide_text(p)) for p in guides.all_programs()
        )
        assert largest < 60000, largest


# ---------------------------------------------------------------------------
# TIER 2 -- the golden set. Real model calls, real cost.
#
# Each case was checked against the PDF. Run with --golden-runs=N to get a
# pass rate rather than a single sample; CLAUDE.md treats a one-run "verified"
# as an undisclosed failure rate.
# ---------------------------------------------------------------------------

GOLDEN_RUNS = int(os.environ.get("GOLDEN_RUNS", "1"))


def _ask_text(question):
    result = chat.answer_programs(question, chat.resolve(question)["programs"])
    return (result["answer"] or ""), result


def _rate(fn, runs=None):
    """Run a golden check N times and return (passes, runs, failures)."""
    runs = runs or GOLDEN_RUNS
    passes, failures = 0, []
    for _ in range(runs):
        try:
            fn()
            passes += 1
        except AssertionError as exc:
            failures.append(str(exc)[:300])
    return passes, runs, failures


def _gate(*programs):
    """Skip this case if CHAT_MODEL is a third-party provider and any guide it
    would send restricts its own redistribution.

    The gate is here rather than in a note to me, because "remember not to
    send the Sage guides to OpenAI" is exactly the kind of instruction that
    survives one round and then does not. 17 of 40 guides carry a marking --
    the whole Sage family is "Privileged and Confidential", Foremost says "do
    not distribute", Progressive is "proprietary" -- and the markings are read
    from the documents at run time, so a re-upload or a newly marked guide
    changes the gate with no code change.

    Anthropic is not gated: that exposure predates this and was approved on
    its own terms. This is the check for sending guide text ANYWHERE ELSE.
    """
    if not chat._is_openai(chat.CHAT_MODEL):
        return
    marked = {p: guides.confidentiality_markings(p) for p in programs}
    marked = {p: m for p, m in marked.items() if m}
    if marked:
        pytest.skip(
            "CHAT_MODEL={} is a third-party provider and this case would send "
            "restricted guide text: {}. Cleared for unmarked guides only.".format(
                chat.CHAT_MODEL,
                "; ".join(
                    "{} ({})".format(p, ", ".join(sorted(m))) for p, m in marked.items()
                ),
            )
        )


def _assert_rate(fn, threshold=1.0):
    passes, runs, failures = _rate(fn)
    rate = passes / runs
    assert rate >= threshold, (
        "pass rate {p}/{r} = {rate:.0%}, below {t:.0%}. Failures: {f}".format(
            p=passes, r=runs, rate=rate, t=threshold, f=failures[:3]
        )
    )


@pytest.mark.baseline
class TestGoldenSet:
    """NOTE ON PHRASING -- read before adding a case.

    Assert the FACT, not one model's wording of it. These assertions were
    originally written against Claude Sonnet's output and silently encoded its
    phrasing; running the same suite against gpt-6-luna scored three cases
    80%, 60% and 0% on answers that were all substantively CORRECT:

        "roofs over 25 years are excluded"      vs demanded "older than 25 years"
        "does not SPECIFICALLY address"         vs demanded "does not address"
        "flat roofs are not listed as ineligible" tripped a bare search for
                                                  the word "ineligible"

    That is the same substring mistake this project keeps catching in the
    product (Lloyds/Lloyd's, HOA+/HOAIC, Foremost's "2.5 feet" matching "5
    feet"), except in the measuring instrument, where it is worse: it reports
    a correct answer as a regression, and it makes any cross-model comparison
    meaningless because the incumbent is graded on the phrasing it happens to
    use. Accept the family of phrasings the fact can be stated in, and assert
    separately that the WRONG answer is absent.
    """

    def test_progressive_galvanized_notes_the_pex_difference(self):
        _gate("Progressive_HO3_-_04.01.2026", "Progressive_HO6_-_10.01.2025",
              "Progressive_DP3_-_10.01.2024")
        """All three Progressive guides make galvanized ineligible, but HO3
        and HO6 exclude only PEX installed before 2011 while DP3 excludes all
        PEX. A per-program answer is the whole point of the feature, so the
        difference has to survive."""
        def check():
            answer, result = _ask_text("does Progressive take galvanized plumbing?")
            assert result["quotes_verified"], result["quote_problems"]
            lowered = answer.lower()
            assert len(result["programs"]) == 3
            assert "galvanized" in lowered
            assert "2011" in answer
        _assert_rate(check)

    def test_swyfft_lloyds_roof_age_is_25_not_30(self):
        _gate("Swyfft_-_Lloyds_(Surplus)_HO3")

        def check():
            answer, result = _ask_text("what is the maximum roof age for Swyfft Lloyds?")
            assert result["quotes_verified"], result["quote_problems"]
            lowered = answer.lower()
            # The FACT is 25, not one model's way of saying it. Demanding the
            # literal "older than 25 years" scored Luna 4/5 for answering
            # "roofs over 25 years are excluded" -- same rule, different
            # words. See NOTE ON PHRASING at the top of this class.
            assert re.search(r"(older than|over|more than|exceed\w*|>\s*)\s*25\b", lowered) \
                or re.search(r"\b25\s*years?\b", lowered)
            # The point of this case is the contrast: Lloyds caps at 25 where
            # the other three Swyfft programs cap at 30. Claiming 30 is the
            # regression.
            assert not re.search(r"maximum[^.]{0,30}\b30\b", lowered)
        _assert_rate(check)

    def test_foremost_pool_fence_is_four_feet_never_five(self):
        _gate("Foremost_DP3_and_HO3_-_07.01.2026")
        """The old extractor bug said 5. An answer saying 5 is worse than no
        answer, so that is asserted separately from the correct value.

        The "never five" half has to be written carefully: Foremost's rule
        legitimately says the fence requirement applies to "pools over 2.5
        feet deep", and a bare `"5 feet" not in answer` check fails on that
        2.5 -- which it did, on every run, against a completely correct
        answer. Only a FENCE HEIGHT of five feet is the regression."""
        def check():
            answer, result = _ask_text("what pool fence height does Foremost require?")
            assert result["quotes_verified"], result["quote_problems"]
            lowered = answer.lower()
            assert "four feet" in lowered or "4 feet" in lowered
            assert not re.search(r"(?<!2\.)(?<!\d\.)\b(five|5) (feet|ft)\b[^.]{0,30}\b(high|fence|tall)", lowered)
            assert not re.search(r"fence[^.]{0,40}\b(five|5) (feet|ft)", lowered)
        _assert_rate(check)

    def test_allied_trust_flat_roofs_require_poured_reinforced_concrete(self):
        _gate("Allied_Trust_HO3")

        def check():
            answer, result = _ask_text("does Allied Trust allow flat roofs?")
            assert result["quotes_verified"], result["quote_problems"]
            lowered = answer.lower()
            assert "concrete" in lowered
            assert "reinforced" in lowered
        _assert_rate(check)

    def test_mercury_flat_roofs_need_binding_approval_not_a_decline(self):
        _gate("Mercury_HO3_-_01.01.2026")
        """THE SPEC'S EXPECTED ANSWER FOR THIS CASE WAS WRONG, and the guide
        settles it. "Dwellings with flat roofs" is item 9 of Mercury HO3's
        section **C. BINDING APPROVAL** -- "The following risks need
        underwriting approval before they are bound:" -- not of section B's
        ineligible list (items a-bb, which ends at "bb) Dwellings with unusual
        or unconventional construction"). Mercury does not decline flat roofs;
        it requires approval before binding.

        This is the project's recurring failure mode in miniature: a phrase
        located by search and assigned to whatever list the reader assumed it
        was in. The model got it right on 5 of 5 runs and the golden answer
        was what was broken.

        Note the shipped pipeline never carried this error --
        structured_rules.mercury_roof_eligibility declines only specific
        MATERIALS (asbestos, tin, T-lock, wood shake/shingle) and says nothing
        about flat roofs -- so nothing needed correcting outside this file.

        Asserting the true rule, and asserting it is NOT reported as a decline,
        because reporting binding-approval as ineligible would lose writable
        business."""
        def check():
            answer, result = _ask_text("does Mercury allow flat roofs?")
            assert result["quotes_verified"], result["quote_problems"]
            lowered = answer.lower()
            assert "approval" in lowered or "approved" in lowered
            # Must not assert a DECLINE. A bare search for "ineligible" is
            # wrong: it fired on Luna's "flat roofs are not listed as
            # ineligible", which is the correct answer stated in the negative.
            # What matters is an AFFIRMATIVE claim that flat roofs are
            # declined, so the pattern requires the subject and the copula.
            assert not re.search(
                r"flat roofs?[^.]{0,40}\b(are|is)\s+(ineligible|not eligible|declined)", lowered
            )
            assert not re.search(r"\b(declines|excludes)\s+(dwellings with\s+)?flat roofs?", lowered)
        _assert_rate(check)

    def test_allied_trust_trampolines_is_not_addressed_not_guessed(self):
        _gate("Allied_Trust_HO3")
        """The guide does not mention trampolines at all. The only correct
        answer is that it does not address it -- inventing a plausible
        industry-standard trampoline rule is the exact failure the system
        prompt's no-general-knowledge rule exists to stop."""
        def check():
            answer, result = _ask_text("does Allied Trust HO3 allow trampolines?")
            lowered = answer.lower()
            # "does not address" / "doesn't address" / "does not SPECIFICALLY
            # address" / "does not mention" are the same answer. The literal
            # two-word check scored Luna 3/5 purely on the inserted adverb.
            assert re.search(
                r"(does\s*n[o']?t|do\s*n[o']?t|no\b)[^.]{0,30}\b(address|mention|specif|cover|discuss)",
                lowered,
            ) or "not addressed" in lowered
            # And it must not have invented a rule.
            assert not re.search(r"trampolines?[^.]{0,40}\b(are|is)\s+(ineligible|prohibited|not permitted|excluded)", lowered)
            assert result["quotes_verified"], result["quote_problems"]
        _assert_rate(check)

    def test_sage_auros_pool_rule_is_liability_coverage_not_a_decline(self):
        _gate("Sage_-_Auros_HO3")
        """Sage's pool rules sit under "Liability Exposure - Swimming Pools".
        They restrict pool LIABILITY COVERAGE; they do not decline the home.
        Reporting a coverage restriction as a decline would lose a writable
        piece of business."""
        def check():
            answer, result = _ask_text(
                "Sage Auros -- above ground pool with no fence, is that a problem?"
            )
            assert result["quotes_verified"], result["quote_problems"]
            lowered = answer.lower()
            assert "liability" in lowered
            assert not re.search(r"\b(ineligible|declined?|not eligible)\b.{0,40}\bhome\b", lowered)
        _assert_rate(check)


@pytest.mark.baseline
def test_cross_carrier_never_reports_silence_as_acceptance():
    """A guide that says nothing must land in "doesn't address", never in
    "yes". This is the audit lesson that cost the most to learn, and it is the
    one thing about the cross-carrier view that is not allowed to drift."""
    result = chat.answer_cross_carrier("which carriers accept galvanized plumbing?")
    assert result["grouped"]["not_addressed"], "nothing landed in not-addressed, which is implausible"
    for row in result["grouped"]["yes"]:
        assert row["quote"], "a YES with no quote is silence presented as acceptance: " + row["program"]
