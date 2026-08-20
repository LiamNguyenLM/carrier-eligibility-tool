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
from structured_rules import (
    sage_family_fpc_eligibility,
    mercury_roof_eligibility,
    sage_markel_roof_exclusion,
    swyfft_max_roof_age_30,
    twico_roof_settlement,
)


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

Do not decline a carrier over a fact that ISN'T given in PROPERTY DETAILS (e.g. county, driving distance to the nearest fire station, wildfire risk score) and isn't otherwise computable from what IS given. A fact simply not being provided is not the same as the property failing that fact's requirement -- treat it as missing_info, not as grounds for INELIGIBLE, unless the carrier's own rule is unconditional regardless of that fact.

Protection Class / PPC is given in PROPERTY DETAILS as a single, final number -- it is NOT ambiguous and does NOT need re-deriving. Before using ANY Protection-Class-related table or sentence from a carrier's document, first classify it as exactly one of these two kinds, and follow the matching rule. Do not skip this classification step.
  (a) A DIRECT RULE that states what happens for a given PPC value or range (e.g. "PPC 9 or greater is ineligible", "PPC 9 is eligible within 5 miles of a fire station, ineligible beyond it", a table capping Coverage A by PPC band). Apply this directly to the given PPC value. If the rule itself depends on a fact that is truly not given anywhere in PROPERTY DETAILS (such as driving distance to a fire station), that specific fact goes in missing_info -- but still state which outcome each possible value of that fact would produce.
  (b) A DISAMBIGUATION RULE whose own text exists to choose between two numbers ISO assigned to the same location (signal phrases: "two or more classifications are shown", "split rating", a slash like "6/9"). This kind of table is IRRELEVANT here and must be treated as if it were never retrieved: do not cite it, do not mention it in reasons, do not add anything about it to missing_info, and do not let it affect the status. The customer's single given PPC number already reflects whatever this table would have resolved.
If you are not sure which of (a) or (b) a table is, re-read the sentence immediately before the table -- that sentence states its purpose.

A rule requiring MULTIPLE conditions joined by "AND" (e.g. "FPC is 9 or greater, AND driving distance is greater than 5 miles = ineligible") only matters if EVERY condition could plausibly be true. Check each AND-condition against the given PPC value FIRST, before considering any other condition: if the given PPC value already fails just the first condition (e.g. customer's PPC is 1, and the rule requires PPC/FPC 9 or greater), the entire rule cannot apply regardless of the other condition's value -- do not ask for driving distance, hydrant distance, or any other fact tied to that same AND-rule, since no answer to it can change the outcome. Likewise, a rule or missing_info item written for a DIFFERENT specific PPC value than the customer's own (e.g. a "PPC 10" rule, when the customer's PPC is 1) has no bearing here -- do not cite it or list it as missing.

Do not reuse a specific term, concept, or classification scheme (e.g. a named "Classification A/B/C" system) that you saw in ONE carrier's excerpt when writing about a DIFFERENT carrier, even one from the same underwriting family (e.g. carriers sharing a common program administrator) -- each carrier's rule structure and terminology is independent unless that exact term also appears in that other carrier's own excerpt.

More generally: when a rule has its own stated conditions (an age threshold, a coverage amount, a home-age-plus-PPC combination) and the given facts place the property OUTSIDE those conditions, the rule simply does not restrict this property -- treat PPC (or whatever the rule covers) as unrestricted here, exactly as if that rule did not exist in the document at all. This means the property PASSES that criterion; it counts toward ELIGIBLE, not toward REFER or missing_info. Do not add anything to missing_info or reasons about "whether the carrier has some other rule" for a combination its own document doesn't address, and do not use REFER for a condition you've just determined doesn't apply. Only flag something as missing when the document's OWN applicable rule (one whose conditions the property actually meets) itself depends on a fact you don't have.

When comparing the property's Home Age, Roof Age (or any given number) against a numeric threshold in a rule (e.g. "eligible up to 20 years", "must be under 15 years"), work out the actual arithmetic comparison explicitly before concluding which side of the threshold the property falls on -- state the comparison itself (e.g. "17 is less than 20, so this condition is met") rather than jumping straight to a conclusion. A carrier's own name (e.g. one containing "Plus" or a product suffix) is NOT evidence about which side of a threshold applies -- only the rule's stated number and the given value decide that.

Pay close attention to whether a threshold is INCLUSIVE or EXCLUSIVE of the boundary value itself, especially when the given value EQUALS the threshold number exactly. "Older than X," "more than X," and "over X" are EXCLUSIVE -- a value of exactly X does NOT satisfy them (e.g. a roof that is exactly 10 years old does NOT meet "required for roofs older than 10 years old"). "X or newer," "X or more," "up to X," and "X or less" are INCLUSIVE -- a value of exactly X DOES satisfy them. When the given value is exactly equal to a rule's stated number, explicitly check the rule's wording for "than"/"over" (exclusive, boundary fails) versus "or"/"up to" (inclusive, boundary passes) before concluding. "Holds/pauses/defers [depreciation or a coverage basis] for N years" is also INCLUSIVE of year N -- a roof at exactly N years old is still within that held/deferred period, so the favorable coverage basis (e.g. RCV) still applies at exactly N. Reach a definite conclusion in these cases -- do not describe the property as merely "at the boundary" without stating which side of it applies.

