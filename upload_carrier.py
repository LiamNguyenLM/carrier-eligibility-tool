import tempfile
import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import FastEmbedEmbeddings
from langchain_community.vectorstores import Chroma

DB_FOLDER = "./carrier_docs_db"


def get_embeddings():
    return FastEmbedEmbeddings(model_name="BAAI/bge-small-en-v1.5")


def detect_lob_from_name(carrier_name):
    name = carrier_name.upper()
    if "DP3" in name or "DP-3" in name:
        return "DP3"
    if "HOA" in name:
        return "HOA"
    if "HOB" in name:
        return "HOB"
    if "HO3" in name or "HO-3" in name or "HOMEOWNERS" in name:
        return "HO3"
    return "Unknown"


def add_carrier_to_database(pdf_bytes, carrier_name):
    embeddings = get_embeddings()
    lob = detect_lob_from_name(carrier_name)

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        loader = PyPDFLoader(tmp_path)
        pages = loader.load()
    except Exception as e:
        os.unlink(tmp_path)
        return 0, str(e)

    os.unlink(tmp_path)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=75
    )
    chunks = splitter.split_documents(pages)

    for chunk in chunks:
        chunk.metadata["carrier"] = carrier_name
        chunk.metadata["source_file"] = carrier_name + ".pdf"
        chunk.metadata["lob"] = lob
        chunk.metadata["state"] = "TX"

    vectorstore = Chroma(
        persist_directory=DB_FOLDER,
        embedding_function=embeddings
    )
    vectorstore.add_documents(chunks)

    return len(chunks), None


def remove_carrier_from_database(carrier_name):
    embeddings = get_embeddings()
    vectorstore = Chroma(
        persist_directory=DB_FOLDER,
        embedding_function=embeddings
    )
    collection = vectorstore._collection
    results = collection.get(where={"carrier": carrier_name})
    if results["ids"]:
        collection.delete(ids=results["ids"])
        return len(results["ids"])
    return 0


def list_carriers_in_database():
    embeddings = get_embeddings()
    vectorstore = Chroma(
        persist_directory=DB_FOLDER,
        embedding_function=embeddings
    )
    collection = vectorstore._collection
    results = collection.get(include=["metadatas"])
    carriers = set()
    for metadata in results["metadatas"]:
        if "carrier" in metadata:
            carriers.add(metadata["carrier"])
    return sorted(list(carriers))
