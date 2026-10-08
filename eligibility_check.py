from dotenv import load_dotenv
load_dotenv()

from langchain_community.vectorstores import Chroma
import anthropic
import copy
import difflib
import json
import os
import re
import threading
from datetime import date
import streamlit as st

try:
    from langchain_core.documents import Document
except ImportError:
    from langchain.schema import Document

try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
    if "OPENAI_API_KEY" in st.secrets:
        os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
except Exception:
    pass

from shared_resources import get_embeddings, get_vectorstore
import data_defects
import guides
import intake_fields
import quotes
import hold_guard
import rules_evaluator
import topics
from concurrent.futures import ThreadPoolExecutor
from structured_rules import (
    sage_family_fpc_eligibility,
    sage_fpc_with_distance,
    mercury_roof_eligibility,
    sage_markel_roof_exclusion,
    swyfft_max_roof_age_30,
    twico_roof_settlement,
    twico_roof_subtype_is_ambiguous,
    sage_roofer_statement_required,
    centauri_dp3_flat_roof,
    sage_county_in_territory,
    SAGE_EAST_TEXAS_COUNTIES,
)


@st.cache_resource
def load_retriever():
    return get_vectorstore().as_retriever(search_kwargs={"k": 10})


retriever = load_retriever()
# CHANGED (round 13): the SDK's default is max_retries=2, which is not
# enough for the transient DNS/connection drops this machine actually sees.
# Evidence, all from this round: the first COASTAL A/B lost 19 of 32 run
# slots to one "APIConnectionError: Connection error." outage, and each of
# the two multi-hour full-suite runs lost exactly one test to
# "[Errno 11001] getaddrinfo failed" -- a DNS failure, not a model or API
# problem. Two retries with the SDK's backoff covers a blip of a few
# seconds; these outlast that.
#
# This is the app-level counterpart to the retry added to
# verification/experiment_flakiness_sweep.py. It is the SDK's own bounded,
# exponentially-backed-off retry -- it does NOT swallow errors, and a
# genuine failure still raises after the budget is spent.
client = anthropic.Anthropic(max_retries=6)

# --- the model, and the only place its identity appears --------------------
# Liam, 2026-09-29 (prototype, internal testing only -- Jonathan has not
# cleared this for agents): default is gpt-6-luna. Reverting to Sonnet is
# one variable: ELIGIBILITY_MODEL=claude-sonnet-4-5. Same switch shape as
# chat.py's CHAT_MODEL / _complete() -- provider dispatch lives in ONE
# function and nowhere else, so a bake-off is an env-var change.
#
# UNVALIDATED ON LUNA: every Tier 2 baseline in this suite was measured
# against Sonnet's output. The verification suite pins ELIGIBILITY_MODEL to
# Sonnet in conftest.py regardless of this default, so the fast and baseline
# tiers keep testing what they were calibrated against; only a real
# deployment (or a test that overrides the env var itself) exercises Luna.
ELIGIBILITY_MODEL = os.environ.get("ELIGIBILITY_MODEL", "gpt-6-luna")

# Reasoning depth for the OpenAI path -- same values and same default as
# chat.py's CHAT_REASONING_EFFORT ('minimal' is rejected; verified against
# the API there).
ELIGIBILITY_REASONING_EFFORT = os.environ.get("ELIGIBILITY_REASONING_EFFORT", "low")

# The Anthropic path's effort (round 28 step 5, 2026-10-07): unset = the model's
# own default (medium on claude-haiku-5-5); "low" / "medium" / "high". Used only
# by Claude 5-generation models (output_config.effort). Measurement only.
ELIGIBILITY_EFFORT = os.environ.get("ELIGIBILITY_EFFORT", "") or None

# Enforced output structure on the OpenAI path (Liam, 2026-09-30). Live
# failure the same day: Luna wrote 23 complete records and left off status and
# flaw_count on every one. A strict json_schema makes the API itself refuse to
# emit a record without them. The API needs an OBJECT at the root, so the
# array is wrapped as {"carriers": [...]}; the bracket extraction in
# check_eligibility already pulls the array out of that. Field order matches
# SYSTEM_INSTRUCTIONS: reasoning first, verdict last.
#
# Default ON, because the acceptance test passed: 10 of 10 real gpt-6-luna
# checks (5 on Liam's PPC-3 profile, 5 on STANDARD) with every record carrying
# a valid status and an integer flaw_count, where 3 of 8 unstructured calls
# the same day had returned no status at all. The schema does NOT prevent
# omissions: Foremost was left out in 3 of the 10 (they get NOT_EVALUATED
# rows). Turn off with ELIGIBILITY_STRUCTURED=0. On the Anthropic path only Claude
# 5-generation models use it (round 28 step 5).
ELIGIBILITY_STRUCTURED = os.environ.get("ELIGIBILITY_STRUCTURED", "1") == "1"

# Round 25 (Liam, 2026-10-03): the rules-table pilot. OFF by default; OFF is
# byte-identical to before. ON: the six carriers in rules_evaluator.PILOT_CARRIERS
# leave retrieval and the main model call; code decides them from the form
# (rules_data/), and one separate call -- in parallel with the main one -- sees
# only the rows code left open. Do not set this on Railway; Liam decides.
RULES_PILOT = os.environ.get("ELIGIBILITY_RULES_PILOT", "0") == "1"
RULES_PILOT_HELP = ('The rules pilot is ON only when the Railway variable ELIGIBILITY_RULES_PILOT is '
                    'exactly "1" (not "true", "yes" or "on"); anything else, or no variable, is OFF. '
                    'The app reads it when it starts, so redeploy after changing it.')
# Round 27 step 6 (Liam's decision 4, 2026-10-06): the Sage batch -- SURE HO-3,
# SafePort HO-3, Wilshire HO3, Trium HO3/HO5, Markel HO3, Vave HO3 -- moves to
# the rules table like the pilot six. Its own switch, exactly "1", default OFF,
# and only with the pilot on. OFF is byte-identical to round 27 step 3. Its rows
# are not yet reviewed: never set on Railway without Liam.
RULES_SAGE_BATCH = RULES_PILOT and os.environ.get("ELIGIBILITY_RULES_SAGE_BATCH", "0") == "1"
# Round 29 step 7 (2026-10-08): the HO3 batch (11 guides), the same pattern: exactly "1",
# only with the pilot on, default OFF. Never set on Railway without Liam.
RULES_HO3_BATCH = RULES_PILOT and os.environ.get("ELIGIBILITY_RULES_HO3_BATCH", "0") == "1"
# Round 29 step 8 (2026-10-08): the remaining (dwelling fire) batch, 14 guides, the same
# pattern. Never set on Railway without Liam.
RULES_DP_BATCH = RULES_PILOT and os.environ.get("ELIGIBILITY_RULES_DP_BATCH", "0") == "1"
# The batch registry's switches (rules_evaluator.BATCHES): registry name -> this module's flag
# name and the panel's label. A further batch is one line here and one entry there.
RULES_BATCH_SWITCHES = {
    "sage": ("RULES_SAGE_BATCH", "Sage batch"),
    "ho3": ("RULES_HO3_BATCH", "HO3 batch"),
    "dp": ("RULES_DP_BATCH", "DP batch"),
}


def _batches_on():
    """The registry names of the batches switched on (read at call time: tests set the flags)."""
    return {name for name, (flag, _) in RULES_BATCH_SWITCHES.items() if globals()[flag]}


def rules_pilot_status_line():
    """Round 27 step 3 (Liam, 2026-10-06): the Fingerprint panel's line, so the
    live site shows whether the Railway variable took effect."""
    if not RULES_PILOT:
        return "Rules pilot: OFF"
    line = f"Rules pilot: ON ({len(rules_evaluator.PILOT_CARRIERS)} carriers)"
    for name, (flag, label) in RULES_BATCH_SWITCHES.items():
        if globals()[flag]:
            line += f" + {label} ON ({len(rules_evaluator.BATCHES[name]['carriers'])} more)"
    return line


# The usage of the last check's calls, for measurement: {"main": ..., "pilot": ...}.
LAST_CALL_USAGE = {}
# What the hold guard did in the last check (round 29 step 1), for measurement.
LAST_GUARD_STATS = {}

_STRING_LIST = {"type": "array", "items": {"type": "string"}}
# Round 26 (Liam, 2026-10-05, decision C): at most two reasons and two
# citations per carrier. Luna's strict mode enforces maxItems (checked live).
_SHORT_LIST = {"type": "array", "maxItems": 2, "items": {"type": "string"}}
CARRIER_RESULTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["carriers"],
    "properties": {
        "carriers": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["carrier", "reasons", "citations", "missing_info", "notes",
                             "status", "flaw_count"],
                "properties": {
                    "carrier": {"type": "string"},
                    "reasons": _SHORT_LIST,
                    "citations": _SHORT_LIST,
                    "missing_info": _STRING_LIST,
                    "notes": {"type": "string"},
                    "status": {"type": "string",
                               "enum": ["ELIGIBLE", "INELIGIBLE", "REFER", "INSUFFICIENT_INFORMATION"]},
                    "flaw_count": {"type": "integer"},
                },
            },
        },
    },
}

# Round 26 step 8 (Liam, 2026-10-05): the strict schema's "carrier" is an enum
# of the exact program names the call is about, so Luna cannot answer under a
# display name ("Orion180", "SageSure Markel") that resolves to nothing and
# leaves the real program NOT_EVALUATED (round 25: 24 such rows in 16 pilot-ON
# runs, 16 in 16 OFF). Set per call through a thread-local, because the main
# and pilot calls run in parallel and tests replace _complete with
# three-argument fakes. ELIGIBILITY_CARRIER_ENUM=0 turns it off (measurement).
CARRIER_ENUM = os.environ.get("ELIGIBILITY_CARRIER_ENUM", "1") == "1"
_CALL = threading.local()


def _results_schema(carriers):
    """CARRIER_RESULTS_SCHEMA, with "carrier" limited to `carriers` when given."""
    if not carriers:
        return CARRIER_RESULTS_SCHEMA
    schema = copy.deepcopy(CARRIER_RESULTS_SCHEMA)
    schema["properties"]["carriers"]["items"]["properties"]["carrier"] = {
        "type": "string", "enum": sorted(set(carriers))}
    return schema


def _complete_named(carriers, system_text, user_content, max_tokens):
    """_complete, with the schema's carrier enum set to `carriers` for this call."""
    _CALL.carriers = list(carriers) if CARRIER_ENUM else None
    try:
        return _complete(system_text, user_content, max_tokens)
    finally:
        _CALL.carriers = None


_openai_client = None


def _is_openai_model(model):
    return model.startswith(("gpt-", "o1", "o3", "o4"))


def _get_openai_client():
    """Lazy, so the Anthropic path never needs OPENAI_API_KEY set."""
    global _openai_client
    if _openai_client is None:
        import openai
        _openai_client = openai.OpenAI(max_retries=6)
    return _openai_client


def _complete(system_text, user_content, max_tokens):
    """THE model call -- the only place ELIGIBILITY_MODEL's identity appears
    below this point. Returns (raw_text, usage_dict); usage_dict's keys are
    Anthropic-shaped (mirrors chat.py's _complete) because that is what the
    cache-visibility print and the truncation diagnostics below already
    speak, and the OpenAI branch maps onto them. "cache_creation_input_tokens"
    has no OpenAI equivalent (its caching is implicit and unbilled-at-write),
    so it stays 0 there -- not a cache write that failed.
    """
    if _is_openai_model(ELIGIBILITY_MODEL):
        return _complete_openai(system_text, user_content, max_tokens)
    return _complete_anthropic(system_text, user_content, max_tokens)


def _is_claude_gen5(model):
    """Claude 5-generation models (claude-haiku-5-5, ...): strict structured
    output via output_config, an effort setting, no temperature (the API
    rejects it: "`temperature` is deprecated for this model"), and thinking
    that counts against max_tokens."""
    m = re.match(r"claude-[a-z]+-(\d+)", model or "")
    return bool(m) and int(m.group(1)) >= 5


def _anthropic_schema(carriers):
    """The production schema for Claude's structured output. Measured
    2026-10-07 on claude-haiku-5-5: the carrier enum and the status enum are
    enforced, but "For 'array' type, property 'maxItems' is not supported" (400),
    so the two-item limit (decision C) is dropped here and enforced on the
    parsed answer by _trim_to_two."""
    schema = copy.deepcopy(_results_schema(carriers))
    item = schema["properties"]["carriers"]["items"]["properties"]
    for key in ("reasons", "citations"):
        item[key] = {k: v for k, v in item[key].items() if k != "maxItems"}
    return schema


def _trim_to_two(text):
    """(text, trimmed): reasons / citations cut to two per record, as Luna's
    strict maxItems does. Unparseable text is returned unchanged."""
    try:
        data = json.loads(text)
    except ValueError:
        return text, 0
    trimmed = 0
    for rec in (data.get("carriers") if isinstance(data, dict) else None) or []:
        for key in ("reasons", "citations"):
            if isinstance(rec, dict) and isinstance(rec.get(key), list) and len(rec[key]) > 2:
                rec[key] = rec[key][:2]
                trimmed += 1
    return (json.dumps(data, ensure_ascii=False) if trimmed else text), trimmed


def _complete_anthropic(system_text, user_content, max_tokens):
    kwargs = dict(
        model=ELIGIBILITY_MODEL,
        max_tokens=max_tokens,
        temperature=0,
        system=[{
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_content}],
        # See the original CHANGED (round 12) note on the caller: an explicit
        # timeout skips the SDK's max_tokens-derived refusal heuristic.
        timeout=900.0,
    )
    gen5 = _is_claude_gen5(ELIGIBILITY_MODEL)
    if gen5:
        # Round 28 step 5 (2026-10-07): production-equal with the Luna path.
        # Older Claude models keep the call above unchanged.
        del kwargs["temperature"]
        kwargs["max_tokens"] = max_tokens + 4000          # thinking counts here, as reasoning does on Luna
        output_config = {}
        if ELIGIBILITY_STRUCTURED:
            output_config["format"] = {"type": "json_schema",
                                       "schema": _anthropic_schema(getattr(_CALL, "carriers", None))}
        if ELIGIBILITY_EFFORT:
            output_config["effort"] = ELIGIBILITY_EFFORT
        if output_config:
            kwargs["output_config"] = output_config
    response = client.messages.create(**kwargs)
    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    trimmed = 0
    if gen5 and ELIGIBILITY_STRUCTURED:
        text, trimmed = _trim_to_two(text)
    usage = response.usage
    return text, {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "stop_reason": getattr(response, "stop_reason", "n/a"),
        "trimmed_lists": trimmed,
    }


def _complete_openai(system_text, user_content, max_tokens):
    """The OpenAI path. A port of the SHAPE, not of the caching strategy --
    see chat.py's _complete_openai for the measured findings (Luna's cache
    keys on the WHOLE prompt, so this pipeline's single-call-per-check shape
    never benefits from it either way)."""
    kwargs = dict(
        model=ELIGIBILITY_MODEL,
        messages=[
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_content},
        ],
        # NOT max_tokens: the OpenAI parameter is max_completion_tokens, and
        # it has to cover REASONING tokens as well as the visible answer --
        # sizing it like an answer-only budget starves the reasoning and
        # returns an empty string with finish_reason="length".
        max_completion_tokens=max_tokens + 4000,
        reasoning_effort=ELIGIBILITY_REASONING_EFFORT,
        # Best-effort determinism only -- Luna rejects temperature=0 (400).
        seed=0,
        timeout=900.0,
    )
    if ELIGIBILITY_STRUCTURED:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "carrier_results", "strict": True,
                            "schema": _results_schema(getattr(_CALL, "carriers", None))},
        }
    response = _get_openai_client().chat.completions.create(**kwargs)
    usage = response.usage
    cached = 0
    if getattr(usage, "prompt_tokens_details", None) is not None:
        cached = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0
    message = response.choices[0].message
    text = message.content or ""
    stop_reason = response.choices[0].finish_reason
    if getattr(message, "refusal", None):
        stop_reason = "refusal: " + str(message.refusal)[:200]
    return text, {
        "input_tokens": usage.prompt_tokens - cached,
        "output_tokens": usage.completion_tokens,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": 0,
        "stop_reason": stop_reason,
    }


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
- HO3 (Homeowners 3): Designed for owner-occupied properties. Not appropriate for tenant-occupied or rental properties. If occupancy is Tenant Occupied or Vacant, HO3 policies should be marked INELIGIBLE for occupancy reason. A Seasonal or Secondary Home is the owner's own home: apply each HO3 guide's own occupancy rules to it (many accept seasonal and secondary residences).
- DP3 (Dwelling Fire 3): Designed for non-owner-occupied properties including rentals and tenant-occupied dwellings. If occupancy is Tenant Occupied, DP3 policies should be evaluated normally and not excluded.
- HOA / HOB / HO6: Condominium and unit-owner programs. HO6 is specifically for condo unit owners.
- If the property's Occupancy Type (given in PROPERTY DETAILS below) is Owner Occupied: Do NOT include DP3 carriers in your response at all. Exclude them entirely.
- If the property's Occupancy Type is Tenant Occupied or Vacant: Do NOT include HO3 or HOMEOWNERS carriers in your response at all. Exclude them entirely. Only evaluate DP3, HOA, HOB, and HO6 programs.
- If the property's Occupancy Type is Seasonal or Secondary Home (the owner's own second home): evaluate the HO3 and DP3 programs in CARRIER DOCUMENTS alike; each guide's own occupancy rules decide.
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

CITATION ATTRIBUTION IS BINDING: every rule you apply to a carrier must come from THAT carrier's own excerpt. Before using any rule to justify a status -- especially INELIGIBLE -- check which carrier's excerpt it actually appeared under (the "--- CarrierName (page N) ---" header above it). If you find yourself writing a citation that names a different carrier than the one you are currently evaluating, that rule does NOT apply to this carrier and must not affect its status, its reasons, or its missing_info -- not even when the two carriers have nearly identical names, are different programs from the same insurer (e.g. an "HOA+" and an "HOB" program from the same company), or plainly cover related products. Two programs from one insurer routinely have DIFFERENT eligibility rules, and one program's age cap, roof rule, or exclusion says nothing about the other's. If a carrier's own excerpt is silent on a topic, that topic is simply unrestricted for that carrier -- never fill the gap with a sibling program's rule.

More generally: when a rule has its own stated conditions (an age threshold, a coverage amount, a home-age-plus-PPC combination) and the given facts place the property OUTSIDE those conditions, the rule simply does not restrict this property -- treat PPC (or whatever the rule covers) as unrestricted here, exactly as if that rule did not exist in the document at all. This means the property PASSES that criterion; it counts toward ELIGIBLE, not toward REFER or missing_info. Do not add anything to missing_info or reasons about "whether the carrier has some other rule" for a combination its own document doesn't address, and do not use REFER for a condition you've just determined doesn't apply. Only flag something as missing when the document's OWN applicable rule (one whose conditions the property actually meets) itself depends on a fact you don't have.

When comparing the property's Home Age, Roof Age (or any given number) against a numeric threshold in a rule (e.g. "eligible up to 20 years", "must be under 15 years"), work out the actual arithmetic comparison explicitly before concluding which side of the threshold the property falls on -- state the comparison itself (e.g. "17 is less than 20, so this condition is met") rather than jumping straight to a conclusion. A carrier's own name (e.g. one containing "Plus" or a product suffix) is NOT evidence about which side of a threshold applies -- only the rule's stated number and the given value decide that.

Pay close attention to whether a threshold is INCLUSIVE or EXCLUSIVE of the boundary value itself, especially when the given value EQUALS the threshold number exactly. "Older than X," "more than X," and "over X" are EXCLUSIVE -- a value of exactly X does NOT satisfy them (e.g. a roof that is exactly 10 years old does NOT meet "required for roofs older than 10 years old"). "X or newer," "X or more," "up to X," and "X or less" are INCLUSIVE -- a value of exactly X DOES satisfy them. When the given value is exactly equal to a rule's stated number, explicitly check the rule's wording for "than"/"over" (exclusive, boundary fails) versus "or"/"up to" (inclusive, boundary passes) before concluding. "Holds/pauses/defers [depreciation or a coverage basis] for N years" is also INCLUSIVE of year N -- a roof at exactly N years old is still within that held/deferred period, so the favorable coverage basis (e.g. RCV) still applies at exactly N. Reach a definite conclusion in these cases -- do not describe the property as merely "at the boundary" without stating which side of it applies.

Carrier documents are frequently split across multiple separate excerpts below, and a rule can be cut off mid-sentence or mid-clause in one excerpt with its continuation appearing in a DIFFERENT excerpt for the SAME carrier (they won't necessarily be adjacent in this prompt). Before concluding that a rule's specific number or detail is "not stated" or "not specified in the retrieved excerpts," check ALL of this carrier's other excerpts for a continuation of the same sentence or clause -- a value that looks absent in one excerpt is often completed a sentence or two later in another.

When a carrier's rule requires a SPECIFIC attribute (an exact fence height, a particular gate mechanism, a named material) and PROPERTY DETAILS only gives a more general description (e.g. Swimming Pool is "In Ground - Fenced" with no height or gate type stated), do not assume the specific requirement is met -- list the specific missing attribute in missing_info. Never state a specific number or detail in reasons, citations, or notes as if it were a fact about THIS property when it actually came from the carrier's rule and was never confirmed by the customer (e.g. do not say "the property has a 4-foot fence" when the customer only said "fenced").

SWIMMING POOL RULES SPECIFICALLY: a pool fence height or gate-mechanism requirement (e.g. "4-foot fence," "self-latching gate," "combination lock or padlock") is a DIFFERENT rule from one carrier's document to the next -- some carriers state a specific number and mechanism, some only say "fenced" or "secured" in general terms, and some don't mention pools at all. Before adding ANY pool-related item to missing_info, or citing a specific height or gate-mechanism type, check THIS carrier's own retrieved excerpt for it specifically:
  - If this carrier's excerpt does not mention swimming pools at all, do not add a pool-related missing_info item for it -- there is nothing to be missing.
  - If this carrier's excerpt only states a GENERAL pool condition ("fenced," "secured," "walled") with no specific height or gate-mechanism menu, and the customer's given Swimming Pool value already describes an enclosed pool (e.g. a value containing "Fenced"), that value already satisfies the condition -- do not manufacture a more specific height/mechanism question the document itself never asks.
  - If this carrier's excerpt lists specific ineligible pool features (e.g. diving board, slide, unfenced) rather than a fence-height/gate requirement, check those specific features against Pool Accessories and Swimming Pool as given, and resolve the rule accordingly -- do not substitute a different carrier's fence-height/gate-mechanism question for it.
  - Only cite a specific fence height or gate-mechanism type if that EXACT figure or mechanism is present in THIS carrier's own excerpt. Do not reuse a specific pool number or mechanism you saw for a different carrier earlier in this same response -- each carrier's pool rule (or absence of one) is independent.

BASE ELIGIBILITY vs. OPTIONAL ENDORSEMENT/COVERAGE: some requirements you'll see (a fence height, a specific material, a distance figure) are conditions of an OPTIONAL endorsement or coverage add-on, not of base policy eligibility -- look for language like "this endorsement," "to qualify for this coverage," or "optional." A condition scoped to an optional endorsement does NOT make the carrier ineligible or create a missing_info blocker if that specific coverage isn't otherwise at issue -- note it in notes as a coverage consideration if relevant, but do not let it drive status or missing_info the way a base eligibility requirement would.

INSPECTION REQUIREMENTS ARE NOT CHECKED BY THIS TOOL. Do not list in missing_info, or base a status on, a requirement that an inspection, photos, a survey, a 4-point or wind-mitigation report, a roofer's letter or Roof Condition Form, a plumber's, electrician's or HVAC contractor's signed statement, or a roof certification be obtained or submitted, including where such a document is what cures a rule. Still apply every rule about the property itself even when an inspection is how it gets verified (e.g. no galvanized plumbing, no more than one overlay).

THE CONDITION OF THE HOME IS NOT CHECKED BY THIS TOOL. A requirement that the home, the roof, a system or an item be in good or proper working condition, well maintained, free of debris, properly installed, or built to / meeting building codes is a condition standard: do not list it in missing_info and do not base a status on it -- including where a guide extends such a standard to a named item (e.g. "not meeting building codes. This includes solar panels" excludes only installations that do not meet code; it says nothing against panels that do). Still apply every rule about a material or a fact (e.g. galvanized plumbing, a roof older than 20 years, no central heat, unrepaired damage).

PROPERTY DETAILS IS THE ONLY SOURCE OF FACTS ABOUT THIS CUSTOMER. Every characteristic of the property -- whether it has solar panels, a pool, dogs, its roof type, its construction, its PPC -- comes from the PROPERTY DETAILS block in this message and from nowhere else. Do not carry a property fact in from a carrier's document, from an example used in these instructions, or from what a typical property might have. In particular, a field whose value is "No"/"None"/"No Pool" is a POSITIVE STATEMENT THAT THE FEATURE IS ABSENT -- it is not a gap to be filled and not an unknown. Before writing any sentence that asserts something about this property, check that PROPERTY DETAILS actually says it. Asserting a feature the intake says the property does not have is a hard error, and an adverse verdict resting on such a feature is the worst kind: it tells an agent a real applicant does not qualify for a carrier they do qualify for.

ROOFING MATERIAL TERMINOLOGY: "Composition Shingle," "Composite Shingle," "Architectural Shingle," "3-tab shingle," and "asphalt shingle" all refer to the SAME underlying family of asphalt-based shingle roofing, and carriers use these terms inconsistently -- one carrier's document may use only one of these phrases, or bundle several together (e.g. "Composite or Architectural Shingle"), to mean the same roofing category the customer's own Roof Type value falls under. If a carrier's document states a rule using ANY of these terms and never uses the customer's EXACT given Roof Type wording, apply that rule to the customer's roof anyway -- do not treat the rule as inapplicable, and do not invent an undefined separate category or lifespan figure "for" the customer's exact wording. Only treat two of these terms as genuinely different categories with different rules if the SAME document explicitly gives them different numeric thresholds.

SOLAR TERMINOLOGY -- INTEGRATED SOLAR ROOFING vs. MOUNTED SOLAR PANELS: these are two different things and carriers exclude only one of them far more often than both. Treat them as separate categories:
  - INTEGRATED SOLAR ROOFING is a roof COVERING made of solar material -- it IS the roof. Signal phrases: "solar roof system," "solar shingles," "solar panel tiles," "solar roof," "Tesla Solar Roof," "BIPV." These appear in lists of roof COVERING MATERIALS alongside things like slate, tin, corrugated metal, wood shakes, rolled tar paper, or built-up tar and gravel. A rule excluding these applies ONLY to a home whose actual roof covering is solar material.
  - MOUNTED SOLAR PANELS are conventional photovoltaic panels attached ON TOP of an ordinary roof (composition/composite/architectural shingle, tile, metal, etc.). The roof covering underneath is unchanged and ordinary.
READ THE CUSTOMER'S ACTUAL "Solar Panels" VALUE BEFORE APPLYING ANY OF THIS. The two cases are:
  - Solar Panels: No -- THIS PROPERTY HAS NO SOLAR OF ANY KIND. Every rule in this section is then irrelevant: no solar exclusion can apply, no solar rule can make a carrier INELIGIBLE, nothing solar-related belongs in missing_info, and you must never write that panels are present, "assumed," or "may be" present. The correct amount to say about solar is nothing at all.
  - Solar Panels: Yes -- the property has MOUNTED PANELS on the roof covering given as its Roof Type; it does NOT mean the roof itself is made of solar material. When a carrier's exclusion list names integrated solar roofing (including when the phrase contains the words "solar panel," as in "solar panel tiles"), that exclusion does NOT apply to such a property, and must not make the carrier INELIGIBLE or generate a missing_info item. Apply a solar rule against it only when the carrier's own text addresses panels mounted on or attached to a roof (e.g. rules about panel installation, attachment, wind/hail damage to panels, or who insures them). If a carrier's text plainly covers both, say which part applies and which does not.
  - A row or line merely stating that solar coverage is AVAILABLE (e.g. "Solar Panel Coverage: Available on endorsement," "optional," "may be added") is a COVERAGE OPTION, not an eligibility restriction and not an open question. It needs no clarification: do not add a solar item to missing_info for it and do not let it hold the carrier at INSUFFICIENT_INFORMATION. Mention it in notes as an available coverage if useful, nothing more.

DO NOT ASSUME AN UNSPECIFIED SUB-CATEGORY: when a carrier's rule keys off a sub-category the customer's given value doesn't specify (e.g. a table with different age brackets for "3-tab" vs. "architectural" composition shingle, when Roof Type is just "Composition Shingle"), do NOT pick one sub-category and state its bracket as the answer -- not even with a hedge like "assuming standard composition." Doing so produces a confidently wrong result. Instead, state each sub-category's outcome explicitly ("if 3-tab: X; if architectural: Y") and put the sub-category itself in missing_info. Never assert one specific bracket, tier, or outcome in reasons or notes while simultaneously listing the fact that determines it as missing -- that is a self-contradiction.

REMAINING-LIFE-EXPECTANCY rules specifically (e.g. "roof should have 3/4 of its life expectancy remaining to qualify for replacement cost coverage"): the TOTAL life expectancy or maximum age figure needed to compute this is very often stated in a DIFFERENT sentence than the fraction itself -- commonly phrased as "should be completely replaced before/by age X" a sentence or two later, for the same or a synonymous roofing category (see ROOFING MATERIAL TERMINOLOGY above). Before concluding a total-life-expectancy figure "is not stated" or "is not fully specified," search ALL of this carrier's other excerpts for such a figure under any synonymous category name. Once found, show the arithmetic explicitly: remaining life = total life expectancy minus Roof Age; required = 3/4 x total life expectancy; state both numbers and whether remaining >= required.

DO NOT DOWNGRADE TO INSUFFICIENT_INFORMATION WHEN EVERY APPLICABLE BRANCH AGREES: some rules are structured as a multi-row table or multi-branch condition (e.g. a Fire-Protection-Class/driving-distance table with several rows). Before concluding a fact is missing and using INSUFFICIENT_INFORMATION, check EVERY row/branch that could possibly apply to the customer's ACTUAL given value (PPC/FPC, roof type, etc.) -- not every row in the whole table, just the ones the given value could land in. If ALL of those applicable rows/branches lead to the SAME eligibility outcome (e.g. every row for this customer's FPC band says "eligible," even if each row attaches DIFFERENT additional conditions like an alarm or road-visibility requirement), that outcome IS the verdict -- do not use INSUFFICIENT_INFORMATION just because the unconfirmed fact would determine WHICH additional conditions apply, when it doesn't change WHETHER the risk is eligible. List the unconfirmed fact in missing_info as something to confirm which conditions apply, and note in notes that eligibility itself doesn't depend on it. Only use INSUFFICIENT_INFORMATION when the applicable rows/branches would produce genuinely DIFFERENT eligibility outcomes (e.g. one applicable row says eligible and another says ineligible) depending on the missing fact.