Carrier documents are frequently split across multiple separate excerpts below, and a rule can be cut off mid-sentence or mid-clause in one excerpt with its continuation appearing in a DIFFERENT excerpt for the SAME carrier (they won't necessarily be adjacent in this prompt). Before concluding that a rule's specific number or detail is "not stated" or "not specified in the retrieved excerpts," check ALL of this carrier's other excerpts for a continuation of the same sentence or clause -- a value that looks absent in one excerpt is often completed a sentence or two later in another.

When a carrier's rule requires a SPECIFIC attribute (an exact fence height, a particular gate mechanism, a named material) and PROPERTY DETAILS only gives a more general description (e.g. Swimming Pool is "In Ground - Fenced" with no height or gate type stated), do not assume the specific requirement is met -- list the specific missing attribute in missing_info. Never state a specific number or detail in reasons, citations, or notes as if it were a fact about THIS property when it actually came from the carrier's rule and was never confirmed by the customer (e.g. do not say "the property has a 4-foot fence" when the customer only said "fenced").

SWIMMING POOL RULES SPECIFICALLY: a pool fence height or gate-mechanism requirement (e.g. "4-foot fence," "self-latching gate," "combination lock or padlock") is a DIFFERENT rule from one carrier's document to the next -- some carriers state a specific number and mechanism, some only say "fenced" or "secured" in general terms, and some don't mention pools at all. Before adding ANY pool-related item to missing_info, or citing a specific height or gate-mechanism type, check THIS carrier's own retrieved excerpt for it specifically:
  - If this carrier's excerpt does not mention swimming pools at all, do not add a pool-related missing_info item for it -- there is nothing to be missing.
  - If this carrier's excerpt only states a GENERAL pool condition ("fenced," "secured," "walled") with no specific height or gate-mechanism menu, the customer's given Swimming Pool value ("In Ground - Fenced") already satisfies it -- do not manufacture a more specific height/mechanism question the document itself never asks.
  - If this carrier's excerpt lists specific ineligible pool features (e.g. diving board, slide, unfenced) rather than a fence-height/gate requirement, check those specific features against Pool Accessories and Swimming Pool as given, and resolve the rule accordingly -- do not substitute a different carrier's fence-height/gate-mechanism question for it.
  - Only cite a specific fence height or gate-mechanism type if that EXACT figure or mechanism is present in THIS carrier's own excerpt. Do not reuse a specific pool number or mechanism you saw for a different carrier earlier in this same response -- each carrier's pool rule (or absence of one) is independent.

BASE ELIGIBILITY vs. OPTIONAL ENDORSEMENT/COVERAGE: some requirements you'll see (a fence height, a specific material, a distance figure) are conditions of an OPTIONAL endorsement or coverage add-on, not of base policy eligibility -- look for language like "this endorsement," "to qualify for this coverage," or "optional." A condition scoped to an optional endorsement does NOT make the carrier ineligible or create a missing_info blocker if that specific coverage isn't otherwise at issue -- note it in notes as a coverage consideration if relevant, but do not let it drive status or missing_info the way a base eligibility requirement would.

ROOFING MATERIAL TERMINOLOGY: "Composition Shingle," "Composite Shingle," "Architectural Shingle," "3-tab shingle," and "asphalt shingle" all refer to the SAME underlying family of asphalt-based shingle roofing, and carriers use these terms inconsistently -- one carrier's document may use only one of these phrases, or bundle several together (e.g. "Composite or Architectural Shingle"), to mean the same roofing category the customer's own Roof Type value falls under. If a carrier's document states a rule using ANY of these terms and never uses the customer's EXACT given Roof Type wording, apply that rule to the customer's roof anyway -- do not treat the rule as inapplicable, and do not invent an undefined separate category or lifespan figure "for" the customer's exact wording. Only treat two of these terms as genuinely different categories with different rules if the SAME document explicitly gives them different numeric thresholds.

REMAINING-LIFE-EXPECTANCY rules specifically (e.g. "roof should have 3/4 of its life expectancy remaining to qualify for replacement cost coverage"): the TOTAL life expectancy or maximum age figure needed to compute this is very often stated in a DIFFERENT sentence than the fraction itself -- commonly phrased as "should be completely replaced before/by age X" a sentence or two later, for the same or a synonymous roofing category (see ROOFING MATERIAL TERMINOLOGY above). Before concluding a total-life-expectancy figure "is not stated" or "is not fully specified," search ALL of this carrier's other excerpts for such a figure under any synonymous category name. Once found, show the arithmetic explicitly: remaining life = total life expectancy minus Roof Age; required = 3/4 x total life expectancy; state both numbers and whether remaining >= required.

DO NOT DOWNGRADE TO INSUFFICIENT_INFORMATION WHEN EVERY APPLICABLE BRANCH AGREES: some rules are structured as a multi-row table or multi-branch condition (e.g. a Fire-Protection-Class/driving-distance table with several rows). Before concluding a fact is missing and using INSUFFICIENT_INFORMATION, check EVERY row/branch that could possibly apply to the customer's ACTUAL given value (PPC/FPC, roof type, etc.) -- not every row in the whole table, just the ones the given value could land in. If ALL of those applicable rows/branches lead to the SAME eligibility outcome (e.g. every row for this customer's FPC band says "eligible," even if each row attaches DIFFERENT additional conditions like an alarm or road-visibility requirement), that outcome IS the verdict -- do not use INSUFFICIENT_INFORMATION just because the unconfirmed fact would determine WHICH additional conditions apply, when it doesn't change WHETHER the risk is eligible. List the unconfirmed fact in missing_info as something to confirm which conditions apply, and note in notes that eligibility itself doesn't depend on it. Only use INSUFFICIENT_INFORMATION when the applicable rows/branches would produce genuinely DIFFERENT eligibility outcomes (e.g. one applicable row says eligible and another says ineligible) depending on the missing fact.

