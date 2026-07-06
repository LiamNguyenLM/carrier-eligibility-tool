from dotenv import load_dotenv
load_dotenv()

from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
import os

# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------
# The folder where your carrier PDFs live
PDF_FOLDER = "Carrier_Eligibility_PDFs"

# Where the searchable database will be saved
DB_FOLDER = "./carrier_docs_db"


# ------------------------------------------------------------
# HELPER: figure out the line of business from the filename
# ------------------------------------------------------------
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


# ------------------------------------------------------------
# STEP 1: Find all PDFs in the folder
# ------------------------------------------------------------
print("Looking for PDFs...")
pdf_files = [f for f in os.listdir(PDF_FOLDER) if f.lower().endswith(".pdf")]
print(f"Found {len(pdf_files)} PDFs")

all_chunks = []

# ------------------------------------------------------------
# STEP 2: Load and chunk each PDF
# ------------------------------------------------------------
splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=150
)

for pdf_file in pdf_files:
    print(f"\nProcessing: {pdf_file}")

    try:
        loader = PyPDFLoader(os.path.join(PDF_FOLDER, pdf_file))
        pages = loader.load()
        print(f"  Loaded {len(pages)} pages")
    except Exception as e:
        print(f"  ERROR loading {pdf_file}: {e}")
        continue

    chunks = splitter.split_documents(pages)
    print(f"  Created {len(chunks)} chunks")

    # Tag every chunk with useful metadata
    carrier_name = pdf_file.replace(".pdf", "").replace(".PDF", "")
    lob = detect_lob(pdf_file)

    for chunk in chunks:
        chunk.metadata["carrier"] = carrier_name
        chunk.metadata["source_file"] = pdf_file
        chunk.metadata["lob"] = lob
        chunk.metadata["state"] = "TX"

    all_chunks.extend(chunks)

print(f"\nTotal chunks across all PDFs: {len(all_chunks)}")

# ------------------------------------------------------------
# STEP 3: Create embeddings and store in ChromaDB
# ------------------------------------------------------------
print("\nCreating embeddings and building the database...")
print("This may take a couple minutes depending on how many PDFs...")

embeddings = OpenAIEmbeddings()
vectorstore = Chroma.from_documents(
    documents=all_chunks,
    embedding=embeddings,
    persist_directory=DB_FOLDER
)

print("\n✅ Database built successfully")
print(f"✅ {len(all_chunks)} chunks stored and ready to search")
dy to search")