CITATION ACCURACY: a citation must reproduce the source text's exact wording, not a paraphrase or a more common word substituted for a less common one that happens to fit the customer's situation (e.g. do not write "asphalt shingles" when the source says "asbestos shingles" -- these are different words with different meanings, even though they look and sound similar and even though this customer happens to have an asphalt roof). If you are not fully certain of the exact wording, quote a shorter, unambiguous fragment you ARE certain of rather than a longer one you might be filling in from context.

Return ONLY a JSON array with no text before or after it.
Each object must follow this exact structure -- NOTE the field order: work out reasons, citations, missing_info, and notes FIRST, and only decide status and flaw_count LAST, after that analysis is already written. Do not decide the verdict before you've written the reasoning -- the verdict must be the conclusion your own reasons/notes already reached, never a separate judgment made in advance of them.

[
  {
    "carrier": "carrier name from document",
    "reasons": ["the deciding fact, at most 20 words"],
    "citations": ["carrier name: \"exact short quote from document\""],
    "missing_info": ["Distance to fire station"],
    "notes": "",
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

Output guidelines (keep every card short -- the agent reads dozens of them):
- reasons: at most 2 items, each at most 20 words, ONLY the deciding facts: the rule the property fails, the fact that is still open, or -- for ELIGIBLE -- the one rule that most needed checking. Never restate a fact that passes.
- citations: at most 2, each exactly carrier name: "quote" -- the quote and nothing else, no commentary.
- missing_info: short noun phrases naming each open fact (e.g. "Distance to fire station"), not sentences. List every fact still needed for a final determination.
- notes: at most one sentence, and empty ("") unless it changes what the agent does (e.g. the roof is settled at ACV, not replacement cost; or the guide excludes from coverage something this property has, such as wind/hail damage to its solar panels).
- Do not invent rules not found in the documents
- You MUST include every single carrier that appears in the provided documents. Never skip or omit a carrier. If you cannot determine eligibility for a carrier from the provided excerpts, use status INSUFFICIENT_INFORMATION. All carriers in the context above must appear in your response.
- Return ONLY the JSON array, no other text
"""


# Round 26 step 5 (Liam's live check, 2026-10-05). TWICO's chunk started
# "meeting building codes. This includes solar panels." -- the start of the
# sentence ("Homes of unconventional construction ... or not") is the end of
# the previous stored chunk -- and Luna held TWICO asking for "the complete
# sentence". A chunk that starts mid-sentence now gets the end of the
# previous chunk of the same program (page order, guides._sorted_chunks)
# back to the sentence start, at most _STITCH_CAP characters.
_STITCH_CAP = 300
_SENTENCE_BREAKS = ("\n", ". ", "? ", "! ", "\u2022", "\ufffd")
_PREVIOUS_CHUNK = {"count": None, "by_carrier": {}}


def starts_mid_sentence(text):
    """Lowercase first letter, or a continuation mark (, ; ))."""
    t = (text or "").lstrip()
    return bool(t) and (t[0].islower() or t[0] in ",;)")


def _sorted_chunks_cached(carrier):
    collection = get_vectorstore()._collection
    count = collection.count()
    if _PREVIOUS_CHUNK["count"] != count:
        _PREVIOUS_CHUNK["by_carrier"], _PREVIOUS_CHUNK["count"] = {}, count
    if carrier not in _PREVIOUS_CHUNK["by_carrier"]:
        _PREVIOUS_CHUNK["by_carrier"][carrier] = guides._sorted_chunks(carrier)
    return _PREVIOUS_CHUNK["by_carrier"][carrier]


def sentence_start_from(previous):
    """The end of `previous` from its last sentence break, capped."""
    tail = previous[-_STITCH_CAP:]
    cut = max(tail.rfind(b) + len(b) - 1 for b in _SENTENCE_BREAKS)
    if cut >= 0:
        tail = tail[cut + 1:]
    elif len(previous) > _STITCH_CAP:
        tail = tail[tail.find(" ") + 1:]          # start on a word
    return tail.strip()


def stitched_text(carrier, chunk_text, is_table=False):
    """chunk_text, with the start of its sentence prepended when it begins
    mid-sentence and the previous stored chunk is prose of the same program."""
    if is_table or not starts_mid_sentence(chunk_text):
        return chunk_text
    ordered = _sorted_chunks_cached(carrier)
    for i, (meta, doc) in enumerate(ordered):
        if doc == chunk_text:
            if i == 0 or ordered[i - 1][0].get("is_table"):
                return chunk_text
            head = sentence_start_from(ordered[i - 1][1])
            return head + " " + chunk_text.lstrip() if head else chunk_text
    return chunk_text


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


# Carriers whose FILENAME carries no product token at all. Each is classified
# from its own document text, quoted below, rather than guessed from the name
# -- "HOA+"/"HOB" are Texas homeowners form names, but nothing in the string
# says so to a substring match, and "HOA" would also match HOAIC, which is a
# different company entirely.
#
#   ARI_(HOA+) / ARI_(HOB):
#       "OCCUPANCY/USE Residence must be: - Owner occupied by owner's
#        immediate family."
#   CHUBB_HO_-_05.22.2026:
#       "Eligible Persons Homeowners Insurance Coverage will only be provided
#        and renewed for persons that qualify..."
#
# Before this map they were kept for EVERY occupancy type, so a
# tenant-occupied run was offered three homeowners programs. Measured across
# 44 tenant-occupied executions they reached the output 30-32 times each --
# never as ELIGIBLE (ARI was INELIGIBLE 32/32), so this was scope noise and
# wasted prompt tokens rather than a wrong-decline risk, but it is still
# three carriers an agent should never have been shown for a rental.
_PRODUCT_BY_DOCUMENT = {
    "ARI_(HOA+)": "HOMEOWNERS",
    "ARI_(HOB)": "HOMEOWNERS",
    "CHUBB_HO_-_05.22.2026": "HOMEOWNERS",
}

# Product tokens, matched against a PUNCTUATION-STRIPPED name. That is the
# whole point: "HO-3" and "HO3" are the same program, and the old check used
# a bare `"HO3" in name`, which silently missed Sage_-_SURE_HO-3 and
# Sage_-_SafePort_HO-3 while correctly catching the hyphenated "DP-3"
# alongside "DP3". Deliberately NOT matching bare "HOA"/"HOB" here -- that
# would swallow HOAIC_-_DP_Guide_DP3, which is a dwelling-fire document.
_HOMEOWNERS_TOKEN_RE = re.compile(r"HO3|HO5|HO6|HOMEOWNERS")
_DWELLING_FIRE_TOKEN_RE = re.compile(r"DP1|DP3")


def _strip_to_alnum(text):
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def carrier_programs(carrier):
    """(is_homeowners, is_dwelling_fire) for one carrier document.

    Single source of truth. Three separate places used to re-derive this with
    slightly different substring checks -- get_combined_program_carriers(),
    get_carriers_for_occupancy(), and the post-parse filter in
    check_eligibility() -- which is exactly how the hyphen gap survived in
    two of them while the third handled it.
    """
    override = _PRODUCT_BY_DOCUMENT.get(carrier)
    if override == "HOMEOWNERS":
        return True, False
    if override == "DWELLING_FIRE":
        return False, True

    flat = _strip_to_alnum(carrier)
    return (
        bool(_HOMEOWNERS_TOKEN_RE.search(flat)),
        bool(_DWELLING_FIRE_TOKEN_RE.search(flat)),
    )


def get_combined_program_carriers():
    """Carriers whose filename bundles more than one program, e.g.
    Foremost_DP3_and_HO3_-_07.01.2026.pdf. These must never be excluded
    by the DP3/HO3 occupancy heuristic -- they're valid for both."""
    combined = set()
    for carrier in get_all_carriers():
        is_ho, is_dp = carrier_programs(carrier)
        if is_ho and is_dp:
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


# Round 29 step 7: the form's plumbing answers that guides decline, and the word each guide uses.
_PLUMBING_MATERIAL_WORDS = {"Galvanized": "galvaniz", "Polybutylene": "polybutylene"}


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
    embedding-rank lottery problem as PPC, pool, and solar.

    CHANGED (round 12): "life expectancy" alone was far too narrow a
    signal. Carriers state the same KIND of roof-age rule in wording that
    never uses that phrase -- Orion's "Roof Material Payment Schedule
    required for the specified roof ages: 16 years and older for
    architectural and composite shingles", TWICO's and Swyfft's
    RCV/ACV/Excluded age-band tables, Mercury's Loss Settlement Payment
    Schedule. Measured across the whole carrier set, the old predicate
    matched ZERO chunks for Orion (whose clause appears in 4 separate
    chunks), TWICO, and all four Swyfft programs -- so their roof-age
    rules had no retrieval guarantee at all and rode entirely on the
    embedding-rank lottery. That directly explains two separate findings:
    Orion's clause appearing in one live run and not the next, and TWICO
    going completely silent on roof/tile in a real run. Broadened to cover
    payment-schedule and age-band phrasings of the same underlying rule."""
    lower = content.lower()
    return (
        "life expectancy" in lower
        or "years old based on national statistics" in lower
        or "payment schedule" in lower
        or "years and older" in lower
        # RCV/ACV/Excluded age-band table (TWICO, Swyfft Lloyds, et al.)
        or ("roof" in lower and "acv" in lower and "excluded" in lower)
    )


# Roof SHAPE restrictions, keyed to the shapes the intake can actually emit
# (see app.py's Roof Shape selectbox). Only shapes carriers actually restrict
# need a guarantee -- Gable and Hip are the unremarkable defaults and appear
# in almost no ineligibility list.
_RESTRICTED_ROOF_SHAPES = {
    "flat": ("flat",),
    "gambrel": ("gambrel",),
    "mansard": ("mansard",),
}


def _mentions_roof_shape_rule(content, shape_keywords):
    """A rule about the customer's ROOF SHAPE, as opposed to its material or
    its age.

    Round 14: roof shape was the one major intake field with no guaranteed
    lookup at all -- PPC, pool, solar and roof AGE each got one, but shape
    rode entirely on embedding rank. Measured on the round 14 DP3 profile
    (Roof Shape: Flat): 14 of 18 carriers state a flat-roof rule and 5 of
    them never reached the prompt, including Centauri DP3, whose text reads
    "ROOFS/SIDING - Ineligible: ... g. Flat (unless poured concrete)". The
    live run consequently said Centauri's "excerpt does not explicitly
    exclude flat roofs", which is exactly backwards. On this profile the
    verdict happened to land ineligible for another reason; on a profile
    with a newer roof it would have returned ELIGIBLE for a carrier that
    flatly excludes the risk.

    Requires the shape word to sit near roof/roofing/dwelling language so a
    stray "flat" (e.g. "flat fee", "flat deductible") is not mistaken for a
    roof-shape rule.
    """
    lower = content.lower()
    for word in shape_keywords:
        for match in re.finditer(re.escape(word), lower):
            window = lower[max(0, match.start() - 160): match.end() + 160]
            if any(k in window for k in ("roof", "dwelling", "structure", "siding")):
                return True
    return False


# Signals that a chunk states WHO or WHAT DWELLING a carrier will insure at
# all -- occupancy, ownership, named-insured eligibility. Deliberately NOT a
# bare "named insured": across this corpus that phrase is mostly noise
# (Sage's scheduled-jewelry questions "Occupation of each Named Insured",
# credit-score rating text, Liberty Mutual's "the contractor is not the named
# insured" course-of-construction rule, binding-procedure steps). Measured
# against the round-17 family survey: 13/13 genuine rules matched, 0 of 16
# known-noise chunks matched.
# Ownership entities as a regex fragment. Word-bounded on purpose: "trustee"
# must not count as "trust" -- Sage's foreclosure rule reads "bank or trustee
# sale are only acceptable if...", which is about how the home was bought.
_OWNERSHIP_ENTITY = (
    r"(?:trusts?|llcs?|llps?|l\.l\.c\.|corporations?|corp\b|business(?:es)?"
    r"|estates?|partnerships?|ira)\b"
)

# Round 17, Liam's decision: the guarantee is split in two.
#
#   OCCUPANCY rules -- who must live there, what kind of dwelling. This is the
#   CHUBB clause-2 fix itself. It was first run for EVERY property; since
#   2026-09-28 it runs only inside the Trust / LLC guarantee, and will run on
#   its own for second homes (see _occupancy_guarantee_applies for why an
#   individual owner no longer gets it).
#
#   ENTITY-OWNERSHIP rules -- trust and LLC/business ownership, exclusions and
#   permissions alike. ONLY when ownership_type is Trust or LLC. Such a rule
#   cannot change an individual owner's verdict, and trust/LLC properties are
#   rare, so the common case should not carry their tokens or spend capped
#   slots on them.
_OCCUPANCY_RULE_RE = re.compile(
    r"owner[- ]?occup(?:ied|ant|ancy)"
    r"|\beligible persons?\b"
    r"|occupancy\s*(?:and|/)\s*use"
    r"|(?:must be|not)\s+occupied by"
    # Title held by the occupant. Narrowed from a bare "deeded to" so Orion's
    # ENTITY rule ("Properties deeded to or owned by a corporation, limited
    # liability company ...") does not ride in on the occupancy side.
    r"|\bdeeded to the named insured\b",
    re.I,
)

_OWNERSHIP_ENTITY_RULE_RE = re.compile(
    r"owned by (?:a|an)\s+(?:business|corporation|llc|limited liability|partnership)"
    # An ownership ENTITY tied to an eligibility or named-insured verdict.
    # Deliberately NOT "not acceptable" / "unacceptable" / bare "may not":
    # those matched Allied Trust's MORTGAGE rule -- "applicants must have a
    # mortgage through an acceptable financial institution ... trust and/or
    # bond for deeds are not acceptable" -- which is about financing, not
    # ownership, and it won a slot over a genuine occupancy rule.
    r"|\b(?:llc|l\.l\.c\.|corporations?|trusts?|partnerships?)\b[^.]{0,80}?"
    r"\b(?:ineligible|not eligible|(?:may not|cannot|can not|not) be (?:listed|named|insured))"
    # PERMISSIVE, CONDITIONAL and REFERRAL ownership rules. The first cut of
    # this predicate was built from exclusion language only. Measured on a
    # clean Trust/LLC profile, every flat LLC exclusion reached the prompt
    # (10/10) while the rules that PERMIT or CONDITION ownership did not:
    # Sage Markel "Residence held by corporations, including LLCs, is
    # eligible", Sage Vave, Foremost, Travelers, Orion's living-trust rule,
    # Swyfft Topa's referral, and Allied Trust's own conditional clause
    # "Properties owned in the name of a trust are eligible if the grantor(s)
    # are still residing in the dwelling". For an LLC or trust property those
    # are exactly the rules that prevent a WRONG DECLINE -- SYSTEM_INSTRUCTIONS
    # carries a generic "most HO3 carriers do not accept LLC" line the model
    # could otherwise fall back on.
    r"|\b(?:in|under) the name of (?:a|an|the)\s+(?:\w+\s+){0,3}?" + _OWNERSHIP_ENTITY
    + r"|\bheld (?:in|by) (?:a\s+)?(?:\w+\s+){0,2}?" + _OWNERSHIP_ENTITY
    + r"|\b" + _OWNERSHIP_ENTITY + r"[^.]{0,60}?\b(?:is|are)\s+(?:only\s+)?(?:eligible|allowed|acceptable)\b"
    + r"|allowed on title|non-personal entit|only eligible business",
    re.I,
)

# Language that DECIDES eligibility, as opposed to mentioning occupancy in
# passing (a coverage-form definition, an endorsement's scope).
_DECISIVE_OCCUPANCY_RE = re.compile(
    r"ineligib|not eligible|\beligible persons?\b|may not be listed"
    r"|must be (?:owner[- ]?occupied|occupied by|deeded)|owned by (?:a|an) "
    # A conditional permission or a referral decides the outcome as surely as
    # an exclusion does -- "eligible IF the grantor resides", "must be
    # referred to Underwriting" -- so it must not rank below passing mentions.
    r"|\b(?:is|are) (?:only )?eligible\b|\beligible (?:if|only|when)\b|only eligible"
    r"|must be referred|underwriting approval|submit for approval|allowed on title",
    re.I,
)

# Per-carrier cap for the occupancy guarantee. Module-level (not local to
# check_eligibility) so tests use the SAME value production does -- a test
# with its own hardcoded copy is exactly how this suite has been fooled before.
#
# 6, measured, not guessed, and measured TWICE because the first answer went
# stale. The first sweep (exclusion-only predicate) chose 5. Adding the
# permissive / conditional / referral ownership rules gave Allied Trust more
# genuine chunks than 5 holds, so it was re-swept against the real acceptance
# criterion -- the named rules in the round-17 tests reaching the prompt, on a
# clean owner-occupied profile, per Ownership Structure:
#
#     cap   Individual   Trust    LLC     prompt (clean profile)
#      5      10/10      29/30   30/30    33,622 tok
#      6      10/10      30/30   30/30    34,388 tok   <- smallest with all
#      7      10/10      30/30   30/30    34,518 tok
#
# The miss at 5 is Allied Trust's "Homes not occupied by the named insured"
# for a Trust profile -- genuine, and relevant, since that carrier's trust
# rule hinges on who occupies. Pre-fix the same prompt was 23,759 tok, so the
# guarantee costs about +10.6K input tokens per run on this profile. A
# carrier's own brand is stripped before ranking (see _carrier_brand), and
# "business" only counts as an ownership term when it is the owner -- both
# measured defects of the ranking, not of the cap.
#
# Since the Individual-Owner gate, this is the TRUST / LLC cap only.
MAX_OWNERSHIP_CHUNKS_PER_CARRIER = 6

# The occupancy-only predicate's cap. It was the Individual Owner cap until
# 2026-09-28, when individual owners stopped getting the guarantee (see
# _occupancy_guarantee_applies); it is kept for second homes, the one place
# occupancy rules alone decide the answer. The sweep that chose it:
# Swept 1-6 on the occupancy-only predicate against the eight occupancy rules
# the round-17 tests name, on STANDARD and the clean ownership base profile,
# with REAL token counts from messages.count_tokens:
#
#     cap   STANDARD tokens   missing
#      1        44,385        CHUBB clause 2, AT not-occupied, Prog HO3, Sage x2
#      2        46,681        AT "not occupied by the named insured"
#      3        49,332        -          <- smallest with all eight
#      4        50,449        -
#      6        51,791        -
#
# Pre-branch main is 42,864 on the same profile, so the CHUBB clause-2 fix
# itself costs an ordinary customer about +6.5K input tokens (+15%).
MAX_OCCUPANCY_CHUNKS_PER_CARRIER = 3

_OWNERSHIP_STRUCTURES_WITH_ENTITY_RULES = {"Trust", "LLC"}


# Liam's decision, 2026-09-28: the guarantee runs only where occupancy or
# ownership rules actually decide answers -- Trust and LLC properties today,
# and second homes once they are routed to HO carriers (after the Luna
# cutover). For an individual owner the round-17 verdict diff (main 72e34db
# vs the gated guarantee, 4 profiles x 3 runs) found no verdict made better,
# three made worse in 3/3 runs -- one of them, CHUBB's tiering section,
# directly by what the guarantee added -- and 19 better citations, at +5.2K
# to +6.6K input tokens (about 2 cents) a check. Individual owners trade those
# 19 citations for zero extra cost and zero new regressions: their prompt is
# byte-identical to 72e34db's. The occupancy-only predicate and its cap stay;
# second homes will use them.
# --- the three OPTIONAL intake fields (Liam, 2026-09-30) -------------------
# County, Dwelling amount (Coverage A), Dwelling type. Blank = unknown. A
# blank field must leave the prompt BYTE-IDENTICAL to what it was before the
# fields existed (Liam has objected to prompt growth twice), so each fact
# line, the House routing and the Coverage A guarantee act only when filled.

def _county(property_details):
    return intake_fields.normalize_county(property_details.get("county"))


def _dwelling_amount(property_details):
    return intake_fields.parse_dwelling_amount(property_details.get("dwelling_amount"))


def _dwelling_type(property_details):
    return intake_fields.normalize_dwelling_type(property_details.get("dwelling_type"))


def _is_condo_program(carrier):
    """HO6 is the condominium unit-owners form (Progressive HO6, Liberty
    Mutual HO6)."""
    return "HO6" in _strip_to_alnum(carrier or "")


def _pool_fence_4ft(property_details):
    return intake_fields.pool_box(property_details, "pool_fence_4ft")


def _pool_gate_locking(property_details):
    return intake_fields.pool_box(property_details, "pool_gate_locking")


def _pool_fact_lines(property_details):
    """PROPERTY DETAILS lines for a TICKED pool box, each starting with a
    newline; "" when neither is ticked (unchecked means unknown)."""
    lines = []
    if _pool_fence_4ft(property_details):
        lines.append("Pool Fence Height: confirmed 4 feet or higher")
    if _pool_gate_locking(property_details):
        lines.append("Pool Gate: confirmed self-latching and can be locked")
    return "".join("\n" + line for line in lines)


def _territory_fact_line(county, carriers):
    """Round 22 (Liam, 2026-10-02). One computed line for the carriers in
    this prompt that have the Sage ADDRESS rule and whose territory the
    County is INSIDE; "" when the County is blank or no such carrier is in
    the prompt. Outside counties are decided in code (_apply_location_holds)
    and get no line. The path depends only on the county, so it is one line."""
    if not county:
        return ""
    inside = [c for c in carriers if c in _SAGE_LOCATION_RULE and sage_county_in_territory(
        county, intake_fields.COUNTY_MAX_LATITUDE, _SAGE_LOCATION_RULE[c][0]) == "IN"]
    if not inside:
        return ""
    path = ("named East Texas county" if county in SAGE_EAST_TEXAS_COUNTIES
            else "South Texas (entirely south of 31 N)")
    return (f"Territory (computed): {county} County is inside this guide's territory -- {path} "
            f"-- for {', '.join(inside)}.")


def _property_details_text(pd, home_age, occupancy, ownership, checked, carriers=()):
    """The PROPERTY DETAILS block. A line whose topic is unchecked is left
    out (Liam: not considered at all); with everything checked the text is
    byte-identical to the round 20 template."""
    rows = [
        (None, "State: TX"),
        ("fact:year_built", f"Year Built: {pd['year_built']}"),
        ("fact:home_age", f"Home Age: {home_age} years"),
        ("fact:roof_age", f"Roof Age: {pd['roof_age']} years"),
        ("fact:roof_type", f"Roof Type: {pd['roof_type']}"),
        ("fact:roof_shape", f"Roof Shape: {pd['roof_shape']}"),
        ("fact:construction_type", f"Construction Type: {pd['construction_type']}"),
        ("fact:plumbing_type", f"Plumbing Type: {pd['plumbing_type']}"),
        (None, f"Occupancy Type: {occupancy}"),
        (None, f"Ownership Structure: {ownership}"),
        ("fact:coastal_tier", f"Coastal Tier: {pd['coastal_tier']}"),
        ("fact:swimming_pool", f"Swimming Pool: {pd['swimming_pool']}"),
        ("fact:pool_accessories", f"Pool Accessories: {pd['pool_accessories']}"),
    ]
    rows += [("fact:pool_boxes", line) for line in _pool_fact_lines(pd).split("\n")[1:]]
    rows += [
        ("fact:has_dogs", f"Dogs on Premises: {pd['has_dogs']}"),
        ("fact:aggressive_breed", f"Aggressive Breed Dogs: {pd['aggressive_breed']}"),
        ("fact:solar_panels", f"Solar Panels: {pd['solar_panels']}"),
        ("fact:ppc", f"PPC Number: {pd['ppc']}"),
    ]
    # Round 26 (Liam, 2026-10-05, decision B): stated only when filled, so a
    # blank / Unknown answer leaves the prompt byte-identical.
    miles = intake_fields.parse_station_miles(pd.get("fire_station_miles"))
    hydrant = intake_fields.hydrant_answer(pd.get("hydrant_1000ft"))
    if miles is not None:
        rows.append(("fact:fire_station_miles", f"Driving Distance to Responding Fire Station: {miles:g} miles"))
    if hydrant:
        rows.append(("fact:hydrant_1000ft", f"Hydrant Within 1,000 Feet: {hydrant}"))
    county, amount, dtype = _county(pd), _dwelling_amount(pd), _dwelling_type(pd)
    if county:
        rows.append(("fact:county", f"County: {county}"))
        territory = _territory_fact_line(county, carriers)
        if territory:
            rows.append(("fact:county_territory", territory))
    if amount:
        rows.append(("fact:dwelling_amount", f"Dwelling Amount (Coverage A): ${amount:,}"))
    if dtype:
        rows.append(("fact:dwelling_type", f"Dwelling Type: {dtype}"))
    return "PROPERTY DETAILS:\n" + "\n".join(
        line for step, line in rows if step is None or _on(step, checked))


def _partial_check_instruction(checked):
    """Only for a partial selection (decision 1); "" when everything is checked."""
    if not topics.is_partial(checked):
        return ""
    others = ", ".join(t.label for t in topics.unchecked(checked))
    return ("\n\nPARTIAL CHECK: only the facts listed in PROPERTY DETAILS are being checked. "
            f"Ignore every rule about any other topic ({others}). Never list one of those "
            "topics in missing_info or reasons.")


def _optional_fact_lines(property_details):
    """Extra PROPERTY DETAILS lines, one per FILLED optional field, each
    starting with a newline; "" when all three are blank."""
    lines = []
    county = _county(property_details)
    if county:
        lines.append(f"County: {county}")
    amount = _dwelling_amount(property_details)
    if amount:
        lines.append(f"Dwelling Amount (Coverage A): ${amount:,}")
    dtype = _dwelling_type(property_details)
    if dtype:
        lines.append(f"Dwelling Type: {dtype}")
    return "".join("\n" + line for line in lines)


# A carrier's own Coverage A / dwelling LIMIT rule: a minimum, maximum or
# binding authority with a dollar figure. Swept 2026-09-30 over the 25 usable
# owner-occupied carriers: the top-ranked match is the real limit for 21
# (e.g. Allied Trust "$200,000 to $1,250,000", HOAIC "$150,000 minimum, up to
# $2,000,000", Progressive "maximum Coverage A - Dwelling Binding Authority is
# $1,500,000"). Known misses: Swyfft Benchmark (Admitted) picks a percentage
# row, Swyfft Topa/Lloyds a total-insured-value cap, CHUBB its water-shutoff
# table; ARI (HOA+) has none.
_COV_A_MONEY = r"\$\s?\d[\d,.]*\s*(?:k\b|m\b|mm\b|million)?"
_COV_A_LIMIT = (r"(?:minimum|maximum|max\.?|min\.?|binding\s+authority|limit(?:s)?\s+(?:above|over|up\s+to)"
                r"|up\s+to|less\s+than|greater\s+than|over|above|in\s+excess\s+of)")
_COV_A_NAME = (r"(?:coverage\s*a\b|cov\.?\s*a\b|dwelling\s+(?:coverage|limit|value)s?"
               r"|coverage\s*a\s*[-–]\s*dwelling)")
_COVERAGE_A_LIMIT_RE = re.compile(
    _COV_A_LIMIT + r"[^.|]{0,40}?" + _COV_A_NAME + r"[^.|]{0,80}?" + _COV_A_MONEY
    + r"|" + _COV_A_NAME + r"[^.]{0,60}?" + _COV_A_LIMIT + r"[^.]{0,40}?" + _COV_A_MONEY
    + r"|" + _COV_A_LIMIT + r"[\s|]{0,6}" + _COV_A_MONEY + r"[^.|]{0,12}?" + _COV_A_NAME
    + r"|" + _COV_A_NAME + r"\s*(?:\([^)]*\))?\s*:\s*(?:maximum\s+)?" + _COV_A_MONEY
    + r"|" + _COV_A_MONEY + r"[^.|]{0,20}?(?:minimum|maximum)?\s*" + _COV_A_NAME + r"\s*(?:minimum|maximum)",
    re.I)
_PERCENT_OF_COV_A_RE = re.compile(r"%\s+of\s+(?:the\s+)?(?:policy.s\s+)?coverage\s*a", re.I)
MAX_COVERAGE_A_CHUNKS_PER_CARRIER = 1


def _mentions_coverage_a_limit(content):
    return bool(_COVERAGE_A_LIMIT_RE.search(content))


def _coverage_a_priority_key(doc):
    t = doc.page_content
    s = 3 * len(re.findall(r"(?i)maximum|minimum|binding authority", t)[:2])
    s += min(3, len(re.findall(_COV_A_MONEY, t)))
    s -= 4 * bool(_PERCENT_OF_COV_A_RE.search(t))
    s -= 3 * bool(re.search(r"(?i)flood policy|nfip|wave ?wash|ordinance and law", t))
    return -s


def _occupancy_guarantee_applies(property_details):
    return property_details.get("ownership_type", "") in _OWNERSHIP_STRUCTURES_WITH_ENTITY_RULES


# Tier PLACEMENT is pricing, decided after eligibility. CHUBB's "VIII.
# Tiering Guidelines": "Risks that qualify for homeowners insurance based on
# the criteria in sections I-III, become eligible for placement in our
# Standard Tier ... for risks that qualify for discounted pricing." Its
# "Discount Tier Conditions" include "Primary residence must be single family
# or two family home and owner-occupied" -- an occupancy phrase under a
# pricing heading. Matched without the heading, it rode into the prompt and
# ALT CHUBB went ELIGIBLE 3/3 -> INSUFFICIENT_INFORMATION 3/3 on "which tier".
# A retrieval predicate is a phrase search, and a phrase found without its
# heading is this project's recurring wrong-answer cause.
#
# Swept over all 2,491 chunks in the store: of the 8 this pattern hits, only
# CHUBB's page-8 chunk also matches the guarantee, so it is the only one
# removed. Bare "tier" is deliberately not a term -- Texas coastal "First
# Tier" counties appear in 58 chunks.
_TIER_PLACEMENT_RE = re.compile(
    r"\btier(?:ing)?\s+(?:conditions|guidelines|placement)\b"
    r"|\bqualify for (?:the |our )?(?:\w+\s+){0,2}tier\b"
    r"|\bdiscounted pricing\b",
    re.I,
)


def _is_tier_placement(content):
    return bool(_TIER_PLACEMENT_RE.search(content))

# Terms that tie a chunk to one specific Ownership Structure intake value.
_OWNERSHIP_TERMS = {
    # Bare "business" is deliberately NOT a term: it boosted Allied Trust's
    # scheduled-personal-property rule ("scheduled property used in any
    # insured's business or profession is not eligible for this coverage") over
    # genuine occupancy rules for an LLC profile. Business only counts when it
    # is the OWNER.
    "LLC": re.compile(
        r"\bllcs?\b|l\.l\.c|limited liability|non-individual|non-personal entit"
        r"|\bcorporations?\b|\bcorp\b|partnerships?"
        r"|(?:owned by|in the name of|held by|deeded to|titled (?:to|in))[^.]{0,40}\bbusiness",
        re.I),
    "Trust": re.compile(r"\btrusts?\b", re.I),
}


def _mentions_occupancy_eligibility(content):
    """A rule about WHO the carrier will insure, or in WHAT kind of dwelling:
    occupancy, ownership structure, named-insured eligibility.

    Round 17: this is the most fundamental eligibility question a guide
    answers, and it had no guaranteed lookup -- it rode entirely on embedding
    rank, like PPC, pool, solar, roof age and roof shape each did before they
    got one. Surfaced by the long-standing CHUBB backlog item ("cites the
    multi-unit clause instead of the single-family 'a house' clause"), which
    had the SYMPTOM right and the cause wrong. CHUBB's Eligible Persons
    section spans two chunks:

        1. owner-occupant of a MULTIPLE UNIT dwelling (<=2 units) ...
        2. owner-occupant or tenant of ... a house, a condominium unit ...

    Retrieval kept the first chunk and dropped the second, so clause 2 never
    reached the prompt. The model cited clause 1 because it was the only
    eligible-persons clause it was ever shown -- 16/20 recorded STANDARD
    runs cited it, 0/20 cited clause 2, and a few reasoned that an
    owner-occupied SINGLE-FAMILY home "satisfies" a multiple-unit-dwelling
    clause. The model had nothing else to pick.

    RECLASSIFIED after measuring: correct verdict basis, citation not
    decidable from the current intake. With clause 2 in every prompt the model
    still often cites clause 1 -- but the intake has no dwelling-type or
    unit-count field, so "single-family", the one fact separating clause 1
    (<=2-unit dwelling) from clause 2 (a house, a condominium unit, ...), is
    never given to it, and both clauses make an owner-occupant eligible.
    Citing clause 1 is one of two valid answers. The genuine reasoning error
    -- inventing a dwelling type, as 3 of 20 pre-fix runs did -- was absent in
    all 3 post-fix runs and is now hard-asserted. What this guarantee fixes is
    that the model can SEE CHUBB's whole eligible-persons section. A
    dwelling-type field is a product decision; no prompt text should push the
    model to assume single-family.

    The family survey found the same miss on about nine carriers, where it
    is silent rather than visible -- Allied Trust (all three of its rules),
    Orion, Progressive HO3, and five Sage programs. For Allied Trust it is
    verdict-bearing: its "Properties owned by a business, corporation..."
    exclusion did not reach the prompt for an LLC-owned property, although
    that is precisely the rule that decides it. (It DID reach for a Trust
    profile, because "trust" happens to sit close to that chunk in
    embedding space and "LLC" does not -- the ranking lottery in miniature.)
    """
    return _mentions_occupancy_rule(content) or _mentions_ownership_entity_rule(content)


def _mentions_occupancy_rule(content):
    """Occupancy half only: who lives there, what kind of dwelling. Part of
    every Trust / LLC guarantee, and on its own the predicate second homes
    will use -- see _occupancy_guarantee_applies. Never a tier-placement
    (pricing) section."""
    return bool(_OCCUPANCY_RULE_RE.search(content)) and not _is_tier_placement(content)


def _mentions_ownership_entity_rule(content):
    """Entity-ownership half: trust and LLC/business rules, exclusions and
    permissions alike. Only for Trust / LLC properties. Never a
    tier-placement (pricing) section."""
    return bool(_OWNERSHIP_ENTITY_RULE_RE.search(content)) and not _is_tier_placement(content)


def _occupancy_predicate_for(ownership):
    """The guarantee's predicate for this Ownership Structure. An individual
    owner gets occupancy rules only -- an LLC exclusion or a trust condition
    cannot change that customer's verdict."""
    if ownership in _OWNERSHIP_STRUCTURES_WITH_ENTITY_RULES:
        return _mentions_occupancy_eligibility
    return _mentions_occupancy_rule


def _occupancy_cap_for(ownership):
    if ownership in _OWNERSHIP_STRUCTURES_WITH_ENTITY_RULES:
        return MAX_OWNERSHIP_CHUNKS_PER_CARRIER
    return MAX_OCCUPANCY_CHUNKS_PER_CARRIER


def _carrier_brand(carrier):
    """The insurer's name as it appears in running text: "Allied_Trust_HO3"
    -> "allied trust". Product tokens, dates and punctuation removed."""
    stem = re.sub(r"\d{2}\.\d{2}\.\d{4}", " ", carrier or "")
    words = [w for w in re.split(r"[^A-Za-z]+", stem)
             if w and not re.fullmatch(r"(?i)ho|dp|hoa|hob|tx|and", w)]
    return " ".join(words[:2]).lower() if len(words) >= 2 else ""


def _occupancy_priority_key(ownership):
    """Rank matching chunks so the ones that decide THIS property survive the
    per-carrier cap.

    Ownership-aware on purpose. Allied Trust has more matching chunks than
    the cap holds; without this, an LLC-owned property can fill the cap with
    owner-occupancy chunks and still drop the business-ownership exclusion
    that is the only rule actually in question. Tables of contents
    ("I. Eligible Person 2-3  II. Physical Conditions 4-5 ...") match on the
    heading alone and carry no rule, so they sort last.
    """
    own_terms = _OWNERSHIP_TERMS.get(ownership)

    def key(chunk):
        lower = chunk.page_content.lower()
        # Strip the carrier's own BRAND before looking for ownership terms.
        # Every Allied Trust chunk says "Allied Trust", so without this a Trust
        # profile boosted all of that carrier's chunks equally -- the
        # ownership-aware ranking did nothing for the one carrier whose trust
        # rule it most needed to surface.
        brand = _carrier_brand(chunk.metadata.get("carrier", ""))
        scan = lower.replace(brand, " ") if brand else lower
        is_toc = len(re.findall(r"\b[ivx]+\.\s", lower)) >= 3 or lower.count("....") >= 3
        return (
            not (own_terms is not None and own_terms.search(scan)),
            is_toc,
            # Third, prefer a chunk that DECIDES eligibility. Without this an
            # Individual Owner profile -- no ownership terms to rank on -- fell
            # back to raw database order, and Allied Trust kept a coverage-form
            # "owner occupied" mention while dropping "Ineligible - Homes not
            # occupied by the named insured".
            not _DECISIVE_OCCUPANCY_RE.search(lower),
        )
    return key


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


def _fits_occupancy(carrier, occupancy, combined):
    """The one occupancy routing rule, shared by get_carriers_for_occupancy
    and the data-defect rows (which must route a program the store does not
    hold -- Centauri HO3 -- exactly as it would route one it does)."""
    if carrier in combined:
        return True
    is_ho, is_dp = carrier_programs(carrier)
    if occupancy == "Owner Occupied" and is_dp:
        return False
    if occupancy != "Owner Occupied" and is_ho and not _owners_other_home_fits(carrier, occupancy):
        return False
    return True


# Round 29 step 4 (Liam's decision 2, 2026-10-08): a Seasonal or Secondary Home is the
# owner's own home, so it is routed to HO3 programs as well as DP programs, and each
# guide's occupancy rows decide. Tenant Occupied and Vacant stay DP-only; HO6 (condo
# unit-owner) routing is unchanged.
OWNERS_OTHER_HOMES = ("Seasonal", "Secondary Home")


def _owners_other_home_fits(carrier, occupancy):
    return occupancy in OWNERS_OTHER_HOMES and not _is_condo_program(carrier)


def get_carriers_for_occupancy(occupancy):
    combined = get_combined_program_carriers()
    return [c for c in sorted(get_all_carriers()) if _fits_occupancy(c, occupancy, combined)]


def _on(step, checked):
    """Is this gated step on for the selection? See topics.STEPS. An untagged
    step name is a KeyError, so a new step cannot slip in ungated."""
    return topics.step_on(step, checked)


def build_retrieval_query(property_details, home_age, checked=None):
    """The similarity-search query used for the per-carrier retrieval pass
    in check_eligibility(). Factored out so verification/diagnose_carrier.py
    can run the identical query against a single carrier -- duplicating
    this inline would drift out of sync with the real prompt over time.

    checked: the selected topics (None = all). A line about an unchecked
    topic is left out; with everything checked the text is unchanged."""
    checked = topics.normalize(checked)
    pd = property_details
    occupancy = pd['occupancy_type']
    rows = [
        (None, "homeowners insurance eligibility requirements:"),
        (None, "state TX"),
        ("query:year_built", f"year built {pd.get('year_built')}"),
        ("query:year_built", f"home age {home_age} years"),
        ("query:roof_age", f"roof age {pd.get('roof_age')} years"),
        ("query:roof_type", f"roof type {pd.get('roof_type')}"),
        ("query:roof_shape", f"roof shape {pd.get('roof_shape')}"),
        ("query:construction_type", f"construction type {pd.get('construction_type')}"),
        ("query:plumbing_type", f"plumbing type {pd.get('plumbing_type')}"),
        (None, f"occupancy {occupancy}"),
        (None, f"ownership {pd.get('ownership_type', 'Individual Owner')}"),
        ("query:coastal_tier", f"coastal {pd.get('coastal_tier')}"),
        ("query:swimming_pool", f"swimming pool {pd.get('swimming_pool')}"),
        ("query:swimming_pool", f"pool accessories {pd.get('pool_accessories')}"),
        ("query:dogs", f"dogs on premises {pd.get('has_dogs')}"),
        ("query:dogs", f"aggressive breed dogs {pd.get('aggressive_breed')}"),
        ("query:solar_panels", f"solar panels {pd.get('solar_panels')}"),
        ("query:ppc", f"protection class PPC {pd.get('ppc')}"),
    ]
    return "\n" + "".join(f"    {line}\n" for step, line in rows
                           if step is None or _on(step, checked)) + "    "


def build_risk_factors(property_details, occupancy, checked=None):
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
    checked = topics.normalize(checked)
    risk_factors = []

    if _on("risk:plumbing", checked) and property_details['plumbing_type'] in ['Galvanized', 'Polybutylene']:
        risk_factors.append("galvanized polybutylene plumbing ineligible requirements")

    if _on("risk:pool", checked) and 'Unfenced' in property_details['swimming_pool']:
        risk_factors.append("swimming pool fence requirement ineligible unfenced")

    if _on("risk:pool", checked) and property_details['pool_accessories'] != 'None':
        risk_factors.append("diving board slide pool liability ineligible")

    if _on("risk:coastal", checked) and property_details['coastal_tier'] in ['Tier 1', 'Tier 2', 'Tier 3']:
        risk_factors.append(
            "coastal tier wind coverage restrictions wind pool zone "
            "base flood elevation ineligible"
        )

    if _on("risk:dogs", checked) and property_details['aggressive_breed'] == 'Yes':
        risk_factors.append("aggressive dog breed ineligible prohibited liability")

    if property_details.get('ownership_type') == 'LLC':
        risk_factors.append("LLC business corporation owned property ineligible not eligible")

    if property_details.get('ownership_type') == 'Trust':
        risk_factors.append("trust owned property eligibility requirements named insured grantor")

    if _on("risk:ppc", checked) and property_details['ppc'] != 'N/A':
        risk_factors.append(
            f"protection class PPC {property_details['ppc']} fire district eligibility requirements"
        )

    if occupancy not in ['Owner Occupied']:
        risk_factors.append("tenant occupied rental dwelling occupancy requirements")
        risk_factors.append("DP3 dwelling policy tenant rental occupancy eligibility")
        risk_factors.append("HO3 owner occupancy requirement restriction")
    if occupancy in OWNERS_OTHER_HOMES:
        # round 29 step 4: HO3 guides now see these homes; their seasonal / secondary rows decide
        risk_factors.append("seasonal secondary residence owner occupied eligibility months unoccupied")

    if _on("risk:roof", checked):
        # A part about an unchecked roof topic is left out of the term.
        roof_type = property_details['roof_type'] if "roof_type" in checked else ""
        roof_age = f" {property_details['roof_age']} years old" if "roof_age" in checked else ""
        risk_factors.append(f"{roof_type} roof{roof_age} eligibility requirements".strip())
    if _on("risk:pool", checked) and property_details['swimming_pool'] != 'No Pool':
        risk_factors.append(
            f"swimming pool {property_details['swimming_pool']} eligibility requirements"
        )
    if _on("risk:solar", checked) and property_details['solar_panels'] == 'Yes':
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
# Sage ADDRESS rule (Liam, 2026-09-30): carrier -> (Nueces excluded?, the
# guide's own sentence, verbatim apart from its bullet glyphs). Keyed on
# carrier identity plus the County field -- never on the model's wording.
# See structured_rules.sage_county_in_territory for the rule and its data.
_SAGE_ADDRESS_HO = (
    "Property must be located in: South Texas (meaning a county located entirely south of 31 "
    "degrees North) except Nueces county, or One of the following counties in East Texas: Bell, "
    "Falls, Robertson, Leon, Madison, Houston, Trinity, and Polk.")
_SAGE_ADDRESS_DP = _SAGE_ADDRESS_HO.replace("except Nueces county", "except in Nueces county")
_SAGE_ADDRESS_TRIUM = (
    "Property must be located in: South Texas (meaning a county located entirely south of 31 "
    "degrees North), or One of the following counties in East Texas: Bell, Falls, Robertson, "
    "Leon, Madison, Houston, Trinity, and Polk.")
_SAGE_LOCATION_RULE = {
    "Sage_-_Auros_HO3": (True, _SAGE_ADDRESS_HO),
    "Sage_-_SURE_HO-3_-_01.31.2026": (True, _SAGE_ADDRESS_HO),
    "Sage_-_SafePort_HO-3_-_01.31.2026": (True, _SAGE_ADDRESS_HO),
    "Sage_-_Wilshire_HO3_-_12.02.2025": (True, _SAGE_ADDRESS_HO),
    "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026": (False, _SAGE_ADDRESS_TRIUM),
    "Sage_-_SURE_DP-3_-_01.31.2026": (True, _SAGE_ADDRESS_DP),
    "Sage_-_SafePort_DP-3_-_01.31.2026": (True, _SAGE_ADDRESS_DP),
    "Sage_-_Occidental_DP3": (True, _SAGE_ADDRESS_DP),
    "Sage_-_Occidental_HO3": (True, _SAGE_ADDRESS_DP),
}
_MERCURY_CARRIERS = {"Mercury_HO3_-_01.01.2026"}
_SAGE_MARKEL_CARRIERS = {"Sage_-_Markel_HO3"}
_SWYFFT_MAX30_CARRIERS = {
    "Swyfft_-_Benchmark_(Admitted)_HO3",
    "Swyfft_-_Benchmark_(Surplus)_HO3",
    "Swyfft_-_Topa_(Surplus)_HO3",
}
_TWICO_CARRIERS = {"TWICO_HO3"}

# The nine Sage documents that actually carry the roofer's-statement rule,
# confirmed by reading each one's extracted text rather than assuming it
# tracks the FPC family. Markel and Vave are deliberately ABSENT: Markel uses
# its own Roof Exclusion form and Vave states a hurricane-rating rule
# instead, so neither has these thresholds. Note this set spans BOTH HO3 and
# DP3 variants -- round 14's audit surfaced it on DP3, and three of the nine
# had never been exercised by any test before that.
_CENTAURI_DP3_CARRIERS = {"Centauri_-_DP3_-_11.16.2022"}

ROOFER_STATEMENT_NOT_CHECKED = ("If it applies, the guide asks for a roofer's statement on its Roof "
                                "Condition Form (not checked).")

_SAGE_ROOFER_STATEMENT_CARRIERS = {
    "Sage_-_Auros_HO3",
    "Sage_-_Occidental_HO3",
    "Sage_-_Occidental_DP3",
    "Sage_-_SURE_HO-3_-_01.31.2026",
    "Sage_-_SURE_DP-3_-_01.31.2026",
    "Sage_-_SafePort_HO-3_-_01.31.2026",
    "Sage_-_SafePort_DP-3_-_01.31.2026",
    "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026",
    "Sage_-_Wilshire_HO3_-_12.02.2025",
}


def _normalize_carrier_name(s):
    return "".join(ch for ch in s.upper() if ch.isalnum())


def _carrier_words(name, drop_parenthetical=False):
    s = (name or "").upper().replace("HO-3", "HO3").replace("DP-3", "DP3")
    if drop_parenthetical:
        s = re.sub(r"\(.*?\)", " ", s)
    return set(re.findall(r"[A-Z0-9]+", s))


def _resolve_structured_carrier(reported_name, canonical_names):
    """The model restates carrier names in its own JSON output rather than
    echoing the exact DB metadata string -- resolve against the known
    carrier list the same tolerant way is_combined_program (above) already
    does for the DP3/HO3 heuristic, rather than requiring an exact match.

    Containment misses a name whose dropped part sits in the MIDDLE: "Orion
    HO3" for Orion_Underwriting_Guide_-_TX_-_07.06.26_HO3, "HOAIC HO3" for
    HOAIC_-_TX-HOMEOWNERS-0326_HO3. A miss returned None, and every
    post-parse guard then skipped that record silently -- 14 of 420 recorded
    round-17 records, in 6 of 15 calls. So, only when containment finds
    nothing, a name whose words are a subset of exactly ONE carrier's words
    resolves to it. Several fits ("Sage HO3") stay unresolved.

    Words in parentheses are NEVER dropped here, although that would also
    catch "NatGen Custom360 (Landlord)". _citation_attributed_carrier asks
    about one carrier at a time, and "ARI (HOB)" minus its parenthetical is
    just "ARI" -- which fits ARI (HOA+) too, so HOB's rule quoted in HOA+'s
    record stopped being recognised as foreign (caught by
    test_reproduces_the_exact_ari_finding). A carrier's parenthetical is part
    of its identity. The Custom360 record is a wrong-guide carrier, left out
    of the prompt entirely once the data-defect row lands."""
    norm_reported = _normalize_carrier_name(reported_name)
    if not norm_reported:
        return None
    for canon in canonical_names:
        norm_canon = _normalize_carrier_name(canon)
        if norm_canon and (norm_canon in norm_reported or norm_reported in norm_canon):
            return canon
    words = _carrier_words(reported_name)
    fits = [c for c in canonical_names if words and words <= _carrier_words(c)]
    return fits[0] if len(fits) == 1 else None


def _force_ineligible(result, reason_text):
    if result.get("status") != "INELIGIBLE":
        result["status"] = "INELIGIBLE"
        result["flaw_count"] = 1
    result.setdefault("reasons", []).append(reason_text)
    result.setdefault("citations", []).append(reason_text)
    _decide_by_code(result, "INELIGIBLE", reason_text)


def _decide_by_code(result, status, reason, citation=None):
    """Round 26 step 2 (Liam, 2026-10-05): a deterministic rule set this
    record's status. The caller still sets the status; this records why, and
    _code_owns_cards() rebuilds the card from it at the end of the chain."""
    result.setdefault("_code_decisions", []).append(
        {"status": status, "reason": reason, "citation": citation})


# Round 27 step 1 (Liam, 2026-10-06, decision 1). TWICO's ineligible list
# says "Homes of unconventional construction including log, do-it-yourself,
# dome, shell, or homes using unconventional parts or not meeting building
# codes. This includes solar panels." Luna reads the last sentence as a flat
# solar exclusion (round 26: 4/4 on LIVE). Liam: standard mounted panels are
# code-compliant, so they do not make a TWICO home ineligible. Keyed on the
# carrier, Solar = Yes, and a flaw that rests on THIS sentence: a citation
# quoting it, or a reason in its own words (solar + unconventional
# construction / building codes) -- never on loose solar wording.
_TWICO = "TWICO_HO3"
TWICO_SOLAR_SENTENCE = ("Homes of unconventional construction including log, do-it-yourself, dome, shell, "
                        "or homes using unconventional parts or not meeting building codes. This includes "
                        "solar panels.")
TWICO_SOLAR_NOTE = ("TWICO lists solar panels with construction that does not meet building codes. Treated "
                    "as eligible for standard, code-compliant mounted panels (Liam, 2026-10-06); confirm the "
                    "panels are permitted and code-compliant.")
_TWICO_SOLAR_REASON_RE = re.compile(
    r"solar[^.]*\b(?:unconventional|building codes?)\b|\b(?:unconventional|building codes?)\b[^.]*solar", re.I)


def _cites_twico_solar_sentence(citation):
    """A citation whose quote is part of TWICO's sentence and says solar."""
    _problem, _label, quote = _parse_citation(citation)
    key = quotes.compare_key(quote or "")
    return (len(key) >= _MIN_QUOTE_KEY and "solar" in key
            and key in quotes.compare_key(TWICO_SOLAR_SENTENCE))


def _apply_twico_solar_decision(results, relevant_carriers, property_details):
    """Remove the flaw that rests on TWICO's building-code sentence. Nothing
    else wrong -> ELIGIBLE (code-decided, with the note); other flaws left ->
    their status stands, without the solar flaw. Any other decline is left
    alone."""
    if property_details.get("solar_panels") != "Yes":
        return
    for r in results:
        if _resolve_structured_carrier(r.get("carrier", ""), relevant_carriers) != _TWICO:
            continue
        if r.get("status") != "INELIGIBLE":
            continue
        cites = [c for c in r.get("citations") or [] if _cites_twico_solar_sentence(c)]
        reasons = [x for x in r.get("reasons") or [] if _TWICO_SOLAR_REASON_RE.search(x)]
        if not cites and not reasons:
            continue
        remaining = max(0, int(r.get("flaw_count") or 0) - 1)
        print("TWICO SOLAR: removed the building-code solar flaw; remaining_flaws=%d" % remaining)
        _append_note(r, TWICO_SOLAR_NOTE)
        if remaining:
            # The model's card stands, minus the solar flaw.
            r["citations"] = [c for c in r.get("citations") or [] if c not in cites]
            r["reasons"] = [x for x in r.get("reasons") or [] if x not in reasons]
            r["flaw_count"] = remaining
        else:
            # Code decides; _code_owns_cards moves the model's wording to
            # diagnostics. A short reason, so the card does not repeat the note.
            r["status"], r["flaw_count"] = "ELIGIBLE", 0
            _decide_by_code(r, "ELIGIBLE", "The only flaw was TWICO's building-code sentence that lists solar "
                                           "panels; mounted panels are treated as code-compliant.",
                            f'{_TWICO}: "{TWICO_SOLAR_SENTENCE}"')


def _code_owns_cards(results):
    """Round 26 step 2 (Liam, 2026-10-05): when a deterministic rule set the
    status, the card says the code's reason (with the guide's own sentence
    where the rule has one), not the model's. On Liam's live check the four
    Sage carriers declined on territory still argued "none states a flat
    ineligible outcome for PPC 3" and listed fire-station questions that
    cannot change a territory decline.
    - reasons / citations: the code decisions that match the final status.
    - missing_info: emptied for a decline (nothing open can change it); kept
      for a hold or a referral (an open item can still change those).
    - The model's own reasons, citations and missing_info move to
      r["diagnostics"], which the card never shows.
    A record whose final status no code decision matches is left alone (a
    later rule overrode the earlier one)."""
    for r in results:
        decisions = r.pop("_code_decisions", None) or []
        own = [d for d in decisions if d["status"] == r.get("status")]
        if not own:
            continue
        r["diagnostics"] = {"model_reasons": list(r.get("reasons") or []),
                            "model_citations": list(r.get("citations") or []),
                            "model_missing_info": list(r.get("missing_info") or [])}
        r["reasons"] = list(dict.fromkeys(d["reason"] for d in own))
        r["citations"] = list(dict.fromkeys(d["citation"] for d in own if d.get("citation")))
        if r["status"] == "INELIGIBLE":
            r["missing_info"] = []
        r["decided_by_code"] = True


def _append_note(result, text):
    existing = result.get("notes", "")
    result["notes"] = (existing + " " + text).strip() if existing else text


# Keywords used ONLY to decide whether a carrier's own adverse verdict is
# ABOUT a given topic. They never decide a verdict themselves -- the
# structured check in structured_rules.py does that.
_AMBIGUITY_TOPIC_KEYWORDS = {
    "roof": (
        "roof", "shingle", "composition", "3-tab", "architectural",
        "acv", "actual cash value", "replacement cost", "rcv",
    ),
    "fpc": (
        "fpc", "fire protection class", "protection class", "ppc",
        "fire station", "hydrant",
    ),
}


# ---------------------------------------------------------------------------
# Pool enclosure specifics (round 13, P3).
#
# A carrier whose OWN document states a specific pool fence height or gate
# mechanism cannot have that requirement satisfied by the intake's generic
# "In Ground - Fenced", which carries no height and no gate type. A live
# run had ARI (HOA+) -- whose rule is "a 6' high fence with locked or self
# locking gates" -- state in its Analysis that the property "meets the
# requirement", from an input that says nothing of the kind.
#
# This is NOT ARI-specific. A scan of every owner-occupied carrier found
# TWENTY with a specific fence height and/or gate mechanism -- 18 state a
# height, 18 state a gate mechanism. Only TWO distinct heights exist in the
# corpus: ARI (HOA+) and ARI (HOB) at 6', and the other sixteen
# height-stating carriers all at 4'. So any per-carrier patch would have
# been wrong by construction, and so would any rule that assumed one shared
# number.
#
# Every one of those figures has been checked against the source clause it
# came from, not against this extractor's own output -- see
# _extract_pool_spec, whose first version reported Foremost at 5' and Sage
# Markel at 4' AND 5', both wrong, and whose "16/16 verified" claim was
# worthless because it compared the extractor to itself. It is also the same underlying gap the suite has been
# tracking as flaky rather than fixed: Sage Occidental's pool-fence rule
# was measured surfacing in only 55% (11/20) of runs, with a
# "post-generation verify + repair" fix explicitly queued for it. This is
# that fix, applied to the whole class at once.
# ---------------------------------------------------------------------------

# A height figure only counts when it sits in a POOL-ENCLOSURE context, and
# only when it is describing the enclosure rather than the water.
#
# CHANGED (round 13, second pass): the first version of this was wrong for
# Foremost, in two independent ways, and the "16/16 verified" claim it
# produced was worthless because it checked the extractor against its own
# output instead of against source text.
#
# Foremost's actual rule, stated five times in its document, is:
#     "Properties with pools (over 2.5 feet deep) must have a fence
#      minimum four feet high (fully enclosing the pool) AND a
#      self-locking gate"
#
#   1. Sentences were split on `[^.]*\.`, which splits on EVERY period --
#      including the decimal point in "2.5". The fragment
#      "5 feet deep) must have a fence minimum four feet high..." was then
#      treated as one sentence, and "5 feet" was harvested from it. That
#      figure is the tail of a pool DEPTH threshold, not a fence height:
#      wrong number and wrong attribute at once. Foremost was reported as
#      the only 5' carrier in the corpus; it is a 4' carrier.
#   2. The real height is SPELLED OUT ("four feet high") and the pattern
#      only matched digits, so the correct figure was never captured at all.
#
# Splitting into sentences is what made (1) possible, and PDF-extracted text
# in this corpus has mangled punctuation everywhere, so this no longer
# splits at all. Each candidate figure is judged by the words immediately
# around it instead.
_MAX_PLAUSIBLE_FENCE_FEET = 12

_SPELLED_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
}

# A length in feet: digits (possibly decimal, so "2.5" is matched WHOLE and
# can be rejected, rather than being torn in half) or a spelled-out number.
_FEET_RE = re.compile(
    r"\b(?P<num>\d+(?:\.\d+)?|" + "|".join(_SPELLED_NUMBERS) + r")\s*"
    r"(?:'|\u2019|-|\s)?\s*(?:foot|feet|ft)\b|"
    r"\b(?P<num2>\d+(?:\.\d+)?)\s*(?:'|\u2019)",
    re.I,
)

# Words that mean the figure describes the WATER, not the enclosure.
_DEPTH_WORDS = ("deep", "depth")

# The figure must sit next to an actual ENCLOSURE NOUN. A bare height word
# is not enough: Sage Markel's pool rule contains
#     "pool slide where the top of the slide is no higher than five feet
#      above the pool deck"
# and an earlier version accepted "five feet" from it because "higher"
# counted as height evidence -- reporting Markel as a 4' AND 5' carrier when
# its fence rule is "Approved fence (at least four feet high)". Same class of
# error as the Foremost depth figure: a number that is genuinely in the pool
# rule, but describing something other than the fence.
_ENCLOSURE_NOUNS = ("fenc", "wall", "enclos", "barrier", "cage")
# Other pool structures whose dimensions must never be read as a fence height.
_COMPETING_STRUCTURES = ("slide", "diving", "board", "ladder", "deck", "depth", "deep")

_POOL_GATE_MECHANISM_RE = re.compile(
    r"\b(self[-\s]?(?:latch|clos|lock)\w*|latching|locking|locked|padlock|combination lock)\b",
    re.I,
)
_POOL_ENCLOSURE_WORDS = ("fenc", "gate", "enclos", "barrier")

# How far around a candidate to look for context. Wide enough to span the
# parenthetical asides these documents are full of ("a fence minimum four
# feet high (fully enclosing the pool) and a self-locking gate").
_POOL_CONTEXT_WINDOW = 160


def _pool_context(lower, start, end):
    return lower[max(0, start - _POOL_CONTEXT_WINDOW): end + _POOL_CONTEXT_WINDOW]


def _nearest_word_distance(window, words, position):
    """Character distance from `position` to the closest occurrence of any of
    `words` in `window`, or None if none appear. Used to decide which noun a
    dimension actually belongs to when several are in play."""
    best = None
    for word in words:
        start = 0
        while True:
            found = window.find(word, start)
            if found == -1:
                break
            distance = abs(found - position)
            if best is None or distance < best:
                best = distance
            start = found + 1
    return best


def _extract_pool_spec(text):
    """The specific fence height(s) and gate mechanism(s) a carrier's own
    pool rule states. Returns {"heights": set[str], "gates": set[str]}.

    Every candidate is judged by its surrounding window, which must mention
    a pool AND an enclosure. A height is additionally required to be
    describing the enclosure ("four feet high", "6' fence") and rejected
    outright when it is describing the water ("over 2.5 feet deep") -- see
    the block comment above for the Foremost case that motivated both rules.
    """
    heights, gates = set(), set()
    lower = text.lower()

    for match in _FEET_RE.finditer(lower):
        raw = match.group("num") or match.group("num2")
        if raw is None:
            continue
        value = _SPELLED_NUMBERS.get(raw, raw)
        if "." in value:
            # A fence height is never fractional in these documents; a
            # fractional figure here is a depth threshold.
            continue
        if not value.isdigit() or not 0 < int(value) <= _MAX_PLAUSIBLE_FENCE_FEET:
            continue

        window = _pool_context(lower, match.start(), match.end())
        if not ("pool" in window or "swimming" in window):
            continue
        if not any(w in window for w in _POOL_ENCLOSURE_WORDS):
            continue

        # Reject a depth figure: "(over 2.5 feet deep)", "4 feet or deeper".
        trailing = lower[match.end(): match.end() + 24]
        if any(w in trailing for w in _DEPTH_WORDS):
            continue
        # Require positive evidence that this figure describes the ENCLOSURE:
        # an enclosure noun must be nearby, and must be closer to the figure
        # than any competing pool structure whose own dimensions could
        # otherwise be mistaken for it.
        near_start = max(0, match.start() - 60)
        near = lower[near_start: match.end() + 40]
        figure_at = match.start() - near_start

        enclosure_gap = _nearest_word_distance(near, _ENCLOSURE_NOUNS, figure_at)
        if enclosure_gap is None:
            continue
        competing_gap = _nearest_word_distance(near, _COMPETING_STRUCTURES, figure_at)
        if competing_gap is not None and competing_gap < enclosure_gap:
            continue

        heights.add(value)

    for match in _POOL_GATE_MECHANISM_RE.finditer(lower):
        window = _pool_context(lower, match.start(), match.end())
        if not ("pool" in window or "swimming" in window):
            continue
        if not any(w in window for w in _POOL_ENCLOSURE_WORDS):
            continue
        gates.add(match.group(1).strip().lower())

    return {"heights": heights, "gates": gates}


def _intake_states_pool_specifics(pool_value):
    """True when the intake's own pool value already states a height or a
    gate mechanism, in which case there is nothing to flag as unconfirmed.
    The current form only ever emits generic values ("In Ground - Fenced"),
    but this keeps the check honest if the form ever gains those fields --
    the rule is "don't assert what the input doesn't support," not "always
    add a pool caveat."
    """
    # The intake value is a fragment, not prose, so give the extractor the
    # pool/fence context its window check needs before asking it.
    spec = _extract_pool_spec("pool fence: " + pool_value.lower())
    if spec["heights"] or spec["gates"]:
        return True
    # Fall back to a bare figure/mechanism anywhere in the value, so a future
    # intake field that states one in an unanticipated shape still counts.
    return bool(_FEET_RE.search(pool_value)) or bool(
        _POOL_GATE_MECHANISM_RE.search(pool_value)
    )


def _describe_unconfirmed_pool_spec(spec):
    wants = []
    if spec["heights"]:
        heights = " or ".join(f"{h}'" for h in sorted(spec["heights"], key=int))
        wants.append(f"fence height (this carrier's rule specifies {heights})")
    if spec["gates"]:
        gates = ", ".join(sorted(spec["gates"]))
        wants.append(f"gate mechanism (this carrier's rule specifies {gates})")
    return " and ".join(wants)


# What the gate box settles, per carrier, read from each guide 2026-10-01
# (the phrase is verbatim; a test checks it is in that carrier's own guide).
# Round 21 (Liam, 2026-10-02): ONE strict box, "Gate confirmed self-latching
# AND can be locked", settles every wording family -- locking / locked /
# lockable (Allied, Progressive, Markel, ...), self-locking (Foremost, NatGen
# Custom360), self-latching (Swyfft), and Sage's list. Round 20's narrower
# box left self-locking and self-latching open. A carrier not listed is never
# settled by the box. Travelers is deliberately absent: the "locking" in its
# pool rule is a "retractable locking ladder", not a gate.
_SAGE_GATE = "combination or padlocked gate or self-locking or self-latching mechanism"
_POOL_GATE_RULE = {
    "ARI_(HOA+)": (True, "Pools secured by a 6' high fence with locked or self locking gates are acceptable"),
    "ARI_(HOB)": (True, "Pools secured by a 6' high fence with locked or self locking gates are acceptable"),
    "Allied_Trust_HO3": (True, "a fence at least 4-foot-high with a locking gate"),
    "Centauri_-_DP3_-_11.16.2022": (True, "a minimum 4-foot high locking fence or alternate approved enclosure"),
    "NatGen_Premier_OneChoice_DP3_-_02.26.2025": (True, "A height of at least four feet and locking gates are required"),
    "NatGen_Premier_OneChoice_HO3_-_02.26.2025": (True, "A height of at least four feet and locking gates are required"),
    "Progressive_DP3_-_10.01.2024": (True, "Must be protected by a locking fence at least 4-feet high, or alternate approved enclosure"),
    "Progressive_HO3_-_04.01.2026": (True, "a minimum of a four-foot fence and locking gate or approved alternate enclosure"),
    "Sage_-_Markel_DP3": (True, "Lockable gate"),
    "Sage_-_Markel_HO3": (True, "Lockable gate"),
    "Sage_-_Auros_HO3": (True, _SAGE_GATE),
    "Sage_-_Occidental_DP3": (True, _SAGE_GATE),
    "Sage_-_SURE_DP-3_-_01.31.2026": (True, _SAGE_GATE),
    "Sage_-_SURE_HO-3_-_01.31.2026": (True, _SAGE_GATE),
    "Sage_-_SafePort_DP-3_-_01.31.2026": (True, _SAGE_GATE),
    "Sage_-_SafePort_HO-3_-_01.31.2026": (True, _SAGE_GATE),
    "Sage_-_Trium_Lloyd's_Non-Admitted_HO3_HO5_-_02.24.2026": (True, _SAGE_GATE),
    "Sage_-_Wilshire_HO3_-_12.02.2025": (True, _SAGE_GATE),
    "Steadily_Underwriting_Guidelines_DP3": (True, "4 ft. high permanently installed, locking fence"),
    "Foremost_DP3_and_HO3_-_07.01.2026": (True, "a fence minimum four feet high (fully enclosing the pool) AND a self-locking gate"),
    "NatGen_Custom360_DP3_-_06.25.2026": (True, "Pools are fenced in with self-locking gate"),
    "Swyfft_-_Benchmark_(Admitted)_HO3": (True, "self-latching gate"),
    "Swyfft_-_Benchmark_(Surplus)_HO3": (True, "self-latching gate"),
    "Swyfft_-_Lloyds_(Surplus)_HO3": (True, "self-latching gate"),
    "Swyfft_-_Topa_(Surplus)_HO3": (True, "self-latching gate"),
}

_POOL_HEIGHT_WORDS_RE = re.compile(r"height|high|tall|\bfeet\b|\bfoot\b|\bft\b|\d\s*(?:'|\u2019|-?foot|-?feet|ft)", re.I)
_POOL_GATE_WORDS_RE = re.compile(r"gate|latch|lock", re.I)


def _pool_boxes_settle(spec, canon, property_details):
    """(height settled, gate settled) by the agent's ticked boxes for this
    carrier. Height: ticked AND every height the carrier states is 4 ft or
    less. Gate: ticked AND the carrier is in _POOL_GATE_RULE."""
    heights = spec["heights"] if spec else set()
    height_ok = _pool_fence_4ft(property_details) and bool(heights) and max(int(h) for h in heights) <= 4
    gate_ok = _pool_gate_locking(property_details) and _POOL_GATE_RULE.get(canon, (False, ""))[0]
    return height_ok, gate_ok


def _drop_answered_pool_questions(r, height_ok, gate_ok):
    """Remove the model's own pool fence-height / gate questions that a
    ticked box has answered for this carrier. An item about both is removed
    only when both are answered. Returns the removed items."""
    if not (height_ok or gate_ok):
        return []
    dropped = []
    for m in r.get("missing_info", []):
        if not _is_manufactured_pool_question(m):
            continue
        asks_height = bool(_POOL_HEIGHT_WORDS_RE.search(m))
        asks_gate = bool(_POOL_GATE_WORDS_RE.search(m))
        if not (asks_height or asks_gate):
            continue
        if (not asks_height or height_ok) and (not asks_gate or gate_ok):
            dropped.append(m)
    if dropped:
        r["missing_info"] = [m for m in r["missing_info"] if m not in dropped]
        _append_note(r, "[Pool spec check] Removed {n} question(s) answered by the agent's "
                        "confirmed pool facts: {items}".format(
                            n=len(dropped), items="; ".join(d[:120] for d in dropped)))
    return dropped


def _enforce_pool_spec_support(results, relevant_carriers, property_details, pool_specs,
                               skip=frozenset()):
    """Guarantee that a carrier stating specific pool-enclosure
    requirements records them as UNCONFIRMED rather than assumed met.

    Deliberately does NOT change status. The false claim reported in the
    audit was in the Analysis text ("meets the requirement"), and the
    finding was not flagged verdict-changing; flipping sixteen carriers
    from ELIGIBLE to INSUFFICIENT_INFORMATION off the back of it would be a
    far larger behavioral change than the evidence supports. What it does
    guarantee is that the specific unconfirmed attribute is always present
    in missing_info, naming THIS carrier's own figure -- so the agent sees
    "6' fence height not confirmed" instead of a bare assertion of
    compliance.
    """
    pool_value = property_details.get("swimming_pool", "No Pool")
    if pool_value == "No Pool":
        return
    if _intake_states_pool_specifics(pool_value):
        return

    any_box = _pool_fence_4ft(property_details) or _pool_gate_locking(property_details)
    for r in results:
        canon = _resolve_structured_carrier(r.get("carrier", ""), relevant_carriers)
        # skip: the rules-table pilot carriers. They were never retrieved, so
        # pool_specs knows nothing about them; their own pool rows decide.
        if canon is None or canon in skip:
            continue
        spec = pool_specs.get(canon)
        if not spec or not (spec["heights"] or spec["gates"]):
            continue

        # Round 20: a ticked box answers what it can for THIS carrier; the
        # rest stays unconfirmed. Both unticked = exactly the old behaviour.
        height_ok, gate_ok = _pool_boxes_settle(spec, canon, property_details)
        dropped = _drop_answered_pool_questions(r, height_ok, gate_ok)
        still_open = {"heights": set() if height_ok else spec["heights"],
                      "gates": set() if gate_ok else spec["gates"]}
        if still_open["heights"] or still_open["gates"]:
            described = _describe_unconfirmed_pool_spec(still_open)
            item = (
                f"Pool enclosure specifics are not confirmed by the intake value "
                f"\"{pool_value}\": {described}."
            )
            mi = r.setdefault("missing_info", [])
            if not any("pool enclosure specifics" in m.lower() for m in mi):
                mi.append(item)

            if any_box:
                _append_note(
                    r,
                    "[Pool spec check] The confirmed pool facts do not settle this carrier's "
                    f"stated {described}, so that part is unconfirmed, not satisfied.",
                )
            else:
                _append_note(
                    r,
                    f"[Pool spec check] The intake value \"{pool_value}\" states neither a fence "
                    f"height nor a gate mechanism, so this carrier's specific pool requirement "
                    f"cannot be treated as met -- it is unconfirmed, not satisfied.",
                )
        elif dropped and r.get("status") == "INSUFFICIENT_INFORMATION" and not r.get("missing_info"):
            r["status"] = "ELIGIBLE"
            r["flaw_count"] = 0
            _append_note(r, "Status corrected to ELIGIBLE: the only open facts were this "
                            "carrier's pool fence height / gate, and the agent confirmed both.")

    _drop_manufactured_pool_questions(results, relevant_carriers, property_details, pool_specs, skip)


# Words that make a missing_info item a POOL-SPECIFICITY question.
_POOL_SPECIFICITY_WORDS = ("fenc", "gate", "height", "enclos", "barrier", "latch", "lock")


def _is_manufactured_pool_question(item):
    low = item.lower()
    if not ("pool" in low or "swimming" in low):
        return False
    return any(w in low for w in _POOL_SPECIFICITY_WORDS)


def _drop_manufactured_pool_questions(results, relevant_carriers, property_details, pool_specs,
                                      skip=frozenset()):
    """The mirror of the check above, and the more consequential half.

    A carrier whose own document states NO specific fence height or gate
    mechanism cannot be blocked on one. SYSTEM_INSTRUCTIONS already says so
    outright -- "if this carrier's excerpt only states a GENERAL pool
    condition ('fenced', 'secured', 'walled') ... do not manufacture a more
    specific height/mechanism question the document itself never asks" --
    but a prompt rule is not a guarantee, and this one is measurably not
    holding.

    Measured on Mercury HO3 over the round 13 STANDARD sweep (n=25): its
    ONLY pool language is "unfenced in-ground swimming pools" in a list of
    hazards, which the intake value "In Ground - Fenced" plainly satisfies.
    Yet 12 of 25 runs came back INSUFFICIENT_INFORMATION, and in all 12 the
    sole missing_info item was a manufactured pool-fence/gate question --
    none of the 12 mentioned the roof at all. That is a verdict-level
    effect: it moves a carrier out of the Eligible bucket in ~48% of runs
    over a question its own document never asks.

    pool_specs is the deterministic answer to "does this carrier state a
    specific requirement?", built by scanning the same chunks the model was
    shown. A carrier absent from it has no such requirement, so the question
    is removed and the removal recorded.

    The status correction is deliberately narrow, mirroring
    _strip_misattributed_citations: only INSUFFICIENT_INFORMATION, only when
    EVERY removed item was a manufactured pool question, and only when
    nothing else remains in missing_info -- i.e. the hold rested entirely on
    a question that should never have been asked. Anything else is left
    alone, because absence of this one blocker is not evidence there was no
    other.
    """
    pool_value = property_details.get("swimming_pool", "No Pool")
    if pool_value == "No Pool":
        return
    # Only when the intake actually says the pool IS enclosed. "In Ground -
    # Unfenced" makes such a question entirely legitimate -- and note the
    # negation has to be checked FIRST, because "unfenced" contains "fenc".
    low_value = pool_value.lower()
    if any(neg in low_value for neg in ("unfenc", "un-fenc", "not fenc", "no fenc", "unenclos")):
        return
    if "fenc" not in low_value and "enclos" not in low_value:
        return

    for r in results:
        canon = _resolve_structured_carrier(r.get("carrier", ""), relevant_carriers)
        # Round 25 step 4: with the pilot ON, a pilot carrier is absent from
        # pool_specs because it was never retrieved -- not because its guide
        # states no fence spec. Reading that absence as "no requirement"
        # dropped Allied's and Swyfft's fence questions and set them ELIGIBLE.
        if canon is None or canon in skip:
            continue
        spec = pool_specs.get(canon)
        if spec and (spec["heights"] or spec["gates"]):
            continue  # this carrier DOES state specifics -- the question is real

        mi = r.get("missing_info", [])
        if not mi:
            continue
        dropped = [m for m in mi if _is_manufactured_pool_question(m)]
        if not dropped:
            continue
        kept = [m for m in mi if not _is_manufactured_pool_question(m)]
        r["missing_info"] = kept

        _append_note(
            r,
            "[Pool spec check] Removed {n} pool-specificity question(s) -- this carrier's "
            "own document states no fence height or gate mechanism, and the intake value "
            "\"{v}\" already satisfies the general condition it does state. Removed: {items}"
            .format(n=len(dropped), v=pool_value, items="; ".join(d[:120] for d in dropped)),
        )

        if r.get("status") == "INSUFFICIENT_INFORMATION" and not kept:
            r["status"] = "ELIGIBLE"
            r["flaw_count"] = 0
            _append_note(
                r,
                "Status corrected to ELIGIBLE: the only fact this carrier was held on was a "
                "pool requirement its own document never states.",
            )


# ---------------------------------------------------------------------------
# Solar: integrated roofing vs. mounted panels (round 13, P4).
#
# The audit asked whether Allied Trust's silence on a mounted-panel property
# meant its solar chunk wasn't retrieved. Measured: it IS retrieved, 2 of 2
# chunks, identically across 5 repeated calls -- the guaranteed lookup is an
# exact keyword scan, so it has no run-to-run variance to lose. Both of its
# solar references are roof COVERING materials ("solar roof system", "Solar
# panel tiles"), which per SYSTEM_INSTRUCTIONS' SOLAR TERMINOLOGY rule
# correctly do NOT apply to panels mounted on an ordinary shingle roof. So
# the model's judgment was right.
#
# But it only SAID so in 1 of 3 measured runs, and total silence is exactly
# what the auditor could not interpret: it looks identical to a retrieval
# miss from outside. This codebase has already settled that question once --
# see the Mercury and TWICO roof branches, whose comments say a silent
# "unremarkable" outcome "is itself a bug, not a no-op". Same reasoning, same
# remedy: state the deterministic conclusion instead of hoping the model
# repeats it.
# ---------------------------------------------------------------------------

# Phrases that name solar material used AS the roof covering. Order matters:
# these are matched and consumed FIRST, because "solar panel tiles" contains
# the substring "solar panel" and would otherwise look like a mounted-panel
# rule -- the exact confusion the SOLAR TERMINOLOGY rule exists to prevent.
_INTEGRATED_SOLAR_ROOFING_PHRASES = (
    "solar roof system", "solar roofing", "solar roof",
    "solar shingle", "solar shingles",
    "solar panel tile", "solar panel tiles",
    "solar tile", "solar tiles",
    "bipv",
)

# Signals that a rule is about conventional panels mounted on top of an
# ordinary roof -- i.e. it genuinely DOES address this customer.
_MOUNTED_SOLAR_PANEL_SIGNALS = (
    "mounted", "mounting", "roof-mounted", "attached to the roof",
    "photovoltaic", "pv system", "panel installation", "installed on the roof",
    "who insures", "wind or hail damage to the panels",
)


def classify_solar_text(text):
    """Is this carrier's solar language about INTEGRATED solar roofing, or
    about MOUNTED panels?

    Returns one of "roofing_only", "addresses_panels", or "none".

    Every integrated-roofing phrase is removed before looking for
    mounted-panel signals, so a document that only ever says "solar panel
    tiles" cannot be read as having a mounted-panel rule.
    """
    lower = text.lower()

    stripped = lower
    for phrase in _INTEGRATED_SOLAR_ROOFING_PHRASES:
        stripped = stripped.replace(phrase, " ")

    # Checked BEFORE the "no solar at all" exit: a carrier can state a
    # mounted-panel rule using only the word "photovoltaic".
    if any(sig in stripped for sig in _MOUNTED_SOLAR_PANEL_SIGNALS):
        return "addresses_panels"
    if "solar" not in lower:
        return "none"
    if "solar" not in stripped:
        # EVERY mention was consumed as an integrated-roofing phrase. This
        # has to be all of them, not merely one of them: Foremost's document
        # lists "Solar shingles" among ineligible roof coverings AND, in a
        # different chunk, covers "wind or hail that results in marring of
        # ... solar panels" -- a real mounted-panel rule. An earlier version
        # returned roofing_only as soon as ANY integrated phrase appeared,
        # which would have had the note below tell an agent that Foremost
        # states no mounted-panel rule. It does.
        return "roofing_only"
    # Something says "solar" that is NOT an integrated-roofing phrase. Do not
    # assert the absence of a mounted-panel rule on that basis.
    return "addresses_panels"


def classify_carrier_solar_text(collection, carrier):
    """Classify a carrier's solar language across its ENTIRE document, not
    just the chunks the guaranteed lookup keeps.

    This distinction is not academic. The lookup keeps at most
    MAX_SOLAR_CHUNKS_PER_CARRIER (2) chunks, and Foremost has 4 that mention
    solar: the two that rank first are both about "Solar shingles" in a list
    of ineligible roof COVERINGS, while the fourth -- outside the keep
    window -- covers "wind or hail that results in marring of ... solar
    panels", which is a genuine MOUNTED-panel rule. Classifying only the
    kept chunks would have had _note_solar_roofing_does_not_apply() tell an
    agent that Foremost "states no rule about roof-mounted panels", which is
    false. A note that asserts the absence of a rule has to be checked
    against the whole document.
    """
    try:
        raw = collection.get(where={"carrier": carrier}, include=["documents"])
    except Exception:
        return "none"
    solar_docs = [d for d in raw.get("documents", []) if _mentions_solar(d)]
    if not solar_docs:
        return "none"
    return classify_solar_text(" ".join(normalize_chunk_text(d) for d in solar_docs))


def _note_solar_roofing_does_not_apply(results, relevant_carriers, property_details, solar_classes):
    """For a property with MOUNTED panels, make every carrier whose solar
    language is integrated-roofing-only say so explicitly.

    Note-only: it never touches status, reasons, citations or missing_info.
    Its whole job is to remove the ambiguity between "correctly judged not
    applicable" and "never retrieved", which is not something an auditor can
    resolve from the outside.
    """
    if property_details.get("solar_panels") != "Yes":
        return
    # Round 26 (Liam, 2026-10-05): one sentence. An unchecked Roof type is
    # absent from property_details; the old template then read "panels
    # mounted on a the stated roof covering roof".
    roof_type = property_details.get("roof_type")
    on_roof = f"on a {roof_type} roof" if roof_type else "on the roof"
    for r in results:
        canon = _resolve_structured_carrier(r.get("carrier", ""), relevant_carriers)
        if canon is None:
            continue
        if solar_classes.get(canon) != "roofing_only":
            continue
        if "[solar check]" in r.get("notes", "").lower():
            continue
        _append_note(
            r,
            f"[Solar check] This guide's solar rule is about solar roofing (solar shingles or "
            f"tiles), so it does not apply to panels mounted {on_roof}.",
        )


def _hold_for_unresolved_topic(result, topic, explanation, model_text):
    """A structured check has reported that this topic's outcome genuinely
    DIVERGES depending on a fact the intake never collects. That conclusion
    has to reach the STATUS field -- not just the prose.

    Round 13 (P2): TWICO_HO3 came back INELIGIBLE on a 21-year
    "Composition Shingle" roof while its own notes field -- written a few
    lines below by this very override -- correctly said "at 21 years, 3-tab
    resolves to EXCLUDED and architectural resolves to ACV. Any single
    bracket stated above without that confirmation is an assumption, not a
    determination." The override computed exactly the right thing and then
    never wired it to the one field an agent actually acts on. This is the
    same shape of bug as round 12's Sage FPC wiring gap (a correct
    conclusion landing only in a free-form field), which is why the fix is
    a SHARED helper rather than another per-carrier patch: every structured
    check that can report genuine ambiguity now routes through it.

    Deliberately conservative -- it only holds a verdict it can actually
    show rests on the unresolved topic:

      * Only ADVERSE determinations (INELIGIBLE / REFER) are downgraded. A
        confident ELIGIBLE that carries the caveat in notes + missing_info
        hides nothing from the agent; an adverse one actively tells them
        not to bother quoting the carrier, on the strength of a coin flip.
        Same asymmetry _strip_misattributed_citations already uses.
      * The topic must actually appear in THIS carrier's own
        reasons/citations/notes. If the model never raised it, the adverse
        verdict is about something else -- leave it alone. `model_text` is
        a snapshot taken BEFORE any override touched this result, and that
        matters: an earlier revision of this helper re-read `notes` live,
        by which point the TWICO branch had already appended its own
        "3-tab vs architectural" caveat there. The topic check then matched
        text the override itself had just written, and fired on a TWICO
        verdict whose sole actual ground was the solar exclusion. A
        relevance check must read what the MODEL said, not what this
        function is in the middle of saying.
      * flaw_count > 1 means the model found other, independent grounds, so
        the verdict does not rest solely on the unresolved fact. The status
        stands; the caveat is still recorded.

    Returns True if the status was actually downgraded.
    """
    if result.get("status") not in ("INELIGIBLE", "REFER"):
        return False

    keywords = _AMBIGUITY_TOPIC_KEYWORDS[topic]
    if not any(k in model_text for k in keywords):
        return False

    if result.get("flaw_count", 0) > 1:
        _append_note(
            result,
            "[Unresolved-fact check] " + explanation + " This carrier's determination "
            "also rests on other, independent grounds, so its status is unchanged.",
        )
        return False

    result["status"] = "INSUFFICIENT_INFORMATION"
    result["flaw_count"] = 0
    _append_note(
        result,
        "Status downgraded to INSUFFICIENT_INFORMATION: " + explanation + " A determination "
        "either way would be an assumption about a fact the intake never collected, not a "
        "finding from this carrier's document.",
    )
    return True


def _citation_attributed_carrier(citation, canonical_names):
    """The carrier a citation labels itself as belonging to, or None if it
    carries no confidently-identifiable label. Citations are formatted
    "<carrier name>: '<quote>'" per SYSTEM_INSTRUCTIONS, so only the text
    before the first colon is treated as a label -- and only when it
    resolves to a known carrier. Anything else returns None (unknown), so
    an unlabeled or oddly-formatted citation is never mistaken for a
    misattributed one."""
    if ":" not in citation:
        return None
    label = citation.split(":", 1)[0]
    # A real label is short; a long prefix is prose that happens to contain
    # a colon, not a carrier name.
    if len(label) > 60:
        return None

    # Must resolve to EXACTLY ONE carrier. An ambiguous label is treated as
    # unknown rather than guessed at: a bare "ARI:" prefix matches both
    # "ARI_(HOA+)" and "ARI_(HOB)", and _resolve_structured_carrier would
    # silently return whichever sorts first -- which, while evaluating the
    # other one, would look like foreign attribution and strip a perfectly
    # legitimate self-citation. Stripping evidence must never rest on a
    # coin flip.
    matches = {
        m for m in (
            _resolve_structured_carrier(label, [c]) for c in canonical_names
        ) if m is not None
    }
    if len(matches) != 1:
        return None
    return matches.pop()


# ---------------------------------------------------------------------------
# Contradicted-property-fact check (round 14, P1).
#
# The worst failure this tool can produce is not misreading a carrier's
# document -- it is asserting something about the CUSTOMER that their own
# intake contradicts. Round 14's DP3 audit found 7 of 12 carriers in one run
# reasoning from "solar panels are present" on a profile whose intake says
# "Solar Panels: No", and NatGen Premier OneChoice DP3 was marked INELIGIBLE
# solely on that fabricated fact: "The carrier's flat exclusion of solar
# panels makes this property ineligible regardless of other factors." A real
# applicant with no solar panels would have been told they do not qualify for
# a carrier they do qualify for.
#
# The prompt now states the rule (PROPERTY DETAILS IS THE ONLY SOURCE OF
# FACTS ABOUT THIS CUSTOMER, plus the solar section is conditional on the
# actual value rather than asserting "Solar Panels: Yes"). This is the
# deterministic half. CLAUDE.md's whole premise is that a prompt instruction
# is not a guarantee -- measured pass rates for prompt-only fixes in this
# project have been as low as 0-25% -- and unlike most rules in here, this
# one can be checked mechanically: the intake value is known, so a claim
# that contradicts it is decidable without any judgment call.
#
# Deliberately narrow: it only fires on fields whose value POSITIVELY states
# absence ("No", "No Pool"), never on an unknown, and it only rewrites a
# verdict when that fabricated feature was the sole stated ground for it.
# ---------------------------------------------------------------------------

_CONTRADICTION_CHECKS = (
    {
        "field": "solar_panels",
        "absent_values": ("no", "none", "n/a"),
        "label": "solar panels",
        # Claims the feature EXISTS on this property.
        "asserts_present": re.compile(
            r"(solar panels?\s*(are|is)\s*(present|installed)|"
            r"(property|home|dwelling|risk)\s+(has|have|with)\s+solar|"
            r"has\s+solar\s+panels?|with\s+solar\s+panels?|"
            r"presence of solar|solar panels?\s*:\s*yes|"
            r"the\s+solar\s+panels?\s+on\b|solar panels? installed)",
            re.I,
        ),
        # Correctly noting ABSENCE must never be treated as a violation.
        "asserts_absent": re.compile(
            r"(no solar|without solar|does not have solar|do not have solar|"
            r"not have solar|absence of solar|solar panels?\s*:\s*no|"
            r"no\s+solar\s+panels?|lacks solar)",
            re.I,
        ),
        "topic": re.compile(r"solar", re.I),
    },
    {
        "field": "swimming_pool",
        "absent_values": ("no pool", "none", "no"),
        "label": "a swimming pool",
        "asserts_present": re.compile(
            r"((property|home|dwelling|risk)\s+(has|have|with)\s+(a\s+)?(swimming\s+)?pool|"
            r"the\s+(swimming\s+)?pool\s+(is|must|has)|"
            r"(swimming\s+)?pool\s*(is|are)\s*present|presence of a (swimming )?pool)",
            re.I,
        ),
        "asserts_absent": re.compile(
            r"(no pool|no swimming pool|without a pool|does not have a pool|"
            r"there is no pool|absence of a pool)", re.I,
        ),
        "topic": re.compile(r"\bpool\b", re.I),
    },
    {
        "field": "aggressive_breed",
        "absent_values": ("no", "none"),
        "label": "an aggressive-breed dog",
        "asserts_present": re.compile(
            r"(aggressive\s+breed\s*(dog)?s?\s*(are|is)\s*present|"
            r"(property|home|risk)\s+(has|have|with)\s+(an?\s+)?aggressive\s+breed|"
            r"aggressive breed dogs? on)", re.I,
        ),
        "asserts_absent": re.compile(
            r"(no aggressive|not an aggressive|aggressive breed[^.]{0,20}:\s*no|"
            r"non-aggressive|without aggressive)", re.I,
        ),
        "topic": re.compile(r"aggressive breed", re.I),
    },
)


# An item that APPLIES a rule against the property, as opposed to merely
# mentioning the topic.
_ADVERSE_APPLICATION_RE = re.compile(
    r"(exclu|ineligib|not eligible|disqualif|declin|prohibit|unacceptable|"
    r"does not qualify|cannot be written|will not write)", re.I
)
# An item that correctly says the rule does NOT bite. These must survive --
# an explicit dismissal is exactly what round 13's P4 work went out of its
# way to encourage.
_INAPPLICABLE_RE = re.compile(
    r"(does not apply|do not apply|doesn'?t apply|not applicable|no effect|"
    r"is not triggered|does not affect|not relevant)", re.I
)


def _states_absence(value, absent_values):
    return str(value).strip().lower() in absent_values


def _strip_contradicted_property_claims(results, property_details, checked=None):
    """Remove claims that a feature exists when the intake says it does not,
    and undo any adverse verdict that rested solely on such a claim.
    A field whose topic is unchecked states nothing, so it is skipped.

    Returns the number of results corrected (for logging/tests).
    """
    checked = topics.normalize(checked)
    corrected = 0
    for check in _CONTRADICTION_CHECKS:
        if not _on("guard:" + check["field"], checked):
            continue
        value = property_details.get(check["field"])
        if value is None or not _states_absence(value, check["absent_values"]):
            continue  # feature may be present, or unknown -- nothing decidable

        for r in results:
            adverse_status = r.get("status") in ("INELIGIBLE", "REFER")
            offending = {"reasons": [], "citations": [], "missing_info": []}
            removed_adverse_ground = False
            for field in offending:
                for item in list(r.get(field, [])):
                    if check["asserts_absent"].search(item) or _INAPPLICABLE_RE.search(item):
                        continue  # correctly notes absence / inapplicability

                    # ARM 1: explicitly claims the feature exists.
                    invalid = bool(check["asserts_present"].search(item))

                    # ARM 2: applies the feature's rule AGAINST the property.
                    # This is the form that actually changed a verdict in the
                    # round 14 audit -- "The carrier's flat exclusion of solar
                    # panels makes this property ineligible regardless of other
                    # factors" never says panels are present, it just applies
                    # the exclusion. No rule about a feature the property does
                    # not have can support an adverse verdict, so this is
                    # invalid whether or not presence was asserted outright.
                    if (
                        adverse_status
                        and check["topic"].search(item)
                        and _ADVERSE_APPLICATION_RE.search(item)
                    ):
                        invalid = True
                        removed_adverse_ground = True

                    if invalid:
                        offending[field].append(item)

            note_text = r.get("notes", "")
            note_bad = bool(
                check["asserts_present"].search(note_text)
                and not check["asserts_absent"].search(note_text)
            )
            total = sum(len(v) for v in offending.values()) + (1 if note_bad else 0)
            if not total:
                continue

            corrected += 1
            # Loud server-side, deliberately. OQ-1 (the round 14 DP3 solar
            # contamination) cannot be closed by sampling: the combined-mode
            # rate is bounded at <=8.9% over 0/32 executions, so confirming
            # it would take ~150-300 runs and a null result still would not
            # prove absence. What CAN close it is catching the next real
            # occurrence -- and this guard fires exactly when one happens.
            # Printing here puts it in the Railway logs, so a recurrence is
            # detectable without waiting for a human to notice a note in the
            # UI. If this line ever appears in production logs, capture the
            # full response: that is the evidence OQ-1 is waiting for.
            print(
                "INTAKE CONTRADICTION [OQ-1]: carrier=%r field=%r intake_value=%r "
                "removed=%d status_was=%r"
                % (r.get("carrier"), check["field"], value, total, r.get("status"))
            )
            for field, items in offending.items():
                if items:
                    r[field] = [x for x in r.get(field, []) if x not in items]
            if note_bad:
                r["notes"] = ""

            removed_preview = "; ".join(
                x[:110] for items in offending.values() for x in items
            )[:400]
            _append_note(
                r,
                "[Intake contradiction] Removed {n} statement(s) asserting {label} on a "
                "property whose intake says \"{field}: {value}\". PROPERTY DETAILS is the "
                "only source of facts about the customer, and it positively states this "
                "feature is absent. Removed: {preview}".format(
                    n=total, label=check["label"], field=check["field"],
                    value=value, preview=removed_preview or "(notes)",
                ),
            )

            # An adverse verdict resting on a feature that does not exist is
            # not a verdict at all. Corrected only when that fabricated
            # feature was the SOLE stated ground -- otherwise the other
            # grounds stand and only the false statement is removed.
            if adverse_status:
                # flaw_count is the model's own count of distinct
                # ineligibility factors. At most one, and we just removed a
                # ground built on a feature that does not exist, means there
                # is nothing left holding the adverse verdict up. Same
                # conservatism as _hold_for_unresolved_topic: more than one
                # flaw and the others stand on their own.
                sole_ground = (
                    (removed_adverse_ground or bool(offending["reasons"]))
                    and r.get("flaw_count", 0) <= 1
                )
                if sole_ground and not r.get("missing_info"):
                    r["status"] = "ELIGIBLE"
                    r["flaw_count"] = 0
                    _append_note(
                        r,
                        "Status corrected to ELIGIBLE: the only ground for the adverse "
                        "determination was {label}, which this property does not have.".format(
                            label=check["label"]
                        ),
                    )
    return corrected


# Round 26 step 4 (Liam, 2026-10-05). A citation is "<label>: <quote>" (the
# label is optional): the label up to the colon that opens the quote, then one
# quoted span, then at most closing punctuation. Straight, curly and single
# quotes all count.
_CITATION_RE = re.compile(
    r"""^\s*(?:(?P<label>.*?):\s*)?["\u201c\u2018'](?P<quote>.+)["\u201d\u2019']\s*[.,;)\]]*\s*$""", re.S)
# Shorter than this (alphanumerics), a quote says too little to tell guides apart.
_MIN_QUOTE_KEY = 12
_GUIDE_KEYS = {"count": None, "keys": {}}


def _parse_citation(citation):
    """(problem, label, quote). problem is None for a clean quote, else why it
    is not one: "no quote" (no quote marks at all) or "text outside the
    quote" (commentary after the quote, or a label that is a sentence)."""
    m = _CITATION_RE.match(citation or "")
    if not m:
        has_quote = any(q in (citation or "") for q in '"\u201c\u201d')
        return ("text outside the quote" if has_quote else "no quote"), None, None
    label, quote = (m.group("label") or "").strip(), m.group("quote")
    if len(label.split()) > 8:
        return "text outside the quote", label, quote
    return None, label, quote


def _guide_keys():
    """{program: quotes.compare_key(full guide text)}, rebuilt whenever the
    store's chunk count changes (an upload or a re-seed)."""
    collection = get_vectorstore()._collection
    count = collection.count()
    if _GUIDE_KEYS["count"] != count:
        _GUIDE_KEYS["keys"] = {p: quotes.compare_key(guides.guide_text(p)) for p in guides.all_programs()}
        _GUIDE_KEYS["count"] = count
    return _GUIDE_KEYS["keys"]


def _quote_belongs_elsewhere(quote, own):
    """The other program whose guide holds `quote`, when the carrier's own
    guide does not; None when the quote is in its own guide, is too short to
    tell, or is in no guide at all (that is not this check's call)."""
    key = quotes.compare_key(quote)
    keys = _guide_keys()
    if len(key) < _MIN_QUOTE_KEY or own not in keys or quotes.appears_in(key, keys[own]):
        return None
    holders = sorted(p for p, k in keys.items() if p != own and quotes.appears_in(key, k))
    return holders[0] if holders else None


def _strip_misattributed_citations(results, relevant_carriers):
    """Post-generation attribution check: a rule may only support a
    carrier's verdict if it came from THAT carrier's own document.

    Round 12 measured ARI (HOA+) inheriting ARI (HOB)'s age-cap rule in 40%
    of runs -- sometimes while correctly labeling the citation "ARI (HOB):"
    in its own citations list, i.e. the model knew which document the rule
    came from and applied it to the wrong carrier anyway. Retrieval is
    clean here (HOA+'s own chunks never contain that text), so this is
    cross-carrier bleed-through inside one big combined completion, and a
    prompt instruction alone can't be relied on to stop it. This is the
    same shape of fix as the Progressive repair layer -- post-generation
    verification plus targeted repair -- but checking ATTRIBUTION rather
    than presence.

    Two actions, in increasing order of severity:
      1. Any citation labeled as a DIFFERENT known carrier is removed, and
         recorded in notes (never silently dropped).
      2. If that leaves an ADVERSE verdict (INELIGIBLE/REFER) with no
         surviving citation from the carrier's own document, the adverse
         verdict is unsupported -- it rested entirely on another carrier's
         text -- so it is downgraded to INSUFFICIENT_INFORMATION rather
         than left standing on evidence that was just removed.

    Deliberately conservative: only citations whose label positively
    resolves to a different known carrier are touched. Unlabeled or
    unrecognized citations are left alone, so this can only ever act on
    misattribution it can actually prove.

    NOTE: this catches misattribution that carries a carrier LABEL. It
    would NOT have caught the historical Sage "Classification A/B/C" bleed,
    which was terminology copied into prose (reasons/notes) with no
    citation label attached -- that remains covered only by the prompt
    instruction and its retrieval-level guard test.

    CHANGED (round 26 step 4, Liam's live check 2026-10-05): until now only
    the LABEL was judged. ARI_(HOA+) cited ARI_(HOB)'s "Homes 0-20 years old"
    under its own label, and the "citation" was commentary rather than a
    quote, so both passed. Two more checks, on every model citation:
      3. A citation must be a quote and nothing else: no quote marks, or text
         outside them (beyond the carrier label), removes it -- noted, never
         a status change.
      4. Its quote must be in the carrier's own guide. A quote found only in
         another program's guide counts as that program's citation (action 1,
         and action 2 if it leaves an adverse verdict unsupported).
    The rules table's citations are attached by code from the workbook, and
    are left alone."""
    for r in results:
        own = _resolve_structured_carrier(r.get("carrier", ""), relevant_carriers)
        if own is None or r.get("rules_table"):
            continue
        citations = r.get("citations", [])
        if not citations:
            continue

        kept, foreign, not_quotes = [], [], []
        saw_own_citation = False
        for c in citations:
            problem, _label, quote = _parse_citation(c)
            if problem:
                not_quotes.append((c, problem))
                continue
            attributed = _citation_attributed_carrier(c, relevant_carriers)
            if attributed is not None and attributed != own:
                foreign.append((c, attributed))
                continue
            elsewhere = _quote_belongs_elsewhere(quote, own)
            if elsewhere is not None:
                foreign.append((c, elsewhere))
                continue
            if attributed == own:
                saw_own_citation = True
            kept.append(c)

        if not_quotes:
            print("CITATION CHECK: carrier=%r removed=%d not a quote: %s"
                  % (own, len(not_quotes), "; ".join(f"{why}: {c[:80]!r}" for c, why in not_quotes)))
            _append_note(
                r,
                "[Citation check] Removed {n} citation(s) that were not a quote from the guide."
                .format(n=len(not_quotes)),
            )
        if not foreign:
            r["citations"] = kept
            continue

        r["citations"] = kept
        foreign_names = sorted({name for _, name in foreign})
        _append_note(
            r,
            "[Attribution check] Removed {n} citation(s) belonging to another carrier "
            "({names}) -- a rule from a different carrier's document cannot support this "
            "carrier's determination.".format(n=len(foreign), names=", ".join(foreign_names)),
        )

        if r.get("status") in ("INELIGIBLE", "REFER") and not saw_own_citation:
            r["status"] = "INSUFFICIENT_INFORMATION"
            r["flaw_count"] = 0
            _append_note(
                r,
                "Status downgraded to INSUFFICIENT_INFORMATION: the adverse determination "
                "rested only on citation(s) from another carrier's document, leaving no "
                "support from this carrier's own guidelines.",
            )


_SAGE_FPC_CONDITION_WORDS = re.compile(
    r"visib|public road|fire alarm|central station|year-round|roadway|fire[- ]equipment|"
    r"home age|age of (?:the )?home|under 25|primary occupancy|rental|fire loss", re.I)


def _sage_fpc_hold(r, status, items, reason, canon):
    """Round 27 step 2: a Sage FPC row with a stated distance that is not a
    plain yes or no. A model decline on another rule stands; otherwise the
    carrier holds (or is referred, when a condition the form answers fails)
    on the row's conditions, code-decided, in the guide's words."""
    if r.get("status") == "INELIGIBLE":
        return
    r["status"], r["flaw_count"] = status, 0
    # The distance is answered; a hydrant item stays only if the row asks for
    # it; and the model's own wording of the row's conditions ("Visibility
    # from main public road") gives way to the guide's (LIVE, Luna, round 27).
    keep_hydrant = "Hydrant within 1,000 ft" in items
    mi = [m for m in r.get("missing_info") or []
          if "fire station" not in m.lower() and (keep_hydrant or "hydrant" not in m.lower())
          and not _SAGE_FPC_CONDITION_WORDS.search(m)]
    r["missing_info"] = list(dict.fromkeys(items + [m for m in mi if m not in items]))
    _decide_by_code(r, status, "Sage FPC table: " + reason)


def _apply_structured_overrides(results, relevant_carriers, property_details, checked=None,
                                fpc_skip=frozenset()):
    """Each branch is gated by its topic tag (topics.STEPS["override:<set>"]);
    a rule needing an unchecked topic is skipped. The carrier sets of the
    elif chain are disjoint (a test checks it), so skipping one branch never
    hands its carrier to another."""
    checked = topics.normalize(checked)
    for r in results:
        canon = _resolve_structured_carrier(r.get("carrier", ""), relevant_carriers)
        if canon is None:
            continue

        # Snapshot of what the MODEL itself wrote, taken before any override
        # below appends to reasons/citations/notes. Used only for topic
        # relevance -- see _hold_for_unresolved_topic's docstring for the
        # bug that made reading these fields live actively wrong.
        model_text = " ".join(
            r.get("reasons", []) + r.get("citations", []) + [r.get("notes", "")]
        ).lower()

        # fpc_skip: with the rules-table pilot ON, Sage Auros's own FPC table
        # rows (SAG-072..SAG-080) decide instead (round 24 found this upgrade
        # overrides them -- round 19's open item). Other Sage carriers keep it.
        if (canon in _SAGE_FPC_CARRIERS and canon not in fpc_skip
                and _on("override:_SAGE_FPC_CARRIERS", checked)):
            # Round 26 (decision B): the optional station distance and hydrant
            # answer pick the table row; Unknown stays None, never "no".
            hydrant = intake_fields.hydrant_answer(property_details.get("hydrant_1000ft"))
            miles = intake_fields.parse_station_miles(property_details.get("fire_station_miles"))
            s_status, s_reasons = sage_family_fpc_eligibility(
                property_details['ppc'], carrier=canon,
                distance_miles=miles,
                hydrant_feet={"Yes": 1000, "No": 1001}.get(hydrant),
            )
            # Round 27 step 2 (Liam, 2026-10-06, decision 2): with a STATED
            # distance, only row A may upgrade to ELIGIBLE and FPC 9+ over 5
            # miles declines (both below, as before); every "eligible only if"
            # row holds on its conditions, and an unknown hydrant within 5
            # miles holds on the hydrant alone. A blank distance never enters.
            if miles is not None:
                d_status, d_items, d_reason, _row = sage_fpc_with_distance(
                    property_details['ppc'], miles, hydrant,
                    home_age=(date.today().year - int(property_details["year_built"])
                              if _on("fact:home_age", checked) and property_details.get("year_built") else None),
                    occupancy=property_details.get("occupancy_type"), carrier=canon)
                if d_status in ("INSUFFICIENT_INFORMATION", "REFER"):
                    _sage_fpc_hold(r, d_status, d_items, d_reason, canon)
                    s_status = None                  # handled; skip the branches below
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
                if any(kw in blob for kw in ("fpc", "fire protection class", "protection class", "ppc",
                                             "fire station", "hydrant")):
                    r["status"] = "ELIGIBLE"
                    r["flaw_count"] = 0
                    # Row 1 (within 5 miles, hydrant within 1,000 ft) has no
                    # conditions and so no reason text -- reachable only since
                    # round 26 gave the form these fields.
                    _append_note(r, "Structured FPC check: " + (s_reasons[0] if s_reasons else (
                        "the fire station is within 5 miles and a hydrant within 1,000 ft, which this "
                        "carrier's FPC table makes eligible with no conditions.")))
                    # Round 26: an item the form now answers is no longer open.
                    answered = [w for w, v in (("fire station", property_details.get("fire_station_miles")),
                                               ("hydrant", hydrant)) if v not in (None, "")]
                    if answered:
                        r["missing_info"] = [m for m in r.get("missing_info") or []
                                             if not any(w in m.lower() for w in answered)]
            elif s_status == "INELIGIBLE":
                # Round 26: only reachable with a stated distance (FPC 9+ over
                # 5 miles) -- the table decides, not the model.
                _force_ineligible(r, "Sage FPC table: " + s_reasons[0])
            elif s_status == "INSUFFICIENT_INFORMATION":
                mi = r.setdefault("missing_info", [])
                if not any("fire station" in m.lower() for m in mi):
                    mi.append(
                        "Driving distance to the responding fire station "
                        "(needed to determine FPC 9+ eligibility)."
                    )
                # CHANGED (round 13, P2): the identical wiring gap the TWICO
                # branch below had. FPC 9+ is ELIGIBLE within 5 driving miles
                # of the station and INELIGIBLE beyond it -- a genuine
                # divergence on a fact the intake never collects -- yet a
                # model verdict of INELIGIBLE here used to stand untouched,
                # with the caveat visible only as a missing_info line.
                _hold_for_unresolved_topic(
                    r, "fpc",
                    s_reasons[0] if s_reasons else (
                        "This carrier's FPC table resolves to different eligibility outcomes "
                        "depending on driving distance to the fire station, which the intake "
                        "does not collect."
                    ),
                    model_text,
                )

        elif canon in _MERCURY_CARRIERS and _on("override:_MERCURY_CARRIERS", checked):
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

        elif canon in _SAGE_MARKEL_CARRIERS and _on("override:_SAGE_MARKEL_CARRIERS", checked):
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

        elif canon in _SWYFFT_MAX30_CARRIERS and _on("override:_SWYFFT_MAX30_CARRIERS", checked):
            s_status, s_reasons = swyfft_max_roof_age_30(property_details['roof_age'])
            if s_status == "INELIGIBLE":
                _force_ineligible(r, s_reasons[0])
            else:
                _append_note(r, f"Roof age {property_details['roof_age']} is within the 30-year maximum.")

        elif canon in _TWICO_CARRIERS and _on("override:_TWICO_CARRIERS", checked):
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
                # CHANGED (round 12, second pass): appending the missing_info
                # item alone was not enough. A real run produced a
                # CONFIDENTLY WRONG bracket claim in the model's own prose
                # ("21 years falls within the 11-20 year range... assuming
                # standard composition") sitting right next to this correct
                # caveat -- age 21 is EXCLUDED under 3-tab, not ACV. The
                # structured table knows both possible outcomes exactly, so
                # state them explicitly rather than leaving the model's
                # guess as the only concrete number in the output.
                age = property_details['roof_age']
                # CHANGED (round 13): gated on the roof type actually being
                # composition. twico_roof_settlement() also returns
                # INSUFFICIENT_INFORMATION for a material simply absent from
                # TWICO's table (e.g. "Foam"), and the sub-type comparison
                # below would have attached a confident, entirely fictional
                # "3-tab vs architectural" caveat to such a roof.
                if twico_roof_subtype_is_ambiguous(property_details['roof_type']):
                    three_tab, _ = twico_roof_settlement("Composition (3-tab)", age)
                    architectural, _ = twico_roof_settlement("Composition (Architectural)", age)
                    if three_tab != architectural:
                        _append_note(
                            r,
                            f"Roof settlement depends on the unconfirmed shingle sub-type: at "
                            f"{age} years, 3-tab resolves to {three_tab} and architectural "
                            f"resolves to {architectural}. Any single bracket stated above "
                            f"without that confirmation is an assumption, not a determination.",
                        )
                        # CHANGED (round 13, P2): and that same conclusion now
                        # reaches STATUS. Writing the caveat into notes while
                        # leaving status at a confident INELIGIBLE was the
                        # entire bug -- the note said "assumption, not a
                        # determination" and the status said otherwise.
                        _hold_for_unresolved_topic(
                            r, "roof",
                            f"TWICO's roof settlement outcome at {age} years diverges by "
                            f"composition shingle sub-type (3-tab resolves to {three_tab}, "
                            f"architectural resolves to {architectural}), and the intake does "
                            f"not collect that sub-type.",
                            model_text,
                        )
                else:
                    _append_note(
                        r,
                        f"Roof type {property_details['roof_type']!r} does not appear in "
                        f"TWICO's roof settlement table -- its settlement basis cannot be "
                        f"determined from this carrier's document.",
                    )
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

        # NOT part of the elif chain above, deliberately: six of these nine
        # carriers also match _SAGE_FPC_CARRIERS, so an elif would silently
        # skip the roof rule for exactly the carriers the round 14 audit
        # flagged. This is the same wiring mistake round 12 made with the
        # Sage FPC check itself -- a correct conclusion that never reaches
        # the output because an earlier branch consumed the carrier.
        if canon in _SAGE_ROOFER_STATEMENT_CARRIERS and _on("override:_SAGE_ROOFER_STATEMENT_CARRIERS", checked):
            s_status, s_reasons = sage_roofer_statement_required(
                property_details['roof_type'], property_details['roof_age'],
            )
            # Round 24 (Liam, 2026-10-02): the roofer's statement is an
            # inspection, so it is not checked. Both branches only NOTE it;
            # neither adds a missing_info item or holds a verdict. Before
            # round 24 the sub-type case added a "Roof shingle sub-type"
            # item plus _hold_for_unresolved_topic, and REQUIRED added a
            # "Roofer's statement attesting ..." item.
            if s_status == "INSUFFICIENT_INFORMATION":
                # Both sides still get stated (round 14): which side applies
                # depends on the unstated 3-tab / architectural sub-type.
                _append_note(r, s_reasons[0] + " " + ROOFER_STATEMENT_NOT_CHECKED)
            elif s_status == "REQUIRED":
                _append_note(r, "Roof is over the guide's age line; the guide asks for a roofer's "
                                "statement on its Roof Condition Form (not checked). " + s_reasons[0])
            else:
                _append_note(r, "No roofer's statement required: " + s_reasons[0])

        # Also an independent `if`. Centauri's flat-roof clause is flatly
        # conditional -- ineligible unless poured concrete -- and Roof Type
        # already settles which side the property falls on, so this is a
        # lookup, not a judgment call. Round 14 added the roof-shape
        # retrieval guarantee that puts the clause in front of the model;
        # measured on 12 runs, surfacing it alone dropped Centauri from
        # 12/12 INELIGIBLE to 5/12, with 7 runs treating "is it poured
        # concrete?" as unknown when the intake already answers it.
        if canon in _CENTAURI_DP3_CARRIERS and _on("override:_CENTAURI_DP3_CARRIERS", checked):
            s_status, s_reasons = centauri_dp3_flat_roof(
                property_details.get('roof_shape'), property_details.get('roof_type'),
            )
            if s_status == "INELIGIBLE":
                _force_ineligible(r, s_reasons[0])
            elif s_status == "INSUFFICIENT_INFORMATION":
                _append_note(r, s_reasons[0])
                mi = r.setdefault("missing_info", [])
                if not any("poured concrete" in m.lower() for m in mi):
                    mi.append(
                        "Whether this flat roof is a poured concrete deck -- Centauri "
                        "excludes flat roofs unless they are."
                    )
            elif s_status == "ELIGIBLE":
                _append_note(r, s_reasons[0])


# ---------------------------------------------------------------------------
# JSON repair: unescaped double quotes inside generated string values.
# (round 13, found while running the round 13 baseline tier.)
#
# This is the THIRD distinct cause behind "JSON PARSE ERROR" in this
# project, and the first two were both diagnosed from partial output and
# then partly misattributed:
#   round 11/12  blamed on ARI's curly apostrophes + embedded newlines
#                (a real cleanup, but not what was failing most runs)
#   round 12     found to be output-token TRUNCATION -- fixed by raising
#                max_tokens to 24000
#   round 13     THIS: a complete, untruncated response (stop_reason
#                "end_turn", 50k chars) whose Mercury citation reads
#                    "The "Roof Surfacing" Loss Settlement Payment Schedule"
#                with RAW, unescaped inner double quotes, which is not legal
#                JSON. Mercury's extracted chunk text has U+FFFD where the
#                source PDF's curly quotes were, and the model helpfully
#                "restores" them as real double quotes inside its own JSON
#                string.
#
# Sanitizing the source text is not a safe fix here: U+FFFD is also what
# extraction produced for Mercury's BULLET characters in the very same
# sentence, so mapping it to a quote would corrupt every bullet list in the
# corpus. 17 of 28 carriers have double-quote characters in their text, so
# this is a broad exposure, not a Mercury quirk.
#
# Repairing the JSON is the general fix: it addresses any unescaped inner
# quote from any carrier, and a failure here is expensive -- the whole
# response, all 28 carriers, is discarded and the agent sees "Parse Error".
# ---------------------------------------------------------------------------

_JSON_CLOSING_THEN_END = re.compile(r"\s*[:\]\}]")
# After a genuine closing quote and a comma, valid JSON must begin the next
# value or key. Bare prose does not.
_JSON_VALID_AFTER_COMMA = re.compile(r'\s*,\s*(?:"|\{|\[|-|\d|true\b|false\b|null\b)')


def _is_json_closing_quote(json_str, i):
    rest = json_str[i + 1:]
    if rest.strip() == "":
        return True
    if _JSON_CLOSING_THEN_END.match(rest):
        return True
    # A following comma alone is NOT sufficient. In
    #     "The rule says "X", which means Y"
    # the inner quote is also followed by a comma; only checking for one
    # would end the string there and turn the rest into garbage.
    return bool(_JSON_VALID_AFTER_COMMA.match(rest))


def repair_unescaped_quotes(json_str):
    """Escape double quotes that appear INSIDE a JSON string value.

    Returns (repaired_text, number_of_quotes_escaped). Verified against the
    real captured failure (Mercury's "Roof Surfacing" citation): 2 quotes
    escaped, all 28 carriers recovered from a response that was otherwise
    thrown away entirely.
    """
    out = []
    in_string = False
    escaped = False
    repairs = 0
    for i, ch in enumerate(json_str):
        if not in_string:
            out.append(ch)
            if ch == '"':
                in_string = True
            continue
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            if _is_json_closing_quote(json_str, i):
                out.append(ch)
                in_string = False
            else:
                out.append('\\"')
                repairs += 1
            continue
        out.append(ch)
    return "".join(out), repairs


def parse_carrier_json(json_str):
    """json.loads, with one repair attempt for unescaped inner quotes.

    Raises the ORIGINAL JSONDecodeError if the repair does not help, so the
    diagnostics downstream describe the real problem rather than the
    repaired text.
    """
    try:
        return json.loads(json_str), 0
    except json.JSONDecodeError as original:
        repaired, n = repair_unescaped_quotes(json_str)
        if n:
            try:
                return json.loads(repaired), n
            except json.JSONDecodeError:
                pass
        raise original


def _rules_pilot_prepare(carriers, property_details, checked):
    """With RULES_PILOT on: evaluate each pilot carrier in `carriers` from the
    form. Carriers code decides alone become records now; the rest go to the
    pilot model call. OFF: nothing (the pipeline is unchanged)."""
    out = {"carriers": frozenset(), "records": [], "open": {}, "outcomes": {}}
    if not RULES_PILOT:
        return out
    on = _batches_on()
    wbs = {c: rules_evaluator.rules_table_wb(c, on, property_details) for c in carriers}
    chosen = [c for c in carriers if wbs[c]]
    out["carriers"] = frozenset(chosen)
    for c in chosen:
        outcomes = rules_evaluator.evaluate_carrier(c, property_details, checked, wb=wbs[c])
        out["outcomes"][c] = outcomes
        rec, decided = rules_evaluator.code_record(c, outcomes)
        if decided:
            out["records"].append(rec)
        else:
            out["open"][c] = outcomes
    return out


def _rules_pilot_model_records(raw, open_carriers):
    """The pilot call's records, one per open carrier, with code-attached
    citations and the never-a-hold notes. A carrier the model left out gets
    no record here (the pipeline's NOT_EVALUATED row covers it)."""
    try:
        body = (raw or "").replace("```json", "").replace("```", "").strip()
        parsed = json.loads(body)
        recs = parsed.get("carriers", parsed) if isinstance(parsed, dict) else parsed
    except (ValueError, AttributeError):
        print("RULES PILOT: unparseable pilot answer; its carriers get NOT_EVALUATED rows")
        return []
    out, done = [], set()
    for r in recs if isinstance(recs, list) else []:
        if not isinstance(r, dict):
            continue
        canon = _resolve_structured_carrier(r.get("carrier", ""), list(open_carriers))
        if canon is None or canon in done:
            continue
        done.add(canon)
        out.append(rules_evaluator.finish_model_record(r, canon, open_carriers[canon]))
    return out


def _reply_records(raw):
    """The records of a JSON reply ({"carriers": [...]} or a bare list), or None."""
    body = (raw or "").replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(body)
    except ValueError:
        return None
    recs = parsed.get("carriers") if isinstance(parsed, dict) else parsed
    return [r for r in recs if isinstance(r, dict)] if isinstance(recs, list) else None


def _retry_omitted(raw, carriers, user_content):
    """Round 29 step 2 (2026-10-08): carriers the reply left out get ONE more call,
    for just them (same prompt and schema, the carrier enum narrowed to them).
    Their records are merged into the reply; a carrier still missing keeps its
    NOT_EVALUATED ("run the check again") row. Round 28: Haiku low left out 4
    carriers in 24 checks, Luna 2. Returns (raw, retry usage or None)."""
    recs = _reply_records(raw)
    if recs is None or not carriers:
        return raw, None
    covered = {_resolve_structured_carrier(r.get("carrier", ""), carriers) for r in recs}
    missing = [c for c in carriers if c not in covered]
    if not missing:
        return raw, None
    print(f"OMITTED CARRIERS: {missing} -- retrying once for just these")
    note = ("\n\nANSWER ONLY FOR THESE CARRIERS (your previous answer left them out; give one record each): "
            + "; ".join(missing))
    raw2, usage2 = _complete_named(missing, SYSTEM_INSTRUCTIONS, user_content + note, MAX_RESPONSE_TOKENS)
    extra = [r for r in (_reply_records(raw2) or [])
             if _resolve_structured_carrier(r.get("carrier", ""), missing) is not None]
    return json.dumps({"carriers": recs + extra}, ensure_ascii=False), usage2


def check_eligibility(property_details, carrier_subset=None, checked_topics=None):
    """carrier_subset: optional iterable of carrier names to restrict
    evaluation to (intersected with the normal occupancy filter). Used to
    pilot splitting the combined multi-carrier completion into smaller
    per-group calls without touching the default single-call behavior when
    omitted.

    checked_topics: the topic keys the agent ticked (topics.TOPIC_KEYS).
    None means everything, exactly as before. An unchecked topic is not
    considered at all (Liam, 2026-10-01): its facts, lookups, query terms
    and rules are skipped, and missing_info items about it are stripped."""
    occupancy = property_details['occupancy_type']
    # Round 21: every gated step below asks _on(step, checked); see topics.py.
    checked = topics.normalize(checked_topics)

    # CHANGED: home age computed here instead of leaving the model to infer
    # the current year -- it was previously off by one year when the model
    # assumed the wrong current year.
    home_age = date.today().year - property_details['year_built']

    query = build_retrieval_query(property_details, home_age, checked)

    relevant_carriers = get_carriers_for_occupancy(occupancy)
    # Carriers whose guide on file is unusable (data_defects: wrong document,
    # or none at all) are left out of the prompt entirely and shown as a fixed
    # warning row instead -- see _add_fixed_rows. Absent programs (Centauri
    # HO3 produced no text, so the store never held it) are routed by the
    # same occupancy rule as stored ones.
    defects = data_defects.defective_programs()
    combined = get_combined_program_carriers()
    unavailable = sorted(
        p for p in defects
        if p in relevant_carriers
        or (p not in get_all_carriers() and _fits_occupancy(p, occupancy, combined))
    )
    if carrier_subset is not None:
        subset = set(carrier_subset)
        relevant_carriers = [c for c in relevant_carriers if c in subset]
        unavailable = [p for p in unavailable if p in subset]
    relevant_carriers = [c for c in relevant_carriers if c not in defects]
    # Dwelling type (optional, Liam 2026-09-30). House routes the condo
    # programs out, the same way occupancy routes DP/HO programs: they never
    # enter the check, and a defective one gets no warning row either.
    # Townhome and Condo change no routing -- they go in as a stated fact.
    if _dwelling_type(property_details) == "House":
        relevant_carriers = [c for c in relevant_carriers if not _is_condo_program(c)]
        unavailable = [p for p in unavailable if not _is_condo_program(p)]
    # Closed programs (round 26 step 9) never reach retrieval or the model;
    # each gets its fixed row at the end.
    closed = closed_programs(relevant_carriers)
    relevant_carriers = [c for c in relevant_carriers if c not in closed]
    # Rules-table pilot: the pilot carriers leave retrieval and the main
    # prompt. Everything after the model call uses all_carriers again.
    all_carriers = relevant_carriers
    pilot = _rules_pilot_prepare(relevant_carriers, property_details, checked)
    if pilot["carriers"]:
        relevant_carriers = [c for c in relevant_carriers if c not in pilot["carriers"]]
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
    if _on("guarantee:ppc", checked) and property_details['ppc'] != 'N/A':
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
    # CHANGED (round 13, P3): the same chunks that go into the prompt are
    # also scanned here for each carrier's OWN stated fence height / gate
    # mechanism, so _enforce_pool_spec_support() below can check the
    # model's answer against the carrier's actual requirement rather than
    # trusting it to have read the number correctly.
    pool_specs = {}
    if _on("guarantee:pool", checked) and property_details['swimming_pool'] != 'No Pool':
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
            spec = {"heights": set(), "gates": set()}
            for chunk in found:
                found_spec = _extract_pool_spec(normalize_chunk_text(chunk.page_content))
                spec["heights"] |= found_spec["heights"]
                spec["gates"] |= found_spec["gates"]
                key = (carrier, chunk.page_content)
                if key not in seen:
                    seen.add(key)
                    chunks.append(chunk)
            if spec["heights"] or spec["gates"]:
                pool_specs[carrier] = spec

    # CHANGED: guaranteed per-carrier solar panel rule lookup, same pattern
    # as PPC and pool above (see _mentions_solar docstring for why this was
    # added -- it missed an actual wrong verdict on TWICO).
    MAX_SOLAR_CHUNKS_PER_CARRIER = 2
    # CHANGED (round 13, P4): each carrier's solar language is also
    # classified as integrated solar ROOFING vs. MOUNTED panels, so a
    # carrier whose rule cannot apply to this property says so explicitly
    # instead of going silent. The classification reads the carrier's WHOLE
    # document, not the chunks kept below -- see classify_carrier_solar_text.
    solar_classes = {}
    if _on("guarantee:solar", checked) and property_details['solar_panels'] == 'Yes':
        for carrier in relevant_carriers:
            found = guaranteed_carrier_lookup(
                collection, carrier, predicate=_mentions_solar, keep=MAX_SOLAR_CHUNKS_PER_CARRIER,
            )
            # Classified over the carrier's WHOLE document, deliberately --
            # see classify_carrier_solar_text()'s docstring for the Foremost
            # case that makes the kept-chunks-only version actively wrong.
            solar_classes[carrier] = classify_carrier_solar_text(collection, carrier)
            for chunk in found:
                key = (carrier, chunk.page_content)
                if key not in seen:
                    seen.add(key)
                    chunks.append(chunk)

    # CHANGED (round 14): guaranteed per-carrier ROOF SHAPE lookup. Same
    # pattern and same rationale as PPC/pool/solar/roof-age above -- see
    # _mentions_roof_shape_rule's docstring for the Centauri DP3 case where
    # a flat-roof INELIGIBILITY never reached the prompt and the model
    # therefore reported the opposite.
    MAX_ROOF_SHAPE_CHUNKS_PER_CARRIER = 2
    shape_keywords = _RESTRICTED_ROOF_SHAPES.get(
        str(property_details.get("roof_shape", "")).strip().lower()
    )
    if _on("guarantee:roof_shape", checked) and shape_keywords:
        for carrier in relevant_carriers:
            found = guaranteed_carrier_lookup(
                collection, carrier,
                predicate=lambda doc: _mentions_roof_shape_rule(doc, shape_keywords),
                keep=MAX_ROOF_SHAPE_CHUNKS_PER_CARRIER,
                # prefer chunks that pair the shape with ineligibility language
                priority_key=lambda c: not any(
                    k in c.page_content.lower()
                    for k in ("ineligib", "not eligible", "exclu", "unacceptable", "prohibited")
                ),
            )
            for chunk in found:
                key = (carrier, chunk.page_content)
                if key not in seen:
                    seen.add(key)
                    chunks.append(chunk)

    # Round 29 step 7 (2026-10-08): guaranteed per-carrier PLUMBING MATERIAL lookup. Round 28 found
    # seven guides (ARI HOA+ / HOB, the three Swyfft Surplus, TWICO, Travelers) whose galvanized
    # decline never reached the prompt for a galvanized home, so no model could apply it. When the
    # form names a material guides decline, every carrier's chunks that name it are kept.
    MAX_PLUMBING_CHUNKS_PER_CARRIER = 2
    material = _PLUMBING_MATERIAL_WORDS.get(str(property_details.get("plumbing_type", "")))
    if _on("guarantee:plumbing", checked) and material:
        for carrier in relevant_carriers:
            found = guaranteed_carrier_lookup(
                collection, carrier, predicate=lambda doc: material in doc.lower(),
                keep=MAX_PLUMBING_CHUNKS_PER_CARRIER,
                # prefer chunks that pair the material with ineligibility language
                priority_key=lambda c: not any(
                    k in c.page_content.lower()
                    for k in ("ineligib", "not eligible", "not accept", "unacceptable", "exclu", "decline")
                ),
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
    for carrier in (relevant_carriers if _on("guarantee:roof_life", checked) else []):
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

    # CHANGED (round 17): guaranteed per-carrier OCCUPANCY / OWNERSHIP
    # eligibility lookup -- who the carrier will insure at all. Same pattern
    # as PPC/pool/solar/roof-age/roof-shape above; see
    # _mentions_occupancy_eligibility's docstring for the CHUBB clause that
    # never reached the prompt and the Allied Trust LLC exclusion that didn't
    # either. Unconditional, like roof life expectancy: every property has an
    # occupancy and an ownership structure, so this rule is always in play.
    # Trust / LLC properties additionally get entity-ownership rules and a
    # larger cap; an individual owner gets occupancy rules only (Liam's call,
    # round 17 -- see the split above _OCCUPANCY_RULE_RE).
    #
    # Since 2026-09-28 it runs only where _occupancy_guarantee_applies says so
    # (Trust / LLC today); an individual owner's prompt is exactly main's.
    ownership = property_details.get("ownership_type", "")
    occupancy_key = _occupancy_priority_key(ownership)
    occupancy_predicate = _occupancy_predicate_for(ownership)
    occupancy_cap = _occupancy_cap_for(ownership)
    for carrier in (relevant_carriers if _on("guarantee:occupancy", checked)
                    and _occupancy_guarantee_applies(property_details) else []):
        found = guaranteed_carrier_lookup(
            collection, carrier,
            predicate=occupancy_predicate,
            keep=occupancy_cap,
            priority_key=occupancy_key,
        )
        for chunk in found:
            key = (carrier, chunk.page_content)
            if key not in seen:
                seen.add(key)
                chunks.append(chunk)

    # Coverage A guarantee (Liam, 2026-09-30): ONLY when the optional
    # Dwelling amount is filled -- the same gating pattern as the ownership
    # guarantee, so a blank field adds nothing to the prompt. One chunk per
    # carrier: its own minimum / maximum / binding-authority dwelling limit.
    for carrier in (relevant_carriers if _on("guarantee:coverage_a", checked)
                    and _dwelling_amount(property_details) else []):
        found = guaranteed_carrier_lookup(
            collection, carrier,
            predicate=_mentions_coverage_a_limit,
            keep=MAX_COVERAGE_A_CHUNKS_PER_CARRIER,
            priority_key=_coverage_a_priority_key,
        )
        for chunk in found:
            key = (carrier, chunk.page_content)
            if key not in seen:
                seen.add(key)
                chunks.append(chunk)

    risk_factors = build_risk_factors(property_details, occupancy, checked)

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
            context += normalize_chunk_text(stitched_text(
                carrier, chunk.page_content, chunk.metadata.get("is_table"))) + "\n"

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
    user_content = (_property_details_text(property_details, home_age, occupancy, ownership, checked,
                                           relevant_carriers)
                    + _partial_check_instruction(checked)
                    + "\n\nCARRIER DOCUMENTS:\n" + context + "\n")

    if no_chunk_carriers:
        user_content += "\nCARRIERS WITH NO RETRIEVED INFORMATION:\n"
        user_content += "\n".join(f"- {c}" for c in no_chunk_carriers)
        user_content += "\n"

    # CHANGED (round 12): MAX_RESPONSE_TOKENS raised from 12000. A recurring
    # "JSON PARSE ERROR" (~20-30% of runs, previously misattributed to a
    # character-escaping issue in ARI's chunk text -- see
    # normalize_chunk_text()'s docstring) was confirmed via a full,
    # untruncated capture of an actual failure to be a plain output-token
    # budget overrun: the response cut off mid-object after only ~20 of ~28
    # carriers, with missing_info's closing "]" but no closing "}" or outer
    # "]" -- the model simply ran out of its 12000-token allowance partway
    # through a verbose ~28-carrier JSON array. The earlier ARI
    # apostrophe/newline fix wasn't wrong to apply (it's still a real,
    # harmless cleanup) but it was NOT the cause of the recurring failures --
    # every previous debug print only showed raw[:1000], which always
    # happens to contain ARI's section since it sorts near the start of the
    # carrier list, regardless of where the actual truncation occurred much
    # later.
    #
    # CHANGED (round 12, separately): the Anthropic SDK estimates a
    # non-streaming call's worst-case duration from max_tokens alone (3600s *
    # max_tokens / 128000) and REFUSES to make the call at all above a
    # 10-minute estimate -- raising MAX_RESPONSE_TOKENS to 24000 alone pushed
    # this past that threshold. _complete_anthropic passes an explicit
    # timeout to skip that heuristic entirely; real calls have taken up to
    # ~180s observed this session, so 900s leaves large headroom.
    if pilot["open"]:
        # The pilot call sees the same PROPERTY DETAILS (and partial-check
        # line) and only the open rows; it runs alongside the main call.
        pilot_content = (_property_details_text(property_details, home_age, occupancy, ownership, checked,
                                                list(pilot["open"]))
                         + _partial_check_instruction(checked) + "\n\n"
                         + rules_evaluator.evidence_text(pilot["open"]))
        with ThreadPoolExecutor(max_workers=2) as pool:
            main_future = pool.submit(_complete_named, relevant_carriers, SYSTEM_INSTRUCTIONS, user_content,
                                      MAX_RESPONSE_TOKENS)
            pilot_future = pool.submit(_complete_named, list(pilot["open"]), SYSTEM_INSTRUCTIONS,
                                       pilot_content, MAX_RESPONSE_TOKENS)
            raw, usage = main_future.result()
            pilot_raw, pilot_usage = pilot_future.result()
        pilot_raw, pilot_retry_usage = _retry_omitted(pilot_raw, list(pilot["open"]), pilot_content)
        pilot["records"] += _rules_pilot_model_records(pilot_raw, pilot["open"])
    else:
        raw, usage = _complete_named(relevant_carriers, SYSTEM_INSTRUCTIONS, user_content, MAX_RESPONSE_TOKENS)
        pilot_usage = pilot_retry_usage = None
    raw, main_retry_usage = _retry_omitted(raw, relevant_carriers, user_content)
    LAST_CALL_USAGE.clear()
    LAST_CALL_USAGE.update(main=usage, pilot=pilot_usage)
    if main_retry_usage:
        LAST_CALL_USAGE["main_retry"] = main_retry_usage
    if pilot_retry_usage:
        LAST_CALL_USAGE["pilot_retry"] = pilot_retry_usage
    LAST_GUARD_STATS.clear()
    relevant_carriers = all_carriers

    # CHANGED: cache visibility. cache_read_input_tokens > 0 means this call
    # got a cache hit; cache_creation_input_tokens > 0 means this call just
    # wrote the cache (normal on the first call, or after the ~5 min TTL
    # lapses between checks). Always 0/0 on the OpenAI path -- see
    # _complete's docstring.
    print(
        "Cache: read=%s created=%s input=%s"
        % (
            usage["cache_read_input_tokens"],
            usage["cache_creation_input_tokens"],
            usage["input_tokens"],
        )
    )

    raw = raw.strip()

    if "```" in raw:
        raw = raw.replace("```json", "").replace("```", "").strip()

    start = raw.find('[')
    end = raw.rfind(']') + 1
    if start != -1 and end > start:
        json_str = raw[start:end]
    else:
        json_str = raw

    try:
        parsed, quote_repairs = parse_carrier_json(json_str)
        if quote_repairs:
            print(
                f"JSON repair: escaped {quote_repairs} unescaped inner double quote(s) "
                f"in the model's response -- recovered {len(parsed)} carrier record(s) "
                f"that would otherwise have been discarded."
            )
        # A wrapper object with no list, or non-object items, is not an
        # answer; treat it as none (NOT_EVALUATED rows + the banner) rather
        # than crash on r.get().
        if not isinstance(parsed, list):
            parsed = []
        parsed = [_normalize_record(r) for r in parsed + pilot["records"] if isinstance(r, dict)]

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
            # Resolve the model's restated name back to the canonical
            # carrier first, so this uses the SAME classification as
            # retrieval. Judging the echoed string directly is what let
            # "Sage - SURE HO-3" through here even when retrieval had
            # already been fixed; and for ARI/CHUBB the echoed name carries
            # no product token at all, so only the canonical lookup knows.
            canon = _resolve_structured_carrier(r.get("carrier", ""), relevant_carriers)
            if canon is not None:
                is_ho3, is_dp3 = carrier_programs(canon)
            else:
                is_ho3, is_dp3 = carrier_programs(name)
            if occupancy != "Owner Occupied" and is_ho3 and not _owners_other_home_fits(canon or name, occupancy):
                continue
            if occupancy == "Owner Occupied" and is_dp3:
                continue
            filtered.append(r)

        # A record whose status is not one the model may write is held out
        # of every post-parse check (none of them should act on a verdict
        # that does not exist) and shown as its own "Could Not Be Checked"
        # row. 2026-09-30, live: gpt-6-luna returned 23 records with NO
        # status or flaw_count key at all; assign_buckets placed none of
        # them, and because _add_fixed_rows counted coverage by NAME, no
        # NOT_EVALUATED row appeared either -- four empty columns.
        unrecognised = [r for r in filtered if r.get("status") not in MODEL_STATUSES]
        filtered = [r for r in filtered if r.get("status") in MODEL_STATUSES]

        # Attribution check runs BEFORE the structured overrides: it can
        # downgrade an unsupported adverse verdict, and the structured
        # overrides should then see (and be able to act on) that corrected
        # status rather than the pre-correction one.
        # Runs before everything else: a claim contradicting the intake is
        # the most fundamental error there is, and the checks below should
        # act on a corrected status rather than a fabricated one.
        # Round 29 step 1: the model's own missing_info, before any code rule adds to it
        # (hold_guard tells a code-made item from a model's by this).
        for r in filtered:
            r["_model_missing_info"] = list(r.get("missing_info") or [])
        _strip_contradicted_property_claims(filtered, property_details, checked)
        _strip_misattributed_citations(filtered, relevant_carriers)
        _apply_structured_overrides(filtered, relevant_carriers, property_details, checked,
                                    fpc_skip=pilot["carriers"])
        # Runs last: it only ever ADDS a missing_info item and a note, so it
        # cannot be undone by an override, and it must see the final set of
        # carriers rather than a pre-override one.
        if _on("check:_enforce_pool_spec_support", checked):
            _enforce_pool_spec_support(
                filtered, relevant_carriers, property_details, pool_specs, skip=pilot["carriers"]
            )
        if _on("check:_note_solar_roofing_does_not_apply", checked):
            # An unchecked roof type is not repeated back in the note.
            solar_pd = property_details if "roof_type" in checked else {
                k: v for k, v in property_details.items() if k != "roof_type"}
            _note_solar_roofing_does_not_apply(
                filtered, relevant_carriers, solar_pd, solar_classes
            )

        # Runs after every other check, the FPC upgrade included: these
        # holds exist because that upgrade turned INSUFFICIENT into ELIGIBLE
        # without asking whether any OTHER question was still open.
        # Before the holds, so a carrier freed here is still held on County /
        # Coverage A.
        _strip_inspection_requests(filtered)
        _strip_condition_requests(filtered)
        _strip_guide_text_requests(filtered)
        _strip_unchecked_topics(filtered, checked)
        if _on("check:_apply_location_holds", checked):
            _apply_location_holds(filtered, relevant_carriers, property_details)
        if _on("check:_apply_chubb_hold", checked):
            _apply_chubb_hold(filtered, relevant_carriers, property_details)
        if _on("check:_apply_twico_solar_decision", checked):
            _apply_twico_solar_decision(filtered, relevant_carriers, property_details)
        # Round 29 step 1 (Liam, 2026-10-08): a fact the form never asks is "confirm", never a hold.
        hold_guard.apply(filtered, _decide_by_code, _append_note, LAST_GUARD_STATS)
        # Last, after every rule that can set a status: a code-decided verdict
        # owns the card (round 26 step 2).
        _code_owns_cards(filtered)

        final = _add_fixed_rows(filtered, relevant_carriers, unavailable, defects, unrecognised)
        final += [_closed_program_row(c) for c in closed]
        if unrecognised or usable_answer_count(final) == 0:
            _print_raw_diagnostics(
                "UNUSABLE MODEL ANSWER: {} usable record(s), {} with an unrecognised status "
                "{}".format(usable_answer_count(final), len(unrecognised),
                            sorted({repr(r.get('_raw_status')) for r in unrecognised})),
                raw, usage)
        return final

    except json.JSONDecodeError as e:
        # CHANGED (round 12): print length + the tail, not just the first
        # 1000 chars -- a real failure was traced to output-token
        # truncation (see max_tokens comment above), and the head of the
        # response is USELESS for diagnosing that: it always looks the
        # same (ARI sorts first alphabetically) regardless of where the
        # cutoff actually happened, which is near the END of a long
        # response. stop_reason directly confirms truncation when present.
        print("JSON PARSE ERROR:", str(e))
        print("RAW RESPONSE LENGTH:", len(raw), "stop_reason:", usage.get("stop_reason", "n/a"))
        print("RAW RESPONSE HEAD:", raw[:500])
        print("RAW RESPONSE TAIL:", raw[-1000:])
        # CHANGED (round 13): also dump the WHOLE response next to the error,
        # and the neighbourhood of the reported offset. Round 12 spent a
        # round misattributing this failure to ARI's apostrophes because only
        # raw[:1000] was ever visible; round 12's own fix then widened that
        # to head+tail, which is right for truncation but still blind to a
        # malformed delimiter in the MIDDLE -- exactly what round 13 hit
        # (stop_reason "end_turn", 43859 chars, error at char 10650, i.e. a
        # complete response with bad syntax partway in, not a cut-off one).
        # Two rounds of guessing from partial output is enough.
        try:
            dump_dir = os.environ.get("ELIGIBILITY_PARSE_DUMP_DIR", ".")
            dump_path = os.path.join(dump_dir, "last_json_parse_failure.txt")
            with open(dump_path, "w", encoding="utf-8") as fh:
                fh.write(raw)
            print("RAW RESPONSE DUMPED TO:", dump_path)
        except Exception as dump_error:
            print("(could not dump raw response:", dump_error, ")")
        offset = getattr(e, "pos", None)
        if isinstance(offset, int):
            window = json_str[max(0, offset - 300): offset + 300]
            print("RAW RESPONSE AROUND OFFSET", offset, ":", repr(window))
        # The warning rows do not depend on the model, so they appear even
        # here; "not evaluated" rows do not -- the Parse Error record already
        # says every carrier needs the check re-run.
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
        }] + [_guide_unavailable_row(p, defects[p]) for p in unavailable] + [
            _closed_program_row(c) for c in closed]