CITATION ACCURACY: a citation must reproduce the source text's exact wording, not a paraphrase or a more common word substituted for a less common one that happens to fit the customer's situation (e.g. do not write "asphalt shingles" when the source says "asbestos shingles" -- these are different words with different meanings, even though they look and sound similar and even though this customer happens to have an asphalt roof). If you are not fully certain of the exact wording, quote a shorter, unambiguous fragment you ARE certain of rather than a longer one you might be filling in from context.

Return ONLY a JSON array with no text before or after it.
Each object must follow this exact structure -- NOTE the field order: work out reasons, citations, missing_info, and notes FIRST, and only decide status and flaw_count LAST, after that analysis is already written. Do not decide the verdict before you've written the reasoning -- the verdict must be the conclusion your own reasons/notes already reached, never a separate judgment made in advance of them.

[
  {
    "carrier": "carrier name from document",
    "reasons": ["reason 1", "reason 2"],
    "citations": ["carrier name: exact short quote from document"],
    "missing_info": ["item needed for final determination"],
    "notes": "any important coverage distinctions such as RCV vs ACV",
    "status": "ELIGIBLE",
    "flaw_count": 0
  }
]

Status must be exactly one of: ELIGIBLE, INELIGIBLE, REFER, INSUFFICIENT_INFORMATION. Use this decision rule, in order:
1. INELIGIBLE -- ONLY when the document states a flat exclusion (no underwriting discretion, no referral path) AND the customer's KNOWN facts (given in PROPERTY DETAILS, or a threshold already fully resolved above) actually satisfy that exclusion. If your own reasons/notes just concluded the customer's number is on the ALLOWED side of a cutoff, or that a rule's conditions don't apply to this property, the status CANNOT be INELIGIBLE for that rule.
2. REFER -- ONLY when the carrier's OWN document explicitly offers a referral, underwriting-discretion, or manual-review path for THIS specific situation (using its own language -- "refer to underwriting," "subject to underwriter approval," etc.). A flat binary rule (e.g. "eligible under 5 miles, ineligible beyond it") is NOT a referral just because the outcome depends on a fact you don't have -- that's INSUFFICIENT_INFORMATION instead, unless the document's own words for that specific rule invoke discretion or review.
3. INSUFFICIENT_INFORMATION -- when a fact genuinely required to reach ELIGIBLE or INELIGIBLE is simply not known (not given in PROPERTY DETAILS and not resolvable from what is given), and the document does NOT itself offer a referral/discretion path for it.
4. ELIGIBLE -- otherwise: no applicable flat exclusion is satisfied, no referral path is invoked, and no required fact is missing.
Before writing status, re-read what you just wrote in reasons and notes for this same carrier -- status must match that conclusion exactly. A self-contradiction (reasons/notes conclude the property passes a rule, but status says INELIGIBLE or REFER for that same rule) is a hard error; catch it before finalizing.

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


# Typographic punctuation PDF extraction sometimes produces, normalized
# before chunk text reaches the prompt (see normalize_chunk_text below).
_SMART_QUOTE_MAP = {
    "‘": "'",  # LEFT SINGLE QUOTATION MARK
    "’": "'",  # RIGHT SINGLE QUOTATION MARK -- e.g. ARI (HOA+)/(HOB)'s
                     # "6’ high fence" citation, used as a foot-mark.
}


def normalize_chunk_text(text):
    """Applied to chunk text right before it's embedded in the prompt sent
    to the model. Fixes a real, recurring JSON-parse failure traced this
    session: ARI (HOA+) and ARI (HOB)'s pool-fence citation
    ("Pools secured by a\\n6’ high fence...") contains BOTH a raw
    mid-sentence newline (a PDF line-wrap artifact, not a real paragraph
    break) and a curly right-single-quote apostrophe (U+2019). The model is
    instructed to quote citations verbatim (see the citation-accuracy
    instruction in SYSTEM_INSTRUCTIONS); when it reproduces this exact text
    -- including the raw embedded newline -- inside its own generated JSON
    string without escaping it, that breaks JSON parsing (a raw, unescaped
    newline inside a JSON string is illegal) -- confirmed via a synthetic
    reproduction, and measured hitting ~20% (4/20) of a real sampled run
    against this specific carrier.

    The apostrophe itself (U+2019) does NOT break JSON syntax on its own
    (it round-trips cleanly through json.dumps/json.loads) -- normalizing
    it here is a smaller, complementary cleanup, not the fix for the parse
    errors. The newline collapse below is the part that actually addresses
    the observed failure.

    Only single line-wrap newlines are collapsed to a space; a genuine
    paragraph break (\\n\\n) is left alone."""
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    for smart, plain in _SMART_QUOTE_MAP.items():
        text = text.replace(smart, plain)
    return text


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


