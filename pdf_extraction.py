"""
Table-aware PDF text extraction using pdfplumber.

Replaces PyPDFLoader in the carrier-eligibility-tool pipeline. Underwriting
matrices (roof age x roof type, etc.) get destroyed by plain text extraction
because rows/columns collapse into a single word-soup line. This module
detects tables per page, converts them to Markdown grids, and keeps
surrounding prose text separate so nothing gets duplicated or garbled.
"""

import os
import re

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


def _is_full_page_bbox(bbox, page, tolerance=0.05):
    """True if a detected table's bbox spans essentially the entire page.
    pdfplumber's line-based detector can mistake a page border (or a stray
    full-width rule) for table edges, producing a 1-column "table" whose
    handful of "rows" are actually the whole page's content flattened into
    a couple of giant cells. Diagnosed on all 4 Swyfft PDFs -- every page
    had exactly one of these alongside the real, properly-bounded tables,
    and its two-giant-cell shape is why _split_markdown_table() had only
    one real data row to split and gave up ("could not be usefully
    row-split")."""
    x0, top, x1, bottom = bbox
    return (
        x0 <= tolerance * page.width
        and top <= tolerance * page.height
        and x1 >= (1 - tolerance) * page.width
        and bottom >= (1 - tolerance) * page.height
    )


def _extract_page_blocks(page, table_settings=None, text_flow=False):
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
    tables = [t for t in tables if not _is_full_page_bbox(t.bbox, page)]
    if not tables:
        text = page.extract_text(use_text_flow=text_flow) or ""
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
    prose_text = (prose_page.extract_text(use_text_flow=text_flow) or "").strip()

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


def load_pdf_as_documents(path_or_fileobj, table_settings=None, text_flow=False):
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
            blocks = _extract_page_blocks(page, table_settings=table_settings, text_flow=text_flow)
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


# --- Round 29 step 5 (2026-10-08): two kinds of guide the default path reads wrong ---------------
#
# 1. OVERLAPPING LIST LABELS. Centauri_-_DP3_-_11.16.2022.pdf draws Word's list labels ("b.", in
#    Cambria-Bold) about 2 pt above the body text at the same x. pdfplumber's line clustering puts both
#    on one line and sorts by x, interleaving them: "b."+"RO" -> "bR.O OFS/SIDING", and lines such as
#    "i. Rolled Roofs" go missing. Reading in content-stream order (use_text_flow) gives the text as
#    written. Opt-in per file, so every other guide's text stays byte-identical;
#    overlapping_label_chars() is the signature, used to list any other guide with the pattern.
FLOW_ORDER_FILES = {"Centauri_-_DP3_-_11.16.2022.pdf"}
#
# 2. SCANNED GUIDES with no text layer (Centauri_-_HO3_-_05.01.2026.pdf: 0 chunks). If an OCR text
#    file exists at ocr_text/<pdf name without .pdf>.txt, with pages marked "=====PAGE n=====", it is
#    the guide's text. No OCR engine is a dependency; the text file is made once, outside the app.
OCR_TEXT_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_text")


def overlapping_label_chars(page, max_dx=1.0, min_dy=0.5, max_dy=3.0):
    """How many non-space characters sit almost on top of a DIFFERENT character
    (x0 within max_dx, top 0.5-3 pt apart): the overlapping-list-label signature."""
    chars = sorted((c for c in page.chars if c.get("text", "").strip()), key=lambda c: c["x0"])
    hits = 0
    for i, a in enumerate(chars):
        for b in chars[i + 1:]:
            if b["x0"] - a["x0"] > max_dx:
                break
            if a["text"] != b["text"] and min_dy <= abs(a["top"] - b["top"]) <= max_dy:
                hits += 1
    return hits


def ocr_text_path(pdf_name):
    return os.path.join(OCR_TEXT_FOLDER, os.path.splitext(os.path.basename(pdf_name))[0] + ".txt")