_CHUBB = "CHUBB_HO_-_05.22.2026"

# CHUBB, read 2026-09-30 (sections I-III and VIII). Risks that qualify under
# I-III "become eligible for placement in our Standard Tier"; the tier table
# then decides, per REGION (the page-10 table is headed "Dallas/Fort Worth,
# Collin County & Rest of Northern counties"; Harris County has its own):
#   - Minimum coverages, Primary Houses: Preferred "Minimum: $1,000,000";
#     Standard "Subject to pre-approval*", footnoted "Coverage will not be
#     declined solely based on the minimum of value of the property."
#   - Wildfire classification 24-50 is "unacceptable in any Tier".
#   - Flood Zone A is "subject to pre-approval"; Flood Zone V is acceptable
#     only for tenants and condominiums on the 3rd floor or higher.
#   - "Risks or applicants with a loss history will require underwriter
#     approval."
# The form asks for none of those except, now, Coverage A.
_CHUBB_COVERAGE_A_ITEM = (
    "Dwelling amount (Coverage A) -- Chubb's discounted tiers start at $1,000,000 Coverage A; "
    "below that the Standard Tier is \"Subject to pre-approval\". The guide also needs the "
    "wildfire classification (24-50 is unacceptable in any tier), the Flood Zone, and 3-year "
    "loss history, which this form does not ask for.")