def _mentions_pool_rule(content):
    """Swimming pool rules have the same embedding-rank problem PPC did:
    confirmed on Sage Occidental HO3, whose own 4-ft-fence-and-locking-gate
    pool rule ranked #19 of 57 chunks under the main query -- well outside
    the per-carrier fetch window -- while its five sibling carriers'
    equivalent rule happened to rank well enough in the same run. An exact
    keyword scan sidesteps the ranking lottery."""
    lower = content.lower()
    return "pool" in lower or "swimming" in lower


def _mentions_solar(content):
    """Solar-panel rules had NO retrieval guarantee at all before this was
    added -- confirmed on a real customer profile with solar panels
    present: 5 of 30 carriers have a directly relevant solar rule (TWICO
    and NatGen Premier OneChoice flatly exclude homes with solar panels,
    Orion/Progressive HO3/HO6 exclude coverage for the panels, HOAIC
    requires an endorsement), and NONE of it reached the tool's output --
    each carrier has exactly one chunk mentioning "solar" out of dozens to
    hundreds of chunks, with only a single shared, non-carrier-filtered
    global search (k=10 across the whole ~40-carrier database) ever
    touching the topic. This missed an actual wrong verdict (TWICO
    returned Eligible despite its own explicit solar exclusion)."""
    return "solar" in content.lower()


def _mentions_roof_life_expectancy(content):
    """A roof's TOTAL life expectancy (or maximum age) figure is often
    stated in a different sentence/chunk than the specific rule that
    depends on it (e.g. a "3/4 of its life expectancy" requirement one
    chunk, "completely replaced before it becomes 21 years old" in
    another). Confirmed on Allied Trust HO3 via a parametrized retrieval
    test across four phrasings of the same roofing category ("Composition
    Shingle" / "Composite or Architectural Shingle" / "Architectural
    Shingle" / "3-tab shingle"): the total-years chunk fell outside the
    main query's top-3 kept window for at least one common phrasing even
    though it ranked within the window for others -- the same
    embedding-rank lottery problem as PPC, pool, and solar."""
    lower = content.lower()
    return "life expectancy" in lower or "years old based on national statistics" in lower


def _is_ppc_disambiguation_table(content):
    """A Protection Class table whose own text exists to resolve which of
    TWO ISO-assigned classes applies to one location (e.g. a "6/9" split
    rating) is never applicable here -- this app's intake only ever
    collects a single, final PPC number, never a split rating, so this
    kind of table can't be the actually-governing rule for any query this
    app will run. Confirmed on ARI (HOA+): even with an explicit prompt
    instruction telling the model to classify a PPC table as a direct rule
    vs. a disambiguation rule before using it, the model still repeatedly
    misapplied this exact table as a direct eligibility gate across
    multiple real API test runs. Excluding it at retrieval time is more
    reliable than asking the model to make that judgment call correctly
    every single time."""
    lower = content.lower()
    return "two or more classification" in lower or "classifications are shown" in lower


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


def build_risk_factors(property_details, occupancy):
    """The targeted risk-factor retrieval terms appended to the main query
    (see check_eligibility()). Factored out so it's directly testable
    without a live LLM call -- round 12 found this list's coastal-tier
    condition only fired for Tier 1/Tier 2, silently excluding Tier 3
    ("outer coastal zone" per app.py's own dropdown -- still an explicitly
    coastal designation, distinct from "Not Coastal") from ANY targeted
    retrieval for wind-pool-zone/flood-elevation content. Whether Tier 3
    should trigger a given carrier's SPECIFIC wind-pool-zone rule depends on
    that carrier's own geographic definition (e.g. TWIA's wind pool
    boundaries), which this tool doesn't have a ground-truth mapping for --
    but under-triggering retrieval for an explicitly-coastal tier is worse
    than over-triggering it: a query that surfaces possibly-inapplicable
    content still lets the model's own reasoning dismiss it, while a query
    that never fires means the content was never in the running at all."""
    risk_factors = []

    if property_details['plumbing_type'] in ['Galvanized', 'Polybutylene']:
        risk_factors.append("galvanized polybutylene plumbing ineligible requirements")

    if 'Unfenced' in property_details['swimming_pool']:
        risk_factors.append("swimming pool fence requirement ineligible unfenced")

    if property_details['pool_accessories'] != 'None':
        risk_factors.append("diving board slide pool liability ineligible")

    if property_details['coastal_tier'] in ['Tier 1', 'Tier 2', 'Tier 3']:
        risk_factors.append(
            "coastal tier wind coverage restrictions wind pool zone "
            "base flood elevation ineligible"
        )

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

    return risk_factors


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

