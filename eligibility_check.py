from dotenv import load_dotenv
load_dotenv()

from langchain_community.vectorstores import Chroma
import anthropic
import difflib
import json
import os
import re
from datetime import date
import streamlit as st

try:
    from langchain_core.documents import Document
except ImportError:
    from langchain.schema import Document

try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:
    pass

from shared_resources import get_embeddings, get_vectorstore


@st.cache_resource
def load_retriever():
    return get_vectorstore().as_retriever(search_kwargs={"k": 10})


retriever = load_retriever()
client = anthropic.Anthropic()


# CHANGED: split out into a module-level constant so the exact same bytes
# are sent as the `system` block on every call -- required for prompt
# caching to actually hit. Anything that varies per property (occupancy,
# ownership, the retrieved carrier excerpts) stays OUT of this block and
# goes in the per-call user message instead, further down.
#
# NOTE: Anthropic enforces a minimum token count before a cached block is
# actually eligible for caching (it's been 1024 tokens for Sonnet-class
# models, higher for Haiku, as of last time I checked -- verify current
# minimums at https://docs.claude.com/en/docs/build-with-claude/prompt-caching
# since this may have changed). This block runs a bit under that on its own.
# If cache_read_input_tokens stays at 0 in testing (see the print statement
# below), the block is too short to cache -- that's an easy thing to verify
# once you're running real queries, not a reason to hold off shipping this.
SYSTEM_INSTRUCTIONS = """You are an insurance underwriting assistant for an independent Texas agency.

Using ONLY the carrier documents provided in the user message, analyze the property for each carrier.

POLICY TYPE AND OCCUPANCY CONTEXT:
- HO3 (Homeowners 3): Designed for owner-occupied properties. Not appropriate for tenant-occupied or rental properties. If occupancy is not owner-occupied, HO3 policies should be marked INELIGIBLE for occupancy reason.
- DP3 (Dwelling Fire 3): Designed for non-owner-occupied properties including rentals and tenant-occupied dwellings. If occupancy is Tenant Occupied, DP3 policies should be evaluated normally and not excluded.
- HOA / HOB / HO6: Condominium and unit-owner programs. HO6 is specifically for condo unit owners.
- If the property's Occupancy Type (given in PROPERTY DETAILS below) is Owner Occupied: Do NOT include DP3 carriers in your response at all. Exclude them entirely.
- If the property's Occupancy Type is Tenant Occupied or any non-owner occupancy: Do NOT include HO3 or HOMEOWNERS carriers in your response at all. Exclude them entirely. Only evaluate DP3, HOA, HOB, and HO6 programs.
- If Ownership Structure is LLC: Most HO3 carriers do not accept LLC or business-owned properties. Flag as INELIGIBLE if carrier guidelines prohibit business ownership.
- If Ownership Structure is Trust: Some carriers allow trust-owned properties if the grantor lives in the dwelling and is the named insured. The trust itself cannot be listed as named insured. Check guidelines carefully and flag any trust-specific requirements.
- If Ownership Structure is Individual Owner: No additional restrictions from ownership structure.

Use the Home Age value given in PROPERTY DETAILS as-is. It has already been computed from the current date -- do not re-derive it from Year Built yourself.

If the user message includes a "CARRIERS WITH NO RETRIEVED INFORMATION" section, you MUST include every carrier listed there in your response with status INSUFFICIENT_INFORMATION, even though no excerpt for them appears in CARRIER DOCUMENTS.

Do not decline a carrier over a fact that ISN'T given in PROPERTY DETAILS (e.g. county, driving distance to the nearest fire station, wildfire risk score) and isn't otherwise computable from what IS given. A fact simply not being provided is not the same as the property failing that fact's requirement -- treat it as missing_info, not as grounds for INELIGIBLE, unless the carrier's own rule is unconditional regardless of that fact. Protection Class / PPC is given in PROPERTY DETAILS: if a carrier's documents key eligibility off Protection Class (directly, or via Fire Protection Class + distance to a fire station), you MUST check the carrier's Protection Class rule against the given PPC value and reason about it explicitly -- do not silently omit it just because the exact driving-distance figure isn't given.

Return ONLY a JSON array with no text before or after it.
Each object must follow this exact structure:

[
  {
    "carrier": "carrier name from document",
    "status": "ELIGIBLE",
    "reasons": ["reason 1", "reason 2"],
    "citations": ["carrier name: exact short quote from document"],
    "missing_info": ["item needed for final determination"],
    "notes": "any important coverage distinctions such as RCV vs ACV",
    "flaw_count": 0
  }
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
- You MUST include every single carrier that appears in the provided documents. Never skip or omit a carrier. If you cannot determine eligibility for a carrier from the provided excerpts, use status INSUFFICIENT_INFORMATION. All carriers in the context above must appear in your response.
- Return ONLY the JSON array, no other text
"""


