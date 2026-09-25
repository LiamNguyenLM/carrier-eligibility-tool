"""Which carrier programs currently hold an unusable document.

ONE place, and it clears itself. `verification/DATA_DEFECTS.md` is the prose
record of how each defect was found; this module is the runtime check, and it
DETECTS the defects rather than listing them by name. That is the difference
between a list that has to be remembered and one that cannot rot: re-upload
the correct Liberty Mutual HO6 PDF and `defective_programs()` stops reporting
it on the next process start, with no code change and nothing to un-hardcode.

Three detectors, matching the three shapes seen in this corpus. The first two
mirror the standing tests in test_eligibility_matrix.py
(`test_no_two_carriers_hold_the_same_document`,
`test_each_document_reads_like_the_product_its_filename_claims`); the third
covers a case NEITHER of those can see.

  DUPLICATE_DOCUMENT  two programs hold byte-identical chunk text, so one of
                      them is the wrong file. Catches Liberty_Mutual_HO6
                      (holds the HO3 guide) and NatGen_Custom360_HO3 (holds
                      the DP3 landlord guide).

  WRONG_PRODUCT       a document's own text reads like the opposite product
                      from the one its filename claims. Catches
                      NatGen_Custom360_HO3 from a second, independent angle.

  NO_TEXT             a program whose PDF is on disk but which contributed no
                      chunks at all, so it is absent from the store entirely.

NO_TEXT is the one this module adds over the two standing tests, and it is
the nastiest of the three because it is invisible from every direction. Both
standing tests iterate over records that EXIST in the vector store, so a PDF
that extracted to nothing never appears for them to check. Centauri HO3 is
the live instance: a 3.5MB scanned PDF sitting in carrier_eligibility_pdfs/
that produced 0 chunks, leaving 40 indexed carriers and no Centauri HO3 among
them. Nothing in the pipeline or the suite says so -- the program simply does
not exist as far as the tool is concerned, which for a chat tab means a
question about it would otherwise resolve to "no such carrier" rather than
"we are missing that guide".

Why detect instead of read the markdown: a parsed list is still a list, and
it would go stale in the same way the audit findings that prompted
DATA_DEFECTS.md went stale -- silently, and only noticed at the next manual
read-through. Detection has no stale state to go wrong.
"""

import hashlib
import os
import re

from shared_resources import get_vectorstore

PDF_FOLDER = "./carrier_eligibility_pdfs"

DUPLICATE_DOCUMENT = "DUPLICATE_DOCUMENT"
WRONG_PRODUCT = "WRONG_PRODUCT"
NO_TEXT = "NO_TEXT"

# Same margins as test_each_document_reads_like_the_product_its_filename_claims,
# and for the same reason its comment gives: a heuristic that fires on a
# legitimate carrier later is worse than no heuristic. Travelers' HO3 guide
# carries a real "LANDLORD DWELLING / LANDLORD CONDOMINIUM ONLY" ineligibility
# section (3 landlord vs 8 homeowners hits, ratio 2.7) and must not trip;
# NatGen Custom360's mis-filed record is 2 vs 34, ratio 17.
_WRONG_PRODUCT_MIN_HITS = 10
_WRONG_PRODUCT_MIN_RATIO = 4.0

_HOMEOWNERS_SIGNALS = ("homeowners", "ho-3", "ho3", "owner occupied", "owner-occupied")
_DWELLING_FIRE_SIGNALS = ("landlord", "dwelling fire", "dp-3", "dp3", "tenant occupied")
_CONDO_SIGNALS = ("condominium", "condo", "unit-owner", "unit owner", "ho-6", "ho6")

HOMEOWNERS = "HOMEOWNERS"
DWELLING_FIRE = "DWELLING_FIRE"
CONDO = "CONDO"

_SIGNALS_BY_PRODUCT = {
    HOMEOWNERS: _HOMEOWNERS_SIGNALS,
    DWELLING_FIRE: _DWELLING_FIRE_SIGNALS,
    CONDO: _CONDO_SIGNALS,
}