# CHANGED (round 12): a real, untruncated capture of a JSON parse failure
# confirmed the model was running out of output tokens partway through a
# verbose ~28-carrier response (missing_info closed, but the carrier object
# and outer array never did -- only ~20 of ~28 carriers had been written).
# Raised from 12000. Kept as a named constant, not inline, so a future
# change can't silently shrink this back down without a test noticing.
MAX_RESPONSE_TOKENS = 24000


def guaranteed_carrier_lookup(collection, carrier, predicate, keep, priority_key=None):
    """Shared implementation behind every "guaranteed lookup" (PPC, pool,
    solar, roof life-expectancy): an exact keyword scan across one
    carrier's FULL raw chunk set, independent of embedding rank, optionally
    sorted so the most relevant matches (not just the first `keep` in
    arbitrary DB order) survive the cap. Factored out of check_eligibility()
    so verification tests call the EXACT same logic production does --
    this exists because a duplicated, un-synced copy in a test previously
    passed while the real (differently-sorted) production code still
    dropped the chunk that mattered."""
    try:
        raw = collection.get(where={"carrier": carrier}, include=["documents", "metadatas"])
    except Exception:
        return []
    candidates = [
        Document(page_content=doc, metadata=meta)
        for doc, meta in zip(raw["documents"], raw["metadatas"])
        if predicate(doc)
    ]
    candidates = [c for c in candidates if is_eligibility_content(c)]
    if priority_key is not None:
        candidates.sort(key=priority_key)
    return candidates[:keep]


# ---------------------------------------------------------------------------
# Structured (non-LLM) overrides -- deterministic code, run AFTER the
# model's own analysis, for rules verified to be purely tabular (see
# structured_rules.py). This exists because measured pass rates for the
# Sage FPC table were as low as 0-25% even with an explicit prompt
# instruction telling the model to reason through every branch -- for a
# genuinely tabular rule, code that evaluates the table directly is much
# closer to 100% deterministic than any prompt fix can get.
#
# TWICO's roof settlement table IS included, for every UNAMBIGUOUS material
# (Tile, Metal Standing-Seam, Wood/Slate/Metal Shingle, Asbestos, Corrugated
# Metal). Round 12: gating twico_roof_settlement() out of production
# entirely (rather than gating only the genuinely ambiguous case) was
# itself a regression -- it silently dropped roof-age transparency for
# every material the table resolves cleanly, not just the one it can't
# (bare "Composition Shingle" with no 3-tab/Architectural qualifier, which
# still returns INSUFFICIENT_INFORMATION -- see
# structured_rules.twico_roof_settlement's own docstring).
# ---------------------------------------------------------------------------

_SAGE_FPC_CARRIERS = {
    "Sage_-_Auros_HO3",
    "Sage_-_Occidental_HO3",
    "Sage_-_Wilshire_HO3_-_12.02.2025",
    "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026",
    "Sage_-_SURE_HO-3_-_01.31.2026",
    "Sage_-_SafePort_HO-3_-_01.31.2026",
}
_MERCURY_CARRIERS = {"Mercury_HO3_-_01.01.2026"}
_SAGE_MARKEL_CARRIERS = {"Sage_-_Markel_HO3"}
_SWYFFT_MAX30_CARRIERS = {
    "Swyfft_-_Benchmark_(Admitted)_HO3",
    "Swyfft_-_Benchmark_(Surplus)_HO3",
    "Swyfft_-_Topa_(Surplus)_HO3",
}
_TWICO_CARRIERS = {"TWICO_HO3"}


def _normalize_carrier_name(s):
    return "".join(ch for ch in s.upper() if ch.isalnum())


def _resolve_structured_carrier(reported_name, canonical_names):
    """The model restates carrier names in its own JSON output rather than
    echoing the exact DB metadata string -- resolve against the known
    carrier list the same tolerant way is_combined_program (above) already
    does for the DP3/HO3 heuristic, rather than requiring an exact match."""
    norm_reported = _normalize_carrier_name(reported_name)
    if not norm_reported:
        return None
    for canon in canonical_names:
        norm_canon = _normalize_carrier_name(canon)
        if norm_canon and (norm_canon in norm_reported or norm_reported in norm_canon):
            return canon
    return None


def _force_ineligible(result, reason_text):
    if result.get("status") != "INELIGIBLE":
        result["status"] = "INELIGIBLE"
        result["flaw_count"] = 1
    result.setdefault("reasons", []).append(reason_text)
    result.setdefault("citations", []).append(reason_text)


def _append_note(result, text):
    existing = result.get("notes", "")
    result["notes"] = (existing + " " + text).strip() if existing else text