def load_ocr_text_as_documents(path):
    """Page Documents from an OCR text file ("=====PAGE n=====" markers), shaped like
    load_pdf_as_documents' output: metadata={"page": n-1, "is_table": False}."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    docs = []
    for m in re.finditer(r"=====PAGE (\d+)=====\n(.*?)(?======PAGE \d+=====|\Z)", text, re.S):
        body = m.group(2).strip()
        if body:
            docs.append(Document(page_content=body, metadata={"page": int(m.group(1)) - 1, "is_table": False}))
    return docs


def load_guide_documents(pdf_path, table_settings=None):
    """(documents, source) for one guide PDF: "pdf", "pdf (text flow order)", or "ocr text".
    The one entry point for load_docs.py and upload_carrier.py."""
    name = os.path.basename(pdf_path)
    if name in UPLOAD_PATH_FILES:                # round 39: hidden text dropped, one document per section
        return load_upload_documents(pdf_path)[0], "pdf (upload path: visible text, sections)"
    flow = name in FLOW_ORDER_FILES
    docs = load_pdf_as_documents(pdf_path, table_settings=table_settings, text_flow=flow)
    if not any(d.page_content.strip() for d in docs) and os.path.exists(ocr_text_path(name)):
        return load_ocr_text_as_documents(ocr_text_path(name)), "ocr text"
    return docs, "pdf (text flow order)" if flow else "pdf"


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


# --- Round 39 steps 2a / 2b (Liam, 2026-10-12): the upload path ----------------------------------------------------
#
# 2b. HIDDEN TEXT. "The Hartford HO3 10.12.2026.pdf" is an Excel export: page 1 carries ~1,300 characters of an auto
#     guide ("MVR", "Vehicle", "PIP", "Accidents") in blue, stacked on one line and off the page's left edge, none of
#     it visible on the rendered page. A character is dropped when it is not visible on the rendered page AND it is
#     off the page, or not black/gray, or part of a run stacked on itself. Text that is merely under an image (black)
#     is kept: Centauri DP3 has a version stamp under its logo, and its rules are in black text.
# 2a. SECTIONS. A guide's own headings decide what a line means (the Hartford's "Swimming pool on premises -> Decline"
#     is under "Rental Property Protection Plus", the landlord program, not the homeowners form). Each section becomes
#     its own document, and every chunk of it starts with "[<heading>]", so the prompt shows the section.
# Both run for every NEW upload (upload_carrier.add_carrier_to_database) and, on a full rebuild, for the files below;
# every other guide on file is read exactly as before (its stored text is byte-identical).
UPLOAD_PATH_FILES = {"The_Hartford_HO3_-_07.09.2026.pdf"}
_RENDER_DPI = 144
_VISIBLE_TOLERANCE = 90
_STACKED = 1.3


def _rgb(color):
    if isinstance(color, (int, float)):
        color = (color,)
    if not isinstance(color, (tuple, list)) or not color:
        return None
    try:
        color = tuple(float(x) for x in color)
    except (TypeError, ValueError):
        return None
    if len(color) == 1:
        return (color[0] * 255,) * 3
    if len(color) == 3:
        return tuple(x * 255 for x in color)
    if len(color) == 4:
        c, m, y, k = color
        return tuple(255 * (1 - v) * (1 - k) for v in (c, m, y))
    return None


def _drawn(px, size, box, rgb):
    """Is the character's own colour on the rendered page inside its box?"""
    x0, y0, x1, y1 = box
    for x in range(max(0, x0), min(size[0] - 1, x1) + 1):
        for y in range(max(0, y0), min(size[1] - 1, y1) + 1):
            p = px[x, y]
            if ((p[0] - rgb[0]) ** 2 + (p[1] - rgb[1]) ** 2 + (p[2] - rgb[2]) ** 2) ** 0.5 < _VISIBLE_TOLERANCE:
                return True
    return False


def hidden_chars(page):
    """The page's characters that are not visible and are off-page, coloured or stacked (see 2b above)."""
    W, H = page.width, page.height
    chars = [c for c in page.chars if c.get("text", "").strip()]
    hidden = {id(c) for c in chars if c["x1"] <= 0 or c["x0"] >= W or c["bottom"] <= 0 or c["top"] >= H}
    groups = {}
    for c in chars:
        groups.setdefault((round(c["top"] / 2), str(c.get("non_stroking_color")), round(c["size"], 1)), []).append(c)
    stacked = set()
    for g in groups.values():
        span = max(c["x1"] for c in g) - min(c["x0"] for c in g)
        if len(g) >= 10 and span > 0 and sum(c["width"] for c in g) / span >= _STACKED:
            stacked.update(id(c) for c in g)
    def coloured(c):                        # not black or a gray: the colour channels differ
        rgb = _rgb(c.get("non_stroking_color"))
        return rgb is None or max(rgb) - min(rgb) > 30
    suspects = [c for c in chars if id(c) not in hidden and (id(c) in stacked or coloured(c))]
    if suspects:
        img = page.to_image(resolution=_RENDER_DPI).original.convert("RGB")
        px, sx, sy = img.load(), img.width / float(W), img.height / float(H)
        for c in suspects:
            rgb = _rgb(c.get("non_stroking_color"))
            box = (int(c["x0"] * sx), int(c["top"] * sy), int(c["x1"] * sx) + 1, int(c["bottom"] * sy) + 1)
            if rgb is None or not _drawn(px, img.size, box, rgb):
                hidden.add(id(c))
    return [c for c in chars if id(c) in hidden]


