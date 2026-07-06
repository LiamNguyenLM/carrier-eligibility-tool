from dotenv import load_dotenv
load_dotenv()

from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
import os

PDF_FOLDER = "Carrier_Eligibility_PDFs"
DB_FOLDER = "./carrier_docs_db"

def detect_lob(filename):
    name = filename.upper()
    if "DP3" in name or "DP-3" in name:
        return "DP3"
    if "HOA" in name:
        return "HOA"
    if "HOB" in name:
        return "HOB"
    if "HO3" in name or "HO-3" in name or "HOMEOWNERS" in name:
        return "HO3"
    return "Unknown"

print("Looking for PDFs...")
pdf_files = [f for f in os.listdir(PDF_FOLDER) if f.lower().endswith(".pdf")]
print("Found " + str(len(pdf_files)) + " PDFs")

all_chunks = []

splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=150
)

for pdf_file in pdf_files:
    print("Processing: " + pdf_file)

    try:
        loader = PyPDFLoader(os.path.join(PDF_FOLDER, pdf_file))
        pages = loader.load()
        print("  Loaded " + str(len(pages)) + " pages")
    except Exception as e:
        print("  ERROR loading " + pdf_file + ": " + str(e))
        continue

    chunks = splitter.split_documents(pages)
    print("  Created " + str(len(chunks)) + " chunks")

    carrier_name = pdf_file.replace(".pdf", "").replace(".PDF", "")
    lob = detect_lob(pdf_file)

    for chunk in chunks:
        chunk.metadata["carrier"] = carrier_name
        chunk.metadata["source_file"] = pdf_file
        chunk.metadata["lob"] = lob
        chunk.metadata["state"] = "TX"

    all_chunks.extend(chunks)

print("Total chunks: " + str(len(all_chunks)))
print("Building database...")

embeddings = OpenAIEmbeddings()
vectorstore = Chroma.from_documents(
    documents=all_chunks,
    embedding=embeddings,
    persist_directory=DB_FOLDER
)

print("Done. Database saved to " + DB_FOLDER)