def _apply_structured_overrides(results, relevant_carriers, property_details):
    for r in results:
        canon = _resolve_structured_carrier(r.get("carrier", ""), relevant_carriers)
        if canon is None:
            continue

        if canon in _SAGE_FPC_CARRIERS:
            s_status, s_reasons = sage_family_fpc_eligibility(
                property_details['ppc'], carrier=canon,
            )
            if s_status == "ELIGIBLE" and r.get("status") == "INSUFFICIENT_INFORMATION":
                # CHANGED (round 12): a real end-to-end run showed the model
                # can correctly conclude "FPC 1-8 is eligible regardless of
                # driving distance" in its narrative while still leaving
                # status=INSUFFICIENT_INFORMATION -- but that narrative
                # sometimes lands in `notes` (a free-form summary field),
                # not `missing_info`/`reasons`. Scanning only the latter two
                # missed it, so the override silently never fired even
                # though the wiring was otherwise correct. Scan citations
                # too for the same reason -- any field the model might use
                # to state its FPC conclusion.
                blob = " ".join(
                    r.get("missing_info", []) + r.get("reasons", []) + r.get("citations", [])
                    + [r.get("notes", "")]
                ).lower()
                if any(kw in blob for kw in ("fpc", "fire protection class", "protection class", "ppc")):
                    r["status"] = "ELIGIBLE"
                    r["flaw_count"] = 0
                    _append_note(r, "Structured FPC check: " + s_reasons[0])
            elif s_status == "INSUFFICIENT_INFORMATION":
                mi = r.setdefault("missing_info", [])
                if not any("fire station" in m.lower() for m in mi):
                    mi.append(
                        "Driving distance to the responding fire station "
                        "(needed to determine FPC 9+ eligibility)."
                    )

        elif canon in _MERCURY_CARRIERS:
            s_status, s_reasons = mercury_roof_eligibility(
                property_details['roof_type'], property_details['roof_age'],
            )
            if s_status == "INELIGIBLE":
                _force_ineligible(r, s_reasons[0])
            elif s_status == "ELIGIBLE_REQUIRES_ENDORSEMENT":
                _append_note(r, s_reasons[0])
            else:
                # CHANGED (round 12): even the "unremarkable" ELIGIBLE/RCV
                # outcome is now always noted -- see the TWICO case below
                # for why silence here is itself a bug, not a no-op.
                _append_note(
                    r,
                    f"Roof age {property_details['roof_age']} is within the standard "
                    f"replacement-cost threshold for this roof type.",
                )

        elif canon in _SAGE_MARKEL_CARRIERS:
            s_status, s_reasons = sage_markel_roof_exclusion(
                property_details['roof_type'], property_details['roof_age'],
            )
            if s_status == "ROOF_EXCLUDED":
                _append_note(r, s_reasons[0])
            else:
                _append_note(
                    r,
                    f"Roof age {property_details['roof_age']} is within the roof-exclusion "
                    f"form's age threshold for this roof type -- roof coverage applies normally.",
                )

        elif canon in _SWYFFT_MAX30_CARRIERS:
            s_status, s_reasons = swyfft_max_roof_age_30(property_details['roof_age'])
            if s_status == "INELIGIBLE":
                _force_ineligible(r, s_reasons[0])
            else:
                _append_note(r, f"Roof age {property_details['roof_age']} is within the 30-year maximum.")

        elif canon in _TWICO_CARRIERS:
            s_status, s_reasons = twico_roof_settlement(
                property_details['roof_type'], property_details['roof_age'],
            )
            if s_status == "INELIGIBLE":
                _force_ineligible(r, s_reasons[0])
            elif s_status in ("ACV", "EXCLUDED"):
                _append_note(r, s_reasons[0])
            elif s_status == "INSUFFICIENT_INFORMATION":
                mi = r.setdefault("missing_info", [])
                if not any("3-tab" in m or "architectural" in m.lower() for m in mi):
                    mi.append(s_reasons[0])
            else:
                # CHANGED (round 12): RCV used to get no note at all, on the
                # assumption the model's own retrieval/narrative would
                # mention roof/tile anyway. A real run proved that wrong --
                # TWICO's roof table doesn't match the generic roof-life-
                # expectancy guaranteed lookup (it never uses the phrase
                # "life expectancy"), so nothing guarantees this carrier's
                # roof clause is even retrieved, and the model's response
                # can go completely silent on roof/tile as a result. Same
                # lesson as the Sage FPC wiring gap: the structured
                # conclusion must always reach the output, not depend on
                # the model rediscovering it on its own.
                _append_note(
                    r,
                    f"Roof age {property_details['roof_age']} ({property_details['roof_type']}) "
                    f"is within TWICO's replacement-cost-value band -- no ACV or exclusion applies.",
                )


