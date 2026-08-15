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


# Rough point past which FastEmbed's underlying model (bge-small, BERT-
# based, typically ~512 token max) may start truncating input before
# creating the embedding -- meaning content past this point in a chunk
# may not meaningfully affect what that chunk matches against in a
# similarity search, even though the full text still reaches the LLM if
# the chunk gets retrieved. Char-per-token ratio varies (table syntax with
# lots of "|" and "---" is less token-efficient than prose), so these are
# deliberately conservative, not exact.
TABLE_SPLIT_THRESHOLD = 1800
TABLE_SPLIT_TARGET_SIZE = 1200


def _split_markdown_table(table_text, max_chars=TABLE_SPLIT_TARGET_SIZE):
    """Split an oversized Markdown table into row-grouped pieces, each
    small enough to be well-represented by the embedding model, with the
    header + separator row repeated at the top of every piece.

    Splitting by ROW GROUPS (not raw characters) is what makes this safe:
    every row stays paired with its column headers in whichever piece it
    lands in, so a PPC-9-specific row several groups deep in a large
    table is still fully self-contained and interpretable on its own --
    unlike the original character-based splitter, which could separate a
    row from its header entirely.

    Returns a list with the original text unchanged if the table isn't a
    well-formed 2+ header-row Markdown grid, or if splitting wouldn't
    actually produce more than one piece.
    """
    lines = table_text.split("\n")
    if len(lines) < 3 or not lines[0].strip().startswith("|"):
        return [table_text]  # not a table shape we recognize -- don't risk mangling it

    header_line, separator_line = lines[0], lines[1]
    data_lines = lines[2:]

    prefix = header_line + "\n" + separator_line
    prefix_len = len(prefix) + 1  # +1 for the newline before the first data row

    groups = []
    current_group = []
    current_len = prefix_len

    for row in data_lines:
        row_len = len(row) + 1
        if current_group and current_len + row_len > max_chars:
            groups.append(current_group)
            current_group = []
            current_len = prefix_len
        current_group.append(row)
        current_len += row_len

    if current_group:
        groups.append(current_group)

    if len(groups) <= 1:
        return [table_text]  # no benefit to splitting -- keep as one chunk

    return [prefix + "\n" + "\n".join(g) for g in groups]


def chunk_documents(pages, splitter):
    """Chunk a list of page-level Documents (from load_pdf_as_documents),
    splitting prose normally, and splitting tables by ROW GROUPS (never
    mid-row) only if they're large enough to risk exceeding the embedding
    model's effective window -- small tables stay as one atomic chunk
    exactly as before. Use this INSTEAD of calling
    splitter.split_documents(pages) directly, in both upload_carrier.py
    and load_docs.py, so both ingestion paths get this fix consistently.
    """
    prose_docs = [d for d in pages if not d.metadata.get("is_table")]
    table_docs = [d for d in pages if d.metadata.get("is_table")]

    chunks = splitter.split_documents(prose_docs) if prose_docs else []

    for doc in table_docs:
        if len(doc.page_content) <= TABLE_SPLIT_THRESHOLD:
            chunks.append(doc)
            continue

        pieces = _split_markdown_table(doc.page_content)

        if len(pieces) > 1:
            print(
                f"INFO: table on page {doc.metadata.get('page')} "
                f"({doc.metadata.get('carrier', doc.metadata.get('source_file', '?'))}) "
                f"was {len(doc.page_content)} chars -- split into {len(pieces)} "
                f"row-grouped pieces (header repeated in each)."
            )
            for piece in pieces:
                chunks.append(Document(page_content=piece, metadata=dict(doc.metadata)))
        else:
            # Couldn't usefully split (e.g. one row alone exceeds the
            # target, or it wasn't a recognizable table shape) -- keep it
            # atomic as before rather than risk mangling it, but still
            # flag it since it's genuinely at risk of truncation.
            print(
                f"WARNING: table on page {doc.metadata.get('page')} "
                f"({doc.metadata.get('carrier', doc.metadata.get('source_file', '?'))}) "
                f"is {len(doc.page_content)} chars and could not be usefully "
                f"row-split -- keeping as one chunk. Consider manually reviewing "
                f"this table."
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