# The two phrases are copied from the guide's text (page-10 table and its
# footnote); a test checks they pass the chat tab's quote verifier.
_CHUBB_BELOW_MINIMUM_REFER_REASON = (
    "Below $1,000,000 Coverage A a primary house goes to Chubb's Standard Tier, which the guide "
    "marks \"Subject to pre-approval\": a referral to underwriting.")
_CHUBB_BELOW_MINIMUM_REFER_NOTE = (
    "Status set to REFER: below $1,000,000 Coverage A a primary house goes to Chubb's Standard "
    "Tier, which the guide marks \"Subject to pre-approval*\" -- \"Coverage will not be declined "
    "solely based on the minimum of value of the property.\" That is a referral to underwriting.")


def _chubb_amount_note(amount):
    if amount < 1_000_000:
        return ("Chubb guide, section VIII, for this amount (${:,}): below the $1,000,000 minimum "
                "of the discounted tiers, a primary house can only be placed in the Standard Tier, "
                "whose minimum-coverages row reads \"Subject to pre-approval\" -- \"Coverage will not "
                "be declined solely based on the minimum of value of the property.\"".format(amount))
    return ("Chubb guide, section VIII, for this amount (${:,}): at or above the $1,000,000 "
            "minimum for a primary house in the Preferred Tier (maximum up to $30,000,000 in the "
            "Dallas/Fort Worth and Northern counties table; other regions differ). Wildfire "
            "classification, Flood Zone and loss history still decide the tier.".format(amount))


