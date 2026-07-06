from dotenv import load_dotenv
load_dotenv()

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

print("Loading database...")
embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vectorstore = Chroma(
    persist_directory="./carrier_docs_db",
    embedding_function=embeddings
)

retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

print("Running test searches...\n")

test_queries = [
    "coastal property eligibility requirements",
    "roof age maximum limit",
    "swimming pool coverage",
    "year built minimum requirement",
    "construction type frame masonry"
]

for query in test_queries:
    print(f"Query: {query}")
    results = retriever.invoke(query)
    print(f"Found {len(results)} chunks")
    for i, chunk in enumerate(results):
        print(f"  Result {i+1}: {chunk.metadata.get('carrier')} - page {chunk.metadata.get('page')}")
        print(f"  Preview: {chunk.page_content[:150]}")
    print()
