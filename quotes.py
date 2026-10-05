"""Quote matching shared by the chat tab's quote verifier (chat.verify_quotes)
and the eligibility pipeline's citation guard
(eligibility_check._strip_misattributed_citations). Moved here from chat.py
in round 26 so the pipeline can use it without importing chat (which imports
eligibility_check). chat.py re-exports both names unchanged.
"""


def compare_key(text):
    """Alphanumerics only, lowercased.

    Deliberately ignores whitespace and punctuation, because this corpus's PDF
    extraction inserts both: Foremost's pool rule really is stored as "P ools
    with a deck", and the Liberty Mutual text carries U+FFFD where smart
    quotes and en-dashes were. A verifier that demanded those artifacts back
    verbatim would reject correct quotes. At 25+ characters the collision risk
    of a text-only comparison is negligible, and a fabricated sentence still
    fails it outright.
    """
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def appears_in(quote, source, max_gap=300, min_segment=25, max_gaps=4):
    """Is `quote` present in `source`, allowing for page furniture?

    Both arguments are already compare_key output.

    A plain substring test is the first thing tried and the common case. It is
    not sufficient on its own, and this is measured, not theoretical: asked
    about Progressive HO3's galvanized plumbing rule, the model quoted the
    ineligible-homes bullet list correctly -- but the PDF has a page footer
    ("3 Uploaded to system 2026-04 Texas Homeowners HO H Program ASI Lloyds")
    sitting between the second and third bullet. The model read across it, as
    it should; the quote is faithful to the document and matches no contiguous
    span of it. Rejecting that would train agents to ignore the verifier,
    which is worse than the failure it was built to catch.

    So a quote may also match as a handful of long, in-order segments
    separated by short gaps. The constraints are what keep this a verifier
    rather than a rubber stamp:

      min_segment  each piece must be a substantial run, so the matcher can
                   never assemble a quote word-by-word from scattered text
      max_gap      what is skipped must be small -- a footer, not a section
      max_gaps     few joins, so this cannot walk the whole document

    A fabricated sentence fails all three, because its words are not present
    in long runs anywhere.
    """
    if quote in source:
        return True

    # A short quote needs a shorter segment, or it can never be matched in
    # pieces at all. Measured on Swyfft Lloyds: the PDF lays its roof rule out
    # in two columns, so "No roofs older than 25 years." is stored as "No roofs
    # [Full Time Annual Rentals] older than 25 years." -- 23 alphanumeric
    # characters of quote interrupted by an unrelated column. With a flat
    # 25-character minimum the matcher demanded the whole thing contiguously
    # and rejected a quote that is verbatim correct.
    # 7 is measured, not picked. Swept 5/6/7/8 against the genuine Swyfft
    # quote and seven adversarial fabrications built from each guide's OWN
    # vocabulary (numeric swaps -- "40 years" for "25 years" -- and negation
    # flips -- "are eligible" for "are ineligible"). 8 rejects the genuine
    # quote; 5, 6 and 7 all accept it and all reject every fabrication, so 7
    # takes the most margin that still works.
    min_segment = max(7, min(min_segment, len(quote) // 3))

    i, pos, gaps = 0, 0, 0
    while i < len(quote):
        remaining = len(quote) - i
        seg_len = min(min_segment, remaining)
        found = source.find(quote[i:i + seg_len], pos)
        if found < 0:
            return False
        if i > 0:
            if found - pos > max_gap:
                return False
            if found > pos:
                gaps += 1
                if gaps > max_gaps:
                    return False
        # Extend the match as far as the two strings agree.
        end = seg_len
        while (i + end < len(quote) and found + end < len(source)
               and source[found + end] == quote[i + end]):
            end += 1
        i += end
        pos = found + end
    return True