def _apply_chubb_hold(results, relevant_carriers, property_details):
    """CHUBB Coverage A hold (Liam, 2026-09-30). Deterministic, keyed on
    carrier identity and the optional Dwelling amount:
      blank   ELIGIBLE / REFER -> INSUFFICIENT_INFORMATION, Coverage A named.
              Live 2026-09-30 CHUBB was Eligible from one sentence; recorded
              Sonnet runs said INSUFFICIENT_INFORMATION 3/3.
      filled  a note of what the guide says for that amount, and:
              below $1,000,000  ELIGIBLE -> REFER, flaw 0 (Liam, 2026-10-01:
                                "Subject to pre-approval" is a referral to
                                underwriting). INELIGIBLE and an
                                INSUFFICIENT_INFORMATION open for another fact
                                are left alone -- another rule may be why.
              $1,000,000 and up the model's verdict stands.
    """
    amount = _dwelling_amount(property_details)
    for r in results:
        if _resolve_structured_carrier(r.get("carrier", ""), relevant_carriers) != _CHUBB:
            continue
        if amount:
            _append_note(r, _chubb_amount_note(amount))
            if amount < 1_000_000 and r.get("status") == "ELIGIBLE":
                r["status"] = "REFER"
                r["flaw_count"] = 0
                _append_note(r, _CHUBB_BELOW_MINIMUM_REFER_NOTE)
                _decide_by_code(r, "REFER", _CHUBB_BELOW_MINIMUM_REFER_REASON,
                                f'{_CHUBB}: "Subject to pre-approval"')
            continue
        if r.get("status") in ("ELIGIBLE", "REFER"):
            r["status"] = "INSUFFICIENT_INFORMATION"
            r["flaw_count"] = 0
            _append_note(r, "Coverage A hold: Chubb's tier placement depends on the dwelling "
                            "amount, and none was given, so it cannot be Eligible yet.")
            _decide_by_code(r, "INSUFFICIENT_INFORMATION",
                            "No Coverage A given: Chubb's tier, and whether it is referred, "
                            "depends on the dwelling amount.")
        if r.get("status") == "INSUFFICIENT_INFORMATION":
            mi = r.setdefault("missing_info", [])
            if not any(m.startswith("Dwelling amount (Coverage A)") for m in mi):
                mi.insert(0, _CHUBB_COVERAGE_A_ITEM)


