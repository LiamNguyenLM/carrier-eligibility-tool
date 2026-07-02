from dotenv import load_dotenv
load_dotenv()

from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
import os

print("Loading carrier PDFs...")

pdf_files = [f for f in os.listdir("carrier_docs") if f.endswith(".pdf")]
print(f"Found {len(pdf_files)} PDFs: {pdf_files}")

all_chunks = []

for pdf_file in pdf_files:
    print(f"\nProcessing: {pdf_file}")
    
    loader = PyPDFLoader(f"carrier_docs/{pdf_file}")
    pages = loader.load()
    print(f"  Loaded {len(pages)} pages")
    
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50
    )
    chunks = splitter.split_documents(pages)
    print(f"  Created {len(chunks)} chunks")
    
    carrier_name = pdf_file.replace(".pdf", "")
    for chunk in chunks:
        chunk.metadata["carrier"] = carrier_name
        chunk.metadata["source_file"] = pdf_file
    
    all_chunks.extend(chunks)

print(f"\nTotal chunks: {len(all_chunks)}")
print("Storing in ChromaDB...")

embeddings = OpenAIEmbeddings()
vectorstore = Chroma.from_documents(
    documents=all_chunks,
    embedding=embeddings,
    persist_directory="./carrier_docs_db"
)

print("✅ Database built successfully")
print(f"✅ {len(all_chunks)} chunks stored and ready to search")
