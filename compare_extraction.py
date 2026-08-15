"""
Compare old (PyPDFLoader) vs new (pdf_extraction.py) PDF extraction on
whatever real carrier PDFs you point it at. Purely local -- no ChromaDB,
no Claude API, no upload to the live app. Answers "did the pdfplumber
change actually help?" without touching anything live.

Usage:
    python compare_extraction.py "Carrier_Eligibility_PDFs/Allied Trust HO3.pdf"
    python compare_extraction.py path/to/one.pdf path/to/two.pdf

For each PDF, writes two files next to this script:
    old_<pdfname>.txt   -- what PyPDFLoader produces today
    new_<pdfname>.txt   -- what pdf_extraction.py produces

Open both in VS Code side by side (right-click a tab -> Split Right) and
scroll to any page you know has a table. That's the real test -- eyeball
whether the table went from word-soup to a readable grid.
"""

import sys
import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter

from pdf_extraction import load_pdf_as_documents, chunk_documents

splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=75)


def looks_mangled(text):
    """Rough heuristic: a lot of very short 'words' packed together, with
    NO markdown table structure, tends to mean a table got flattened into
    a run-on line. A real Markdown table (lots of short cell values like
    'Eligible'/'Decline') is excluded on purpose -- that's the fix working,
    not the problem."""
    if "|" in text and "---" in text:
        return False  # already a Markdown table -- that's the goal, not a flag
    words = text.split()
    if len(words) < 8:
        return False
    short = sum(1 for w in words if len(w) <= 3)
    return short / len(words) > 0.5


def run_old(pdf_path):
    loader = PyPDFLoader(pdf_path)
    pages = loader.load()
    chunks = splitter.split_documents(pages)
    return [c for c in chunks if c.page_content.strip() and len(c.page_content.strip()) > 20]


def run_new(pdf_path):
    pages = load_pdf_as_documents(pdf_path)
    chunks = chunk_documents(pages, splitter)
    return [c for c in chunks if c.page_content.strip() and len(c.page_content.strip()) > 20]


def main(pdf_paths):
    for pdf_path in pdf_paths:
        name = os.path.splitext(os.path.basename(pdf_path))[0]
        print(f"\n=== {name} ===")

        old_chunks = run_old(pdf_path)
        new_chunks = run_new(pdf_path)

        old_mangled = sum(1 for c in old_chunks if looks_mangled(c.page_content))
        new_mangled = sum(1 for c in new_chunks if looks_mangled(c.page_content))

        print(f"  OLD (PyPDFLoader):  {len(old_chunks)} chunks, {old_mangled} flagged as possibly mangled")
        print(f"  NEW (pdfplumber):   {len(new_chunks)} chunks, {new_mangled} flagged as possibly mangled")

        old_out = f"old_{name}.txt"
        new_out = f"new_{name}.txt"

        with open(old_out, "w", encoding="utf-8") as f:
            for i, c in enumerate(old_chunks):
                f.write(f"--- chunk {i} (page {c.metadata.get('page', '?')}) ---\n")
                f.write(c.page_content + "\n\n")

        with open(new_out, "w", encoding="utf-8") as f:
            for i, c in enumerate(new_chunks):
                f.write(f"--- chunk {i} (page {c.metadata.get('page', '?')}) ---\n")
                f.write(c.page_content + "\n\n")

        print(f"  Wrote {old_out} and {new_out} -- open both, jump to a page you know has a table.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python compare_extraction.py <pdf1> [pdf2 ...]")
        sys.exit(1)
    main(sys.argv[1:])