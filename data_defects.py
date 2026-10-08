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

# The programs that SHOULD be in the store, committed next to this module.
# Production (Railway) has no PDF folder -- it is gitignored and the volume is
# seeded from carrier_docs_db_seed/ alone -- and an upload through the app
# writes its PDF to a temp file it deletes. So without this list a program
# whose PDF extracted to nothing (Centauri HO3) is invisible in production.
# It says only what is EXPECTED: whether a program is present, and whether
# it is defective, always comes from the store, so a later upload clears the
# program's warning row with no edit here. test_expected_programs_list_
# matches_the_pdf_folder keeps it in step with the local PDFs.
EXPECTED_PROGRAMS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "expected_programs.txt")

# Round 29 step 5 (2026-10-08): programs whose stored text does not come from the
# PDF's own text layer as pdfplumber reads it by default. Not defects -- both
# programs are usable -- recorded so their text is never "corrected":
ALTERNATE_TEXT_SOURCES = {
    # DD-3, fixed: a scanned PDF with no text layer (0 chunks, NO_TEXT until now).
    "Centauri_-_HO3_-_05.01.2026": (
        "OCR text (Tesseract, 300 dpi, psm 4, made by Claude 2026-10-07) from "
        "ocr_text/Centauri_-_HO3_-_05.01.2026.txt, loaded by pdf_extraction.load_guide_documents. "
        "The OCR misreads (e.g. 'Centaurl') are in the text ON PURPOSE: the rules-table quotes "
        "were taken from it and must match it."),
    # Garbled stored text, fixed: Word's list labels sit 2 pt above the body text at the same x,
    # so the default line clustering interleaved them ("bR.O OFS/SIDING", "CoveragCeo nBtaining")
    # and dropped lines ("i. Rolled Roofs").
    "Centauri_-_DP3_-_11.16.2022": (
        "read in content-stream order (pdf_extraction.FLOW_ORDER_FILES; use_text_flow): overlapping "
        "list labels made the default extraction interleave and drop text."),
}

DUPLICATE_DOCUMENT = "DUPLICATE_DOCUMENT"
WRONG_PRODUCT = "WRONG_PRODUCT"
NO_TEXT = "NO_TEXT"

# Round 29 step 6 (2026-10-08): the evidence for the three wrong files on record, for whoever
# re-uploads them. A RECORD, not a list the runtime reads: defective_programs() still detects
# each one (the kind below is what it reports today), and a correct re-upload clears it with no
# edit here. Today a profile that reaches one of these gets a GUIDE_UNAVAILABLE row ("The guide on
# file is the wrong document -- check with the carrier directly."), never a verdict. The files are
# kept (not removed) so the row keeps showing until the right PDF arrives.
# program: (detected kind, PDF bytes, sha256 of the PDF, what the PDF actually is)
WRONG_FILE_EVIDENCE = {
    "Liberty_Mutual_HO6_-_02.21.2026": (
        DUPLICATE_DOCUMENT, 207340, "c454ca0a8682970c486c5761aa6310047bc4720cdd2e87fe1a40111841846dcc",
        "byte-identical to Liberty_Mutual_HO3_-_02.21.2026.pdf (same size and sha256); 12 pages, page 1 "
        "'Texas What's New ... Home and Updates ... Eligibility Guidelines' -- the homeowners guide, no "
        "condo / HO6 text. Reached only by an Owner Occupied condo check."),
    "NatGen_Custom360_HO3_-_06.25.2026": (
        DUPLICATE_DOCUMENT, 434289, "bc0f9c6dc28f939a3a8227af601e3d115af626236d74158cdab33ee74ef92fc6",
        "byte-identical to NatGen_Custom360_DP3_-_06.25.2026.pdf; 24 pages, page 1 'Texas Landlord -- "
        "Custom360 ... Form Number: 15606' -- the landlord (DP3) guide."),
    "Sage_-_Occidental_HO3": (
        WRONG_PRODUCT, 308623, "2a34fcb2a72ad7556818daac51511850774b8c2fbbc8a503eaca8d86609bd025",
        "15 pages, page 1 'TEXAS OCCIDENTAL DWELLING FIRE PROGRAM (DP3)' -- a dwelling fire guide, and "
        "a different copy from Sage_-_Occidental_DP3.pdf (324,527 bytes, sha256 a03f9aba92f0...)."),
}

