from dotenv import load_dotenv
load_dotenv()

from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
import anthropic
import json
import os
import streamlit as st

try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

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

    if property_details['occupancy_type'] not in ['Owner Occupied']:
        risk_factors.append("tenant occupied rental dwelling occupancy requirements")
        risk_factors.append("DP3 dwelling policy tenant rental occupancy eligibility")
        risk_factors.append("HO3 owner occupancy requirement restriction")

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

    occupancy = property_details['occupancy_type']

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
Occupancy Type: {occupancy}
Coastal Tier: {property_details['coastal_tier']}
Swimming Pool: {property_details['swimming_pool']}
Pool Accessories: {property_details['pool_accessories']}
Dogs on Premises: {property_details['has_dogs']}
Aggressive Breed Dogs: {property_details['aggressive_breed']}
Solar Panels: {property_details['solar_panels']}
PPC Number: {property_details['ppc']}

POLICY TYPE AND OCCUPANCY CONTEXT:
- HO3 (Homeowners 3): Designed for owner-occupied properties. Not appropriate for tenant-occupied or rental properties. If occupancy is not owner-occupied, HO3 policies should be marked INELIGIBLE for occupancy reason.
- DP3 (Dwelling Fire 3): Designed for non-owner-occupied properties including rentals and tenant-occupied dwellings. If occupancy is Tenant Occupied, DP3 policies should be evaluated normally and not excluded.
- HOA / HOB: Condominium and unit-owner programs.
- Current occupancy is: {occupancy}
- If Owner Occupied: Do NOT include DP3 carriers in your response at all. Exclude them entirely.
- If Tenant Occupied or any non-owner occupancy: Do NOT include HO3 or HOMEOWNERS carriers in your response at all. Exclude them entirely. Only evaluate DP3, HOA, and HOB programs.

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
    "notes": "any important coverage distinctions such as RCV vs ACV",
    "flaw_count": 0
  }}
]

Status must be exactly one of: ELIGIBLE, INELIGIBLE, REFER, INSUFFICIENT_INFORMATION
flaw_count rules:
- ELIGIBLE: always 0
- INELIGIBLE: count the number of distinct ineligibility factors found
- REFER: always 0
- INSUFFICIENT_INFORMATION: always 0

Output guidelines:
- Provide 2 to 4 analysis points in reasons covering key property characteristics
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

    if "```" in raw:
        raw = raw.replace("```json", "").replace("```", "").strip()

    start = raw.find('[')
    end = raw.rfind(']') + 1
    if start != -1 and end > start:
        json_str = raw[start:end]
    else:
        json_str = raw

    try:
        parsed = json.loads(json_str)

        occupancy = property_details.get('occupancy_type', 'Owner Occupied')
        filtered = []
        for r in parsed:
            name = r.get("carrier", "").upper()
            is_ho3 = "HO3" in name or "HOMEOWNERS" in name
            is_dp3 = "DP3" in name or "DP-3" in name
            if occupancy != "Owner Occupied" and is_ho3:
                continue
            if occupancy == "Owner Occupied" and is_dp3:
                continue
            filtered.append(r)

        return filtered

    except json.JSONDecodeError as e:

        print("JSON PARSE ERROR:", str(e))
        print("RAW RESPONSE:", raw[:1000])
        return [{
            "carrier": "Parse Error",
            "status": "INSUFFICIENT_INFORMATION",
            "reasons": [
                "Claude returned an unexpected format. Please try again.",
                "Raw preview: " + raw[:200]
            ],
            "citations": [],
            "missing_info": ["Try submitting again"],
            "notes": "",
            "flaw_count": 0
        }]


if __name__ == "__main__":
    test_property = {
        "year_built": 2000,
        "roof_age": 10,
        "roof_type": "Composition Shingle",
        "roof_shape": "Gable",
        "construction_type": "Frame",
        "plumbing_type": "Copper",
        "occupancy_type": "Tenant Occupied",
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
        print(r["carrier"], "-", r["status"], "- flaws:", r.get("flaw_count", 0))
