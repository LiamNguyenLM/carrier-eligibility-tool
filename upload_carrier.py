import tempfile
import os
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
import gc

from shared_resources import get_embeddings, get_vectorstore, DB_FOLDER
from pdf_extraction import load_pdf_as_documents, chunk_documents


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
        pages = load_pdf_as_documents(tmp_path)
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
        gc.collect()

    return len(chunks), None


def remove_carrier_from_database(carrier_name):
    vectorstore = get_vectorstore()
    collection = vectorstore._collection
    results = collection.get(where={"carrier": carrier_name})
    if results["ids"]:
        collection.delete(ids=results["ids"])
        return len(results["ids"])
    return 0


def list_carriers_in_database():
    vectorstore = get_vectorstore()
    collection = vectorstore._collection
    results = collection.get(include=["metadatas"])
    carriers = set()
    for metadata in results["metadatas"]:
        if "carrier" in metadata:
            carriers.add(metadata["carrier"])
    return sorted(list(carriers))