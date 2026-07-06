from dotenv import load_dotenv
load_dotenv()

from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
import anthropic

# Load database
embeddings = OpenAIEmbeddings()
vectorstore = Chroma(
    persist_directory="./carrier_docs_db",
    embedding_function=embeddings
)
retriever = vectorstore.as_retriever(search_kwargs={"k": 8})

# Claude client
client = anthropic.Anthropic()

def check_eligibility(property_details):
    # Build search query from property details
    query = f"""
    homeowners insurance eligibility requirements:
    state {property_details['state']}
    year built {property_details['year_built']}
    roof age {property_details['roof_age']} years
    roof type {property_details['roof_type']}
    roof shape {property_details['roof_shape']}
    construction type {property_details['construction_type']}
    plumbing type {property_details['plumbing_type']}
    occupancy {property_details['occupancy_type']}
    coastal property {property_details['coastal']}
    swimming pool {property_details['swimming_pool']}
    solar panels {property_details['solar_panels']}
    PPC {property_details['ppc']}
    """


    # Retrieve relevant chunks
    chunks = retriever.invoke(query)
    
    # Build context from chunks
    context = ""
    for chunk in chunks:
        context += f"\n--- {chunk.metadata.get('carrier')} ---\n"
        context += chunk.page_content
        context += "\n"

    # Build prompt
    prompt = f"""
You are an insurance underwriting assistant for an independent insurance agency.

Using ONLY the carrier documents provided below, analyze this property's eligibility 
for each carrier. Do not make assumptions or invent rules not in the documents.

PROPERTY DETAILS:
State: {property_details['state']}
Year Built: {property_details['year_built']}
Roof Age: {property_details['roof_age']} years
Roof Type: {property_details['roof_type']}
Roof Shape: {property_details['roof_shape']}
Construction Type: {property_details['construction_type']}
Plumbing Type: {property_details['plumbing_type']}
Occupancy Type: {property_details['occupancy_type']}
Coastal Property: {property_details['coastal']}
Swimming Pool: {property_details['swimming_pool']}
Solar Panels: {property_details['solar_panels']}
PPC Number: {property_details['ppc']}

CARRIER DOCUMENTS:
{context}

For each carrier in the documents above, provide:
1. ELIGIBLE or INELIGIBLE or REFER (needs underwriter review)
2. Specific reasons based on the documents
3. Exact citation (carrier name and relevant rule)
4. Any missing information needed to make a final determination

If a carrier's guidelines do not address a specific property characteristic, 
note it as "not specified in guidelines."

Format your response clearly with each carrier as a separate section.
"""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


# Test it with a sample property
if __name__ == "__main__":
    test_property = {
        "state": "TX",
        "year_built": 1998,
        "roof_age": 12,
        "roof_type": "Composition Shingle",
        "roof_shape": "Gable",
        "construction_type": "Frame",
        "plumbing_type": "Copper",
        "occupancy_type": "Owner Occupied",
        "coastal": "No",
        "swimming_pool": "No Pool",
        "solar_panels": "No",
        "ppc": "3"
    }

    print("Running eligibility check...\n")
    result = check_eligibility(test_property)
    print(result)
