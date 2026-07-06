from dotenv import load_dotenv
load_dotenv()

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
import anthropic
import json

embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vectorstore = Chroma(
    persist_directory="./carrier_docs_db",
    embedding_function=embeddings
)
retriever = vectorstore.as_retriever(search_kwargs={"k": 15})
client = anthropic.Anthropic()

def check_eligibility(property_details):

    query = f"""
    homeowners insurance eligibility requirements:
    state TX
    year built {property_details['year_built']}
    roof age {property_details['roof_age']} years
    roof type {property_details['roof_type']}
    roof shape {property_details['roof_shape']}
    construction type {property_details['construction_type']}
    plumbing type {property_details['plumbing_type']}
    occupancy {property_details['occupancy_type']}
    coastal {property_details['coastal_tier']}
    swimming pool {property_details['swimming_pool']}
    pool accessories {property_details['pool_accessories']}
    dogs on premises {property_details['has_dogs']}
    aggressive breed dogs {property_details['aggressive_breed']}
    solar panels {property_details['solar_panels']}
    PPC {property_details['ppc']}
    """

    chunks = retriever.invoke(query)

    risk_factors = []
    if property_details['plumbing_type'] in ['Galvanized', 'Polybutylene']:
        risk_factors.append("galvanized polybutylene plumbing ineligible requirements")
    if 'Unfenced' in property_details['swimming_pool']:
        risk_factors.append("swimming pool fence requirement ineligible unfenced")
    if property_details['pool_accessories'] != 'None':
        risk_factors.append("diving board slide pool liability ineligible")
    if property_details['coastal_tier'] in ['Tier 1', 'Tier 2']:
        risk_factors.append("coastal tier wind coverage restrictions ineligible")
    if property_details['aggressive_breed'] == 'Yes':
        risk_factors.append("aggressive dog breed ineligible prohibited liability")

    if risk_factors:
        risk_chunks = retriever.invoke(" ".join(risk_factors))
        seen = set()
        combined = []
        for chunk in chunks + risk_chunks:
            if chunk.page_content not in seen:
                seen.add(chunk.page_content)
                combined.append(chunk)
        chunks = combined

    context = ""
    for chunk in chunks:
        context += f"\n--- {chunk.metadata.get('carrier', 'Unknown')} (page {chunk.metadata.get('page', '?')}) ---\n"
        context += chunk.page_content + "\n"

    prompt = f"""You are an insurance underwriting assistant for an independent Texas agency.

Using ONLY the carrier documents provided below, analyze this property for each carrier.

PROPERTY DETAILS:
State: TX
Year Built: {property_details['year_built']}
Roof Age: {property_details['roof_age']} years
Roof Type: {property_details['roof_type']}
Roof Shape: {property_details['roof_shape']}
Construction Type: {property_details['construction_type']}
Plumbing Type: {property_details['plumbing_type']}
Occupancy Type: {property_details['occupancy_type']}
Coastal Tier: {property_details['coastal_tier']}
Swimming Pool: {property_details['swimming_pool']}
Pool Accessories: {property_details['pool_accessories']}
Dogs on Premises: {property_details['has_dogs']}
Aggressive Breed Dogs: {property_details['aggressive_breed']}
Solar Panels: {property_details['solar_panels']}
PPC Number: {property_details['ppc']}

CARRIER DOCUMENTS:
{context}

Return ONLY a JSON array with no text before or after it.
Each object must follow this exact structure:

[
  {{
    "carrier": "carrier name from document",
    "status": "ELIGIBLE",
    "reasons": ["reason 1", "reason 2"],
    "citations": ["carrier name: exact short quote from document"],
    "missing_info": ["item needed for final determination"],
    "notes": "any important coverage distinctions such as RCV vs ACV"
  }}
]

Status must be exactly one of: ELIGIBLE, INELIGIBLE, REFER, INSUFFICIENT_INFORMATION
- ELIGIBLE: property meets all guidelines found in documents
- INELIGIBLE: property fails one or more clear guidelines
- REFER: eligible but needs underwriter review before binding
- INSUFFICIENT_INFORMATION: relevant guidelines not present in provided documents

Output guidelines:
- Provide 2 to 4 analysis points in reasons covering the key property characteristics
- Include 1 to 2 citations with enough context to identify where the rule appears
- List all missing information needed to make a final determination
- Use the notes field for important coverage distinctions like replacement cost vs ACV
- Do not invent rules not found in the documents
- Only include carriers that appear in the provided documents
- Return ONLY the JSON array, no other text
"""

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}]
    )

    raw = response.content[0].text.strip()

    # Remove markdown code blocks if Claude wrapped the JSON
    if "```" in raw:
        raw = raw.replace("```json", "").replace("```", "").strip()

    # Find JSON array boundaries
    start = raw.find('[')
    end = raw.rfind(']') + 1

    if start != -1 and end > start:
        json_str = raw[start:end]
    else:
        json_str = raw

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print("JSON PARSE ERROR:", str(e))
        print("RAW RESPONSE:", raw[:1000])
        return [{
            "carrier": "Parse Error",
            "status": "INSUFFICIENT_INFORMATION",
            "reasons": [
                "Claude returned an unexpected format. Check the terminal for details.",
                "Raw response preview: " + raw[:300]
            ],
            "citations": [],
            "missing_info": ["Try submitting again — this is usually a one-time occurrence"],
            "notes": ""
        }]



if __name__ == "__main__":
    test_property = {
        "year_built": 1998,
        "roof_age": 12,
        "roof_type": "Composition Shingle",
        "roof_shape": "Gable",
        "construction_type": "Frame",
        "plumbing_type": "Copper",
        "occupancy_type": "Owner Occupied",
        "coastal_tier": "Not Coastal",
        "swimming_pool": "No Pool",
        "pool_accessories": "None",
        "has_dogs": "No",
        "aggressive_breed": "No",
        "solar_panels": "No",
        "ppc": "3"
    }
    results = check_eligibility(test_property)
    for r in results:
        print(r["carrier"], "-", r["status"])