def _claimed_product(program):
    """What a program's NAME claims it is, at condo-level granularity.

    Built on top of carrier_programs() rather than replacing it -- that stays
    the single source of truth for the homeowners/dwelling-fire split the
    eligibility pipeline turns on, and this only refines its homeowners side
    into HO6-condo vs everything else.

    That refinement exists solely to tell apart the two halves of a duplicate
    pair. Liberty Mutual's HO3 and HO6 records hold the same file, and
    carrier_programs() answers "homeowners" for both (its regex lists HO6
    alongside HO3), so it alone cannot say which of the two the shared
    document actually belongs to. Condo signals can, and do: the shared file
    mentions "condominium" exactly once, in a coverage-limit table row.
    """
    from eligibility_check import carrier_programs, _strip_to_alnum

    is_ho, is_dp = carrier_programs(program)
    if is_ho and is_dp:
        return None  # a genuinely combined guide, e.g. Foremost DP3+HO3
    if is_dp:
        return DWELLING_FIRE
    if is_ho:
        return CONDO if "HO6" in _strip_to_alnum(program) else HOMEOWNERS
    return None


def _chunks_by_carrier():
    """Every stored chunk, grouped by carrier, in insertion order."""
    collection = get_vectorstore()._collection
    raw = collection.get(include=["documents", "metadatas"])
    grouped = {}
    for doc, meta in zip(raw["documents"], raw["metadatas"]):
        carrier = meta.get("carrier")
        if carrier:
            grouped.setdefault(carrier, []).append((meta, doc))
    return grouped


_SIGNAL_RE_CACHE = {}


def _count_signals(text, signals):
    """Occurrences of any signal, counted NON-OVERLAPPING and longest-first.

    Summing per-signal `str.count` double-counts nested signals, and that is
    not hypothetical: "condominium" also contains "condo", so Liberty
    Mutual's single condominium mention scored 2 and tied the HO3/HO6
    duplicate pair at 2-2. A tie is treated as undecidable, so that arithmetic
    alone would have condemned the perfectly good HO3 guide along with the
    HO6 record that actually holds the wrong file.
    """
    key = tuple(signals)
    if key not in _SIGNAL_RE_CACHE:
        alternation = "|".join(
            re.escape(s) for s in sorted(signals, key=len, reverse=True)
        )
        _SIGNAL_RE_CACHE[key] = re.compile(alternation)
    return len(_SIGNAL_RE_CACHE[key].findall(text.lower()))


def _expected_programs_from_pdfs():
    """Program names implied by the PDFs actually sitting on disk.

    This is what makes NO_TEXT detectable: the store cannot tell you about a
    document that produced nothing, so the filesystem has to. A PDF present
    here with no chunks in the store extracted to nothing.
    """
    if not os.path.isdir(PDF_FOLDER):
        return set()
    return {
        os.path.splitext(name)[0]
        for name in os.listdir(PDF_FOLDER)
        if name.lower().endswith(".pdf")
    }


