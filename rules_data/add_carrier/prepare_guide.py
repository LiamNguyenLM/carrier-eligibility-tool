"""Add a carrier, step 2 (pilot_structured_rules/ADD_CARRIER.md): a guide's text and page images for the extractor and
the reviewer, read the way the app stores it (pdf_extraction.load_upload_documents: hidden text dropped, each section's
heading kept).

usage: python rules_data/add_carrier/prepare_guide.py <guide.pdf> <work folder>
writes into the work folder:
  reading_order.txt  the stored text, page by page ("=====PAGE n=====", 1-based), "[section]" headings included
  layout.txt         the visible characters of each page in column layout (tables keep their columns)
  page_N.png         each page rendered at 144 dpi (the source of truth for the reviewer)
  guide.txt          the guide's date and where it was read, the hidden characters dropped, the page count
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import pdfplumber  # noqa: E402

import pdf_extraction as pe  # noqa: E402


def main(pdf, out):
    os.makedirs(out, exist_ok=True)
    docs, dropped = pe.load_upload_documents(pdf)
    pages = {}
    for d in docs:
        pages.setdefault(d.metadata.get("page", 0), []).append(d.page_content)
    n = max(pages) + 1 if pages else 0
    with open(os.path.join(out, "reading_order.txt"), "w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(f"=====PAGE {i + 1}=====\n" + "\n".join(pages.get(i, [])) + "\n")
    with pdfplumber.open(pdf) as doc, open(os.path.join(out, "layout.txt"), "w", encoding="utf-8") as fh:
        for i, page in enumerate(doc.pages):
            visible, _ = pe.visible_page(page)
            fh.write(f"=====PAGE {i + 1}=====\n" + (visible.extract_text(layout=True) or "") + "\n")
            page.to_image(resolution=144).save(os.path.join(out, f"page_{i + 1}.png"))
    date, phrase, where = pe.guide_date_from_docs(docs)
    with open(os.path.join(out, "guide.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"pages: {n}\nhidden characters dropped: {dropped}\n"
                 f"guide date: {date or 'not found in the text'}" + (f" ({where}: \"{phrase}\")" if date else "") + "\n")
    print(f"{n} pages, {dropped} hidden characters dropped, guide date {date or 'not found'} -> {out}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