def _is_header_only_table(page_content):
    """True if page_content is a Markdown table with a header + separator
    row and NO data rows -- e.g. a repeated page-header banner ("| Texas
    Homeowners | Eligibility Rules |") that pdfplumber's line-based table
    detector mistakes for a real 1-row table. These carry zero eligibility
    information, but their literal text (carrier name, "Homeowners",
    "Eligibility") echoes the retrieval query closely enough to outrank
    every real content chunk for that carrier -- diagnosed via
    verification/diagnose_carrier.py against Allied Trust HO3, where 12
    byte-identical copies of one such banner were the ONLY chunks the
    carrier ever contributed to the prompt."""
    lines = [l for l in page_content.strip().split("\n") if l.strip()]
    if len(lines) != 2:
        return False
    header, separator = lines
    sep = separator.strip()
    if not header.strip().startswith("|") or not sep.startswith("|"):
        return False
    return all(ch in "|-: " for ch in sep)


def is_eligibility_content(chunk):
    content = chunk.page_content.lower()
    if "accredited builder" in content and "burglary prevention" in content:
        return False
    if "additional amount of insurance" in content and "lock replacement" in content:
        return False
    if "paved driveway at least 12 feet" in content and "firefighting apparatus" in content:
        return False
    if _is_header_only_table(chunk.page_content):
        return False
    return True


def get_all_carriers():
    vectorstore = get_vectorstore()
    collection = vectorstore._collection
    results = collection.get(include=["metadatas"])
    all_carriers = set()
    for m in results["metadatas"]:
        if "carrier" in m:
            all_carriers.add(m["carrier"])
    return all_carriers


def get_combined_program_carriers():
    """Carriers whose filename bundles more than one program, e.g.
    Foremost_DP3_and_HO3_-_07.01.2026.pdf. These must never be excluded
    by the DP3/HO3 occupancy heuristic -- they're valid for both."""
    combined = set()
    for carrier in get_all_carriers():
        upper = carrier.upper()
        is_ho3 = "HO3" in upper or "HOMEOWNERS" in upper
        is_dp3 = "DP3" in upper or "DP-3" in upper
        if is_ho3 and is_dp3:
            combined.add(carrier)
    return combined


def _mentions_protection_class(content):
    """Matches both naming conventions carriers use for this concept: ISO's
    "(Public) Protection Class" / "PPC", and the SageSure family's own
    "Fire Protection Class" / "FPC" -- confirmed on Sage Auros HO3, where
    the actual "FPC 9 or greater ... Risk is ineligible" rule never spells
    out "protection class" at all, so a filter checking only for that
    phrase (or "PPC") missed it entirely even though it's the exact rule
    this lookup exists to guarantee."""
    lower = content.lower()
    return (
        "protection class" in lower
        or re.search(r"\bppc\b", lower) is not None
        or re.search(r"\bfpc\b", lower) is not None
    )


def get_carriers_for_occupancy(occupancy):
    combined = get_combined_program_carriers()

    relevant = []
    for carrier in sorted(get_all_carriers()):
        if carrier in combined:
            relevant.append(carrier)
            continue
        upper = carrier.upper()
        is_ho3 = "HO3" in upper or "HOMEOWNERS" in upper or "HO6" in upper
        is_dp3 = "DP3" in upper or "DP-3" in upper
        if occupancy == "Owner Occupied" and is_dp3:
            continue
        if occupancy != "Owner Occupied" and is_ho3:
            continue
        relevant.append(carrier)
    return relevant


def build_retrieval_query(property_details, home_age):
    """The similarity-search query used for the per-carrier retrieval pass
    in check_eligibility(). Factored out so verification/diagnose_carrier.py
    can run the identical query against a single carrier -- duplicating
    this inline would drift out of sync with the real prompt over time."""
    occupancy = property_details['occupancy_type']
    return f"""
    homeowners insurance eligibility requirements:
    state TX
    year built {property_details['year_built']}
    home age {home_age} years
    roof age {property_details['roof_age']} years
    roof type {property_details['roof_type']}
    roof shape {property_details['roof_shape']}
    construction type {property_details['construction_type']}
    plumbing type {property_details['plumbing_type']}
    occupancy {occupancy}
    ownership {property_details.get('ownership_type', 'Individual Owner')}
    coastal {property_details['coastal_tier']}
    swimming pool {property_details['swimming_pool']}
    pool accessories {property_details['pool_accessories']}
    dogs on premises {property_details['has_dogs']}
    aggressive breed dogs {property_details['aggressive_breed']}
    solar panels {property_details['solar_panels']}
    protection class PPC {property_details['ppc']}
    """