def check_eligibility(property_details, carrier_subset=None):
    """carrier_subset: optional iterable of carrier names to restrict
    evaluation to (intersected with the normal occupancy filter). Used to
    pilot splitting the combined multi-carrier completion into smaller
    per-group calls without touching the default single-call behavior when
    omitted."""
    occupancy = property_details['occupancy_type']

    # CHANGED: home age computed here instead of leaving the model to infer
    # the current year -- it was previously off by one year when the model
    # assumed the wrong current year.
    home_age = date.today().year - property_details['year_built']

    query = build_retrieval_query(property_details, home_age)

    relevant_carriers = get_carriers_for_occupancy(occupancy)
    if carrier_subset is not None:
        subset = set(carrier_subset)
        relevant_carriers = [c for c in relevant_carriers if c in subset]
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
    collection = vectorstore._collection

    MAX_PPC_CHUNKS_PER_CARRIER = 2
    if property_details['ppc'] != 'N/A':
        ppc_value = str(property_details['ppc'])
        for carrier in relevant_carriers:
            # prefer chunks that name this exact PPC value over generic ones
            found = guaranteed_carrier_lookup(
                collection, carrier,
                predicate=lambda doc: _mentions_protection_class(doc) and not _is_ppc_disambiguation_table(doc),
                keep=MAX_PPC_CHUNKS_PER_CARRIER,
                priority_key=lambda c: ppc_value not in c.page_content,
            )
            for chunk in found:
                key = (carrier, chunk.page_content)
                if key not in seen:
                    seen.add(key)
                    chunks.append(chunk)

    # CHANGED: guaranteed per-carrier swimming pool rule lookup, same
    # rationale and pattern as the PPC guarantee above -- confirmed on Sage
    # Occidental HO3 (see _mentions_pool_rule docstring), where the
    # carrier's own pool-fence rule ranked #19/57 under the main query.
    MAX_POOL_CHUNKS_PER_CARRIER = 3
    if property_details['swimming_pool'] != 'No Pool':
        for carrier in relevant_carriers:
            # prefer chunks that pair "pool" with fence/gate language over
            # incidental pool mentions (acreage referrals, construction
            # material exclusions, etc. that happen to name "pool" once)
            found = guaranteed_carrier_lookup(
                collection, carrier,
                predicate=_mentions_pool_rule,
                keep=MAX_POOL_CHUNKS_PER_CARRIER,
                priority_key=lambda c: not ("fenc" in c.page_content.lower() or "gate" in c.page_content.lower()),
            )
            for chunk in found:
                key = (carrier, chunk.page_content)
                if key not in seen:
                    seen.add(key)
                    chunks.append(chunk)

    # CHANGED: guaranteed per-carrier solar panel rule lookup, same pattern
    # as PPC and pool above (see _mentions_solar docstring for why this was
    # added -- it missed an actual wrong verdict on TWICO).
    MAX_SOLAR_CHUNKS_PER_CARRIER = 2
    if property_details['solar_panels'] == 'Yes':
        for carrier in relevant_carriers:
            found = guaranteed_carrier_lookup(
                collection, carrier, predicate=_mentions_solar, keep=MAX_SOLAR_CHUNKS_PER_CARRIER,
            )
            for chunk in found:
                key = (carrier, chunk.page_content)
                if key not in seen:
                    seen.add(key)
                    chunks.append(chunk)

    # CHANGED: guaranteed per-carrier roof life-expectancy lookup, same
    # pattern as PPC/pool/solar above (see _mentions_roof_life_expectancy
    # docstring -- confirmed via a parametrized retrieval test that this
    # embedding-rank lottery affected at least one common roof-type phrasing
    # on Allied Trust HO3, after two prior prompt-only fix attempts).
    MAX_ROOF_LIFE_CHUNKS_PER_CARRIER = 3
    for carrier in relevant_carriers:
        # prefer chunks that actually name a roofing/shingle category over
        # incidental "life expectancy is 5 or more years" boilerplate that
        # appears in this same carrier's plumbing/heating/electrical rules
        found = guaranteed_carrier_lookup(
            collection, carrier,
            predicate=_mentions_roof_life_expectancy,
            keep=MAX_ROOF_LIFE_CHUNKS_PER_CARRIER,
            priority_key=lambda c: "shingle" not in c.page_content.lower(),
        )
        for chunk in found:
            key = (carrier, chunk.page_content)
            if key not in seen:
                seen.add(key)
                chunks.append(chunk)

    risk_factors = build_risk_factors(property_details, occupancy)

    if risk_factors:
        risk_chunks = retriever.invoke(" ".join(risk_factors))
        risk_chunks = [c for c in risk_chunks if is_eligibility_content(c)]
        for chunk in risk_chunks:
            key = (chunk.metadata.get('carrier'), chunk.page_content)
            if key not in seen:
                seen.add(key)
                chunks.append(chunk)

    # CHANGED: group by carrier instead of emitting chunks in insertion
    # order. `chunks` is built in separate passes (main per-carrier query,
    # then the guaranteed PPC lookup, then the global risk-factor pass) --
    # rendered in insertion order, that meant every carrier's main content
    # appeared in one place and that SAME carrier's guaranteed PPC chunk
    # showed up far later, after every other carrier's main content, in a
    # 25k+ token prompt. Diagnosed on Swyfft Lloyd's Surplus HO3: the
    # guaranteed PPC chunk was confirmed present in `chunks`, but the model
    # still reported PPC as missing -- its own evidence for this carrier
    # was split across two widely separated locations in the context. This
    # also incidentally guards against the risk-factor pass (which searches
    # the whole DB, not just relevant_carriers) leaking content from a
    # carrier the occupancy filter already excluded.
    relevant_carrier_set = set(relevant_carriers)
    chunks_by_carrier = {}
    for chunk in chunks:
        carrier_name = chunk.metadata.get('carrier', 'Unknown')
        if carrier_name not in relevant_carrier_set:
            continue
        chunks_by_carrier.setdefault(carrier_name, []).append(chunk)

    context = ""
    for carrier in relevant_carriers:
        for chunk in chunks_by_carrier.get(carrier, []):
            context += f"\n--- {carrier} (page {chunk.metadata.get('page', '?')}) ---\n"
            context += normalize_chunk_text(chunk.page_content) + "\n"

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
        # CHANGED (round 12): raised from 12000. A recurring "JSON PARSE
        # ERROR" (~20-30% of runs, previously misattributed to a
        # character-escaping issue in ARI's chunk text -- see
        # normalize_chunk_text()'s docstring) was confirmed via a full,
        # untruncated capture of an actual failure to be a plain output-
        # token budget overrun: the response cut off mid-object after only
        # ~20 of ~28 carriers, with missing_info's closing "]" but no
        # closing "}" or outer "]" -- the model simply ran out of its
        # 12000-token allowance partway through a verbose ~28-carrier JSON
        # array. The earlier ARI apostrophe/newline fix wasn't wrong to
        # apply (it's still a real, harmless cleanup) but it was NOT the
        # cause of the recurring failures -- every previous debug print
        # only showed raw[:1000], which always happens to contain ARI's
        # section since it sorts near the start of the carrier list,
        # regardless of where the actual truncation occurred much later.
        max_tokens=MAX_RESPONSE_TOKENS,
        temperature=0,
        system=[
            {
                "type": "text",
                "text": SYSTEM_INSTRUCTIONS,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_content}],
        # CHANGED (round 12): the anthropic SDK estimates a non-streaming
        # call's worst-case duration from max_tokens alone (3600s *
        # max_tokens / 128000) and REFUSES to make the call at all above a
        # 10-minute estimate -- raising MAX_RESPONSE_TOKENS to 24000 alone
        # pushed this past that threshold and made every single call raise
        # ValueError immediately (a hard, total failure, worse than the
        # intermittent truncation it was meant to fix). Passing an explicit
        # timeout here skips that heuristic entirely (the SDK only applies
        # it when timeout is NOT explicitly given) while still using a
        # normal non-streaming call -- real calls have taken up to ~180s
        # observed this session, so 900s leaves large headroom without
        # needing to implement streaming.
        timeout=900.0,
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

        _apply_structured_overrides(filtered, relevant_carriers, property_details)

        return filtered

    except json.JSONDecodeError as e:
        # CHANGED (round 12): print length + the tail, not just the first
        # 1000 chars -- a real failure was traced to output-token
        # truncation (see max_tokens comment above), and the head of the
        # response is USELESS for diagnosing that: it always looks the
        # same (ARI sorts first alphabetically) regardless of where the
        # cutoff actually happened, which is near the END of a long
        # response. stop_reason directly confirms truncation when present.
        print("JSON PARSE ERROR:", str(e))
        print("RAW RESPONSE LENGTH:", len(raw), "stop_reason:", getattr(response, "stop_reason", "n/a"))
        print("RAW RESPONSE HEAD:", raw[:500])
        print("RAW RESPONSE TAIL:", raw[-1000:])
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