def defective_programs():
    """{program_name: {"kind": ..., "detail": ...}} for every unusable program.

    Empty dict means the corpus is clean and every caller's defect handling
    silently switches off, which is the point.
    """
    grouped = _chunks_by_carrier()
    defects = {}

    # --- NO_TEXT: on disk, absent from the store -------------------------
    for program in sorted(_expected_programs_from_pdfs() - set(grouped)):
        defects[program] = {
            "kind": NO_TEXT,
            "detail": (
                "The PDF on file produced no readable text at all (it appears to be a "
                "scanned image), so this program has no searchable content in the "
                "database. It cannot be answered from."
            ),
        }

    # --- DUPLICATE_DOCUMENT ----------------------------------------------
    by_hash = {}
    for carrier, chunks in grouped.items():
        digest = hashlib.sha256(
            "\n".join(doc for _, doc in chunks).encode("utf-8", "replace")
        ).hexdigest()
        by_hash.setdefault(digest, []).append(carrier)

    for digest, carriers in by_hash.items():
        if len(carriers) < 2:
            continue

        # Only the program the shared document does NOT belong to is
        # defective. Flagging both members would throw away a perfectly good
        # guide alongside the bad one: Liberty_Mutual_HO3 and
        # NatGen_Custom360_DP3 are the CORRECT records of their pairs, and
        # refusing to answer from them would be a self-inflicted second
        # defect. Which one is right is decided from the document's own text,
        # the same way DATA_DEFECTS.md decided it by hand.
        text = "\n".join(doc for _, doc in grouped[carriers[0]])
        scored = {
            c: _count_signals(text, _SIGNALS_BY_PRODUCT[_claimed_product(c)])
            for c in carriers
            if _claimed_product(c) is not None
        }
        best = max(scored.values()) if scored else None

        for carrier in sorted(carriers):
            # A tie (or an unclassifiable name) means the text cannot say
            # which program it belongs to, so every member stays flagged --
            # conservative, because the alternative is silently blessing a
            # document that might be the wrong one.
            if best is not None and scored.get(carrier) == best and list(scored.values()).count(best) == 1:
                continue
            others = sorted(c for c in carriers if c != carrier)
            defects.setdefault(carrier, {
                "kind": DUPLICATE_DOCUMENT,
                "detail": (
                    "This program's document is byte-identical to {others} "
                    "(sha256 {digest}), and the shared text reads as the {others} "
                    "program rather than this one -- so the correct PDF for this "
                    "program was never ingested."
                ).format(others=" and ".join(others), digest=digest[:12]),
            })

    # --- WRONG_PRODUCT ----------------------------------------------------
    # Imported here rather than at module scope: eligibility_check imports
    # heavily (and builds the retriever) at import time, and this module is
    # also used by fast tests that have no reason to pay for that.
    from eligibility_check import carrier_programs

    for carrier, chunks in grouped.items():
        text = "\n".join(doc for _, doc in chunks)
        is_ho, is_dp = carrier_programs(carrier)
        if is_ho == is_dp:
            # No product token, or a combined HO3+DP3 guide like Foremost.
            # Neither can be judged against "the opposite product".
            continue

        own, opposite = (
            (_HOMEOWNERS_SIGNALS, _DWELLING_FIRE_SIGNALS) if is_ho
            else (_DWELLING_FIRE_SIGNALS, _HOMEOWNERS_SIGNALS)
        )
        own_hits = _count_signals(text, own)
        opposite_hits = _count_signals(text, opposite)

        if opposite_hits < _WRONG_PRODUCT_MIN_HITS:
            continue
        if opposite_hits < _WRONG_PRODUCT_MIN_RATIO * max(own_hits, 1):
            continue

        defects.setdefault(carrier, {
            "kind": WRONG_PRODUCT,
            "detail": (
                "This program's filename says {claimed}, but its text reads like "
                "{actual} ({opposite} opposite-product mentions against {own} of its "
                "own). The file on record is the wrong document."
            ).format(
                claimed="homeowners" if is_ho else "dwelling fire",
                actual="dwelling fire / landlord" if is_ho else "homeowners",
                opposite=opposite_hits,
                own=own_hits,
            ),
        })

    return defects


def defect_for(program, defects=None):
    """The defect record for one program, or None if it is usable."""
    if defects is None:
        defects = defective_programs()
    return defects.get(program)


def guide_date(program):
    """The guide's date as written in its filename, or None.

    Agents need to know how current a rule is, and the filename is the only
    place this corpus records it -- 'Progressive_HO3_-_04.01.2026' is April 1
    2026. Several programs (Allied_Trust_HO3, the Sage family) carry no date
    at all, and None is returned rather than a guess.
    """
    match = re.search(r"(\d{2}\.\d{2}\.\d{4})", program or "")
    return match.group(1) if match else None