def _county_item_present(missing_info):
    return any(re.match(r"\s*county\b", m, re.I) for m in missing_info)


# Inspection requirements are not checked (Liam, 2026-10-01). An item is an
# inspection REQUEST when it asks for an inspection / photos / pictures /
# survey / 4-point / wind-mitigation report, and is NOT also about a fact of
# the property. Tested 2026-10-01 against the 96 inspection-flavoured items in
# the 3,895 recorded Sonnet records. KEEP wins: Centauri's "4-point inspection
# confirming all updates ... in past 20 years" is a rule about the updates,
# NatGen's "photos showing completely renovated kitchens" one about the
# renovation, Sage's furnace items and Markel's Coverage A items are facts.
# Round 24 (Liam, 2026-10-02): a roofer's letter, a plumber's / electrician's /
# HVAC signed statement, a roof certification or Roof Condition Form is an
# inspection too -- and so is a rule whose CURE is one of them. Those items are
# stripped even when they also name a property fact (_LETTER_RE wins over KEEP).
_INSPECTION_ASK_RE = re.compile(
    r"inspect|\bphotos?\b|photograph|\bpictures?\b|\bsurvey\b|\b4[- ]?point\b|four[- ]point|"
    r"wind[- ]?mitigation|\bwind[- ]mit\b", re.I)