def assign_buckets(results):
    """Split check_eligibility() results into the four UI buckets, one per
    actual status. Extracted out of app.py so it's testable without a
    Streamlit session -- this exact logic was the source of a labeling bug
    confirmed identically across three separate audit rounds and three
    customer profiles: the old 3-bucket version collapsed REFER and
    single-flaw INELIGIBLE into "One Issue" and everything else into "Not
    Eligible", which assumed REFER would be common and INSUFFICIENT_INFORMATION
    rare. Once this tool started deliberately avoiding REFER (a flat rule
    blocked on one missing fact is INSUFFICIENT_INFORMATION, not a referral --
    see the status decision rule in SYSTEM_INSTRUCTIONS), REFER nearly stopped
    firing and INSUFFICIENT_INFORMATION became common, so "One Issue" ended up
    holding only hard INELIGIBLE declines (backwards -- that label implies
    something soft) and "Not Eligible" ended up holding only
    INSUFFICIENT_INFORMATION carriers (also backwards -- those aren't
    declined, they're unresolved). Each bucket below maps to exactly one
    status so a relabeling of ANY status can never produce a mixed, mislabeled
    bucket again."""
    eligible = [r for r in results if r.get("status") == "ELIGIBLE"]
    one_issue = [
        r for r in results
        if (r.get("status") == "INELIGIBLE" and r.get("flaw_count", 0) == 1)
        or r.get("status") == "REFER"
    ]
    insufficient_info = [r for r in results if r.get("status") == "INSUFFICIENT_INFORMATION"]
    not_eligible = [
        r for r in results
        if r.get("status") == "INELIGIBLE" and r.get("flaw_count", 0) != 1
    ]
    return {
        "eligible": eligible,
        "one_issue": one_issue,
        "insufficient_info": insufficient_info,
        "not_eligible": not_eligible,
    }