def visible_page(page):
    """(the page without its hidden characters, how many were dropped)."""
    keys = {(c["x0"], c["top"], c["text"]) for c in hidden_chars(page)}
    if not keys:
        return page, 0
    return page.filter(lambda o: not (o.get("object_type") == "char" and (o["x0"], o["top"], o["text"]) in keys)), len(keys)


_HEADER_LINES = {"condition action", "condition", "action"}


def _is_heading(line):
    """A line that starts with a bold run and has nothing after it but a parenthetical: "Losses", "Rental Property
    Protection Plus", "High Value Homes ($1,500,000+)" -- not "APPLIANCE RELATED LOSS MEANS: a loss arising ..."."""
    chars = [c for c in line.get("chars", []) if c.get("text", "").strip()]
    text = line["text"].strip()
    if not chars or not (2 < len(text) <= 70) or not text[0].isupper():     # "in the counties of:" continues a line
        return False
    if text.lower() in _HEADER_LINES or text.lower().startswith("note"):
        return False
    n = 0
    while n < len(chars) and "bold" in chars[n]["fontname"].lower():
        n += 1
    rest = "".join(c["text"] for c in chars[n:]).strip()
    if n < 3:
        return False
    if not rest or rest.startswith("("):
        return True
    # a bold condition with its action on the same line ("Unfenced inground swimming pool  Decline"): a heading of
    # its own, holding that line
    return "row" if re.match(r"(Decline|Refer|Accept|Required|Coverage available|See )", rest) else False


def section_documents(lines, page_index, boilerplate=frozenset(), first_page=False):
    """One page's lines (pdfplumber extract_text_lines) as one Document per section: "[<heading>]" then its lines,
    metadata section=<heading>. A page header repeated on most pages (boilerplate) is kept once, on the first page,
    as "[Guide header]"; a heading wrapped over two lines is one heading; lines before a page's first heading
    continue the last section of the page before (section_documents.last)."""
    docs, heading, body, header = [], getattr(section_documents, "last", ""), [], []
    prev_heading = False

    def flush():
        text = "\n".join(body).strip()
        if text:
            docs.append(Document(page_content=(f"[{heading}]\n" if heading else "") + text,
                                 metadata={"page": page_index, "is_table": False, "section": heading}))
    for line in lines:
        text = line["text"].strip()
        if text in boilerplate:
            if first_page:
                header.append(text)
            continue
        kind = _is_heading(line)
        if kind == "row":
            flush()
            head = re.split(r"\s+(?=Decline|Refer|Accept|Required|Coverage available|See )", text, maxsplit=1)[0]
            heading, body = head.strip().rstrip(":"), [line["text"]]
            prev_heading = False
            continue
        if kind:
            if prev_heading and not body:
                heading = (heading + " " + text).rstrip(":")
            else:
                flush()
                heading, body = text.rstrip(":"), []
            prev_heading = True
            continue
        body.append(line["text"])
        prev_heading = False
    flush()
    if header:
        docs.insert(0, Document(page_content="[Guide header]\n" + "\n".join(header),
                                metadata={"page": page_index, "is_table": False, "section": "Guide header"}))
    section_documents.last = heading
    return docs


def load_upload_documents(path_or_fileobj):
    """Round 39: the upload path -- hidden text dropped (2b), one Document per section (2a). Returns (docs, dropped)."""
    pages, dropped = [], 0
    with pdfplumber.open(path_or_fileobj) as pdf:
        for page in pdf.pages:
            page, n = visible_page(page)
            dropped += n
            pages.append(page.extract_text_lines())
            page.flush_cache()
    counts = {}
    for lines in pages:
        for t in {ln["text"].strip() for ln in lines}:
            counts[t] = counts.get(t, 0) + 1
    boilerplate = frozenset(t for t, n in counts.items() if len(pages) > 2 and n > len(pages) / 2)
    docs = []
    section_documents.last = ""
    for i, lines in enumerate(pages):
        docs.extend(section_documents(lines, i, boilerplate, first_page=(i == 0)))
    return docs, dropped


def section_prefixed(chunks):
    """Every chunk of a section starts with its "[<heading>]" (the splitter keeps it only on the first piece)."""
    for c in chunks:
        s = c.metadata.get("section")
        if s and not c.page_content.startswith(f"[{s}]"):
            c.page_content = f"[{s}]\n" + c.page_content
    return chunks
