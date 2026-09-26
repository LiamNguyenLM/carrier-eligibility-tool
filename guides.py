"""Rebuilding a carrier program's whole guide text out of Chroma's chunks.

The chat tab feeds the model WHOLE guides rather than top-k snippets for
questions about a handful of named programs. The reason is written all over
the last few audits: "the retrieved excerpts do not provide..." kept coming
back for rules that are demonstrably in the guide (the HOAIC and Mercury pool
rules, CHUBB, Liberty Mutual). Those are retrieval misses, not document gaps,
and no amount of raising k fixes the class -- eligibility_check.py already
carries a whole layer of per-topic "guaranteed lookup" predicates built to
paper over exactly this, one topic at a time. A chat tab takes arbitrary
questions, so there is no fixed list of topics to guarantee. Sending the
whole guide removes the failure mode instead of narrowing it.

It is affordable here in a way it is not in the eligibility pipeline, which
reasons over ~30 carriers at once. Measured over this corpus:

    total across 40 programs   ~290K tokens
    largest single program     Foremost DP3+HO3, ~44.5K tokens
    median program             ~9K tokens

So one to three named programs is typically well under 30K tokens of guide
text, and the worst realistic case (three Sage programs, or Foremost alone)
stays inside a single request comfortably.

DOCUMENT ORDER
--------------
Chunks do NOT come back from Chroma in reading order, and the reason matters
because it makes the order recoverable rather than lost. The loader writes
all of a document's prose chunks first, in page order, and then appends its
table chunks, also in page order. So insertion order is two interleaved
ascending runs, not noise -- verified across all 40 programs, where 36 are
non-monotonic in raw insertion order and every one of them sorts cleanly
under `(page, is_table)`.

A stable sort on that key puts each page's prose before that page's tables
and restores a faithful reading of the document. `is_table` is the tiebreak
rather than a separate section because a table belongs with the page it was
lifted from -- appending all tables at the end would separate, say, Liberty
Mutual's "Minimum Coverage Requirements" table from the eligibility text on
its own page that refers to it.
"""

from shared_resources import get_vectorstore


def _sorted_chunks(program):
    collection = get_vectorstore()._collection
    raw = collection.get(
        where={"carrier": program}, include=["documents", "metadatas"]
    )
    pairs = list(zip(raw["metadatas"], raw["documents"]))
    # Stable sort: within one (page, is_table) group the loader's own order is
    # already correct, so it must be preserved rather than re-derived.
    return sorted(
        pairs,
        key=lambda pair: (pair[0].get("page", 0), bool(pair[0].get("is_table"))),
    )


def guide_text(program):
    """The program's full guide as one string, in document order.

    Returns "" for a program with no stored chunks -- see data_defects.NO_TEXT,
    which is how Centauri HO3 presents.
    """
    return "\n\n".join(doc for _, doc in _sorted_chunks(program))


def guide_text_with_pages(program):
    """Same text, but each page marked, so the model can cite a page number.

    Agents check quotes against the real PDF, and a page number is what makes
    that a ten-second job instead of a search.
    """
    out, current = [], None
    for meta, doc in _sorted_chunks(program):
        page = meta.get("page", 0)
        if page != current:
            out.append("\n[page {}]".format(page + 1))
            current = page
        out.append(doc)
    return "\n\n".join(out).strip()


def all_programs():
    """Every program that actually has text in the store, sorted."""
    collection = get_vectorstore()._collection
    raw = collection.get(include=["metadatas"])
    return sorted({m["carrier"] for m in raw["metadatas"] if m.get("carrier")})


# Markings a carrier put on its own document to restrict how it may be shared.
# Not a data defect and not a bug -- a governance fact about the file.
_CONFIDENTIALITY_MARKERS = (
    "privileged", "confidential", "proprietary",
    "internal use only", "do not distribute",
)


def confidentiality_markings(program):
    """{marker: count} for the sharing restrictions a guide carries.

    Exists because "which documents may we send to a third-party vendor" is a
    question that must be answered from the documents themselves, every time,
    rather than from a list someone wrote once and forgot to update. 17 of the
    40 guides carry a marking today, and they are not the ones you would
    guess: the entire Sage family is "Privileged and Confidential", Foremost
    says "do not distribute" outright, and Progressive is "proprietary", while
    Allied Trust, Mercury and the Swyfft programs carry nothing at all.

    Derived rather than listed, for the same reason data_defects is: a
    re-uploaded guide changes its own answer here with no code change.
    """
    text = guide_text(program).lower()
    return {m: text.count(m) for m in _CONFIDENTIALITY_MARKERS if text.count(m)}


def is_confidential(program):
    """True if the guide restricts its own redistribution.

    Used to gate what may be sent to a NON-Anthropic provider. The eligibility
    pipeline's existing Anthropic exposure was approved separately and on
    retrieved snippets; this is the check for anything beyond that.
    """
    return bool(confidentiality_markings(program))


def unmarked_programs():
    """Programs whose guides carry no redistribution restriction."""
    return [p for p in all_programs() if not is_confidential(p)]


def estimate_tokens(text):
    """Rough token count. Deliberately a cheap local estimate: this is used to
    decide whether a question is affordable to answer in full-guide mode, and
    paying a network round-trip to the token-counting endpoint to find out
    whether to make a request would defeat the purpose."""
    return len(text) // 4