_LETTER_RE = re.compile(
    r"roofer'?s?\b[^.;]{0,40}\b(?:letter|statement|certif\w*|documentation|questionnaire)|"
    r"(?:plumber|electrician|hvac(?: contractor)?|contractor)'?s?\s+(?:signed\s+)?"
    r"(?:statement|letter|attestation|certif\w*)|"
    r"(?:hvac|electrical|plumbing) contractor inspection|inspected by (?:a )?licensed|"
    r"signed statement|attestation|roof(?:ing)?\s+certif\w*|roof condition (?:form|questionnaire)|"
    r"(?:letter|statement) from (?:a |the )?(?:licensed|qualified|certified)|"
    # Round 24 live Luna wording: "Roof condition statement from a roofer ..."
    r"(?:letter|statement|attestation|certif\w*|form|documentation)\s+(?:from|by|signed by|completed by)\s+"
    r"(?:a |an |the )?(?:licensed |qualified |certified )?(?:roofer|plumber|electrician|hvac|contractor)",
    re.I)
_INSPECTION_KEEP_RE = re.compile(
    r"update|renovat|"
    r"\bcondition\b(?!\s+(?:questionnaire|form))|furnace|burner|hvac|plumb|wiring|electric|"
    r"galvaniz|polybut|overlay|replac|coverage a|threshold|timeframe|solar|photovolt|"
    r"useful life", re.I)
