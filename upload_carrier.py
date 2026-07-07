import tempfile
import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

DB_FOLDER = "./carrier_docs_db"

def add_carrier_to_database(pdf_bytes, carrier_name, lob):
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

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


def list_carriers_in_database():
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
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
