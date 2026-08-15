"""
Table-aware PDF text extraction using pdfplumber.

Replaces PyPDFLoader in the carrier-eligibility-tool pipeline. Underwriting
matrices (roof age x roof type, etc.) get destroyed by plain text extraction
because rows/columns collapse into a single word-soup line. This module
detects tables per page, converts them to Markdown grids, and keeps
surrounding prose text separate so nothing gets duplicated or garbled.
"""

import pdfplumber

try:
    from langchain_core.documents import Document
except ImportError:
    from langchain.schema import Document


def _table_to_markdown(table_data):
    """Convert a pdfplumber-extracted table (list of rows, each a list of
    cell strings/None) into a Markdown grid."""
    if not table_data:
        return ""

    cleaned = []
    for row in table_data:
        cleaned_row = [(cell or "").replace("\n", " ").strip() for cell in row]
        cleaned.append(cleaned_row)

    # Drop fully-empty rows (reportlab/pdfplumber sometimes yields these)
    cleaned = [r for r in cleaned if any(c for c in r)]
    if not cleaned:
        return ""

    header = cleaned[0]
    body = cleaned[1:]
    col_count = len(header)

    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * col_count) + " |",
    ]
    for row in body:
        row = (row + [""] * col_count)[:col_count]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _extract_page_blocks(page, table_settings=None):
    """Extract one page as a list of (text, is_table) tuples. Prose and
    table content are kept as SEPARATE blocks (rather than one merged
    string) so the caller can chunk them differently: prose gets the
    normal 500-char splitter, tables stay atomic regardless of size.

    This matters because a multi-row matrix (e.g. a PPC/Fire-Protection-
    Class table with a different rule per protection-class band) can
    exceed 500 chars. Splitting it mid-table separates a row's condition
    from its consequence, or drops rows entirely from what gets embedded
    -- which is consistent with a real failure an accuracy audit found:
    the model citing a fabricated or misapplied rule for PPC 9 when the
    real rule was in a row that never made it into the retrieved chunk
    intact.
    """
    tables = page.find_tables(table_settings=table_settings) if table_settings else page.find_tables()
    if not tables:
        text = page.extract_text() or ""
        return [(text, False)] if text.strip() else []

    table_bboxes = [t.bbox for t in tables]

    def not_in_table(obj):
        x0, top, x1, bottom = obj.get("x0"), obj.get("top"), obj.get("x1"), obj.get("bottom")
        if x0 is None:
            return True
        cx, cy = (x0 + x1) / 2, (top + bottom) / 2
        for (bx0, btop, bx1, bbottom) in table_bboxes:
            if bx0 <= cx <= bx1 and btop <= cy <= bbottom:
                return False
        return True

    prose_page = page.filter(not_in_table)
    prose_text = (prose_page.extract_text() or "").strip()

    blocks = []
    if prose_text:
        blocks.append((prose_text, False))

    for t in tables:
        md = _table_to_markdown(t.extract())
        if md:
            blocks.append((md, True))

    return blocks


# A table chunk this large risks exceeding the embedding model's max
# sequence length (FastEmbed's bge-small is BERT-based, typically capped
# around 512 tokens / ~2000 chars) -- past that point the embedding
# function may silently truncate it, which would defeat the point of
# keeping it atomic. Not auto-split (that would reintroduce the original
# bug); just flagged loudly so an oversized table gets noticed rather
# than silently mis-embedded.
TABLE_SIZE_WARNING_THRESHOLD = 2000


def chunk_documents(pages, splitter):
    """Chunk a list of page-level Documents (from load_pdf_as_documents),
    splitting prose normally but keeping every table Document as a single
    atomic chunk, however large. Use this INSTEAD of calling
    splitter.split_documents(pages) directly, in both upload_carrier.py
    and load_docs.py, so both ingestion paths get this fix consistently.
    """
    prose_docs = [d for d in pages if not d.metadata.get("is_table")]
    table_docs = [d for d in pages if d.metadata.get("is_table")]

    chunks = splitter.split_documents(prose_docs) if prose_docs else []

    for doc in table_docs:
        if len(doc.page_content) > TABLE_SIZE_WARNING_THRESHOLD:
            print(
                f"WARNING: table on page {doc.metadata.get('page')} "
                f"({doc.metadata.get('carrier', doc.metadata.get('source_file', '?'))}) "
                f"is {len(doc.page_content)} chars -- may exceed the embedding "
                f"model's max sequence length and get silently truncated. "
                f"Consider manually reviewing this table."
            )
        chunks.append(doc)

    return chunks


def load_pdf_as_documents(path_or_fileobj, table_settings=None):
    """Drop-in replacement for `PyPDFLoader(path).load()`.

    Returns a list of langchain Document objects with
    metadata={"page": <0-indexed page number>, "is_table": <bool>}.
    A page with both prose and a table now produces TWO Document objects
    (previously one merged string) -- use chunk_documents() above to
    split them, not splitter.split_documents() directly, or tables lose
    their atomic-chunk protection.

    table_settings: optional pdfplumber table_settings dict, for carriers
    whose tables aren't caught by the default line-based detection. See
    the TABLE_SETTINGS comment below.
    """
    docs = []
    with pdfplumber.open(path_or_fileobj) as pdf:
        for i, page in enumerate(pdf.pages):
            blocks = _extract_page_blocks(page, table_settings=table_settings)
            for block_text, is_table in blocks:
                if block_text and block_text.strip():
                    docs.append(Document(
                        page_content=block_text,
                        metadata={"page": i, "is_table": is_table},
                    ))
            # Release this page's cached layout objects before moving on --
            # keeps peak memory down when processing large multi-page PDFs.
            page.flush_cache()
    return docs


# pdfplumber's default find_tables() detects tables via ruling lines
# (bordered tables/grids). Some carrier guides use whitespace-aligned
# tables with no visible borders -- those won't be picked up by the
# default and will just fall through to plain prose extraction (no worse
# than before, but no better either). If spot-checking a specific carrier
# shows a matrix isn't being detected, try:
#   TABLE_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text"}
# and pass it through load_pdf_as_documents(path, table_settings=TABLE_SETTINGS).
# This is more prone to false positives on aligned prose, so don't make it
# the global default without checking a few pages first.
TABLE_SETTINGS = None  # None = pdfplumber defaults (line-based detection)


if __name__ == "__main__":
    docs = load_pdf_as_documents("/home/claude/test/sample_underwriting.pdf")
    for d in docs:
        print(f"--- page {d.metadata['page']} (is_table={d.metadata['is_table']}) ---")
        print(d.page_content)
        print()