INSPECTION_NOT_CHECKED_NOTE = "(inspection requirements are not checked)"


def _is_inspection_request(item):
    if not isinstance(item, str):
        return False
    if _LETTER_RE.search(item):
        return True
    return bool(_INSPECTION_ASK_RE.search(item)) and not _INSPECTION_KEEP_RE.search(item)


def _strip_missing_info(results, is_match, removed_note, freed_note, log_label):
    """Remove missing_info items for which is_match(item) is true. An
    INSUFFICIENT_INFORMATION record left with nothing open BECAUSE of that
    becomes ELIGIBLE. INELIGIBLE and REFER keep their status; reasons and
    citations are never touched. Returns the number of items removed."""
    removed = 0
    for r in results:
        mi = r.get("missing_info") or []
        dropped = [m for m in mi if is_match(m)]
        if not dropped:
            continue
        removed += len(dropped)
        r["missing_info"] = [m for m in mi if m not in dropped]
        _append_note(r, removed_note.format(n=len(dropped), items="; ".join(d[:120] for d in dropped)))
        if r.get("status") == "INSUFFICIENT_INFORMATION" and not r["missing_info"]:
            r["status"] = "ELIGIBLE"
            r["flaw_count"] = 0
            _append_note(r, freed_note)
    if removed:
        print("%s: removed=%d item(s)" % (log_label, removed))
    return removed


def _strip_inspection_requests(results):
    """Layer 2: remove missing_info items that only ask for an inspection,
    photos or a report. Layer 3: an INSUFFICIENT_INFORMATION record left with
    nothing open BECAUSE of that becomes ELIGIBLE."""
    return _strip_missing_info(
        results, _is_inspection_request,
        "[Inspection check] Removed {n} inspection / photo request(s) "
        + INSPECTION_NOT_CHECKED_NOTE.replace("{", "{{").replace("}", "}}") + ": {items}",
        "Status set to ELIGIBLE: the only open items were inspection / photo "
        "requests " + INSPECTION_NOT_CHECKED_NOTE + ".",
        "INSPECTION STRIP")


# Round 26 step 5 (Liam, 2026-10-05): a missing_info item that asks the agent
# for the GUIDE's text -- the rest of a sentence, a table, criteria "not in
# the excerpts" -- is a retrieval failure, not missing information about the
# property. It must never hold a carrier. Same mechanism as the inspection
# strip; counted in the log.
_GUIDE_TEXT_REQUEST_RE = re.compile(
    r"complete sentence|rest of the (?:rule|sentence|text|table|list|section|clause)|"
    r"full (?:text|sentence|rule|table|list|section|clause)\b|"
    r"complete (?:applicable |base |owner-occupied |homeowners |ho3 )*(?:text|table|rule|list|section|guide|"
    r"eligibility (?:criteria|requirements|rules)|underwriting (?:criteria|guidelines|requirements)|"
    r"requirements|criteria)|"
    r"complete [\w-]+ (?:table|list)|"
    r"not (?:included|provided|shown|contained|present|stated|reproduced)?\s*in the "
    r"(?:retrieved |provided |supplied |given |available )?(?:excerpts?|text|pages?|guide text|document excerpts?)|"
    r"(?:excerpt|sentence|rule|table|clause)s?\s+(?:is |was |are )?(?:truncated|cut off|incomplete)|"
    r"(?:beginning|start|end) of the (?:sentence|rule|clause)|table (?:headers?|labels?|row labels?)|"
    r"missing (?:table|text|rows?|headers?)\b|referenced but not shown",
    re.I)
# An item that ALSO asks for a fact the agent can supply stays (replay of the
# round 25/26 runs: "For PPC 6, driving distance to the responding fire
# station and hydrant distance ... its table is incomplete").
_GUIDE_TEXT_KEEP_RE = re.compile(
    r"distance|hydrant|fire station|responding station|fence|\bgates?\b|\bcounty\b|coverage a\b|"
    r"dwelling amount|\bacre", re.I)
GUIDE_TEXT_NOT_ASKED_NOTE = "(a request for guide text is not missing information)"


def _is_guide_text_request(item):
    return bool(_GUIDE_TEXT_REQUEST_RE.search(item or "")) and not _GUIDE_TEXT_KEEP_RE.search(item or "")


def _strip_guide_text_requests(results):
    """Remove missing_info items that ask for guide text; an
    INSUFFICIENT_INFORMATION record left with nothing open because of that
    becomes ELIGIBLE (the inspection layer's rule)."""
    return _strip_missing_info(
        results, _is_guide_text_request,
        "[Excerpt check] Removed {n} request(s) for guide text "
        + GUIDE_TEXT_NOT_ASKED_NOTE + ": {items}",
        "Status set to ELIGIBLE: the only open items asked for guide text "
        + GUIDE_TEXT_NOT_ASKED_NOTE + ".",
        "GUIDE-TEXT STRIP")


# Round 26 step 6 (Liam, 2026-10-05, decision D): condition standards are
# notes, never a hold, in the whole tool -- like inspections. An item is a
# CONDITION ask when it only asks whether something is in good / proper
# working condition, maintained, properly installed or built to / meeting
# building codes. KEEP wins: an item that also names a material or a fact
# (overlay / layers, age or years, galvanized, knob-and-tube, type,
# "details", central heat, damage, replacement, fence, distance ...) stays.
# "Conditions" in the sense of a rule's branches ("which PPC 3 conditions
# apply") is not this, and does not match.
_CONDITION_ASK_RE = re.compile(
    r"good (?:condition|repair|working order)|"
    r"(?:proper|good|safe|sound|satisfactory|acceptable) (?:working )?(?:condition|order)\b|"
    r"working condition|very[- ]good[- ]condition|"
    r"\bcondition of (?:the )?(?:home|dwelling|house|roof|property|plumbing|electrical|heating|systems?)\b|"
    r"\b(?:roof|home|dwelling|property|plumbing|electrical|heating|hvac)(?: system)? condition\b(?! (?:form|questionnaire))|"
    r"well[- ]maintained|\bmaintained\b|\bmaintenance\b|"
    r"built to code|code[- ]complian|"
    r"(?:meets?|meeting|comply with|complies with|compliant with|up to) (?:all |current |state |local |applicable )*"
    r"(?:building )?codes?\b|building codes?\b|properly installed|\bdebris\b|unduly exposed|disrepair",
    re.I)
_CONDITION_KEEP_RE = re.compile(
    r"overlay|\blayers?\b|\bage\b|\byears?\b|galvaniz|polybut|knob|\bfuses?\b|material|\btype\b|details|"
    r"central heat|heat source|\bcentral\b|thermostat|damage|unrepaired|replac|renovat|update|"
    r"life expectancy|useful life|remaining life|fence|\bgates?\b|distance|hydrant|"
    r"square f|\bacre|coverage a", re.I)
CONDITION_NOT_CHECKED_NOTE = "(condition of the home is not checked)"


def _is_condition_request(item):
    if not isinstance(item, str):
        return False
    return bool(_CONDITION_ASK_RE.search(item)) and not _CONDITION_KEEP_RE.search(item)


def _strip_condition_requests(results):
    """Layer 2: remove missing_info items that only ask about the condition
    of the home. Layer 3: an INSUFFICIENT_INFORMATION record left with
    nothing open because of that becomes ELIGIBLE."""
    return _strip_missing_info(
        results, _is_condition_request,
        "[Condition check] Removed {n} condition-standard question(s) "
        + CONDITION_NOT_CHECKED_NOTE + ": {items}",
        "Status set to ELIGIBLE: the only open items were about the condition of the home "
        + CONDITION_NOT_CHECKED_NOTE + ".",
        "CONDITION STRIP")


UNCHECKED_NOT_CONSIDERED_NOTE = "(unchecked topics were not considered)"


def _is_about_unchecked_only(item, checked):
    """The item matches some UNCHECKED topic's keywords and no checked one's.
    An item that also matches a checked topic stays: it may be about that."""
    hit = topics.item_topics(item)
    return bool(hit) and not (hit & set(checked))


def _strip_unchecked_topics(results, checked):
    """Partial selection only (decision 1, Step 2e): remove missing_info items
    about unchecked topics, with the same mechanism as the inspection strip."""
    if not topics.is_partial(checked):
        return 0
    return _strip_missing_info(
        results, lambda m: _is_about_unchecked_only(m, checked),
        "[Partial check] Removed {n} item(s) about unchecked topics "
        + UNCHECKED_NOT_CONSIDERED_NOTE + ": {items}",
        "Status set to ELIGIBLE: the only open items were about unchecked topics "
        + UNCHECKED_NOT_CONSIDERED_NOTE + ".",
        "UNCHECKED-TOPIC STRIP")


# Round 22 (Liam, 2026-10-02). A reason or citation that rests on the Sage
# location rule. Tested on the real Luna outputs (round 21 step 8: the five
# wrong Harris declines; round 22: the correct Nueces declines) and on the 83
# reasons of the 43 recorded Sonnet Sage INELIGIBLE records (all occupancy
# declines -- no false hit).
_LOCATION_FLAW_RE = re.compile(r"south texas|\b31\b|territory|\bcounty\b|\bcounties\b|\blocation\b", re.I)
LOCATION_DECLINE_NOTE = ("The county is inside this guide's territory. The model declined on "
                         "location only; re-run to confirm.")


def _undo_location_decline(r, canon, county):
    """County INSIDE the territory (computed from the county table, never the
    model's wording) and the model said INELIGIBLE: remove the reasons and
    citations that rest on location. The location rule is one flaw. Other
    flaws left -> INELIGIBLE with the rest; none left -> REFER, never
    ELIGIBLE (the model did not evaluate the other items properly in that
    run). Returns True when it changed the record."""
    reasons = r.get("reasons") or []
    loc = [x for x in reasons if _LOCATION_FLAW_RE.search(x)]
    if not loc:
        return False
    r["reasons"] = [x for x in reasons if x not in loc]
    r["citations"] = [c for c in (r.get("citations") or []) if not _LOCATION_FLAW_RE.search(c)]
    remaining = max(0, int(r.get("flaw_count") or 0) - 1)
    print("LOCATION DECLINE CORRECTED: carrier=%r county=%r removed=%d remaining_flaws=%d"
          % (canon, county, len(loc), remaining))
    if remaining:
        r["flaw_count"] = remaining
        _append_note(r, f"{county} County is inside this guide's territory; the location "
                        f"reason was removed and the other flaw(s) stand.")
    else:
        r["status"] = "REFER"
        r["flaw_count"] = 0
        _append_note(r, LOCATION_DECLINE_NOTE)
        _decide_by_code(r, "REFER", f"{county} County is inside this guide's territory; the "
                                    f"model declined on location only, so this is referred, "
                                    f"not declined. Re-run to confirm.")
    return True


def _apply_location_holds(results, relevant_carriers, property_details):
    """Sage ADDRESS rule (Liam, 2026-09-30), decided from carrier identity and
    the optional County field alone:

      County blank   ELIGIBLE / REFER -> INSUFFICIENT_INFORMATION, with County
                     named in missing_info. Live 2026-09-30 and in recorded
                     Sonnet runs (131 of 140 ELIGIBLE records for these five
                     carriers across 48 runs), the Sage FPC upgrade had turned
                     the model's own INSUFFICIENT into ELIGIBLE while the card
                     still said the location could not be resolved.
      In territory   the model's verdict stands -- except an INELIGIBLE resting
                     on location (round 22, _undo_location_decline).
      Outside        INELIGIBLE (one more flaw), citing the guide's own
                     sentence.
    """
    county = _county(property_details)
    for r in results:
        canon = _resolve_structured_carrier(r.get("carrier", ""), relevant_carriers)
        rule = _SAGE_LOCATION_RULE.get(canon)
        if rule is None:
            continue
        nueces_excluded, sentence = rule
        territory = sage_county_in_territory(county, intake_fields.COUNTY_MAX_LATITUDE,
                                             nueces_excluded)
        # Round 27 step 6 (Sage batch), round 28 step 1 (Sage Auros, 2026-10-07):
        # on a rules-table carrier the rules table owns the territory. Its rows
        # test the same county table, so the hold and the rows agree; when both
        # would act, the evaluator's row decides and the card shows it once.
        owned = r.get("rules_table") and rules_evaluator.territory_rows(canon)
        if owned and territory != "UNKNOWN":
            continue
        if territory == "UNKNOWN":
            if r.get("status") in ("ELIGIBLE", "REFER"):
                r["status"] = "INSUFFICIENT_INFORMATION"
                r["flaw_count"] = 0
                _append_note(r, "County hold: this carrier only writes in specific counties, "
                                "and no County was given, so it cannot be Eligible yet.")
                _decide_by_code(r, "INSUFFICIENT_INFORMATION",
                                "No County given, and this carrier only writes in specific "
                                "counties. The guide says: \"{}\"".format(sentence),
                                f"{canon}: '{sentence}'")
            if r.get("status") == "INSUFFICIENT_INFORMATION":
                mi = r.setdefault("missing_info", [])
                if not _county_item_present(mi):
                    mi.insert(0, "County -- this guide only writes in specific counties: " + sentence)
            if owned:
                # the County item above says it; the rows' "blank County" notes would repeat it
                rows = rules_evaluator.territory_rows(canon)
                r["also_confirm"] = [n for n in r.get("also_confirm") or []
                                     if not any(n.startswith(f"[{rid}]") for rid in rows)]
        elif territory == "IN" and r.get("status") == "INELIGIBLE":
            _undo_location_decline(r, canon, county)
        elif territory == "OUT":
            reason = ("{} County is outside this carrier's territory. The guide says: \"{}\""
                      .format(county, sentence))
            if r.get("status") == "INELIGIBLE":
                r["flaw_count"] = int(r.get("flaw_count") or 0) + 1
            else:
                r["status"] = "INELIGIBLE"
                r["flaw_count"] = 1
            r.setdefault("reasons", []).append(reason)
            r.setdefault("citations", []).append(f"{canon}: '{sentence}'")
            _decide_by_code(r, "INELIGIBLE", reason, f"{canon}: '{sentence}'")


# Two statuses the PIPELINE writes -- never the model -- for carriers it could
# not check. Liam's decisions, 2026-09-28/29. Each has its own UI bucket.
GUIDE_UNAVAILABLE = "GUIDE_UNAVAILABLE"
NOT_EVALUATED = "NOT_EVALUATED"
UNRECOGNISED_VERDICT = "UNRECOGNISED_VERDICT"

# The four statuses SYSTEM_INSTRUCTIONS lets the model write.
MODEL_STATUSES = ("ELIGIBLE", "INELIGIBLE", "REFER", "INSUFFICIENT_INFORMATION")


def _normalize_status(value):
    """Trim, uppercase, spaces and hyphens to underscores -- and nothing
    else. No synonyms: "NOT_ELIGIBLE" is NOT mapped to "INELIGIBLE"; a word
    the model was never asked for is unrecognised, not guessed at."""
    if not isinstance(value, str):
        return None
    return re.sub(r"[\s\-]+", "_", value.strip()).upper() or None


def _coerce_flaw_count(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _normalize_record(r):
    """Normalise one parsed model record in place; the raw status is kept
    as _raw_status so an unrecognised one can be shown as written."""
    r["_raw_status"] = r.get("status")
    r["status"] = _normalize_status(r.get("status"))
    r["flaw_count"] = _coerce_flaw_count(r.get("flaw_count", 0))
    return r


def _unrecognised_row(record, carrier):
    raw = record.get("_raw_status")
    shown = "no status given" if raw is None or raw == "" else str(raw)
    return {
        "carrier": carrier,
        "status": UNRECOGNISED_VERDICT,
        "flaw_count": 0,
        "reasons": ["The model gave a verdict this tool doesn't recognise ('{}') -- run the "
                    "check again.".format(shown)],
        "citations": [],
        "missing_info": [],
        "notes": "Raw status value from the model: {!r}. Its reasoning, not acted on: {}".format(
            raw, " ".join(record.get("reasons") or [])[:1500]),
    }


def usable_answer_count(results):
    """Records the model actually decided -- one of the four statuses, and
    not the pipeline's own Parse Error stand-in. Zero means the check did not
    return usable answers, whatever else is on screen."""
    return sum(1 for r in results
               if r.get("status") in MODEL_STATUSES and r.get("carrier") != "Parse Error"
               and not r.get("fixed_row"))   # round 26: a closed program's row is code's, not an answer


def _print_raw_diagnostics(headline, raw, usage):
    """Railway captures stdout. Same shape as the JSON PARSE ERROR path."""
    print(headline)
    print("RAW RESPONSE LENGTH:", len(raw), "stop_reason:", (usage or {}).get("stop_reason", "n/a"))
    print("RAW RESPONSE HEAD:", raw[:500])
    print("RAW RESPONSE TAIL:", raw[-500:])

_GUIDE_UNAVAILABLE_TEXT = {
    data_defects.NO_TEXT: "The guide on file has no readable text -- check with the carrier directly.",
}
_GUIDE_WRONG_DOCUMENT_TEXT = "The guide on file is the wrong document -- check with the carrier directly."
_NOT_EVALUATED_TEXT = "No answer came back for this carrier in this check -- run the check again."


# Round 26 step 9 (Liam, 2026-10-05). A program its own guide closes to new
# business is a fixed row like the wrong-guide rows: INELIGIBLE, quoted, and
# no model tokens -- the model re-decided it on every check. The quote is
# re-checked against the stored guide each time, so a re-uploaded guide
# without it clears the row with no code change. Only programs Liam has
# decided are listed; handoff.md lists the other closure-like statements.
CLOSED_PROGRAMS = {
    "NatGen_Premier_OneChoice_HO3_-_02.26.2025": (
        3, "Homeowners policies are not eligible for new business effective 11/30/2023."),
    # Round 29 step 8 (2026-10-08): the dwelling fire program is closed too (remaining batch row NPD-001).
    "NatGen_Premier_OneChoice_DP3_-_02.26.2025": (
        3, "Dwelling fire policies are not eligible for new business effective 11/30/2023."),
}


def closed_programs(carriers):
    """The carriers in `carriers` whose guide still says they are closed."""
    keys = _guide_keys()
    return [c for c in carriers if c in CLOSED_PROGRAMS and c in keys
            and quotes.appears_in(quotes.compare_key(CLOSED_PROGRAMS[c][1]), keys[c])]


def _closed_program_row(program):
    page, quote = CLOSED_PROGRAMS[program]
    return {
        "carrier": program,
        "status": "INELIGIBLE",
        "flaw_count": 1,
        "reasons": [f'Closed to new business (guide, p.{page}): "{quote}"'],
        "citations": [f'{program}: "{quote}"'],
        "missing_info": [],
        "notes": "",
        "decided_by_code": True,
        "fixed_row": True,
    }


def _guide_unavailable_row(program, defect):
    """A fixed row for a carrier whose guide on file cannot be used. It is
    never sent to the model: a mis-filed PDF produces confident, well-cited
    answers about the WRONG program (DATA_DEFECTS.md), and a program with no
    text has nothing to answer from. The row clears by itself once the
    store holds a usable guide."""
    return {
        "carrier": program,
        "status": GUIDE_UNAVAILABLE,
        "flaw_count": 0,
        "reasons": [_GUIDE_UNAVAILABLE_TEXT.get(defect["kind"], _GUIDE_WRONG_DOCUMENT_TEXT)],
        "citations": [],
        "missing_info": [],
        "notes": defect["detail"],
    }


def _not_evaluated_row(program):
    return {
        "carrier": program,
        "status": NOT_EVALUATED,
        "flaw_count": 0,
        "reasons": [_NOT_EVALUATED_TEXT],
        "citations": [],
        "missing_info": [],
        "notes": ("This carrier was in the check, but the model's answer left it out "
                  "entirely, so nothing was decided for it."),
    }


def _add_fixed_rows(results, relevant_carriers, unavailable, defects, unrecognised=()):
    """Append the rows the pipeline owns, so no carrier ever silently
    disappears from the results:

      GUIDE_UNAVAILABLE -- every carrier in `unavailable`. A model record for
        one is dropped first; it cannot come from this prompt, which omits
        those carriers, but a replayed or invented one must not sit beside
        the warning.
      NOT_EVALUATED -- every carrier that WAS in the prompt and got no record.
        Round 17: 1 of 48 recorded calls returned 26 of 28 carriers
        (stop_reason end_turn, not a truncation), and nothing said so.

    Deliberately conservative: a record whose name matches no carrier at all
    does not cover one, so a badly misnamed record yields a row alongside it
    rather than risk hiding a real omission."""
    def is_unavailable(r):
        name = r.get("carrier", "")
        # A name that fits a USABLE carrier is kept, even if it also fits a
        # defective one: "Liberty Mutual" is as likely LM HO3 as LM HO6.
        if _resolve_structured_carrier(name, relevant_carriers) is not None:
            return False
        if _resolve_structured_carrier(name, unavailable) is not None:
            return True
        # A name that fits no usable carrier, but fits a defective one once a
        # model-added parenthetical is dropped: "NatGen Custom360 (Landlord)".
        # Safe only here, where no usable carrier competes for the name.
        words = _carrier_words(name, drop_parenthetical=True)
        return bool(words) and sum(words <= _carrier_words(p) for p in unavailable) == 1

    kept = [r for r in results if not (unavailable and is_unavailable(r))]
    covered = {_resolve_structured_carrier(r.get("carrier", ""), relevant_carriers) for r in kept}
    missing = [c for c in relevant_carriers if c not in covered]

    # UNRECOGNISED_VERDICT: a record whose status is not one the model may
    # write never counts as covering its carrier (2026-09-30: coverage by
    # NAME alone let 23 status-less Luna records vanish with no row). The
    # carrier gets exactly one row -- the unrecognised-verdict one, which says
    # more than "no answer" -- instead of a NOT_EVALUATED beside it. A record
    # that fits no usable carrier, or duplicates one that has a real answer,
    # still gets its own row: nothing the model wrote disappears.
    unrec_rows, explained = [], set()
    for r in unrecognised:
        if unavailable and is_unavailable(r):
            continue
        canon = _resolve_structured_carrier(r.get("carrier", ""), relevant_carriers)
        if canon in missing and canon not in explained:
            explained.add(canon)
        unrec_rows.append(_unrecognised_row(r, canon or r.get("carrier", "(unnamed)")))
    return (kept
            + unrec_rows
            + [_not_evaluated_row(c) for c in missing if c not in explained]
            + [_guide_unavailable_row(p, defects[p]) for p in unavailable])


def assign_buckets(results):
    """Split check_eligibility() results into the UI buckets, one per actual
    status, plus one bucket each for the two pipeline-written statuses
    (GUIDE_UNAVAILABLE, NOT_EVALUATED) and a catch-all. Extracted out of
    app.py so it's testable without a Streamlit session.

    CHANGED (Liam, 2026-10-05, decision A): the middle column holds REFERRALS
    ONLY and is labelled "Refer to Underwriting"; every INELIGIBLE goes to
    "Not Eligible", whatever its flaw_count. Before this, a single-flaw
    INELIGIBLE sat under "One Issue" -- so on Liam's live check four Sage
    carriers declined for the same territory reason as Sage Trium appeared
    under "One Issue" while Trium (flaw_count 2) appeared under "Not
    Eligible". flaw_count no longer decides a bucket.

    History: rounds 9-11 found the old 3-bucket version mislabeling
    INSUFFICIENT_INFORMATION as "Not Eligible"; that is why each bucket maps
    to exactly one status, so a relabeling of ANY status can never produce a
    mixed, mislabeled bucket again."""
    eligible = [r for r in results if r.get("status") == "ELIGIBLE"]
    refer = [r for r in results if r.get("status") == "REFER"]
    insufficient_info = [r for r in results if r.get("status") == "INSUFFICIENT_INFORMATION"]
    not_eligible = [r for r in results if r.get("status") == "INELIGIBLE"]
    return {
        "eligible": eligible,
        "refer": refer,
        "insufficient_info": insufficient_info,
        "not_eligible": not_eligible,
        "guide_unavailable": [r for r in results if r.get("status") == GUIDE_UNAVAILABLE],
        "not_evaluated": [r for r in results if r.get("status") == NOT_EVALUATED],
        # Catch-all, so every record lands in exactly one bucket whatever its
        # status (2026-09-30: an unplaceable status used to fall out of every
        # bucket, and four empty columns were all that showed). The pipeline
        # writes UNRECOGNISED_VERDICT; anything else here arrived raw.
        "unrecognised": [r for r in results if r.get("status") not in _PLACED_STATUSES],
    }


_PLACED_STATUSES = MODEL_STATUSES + (GUIDE_UNAVAILABLE, NOT_EVALUATED)