# CHANGED: over-fetch past is_eligibility_content filtering. Filtering used
# to run AFTER a k=3 search, so if the top 3 raw hits for a carrier were all
# junk (e.g. duplicate page-header banners), the carrier got zero real
# content with no fallback -- diagnosed against Allied Trust HO3 via
# verification/diagnose_carrier.py, which had 12 byte-identical banner
# chunks outranking all 582 real content chunks for every query. Fetching
# wider and keeping only the first PER_CARRIER_KEEP survivors preserves the
# original per-carrier chunk budget while giving filtering room to work.
PER_CARRIER_FETCH_K = 15
PER_CARRIER_KEEP = 3


def check_eligibility(property_details):
    occupancy = property_details['occupancy_type']

    # CHANGED: home age computed here instead of leaving the model to infer
    # the current year -- it was previously off by one year when the model
    # assumed the wrong current year.
    home_age = date.today().year - property_details['year_built']

    query = build_retrieval_query(property_details, home_age)

    relevant_carriers = get_carriers_for_occupancy(occupancy)
    vectorstore = get_vectorstore()

    seen = set()
    chunks = []

    for carrier in relevant_carriers:
        try:
            car_chunks = vectorstore.similarity_search(
                query, k=PER_CARRIER_FETCH_K, filter={"carrier": carrier}
            )
            car_chunks = [c for c in car_chunks if is_eligibility_content(c)][:PER_CARRIER_KEEP]
            for chunk in car_chunks:
                # CHANGED: dedup key includes carrier, not just content. Two
                # different carriers can legitimately share identical
                # underlying document text (e.g. Liberty Mutual HO6 and HO3
                # turned out to be byte-identical PDFs) -- deduping on
                # content alone silently zeroed out every chunk for
                # whichever carrier sorted second, which then tripped the
                # zero-chunk safety net into falsely reporting "no
                # documents retrieved" for a carrier that had real, matching
                # content all along.
                key = (carrier, chunk.page_content)
                if key not in seen:
                    seen.add(key)
                    chunks.append(chunk)
        except Exception:
            continue

    # CHANGED: guaranteed per-carrier Protection Class / PPC lookup, by exact
    # keyword rather than embedding similarity. PPC is flagged across three
    # audit rounds as the single most consequential fact in this profile,
    # but its embedding rank is unreliable -- carriers often bury their PPC
    # rule as one bullet in a list of a dozen unrelated ineligibility
    # criteria, diluting the chunk's embedding enough that neither the main
    # query above nor a PPC-specific similarity search reliably surfaces it
    # in the top few results (confirmed on Swyfft Lloyd's Surplus HO3: the
    # carrier's own "ISO Protection Class 9 or 10" decline ranked #7 under
    # the main query and still only #4 under a dedicated PPC query, in a
    # 19-chunk document). An exact keyword scan across each carrier's full
    # raw chunk set sidesteps that entirely.
    MAX_PPC_CHUNKS_PER_CARRIER = 2
    if property_details['ppc'] != 'N/A':
        collection = vectorstore._collection
        ppc_value = str(property_details['ppc'])
        for carrier in relevant_carriers:
            try:
                raw = collection.get(where={"carrier": carrier}, include=["documents", "metadatas"])
            except Exception:
                continue
            candidates = [
                Document(page_content=doc, metadata=meta)
                for doc, meta in zip(raw["documents"], raw["metadatas"])
                if _mentions_protection_class(doc)
            ]
            candidates = [c for c in candidates if is_eligibility_content(c)]
            # prefer chunks that name this exact PPC value over generic ones
            candidates.sort(key=lambda c: ppc_value not in c.page_content)
            for chunk in candidates[:MAX_PPC_CHUNKS_PER_CARRIER]:
                key = (carrier, chunk.page_content)
                if key not in seen:
                    seen.add(key)
                    chunks.append(chunk)

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

    if property_details.get('ownership_type') == 'LLC':
        risk_factors.append("LLC business corporation owned property ineligible not eligible")

    if property_details.get('ownership_type') == 'Trust':
        risk_factors.append("trust owned property eligibility requirements named insured grantor")

    if property_details['ppc'] != 'N/A':
        risk_factors.append(
            f"protection class PPC {property_details['ppc']} fire district eligibility requirements"
        )

    if occupancy not in ['Owner Occupied']:
        risk_factors.append("tenant occupied rental dwelling occupancy requirements")
        risk_factors.append("DP3 dwelling policy tenant rental occupancy eligibility")
        risk_factors.append("HO3 owner occupancy requirement restriction")

    risk_factors.append(
        f"{property_details['roof_type']} roof {property_details['roof_age']} years old eligibility requirements"
    )
    if property_details['swimming_pool'] != 'No Pool':
        risk_factors.append(
            f"swimming pool {property_details['swimming_pool']} eligibility requirements"
        )
    if property_details['solar_panels'] == 'Yes':
        risk_factors.append("solar panels roof eligibility requirements")

    if risk_factors:
        risk_chunks = retriever.invoke(" ".join(risk_factors))
        risk_chunks = [c for c in risk_chunks if is_eligibility_content(c)]
        for chunk in risk_chunks:
            key = (chunk.metadata.get('carrier'), chunk.page_content)
            if key not in seen:
                seen.add(key)
                chunks.append(chunk)

    context = ""
    for chunk in chunks:
        context += f"\n--- {chunk.metadata.get('carrier', 'Unknown')} (page {chunk.metadata.get('page', '?')}) ---\n"
        context += chunk.page_content + "\n"

    # CHANGED: carrier safety net. A carrier can pass the occupancy filter
    # but still end up with zero chunks in `chunks` (e.g. retrieval just
    # didn't surface anything relevant) -- without this, the model has no
    # way to know the carrier was ever supposed to be evaluated, and would
    # silently omit it from the response instead of reporting
    # INSUFFICIENT_INFORMATION.
    carriers_with_chunks = {chunk.metadata.get('carrier') for chunk in chunks}
    no_chunk_carriers = [c for c in relevant_carriers if c not in carriers_with_chunks]

    ownership = property_details.get('ownership_type', 'Individual Owner')

    # CHANGED: this is now just the dynamic per-property content. The
    # instructions/schema/output-format text that used to live in this
    # same f-string moved to SYSTEM_INSTRUCTIONS above so it can be cached.
    user_content = f"""PROPERTY DETAILS:
State: TX
Year Built: {property_details['year_built']}
Home Age: {home_age} years
Roof Age: {property_details['roof_age']} years
Roof Type: {property_details['roof_type']}
Roof Shape: {property_details['roof_shape']}
Construction Type: {property_details['construction_type']}
Plumbing Type: {property_details['plumbing_type']}
Occupancy Type: {occupancy}
Ownership Structure: {ownership}
Coastal Tier: {property_details['coastal_tier']}
Swimming Pool: {property_details['swimming_pool']}
Pool Accessories: {property_details['pool_accessories']}
Dogs on Premises: {property_details['has_dogs']}
Aggressive Breed Dogs: {property_details['aggressive_breed']}
Solar Panels: {property_details['solar_panels']}
PPC Number: {property_details['ppc']}

CARRIER DOCUMENTS:
{context}
"""

    if no_chunk_carriers:
        user_content += "\nCARRIERS WITH NO RETRIEVED INFORMATION:\n"
        user_content += "\n".join(f"- {c}" for c in no_chunk_carriers)
        user_content += "\n"

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=12000,
        temperature=0,
        system=[
            {
                "type": "text",
                "text": SYSTEM_INSTRUCTIONS,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
    )

    # CHANGED: cache visibility. cache_read_input_tokens > 0 means this call
    # got a cache hit; cache_creation_input_tokens > 0 means this call just
    # wrote the cache (normal on the first call, or after the ~5 min TTL
    # lapses between checks).
    usage = getattr(response, "usage", None)
    if usage is not None:
        print(
            "Cache: read=%s created=%s input=%s"
            % (
                getattr(usage, "cache_read_input_tokens", "n/a"),
                getattr(usage, "cache_creation_input_tokens", "n/a"),
                getattr(usage, "input_tokens", "n/a"),
            )
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

        # CHANGED: the model's own restated carrier name can drop a token
        # from an ambiguous combined-program name (e.g. return "Foremost"
        # instead of "Foremost DP3 and HO3"), which would make the naive
        # DP3/HO3 substring check below wrongly exclude it. Trust a fuzzy
        # match against the known combined-program carriers (derived from
        # the reliable raw metadata name) before applying that heuristic.
        combined_carriers = get_combined_program_carriers()
        combined_brands = {
            re.split(r"[\s_\-]+", c)[0].upper() for c in combined_carriers if c
        }
        combined_upper = [c.upper() for c in combined_carriers]

        def is_combined_program(name_upper):
            if any(brand in name_upper for brand in combined_brands if brand):
                return True
            return bool(difflib.get_close_matches(name_upper, combined_upper, n=1, cutoff=0.3))

        filtered = []
        for r in parsed:
            name = r.get("carrier", "").upper()
            if is_combined_program(name):
                filtered.append(r)
                continue
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