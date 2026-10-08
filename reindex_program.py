"""Re-ingest ONE program into the store, leaving every other program's chunks
untouched (round 29 step 5, 2026-10-08). The same extraction and chunking as
load_docs.py (pdf_extraction.load_guide_documents: text-flow order for the
overlapping-label guides, the OCR text file for a scanned guide), the same
metadata, the same embeddings.

usage: python reindex_program.py <db folder> <pdf file name> [<pdf file name> ...]
       e.g. python reindex_program.py ./carrier_docs_db Centauri_-_DP3_-_11.16.2022.pdf
Then copy the store to carrier_docs_db_seed/ to re-seed."""
import os
import sys

from dotenv import load_dotenv
load_dotenv()

from langchain_community.embeddings import FastEmbedEmbeddings  # noqa: E402
from langchain_community.vectorstores import Chroma  # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402

from load_docs import PDF_FOLDER, detect_lob  # noqa: E402
from pdf_extraction import chunk_documents, load_guide_documents  # noqa: E402


def reindex(db_folder, pdf_file):
    program = os.path.splitext(pdf_file)[0]
    store = Chroma(persist_directory=db_folder,
                   embedding_function=FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5"))
    before = store._collection.get(where={"carrier": program}, include=[])["ids"]
    pages, source = load_guide_documents(os.path.join(PDF_FOLDER, pdf_file))
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=75)
    chunks = [c for c in chunk_documents(pages, splitter) if len(c.page_content.strip()) > 20]
    for c in chunks:
        c.metadata.update(carrier=program, source_file=pdf_file, lob=detect_lob(pdf_file), state="TX")
        c.metadata.setdefault("is_table", False)
    if before:
        store._collection.delete(ids=before)
    if chunks:
        store.add_documents(chunks)
    print(f"{program}: {len(before)} chunks -> {len(chunks)} (from {source})")
    return len(before), len(chunks)


if __name__ == "__main__":
    for name in sys.argv[2:]:
        reindex(sys.argv[1], name)
