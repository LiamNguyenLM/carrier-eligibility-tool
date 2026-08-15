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


def _extract_page_text_with_tables(page, table_settings=None):
    """Extract one page as a string. Table regions are pulled out separately
    and rendered as Markdown grids; everything else is extracted as normal
    prose text with the table content excluded so nothing is duplicated.

    Note: tables are appended after the page's prose text rather than
    precisely interleaved at their pixel position. Underwriting PDFs
    typically present as intro text -> table -> follow-up text per section,
    so this keeps each table intact and adjacent to its page's context
    without the complexity/fragility of position-based interleaving.
    """
    tables = page.find_tables(table_settings=table_settings) if table_settings else page.find_tables()
    if not tables:
        return page.extract_text() or ""

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

    table_blocks = []
    for t in tables:
        md = _table_to_markdown(t.extract())
        if md:
            table_blocks.append(md)

    parts = [p for p in [prose_text] if p]
    parts.extend(table_blocks)
    return "\n\n".join(parts)


def load_pdf_as_documents(path_or_fileobj, table_settings=None):
    """Drop-in replacement for `PyPDFLoader(path).load()`.

    Returns a list of langchain Document objects, one per non-empty page,
    with metadata={"page": <0-indexed page number>} -- matching PyPDFLoader's
    metadata shape so downstream code (chunk.metadata.get('page')) keeps
    working unchanged.

    table_settings: optional pdfplumber table_settings dict, for carriers
    whose tables aren't caught by the default line-based detection. See the
    TABLE_SETTINGS comment above.
    """
    docs = []
    with pdfplumber.open(path_or_fileobj) as pdf:
        for i, page in enumerate(pdf.pages):
            text = _extract_page_text_with_tables(page, table_settings=table_settings)
            if text and text.strip():
                docs.append(Document(page_content=text, metadata={"page": i}))
            # Release this page's cached layout objects before moving on --
            # keeps peak memory down when processing large multi-page PDFs.
            page.flush_cache()
    return docs


if __name__ == "__main__":
    docs = load_pdf_as_documents("/home/claude/test/sample_underwriting.pdf")
    for d in docs:
        print(f"--- page {d.metadata['page']} ---")
        print(d.page_content)
        print()