# Same margins as test_each_document_reads_like_the_product_its_filename_claims,
# and for the same reason its comment gives: a heuristic that fires on a
# legitimate carrier later is worse than no heuristic. Travelers' HO3 guide
# carries a real "LANDLORD DWELLING / LANDLORD CONDOMINIUM ONLY" ineligibility
# section (3 landlord vs 8 homeowners hits, ratio 2.7) and must not trip;
# NatGen Custom360's mis-filed record is 2 vs 34, ratio 17.
_WRONG_PRODUCT_MIN_HITS = 10
_WRONG_PRODUCT_MIN_RATIO = 4.0

# Policy FORMS and PRODUCT names a guide gives ITSELF -- endorsement numbers
# excluded, since DP guides cite HO 04 70 and vice versa. Mirrors the standing
# test's reference rule; see the WRONG_PRODUCT block below for why it exists.
_HO_PRODUCT_REF_RE = re.compile(
    r"(?i)\bHO[- ]?00[- ]?0[2-8]\b|\bHO[- ]?[3568]\b(?![- ]?\d)|homeowners? program")
_DP_PRODUCT_REF_RE = re.compile(
    r"(?i)\bDP[- ]?00[- ]?0[1-3]\b|\bDP[- ]?[13]\b(?![- ]?\d)|dwelling fire program|landlord program")
_PRODUCT_REF_FLOOR = 3

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


def _expected_programs_from_list():
    """Program names in EXPECTED_PROGRAMS_FILE: one per line, '#' comments."""
    try:
        with open(EXPECTED_PROGRAMS_FILE, encoding="utf-8") as fh:
            return {line.strip() for line in fh
                    if line.strip() and not line.lstrip().startswith("#")}
    except FileNotFoundError:
        return set()


def expected_programs():
    """Every program that should be in the store: the committed list plus any
    PDF on disk. Used ONLY to find programs MISSING from the store; presence
    and every other defect come from the store itself."""
    return _expected_programs_from_list() | _expected_programs_from_pdfs()


def defective_programs():
    """{program_name: {"kind": ..., "detail": ...}} for every unusable program.

    Empty dict means the corpus is clean and every caller's defect handling
    silently switches off, which is the point.
    """
    grouped = _chunks_by_carrier()
    defects = {}

    # --- NO_TEXT: expected, absent from the store -------------------------
    for program in sorted(expected_programs() - set(grouped)):
        defects[program] = {
            "kind": NO_TEXT,
            "detail": (
                "No readable guide for this program is in the database. Its PDF produced "
                "no text when it was loaded (it appears to be a scanned image), so it "
                "cannot be answered from."
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
        word_rule = (opposite_hits >= _WRONG_PRODUCT_MIN_HITS
                     and opposite_hits >= _WRONG_PRODUCT_MIN_RATIO * max(own_hits, 1))

        # The REFERENCE rule -- same signal and floor as the standing test
        # (verification/test_eligibility_matrix.py, _product_mismatches), and
        # the one that catches DD-4: Sage_-_Occidental_HO3 holds Occidental's
        # DWELLING FIRE PROGRAM (DP3) guide, 0 HO references vs 5 DP. The word
        # rule alone misses it because 5 of its 6 "homeowners" hits are
        # "owner occupied", which dwelling-fire guides say constantly.
        flat = re.sub(r"\s+", " ", text)
        ho_refs = len(_HO_PRODUCT_REF_RE.findall(flat))
        dp_refs = len(_DP_PRODUCT_REF_RE.findall(flat))
        own_refs, opposite_refs = (ho_refs, dp_refs) if is_ho else (dp_refs, ho_refs)
        ref_rule = own_refs == 0 and opposite_refs >= _PRODUCT_REF_FLOOR

        if not (word_rule or ref_rule):
            continue

        evidence = []
        if word_rule:
            evidence.append("{} opposite-product mentions against {} of its own".format(
                opposite_hits, own_hits))
        if ref_rule:
            evidence.append("it names the other product's policy forms {} times and its "
                            "own none".format(opposite_refs))
        defects.setdefault(carrier, {
            "kind": WRONG_PRODUCT,
            "detail": (
                "This program's filename says {claimed}, but its text reads like "
                "{actual} ({evidence}). The file on record is the wrong document."
            ).format(
                claimed="homeowners" if is_ho else "dwelling fire",
                actual="dwelling fire / landlord" if is_ho else "homeowners",
                evidence="; ".join(evidence),
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
