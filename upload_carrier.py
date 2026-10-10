import tempfile
import os
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
import gc

from shared_resources import get_embeddings, get_vectorstore, DB_FOLDER
import store_cache
from pdf_extraction import (load_pdf_as_documents, chunk_documents, FLOW_ORDER_FILES, ocr_text_path,
                            load_ocr_text_as_documents)


def detect_lob_from_name(carrier_name):
    name = carrier_name.upper()
    if "DP3" in name or "DP-3" in name:
        return "DP3"
    if "HOA" in name:
        return "HOA"
    if "HOB" in name:
        return "HOB"
    if "HO6" in name or "HO-6" in name:
        return "HO6"
    if "HO3" in name or "HO-3" in name or "HOMEOWNERS" in name:
        return "HO3"
    return "Unknown"


def add_carrier_to_database(pdf_bytes, carrier_name):
    lob = detect_lob_from_name(carrier_name)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        # CHANGED: table-aware extraction (pdfplumber) instead of PyPDFLoader.
        # Underwriting matrices (roof age x roof type, etc.) survive as
        # Markdown tables instead of getting chopped into meaningless
        # fragments. See pdf_extraction.py for details.
        # Round 29 step 5: the overlapping-label guides read in text-flow order, and a
        # scanned guide falls back to its OCR text file (pdf_extraction.load_guide_documents).
        name = carrier_name + ".pdf"
        pages = load_pdf_as_documents(tmp_path, text_flow=name in FLOW_ORDER_FILES)
        if not any(p.page_content.strip() for p in pages) and os.path.exists(ocr_text_path(name)):
            pages = load_ocr_text_as_documents(ocr_text_path(name))
    except Exception as e:
        os.unlink(tmp_path)
        return 0, str(e)

    os.unlink(tmp_path)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=75
    )
    chunks = chunk_documents(pages, splitter)

    chunks = [c for c in chunks if c.page_content.strip() and len(c.page_content.strip()) > 20]
    if not chunks:
        return 0, "No readable text found in this PDF. It may be a scanned document. Please convert it using an OCR tool first (ilovepdf.com/ocr-pdf)."

    for chunk in chunks:
        chunk.metadata["carrier"] = carrier_name
        chunk.metadata["source_file"] = carrier_name + ".pdf"
        chunk.metadata["lob"] = lob
        chunk.metadata["state"] = "TX"

    vectorstore = get_vectorstore()

    batch_size = 50
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        vectorstore.add_documents(batch)
        store_cache.bump()  # round 36 step 1: cached whole-store reads are stale now
        gc.collect()

    return len(chunks), None


def remove_carrier_from_database(carrier_name):
    vectorstore = get_vectorstore()
    collection = vectorstore._collection
    results = collection.get(where={"carrier": carrier_name})
    if results["ids"]:
        collection.delete(ids=results["ids"])
        store_cache.bump()  # round 36 step 1: cached whole-store reads are stale now
        return len(results["ids"])
    return 0


def database_fingerprint(collection=None):
    """What is in the database, as numbers two copies can be compared by:
    carrier count, chunk count, and one sha256 over every chunk's text and
    one over every chunk's metadata.

    Order-independent and id-independent (each list is sorted before
    hashing), so a seed copied into the volume and a store rebuilt from the
    same PDFs give the same values. Shown in the Manage Carriers tab so the
    live database can be checked against the committed seed: the seed was
    rebuilt four times on 08-15, and seed_db.sh only copies into an EMPTY
    volume, so production may hold an older one."""
    # Round 36 step 1: the live store's fingerprint is computed once per store version (the Manage tab
    # computed it on every rerun, i.e. on every click anywhere in the app); an explicit collection is read
    if collection is None:
        return dict(store_cache.derived("fingerprint", get_vectorstore()._collection, _fingerprint, documents=True))
    return _fingerprint(collection.get(include=["documents", "metadatas"]))


def _fingerprint(raw):
    import hashlib
    import json
    docs = raw["documents"]
    metas = raw["metadatas"]

    def digest(items):
        return hashlib.sha256("\n".join(sorted(items)).encode("utf-8")).hexdigest()

    return {
        "carriers": len({m.get("carrier") for m in metas if m.get("carrier")}),
        "chunks": len(docs),
        "documents_sha256": digest(json.dumps(d, ensure_ascii=False) for d in docs),
        "metadata_sha256": digest(json.dumps(m, sort_keys=True, ensure_ascii=False) for m in metas),
    }


def list_carriers_in_database():
    # Round 36 step 1: one cached read per store version (store_cache)
    return sorted(store_cache.carriers(get_vectorstore()._collection))