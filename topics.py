"""The checkable inputs ("topics") of the eligibility form -- the single
source of truth for what a "Check this" box governs (Liam, 2026-10-01/02).

UNCHECKED means "don't consider this at all": the guides are not searched
for rules about it, the model is not asked about it, and no automatic rule
fires for it. ELIGIBLE then means only "no problem found on what was
checked". Occupancy, Ownership and Dwelling type are always on.

Each topic lists:
  owns        the property_details keys it governs (each key is owned by
              exactly one topic, or is always-on -- a test enforces it)
  steps       the retrieval guarantees, query terms, post-parse checks and
              deterministic overrides it switches. A step needing SEVERAL
              topics is listed in STEPS with all of them (see below).
  strip       a regex for missing_info items ABOUT this topic, removed when
              the topic is unchecked (eligibility_check._strip_unchecked_topics)

STEPS maps every gated step in eligibility_check to the topics it needs and
how they combine:
  "all"  a RULE (override, hold, guard, fact line): runs only when every
         listed topic is checked. Liam: a rule needing an unchecked topic is
         skipped.
  "any"  RETRIEVAL (a guaranteed lookup, a query term): runs when any listed
         topic is checked -- it only puts text in front of the model.
CORE_STEPS are the post-parse functions that run whatever is checked, each
with the reason. A function called from check_eligibility that is in
neither table fails the build (verification/test_eligibility_matrix.py,
TestTopicRegistry).
"""
import re
from collections import namedtuple

Topic = namedtuple("Topic", "key label short owns strip")

TOPICS = (
    Topic("ppc", "PPC", "PPC", ("ppc",),
          r"\bppc\b|protection class|\bfpc\b|fire protection|fire station|fire department|"
          r"hydrant|fire district|responding station"),
    Topic("coastal", "Coastal tier", "Coastal", ("coastal_tier",),
          r"coastal|wind ?pool|\btwia\b|first tier|tier [123]\b|windstorm|named storm|seaward|"
          r"distance to (?:the )?(?:coast|gulf|water)"),
    Topic("home_age", "Year built (home age)", "Home age", ("year_built",),
          r"year built|home age|\bage of (?:the )?(?:home|dwelling|house|property)|"
          r"(?:home|dwelling|house)s? (?:built|older)|built (?:before|after|prior|in \d{4})|"
          r"(?:home|dwelling|house)s? (?:over|more than) \d+ years|(?:home|dwelling|house) is \d+ years|"
          r"pre-19\d\d"),
    Topic("roof_age", "Roof age", "Roof age", ("roof_age",),
          r"\broof age|age of (?:the )?roof|\broof (?:is|was) \d+|\broof\b[^.;]{0,30}\b\d+[- ]years?|"
          r"\bre-?roof|\broof (?:was )?replace"),
    Topic("roof_type", "Roof type", "Roof type", ("roof_type",),
          r"\broof (?:type|covering|material|surfac)|shingle|3-tab|three-tab|architectural|"
          r"metal roof|\btile\b|\bslate\b|wood shake|composition|built-up"),
    Topic("roof_shape", "Roof shape", "Roof shape", ("roof_shape",),
          r"roof shape|flat roof|\bgable\b|hip roof|mansard|gambrel|poured concrete"),
    Topic("construction", "Construction type", "Construction", ("construction_type",),
          r"construction type|type of construction|\bframe\b|masonry|brick|veneer|manufactured|"
          r"mobile home|log home|\beifs\b|stucco"),
    Topic("plumbing", "Plumbing", "Plumbing", ("plumbing_type",),
          # The plumbing MATERIAL. "Renovated ... including plumbing" and
          # "plumbing updated within 30 years" are home-age rules, not this.
          r"plumbing type|type of plumbing|galvaniz|polybutylene|\bpex\b|cast iron|\bpipes?\b|piping|"
          r"(?:steel|iron|copper|pvc|cpvc) plumbing|plumbing (?:material|system)s?\b"),
    Topic("pool", "Swimming pool", "Pool",
          ("swimming_pool", "pool_accessories", "pool_fence_4ft", "pool_gate_locking"),
          r"(?<!wind )\bpools?\b|swimming|\bfenc|\bgates?\b|diving|\bslides?\b|hot tub|\bspa\b"),
    Topic("dogs", "Dogs", "Dogs", ("has_dogs", "aggressive_breed"),
          r"\bdogs?\b|canine|breed|pit ?bull|rottweiler|\banimals?\b"),
    Topic("solar", "Solar panels", "Solar", ("solar_panels",),
          r"solar|photovoltaic|\bpv\b"),
    Topic("county", "County", "County", ("county", "zip"),
          r"\bcounty\b|\bcounties\b|\bzip\b|territory|latitude|31 degrees|"
          r"property location|location of the property"),
    Topic("dwelling_amount", "Dwelling amount", "Coverage A", ("dwelling_amount",),
          r"coverage a\b|dwelling (?:amount|limit|coverage|value)|insured value|"
          r"replacement cost value of the (?:home|dwelling)"),
)

# Always on (decision 2): never unchecked, never stripped.
ALWAYS_ON = (
    Topic("occupancy", "Occupancy", "Occupancy", ("occupancy_type",), None),
    Topic("ownership", "Ownership", "Ownership", ("ownership_type",), None),
    Topic("dwelling_type", "Dwelling type", "Dwelling type", ("dwelling_type",), None),
)

TOPIC_KEYS = tuple(t.key for t in TOPICS)
BY_KEY = {t.key: t for t in TOPICS + ALWAYS_ON}

STEPS = {
    # -- PROPERTY DETAILS lines -------------------------------------------
    "fact:year_built": (("home_age",), "all"),
    "fact:home_age": (("home_age",), "all"),
    "fact:roof_age": (("roof_age",), "all"),
    "fact:roof_type": (("roof_type",), "all"),
    "fact:roof_shape": (("roof_shape",), "all"),
    "fact:construction_type": (("construction",), "all"),
    "fact:plumbing_type": (("plumbing",), "all"),
    "fact:coastal_tier": (("coastal",), "all"),
    "fact:swimming_pool": (("pool",), "all"),
    "fact:pool_accessories": (("pool",), "all"),
    "fact:pool_boxes": (("pool",), "all"),
    "fact:has_dogs": (("dogs",), "all"),
    "fact:aggressive_breed": (("dogs",), "all"),
    "fact:solar_panels": (("solar",), "all"),
    "fact:ppc": (("ppc",), "all"),
    "fact:county": (("county",), "all"),
    "fact:county_territory": (("county",), "all"),
    "fact:dwelling_amount": (("dwelling_amount",), "all"),
    # -- build_retrieval_query lines (retrieval) --------------------------
    "query:year_built": (("home_age",), "any"),
    "query:roof_age": (("roof_age",), "any"),
    "query:roof_type": (("roof_type",), "any"),
    "query:roof_shape": (("roof_shape",), "any"),
    "query:construction_type": (("construction",), "any"),
    "query:plumbing_type": (("plumbing",), "any"),
    "query:coastal_tier": (("coastal",), "any"),
    "query:swimming_pool": (("pool",), "any"),
    "query:dogs": (("dogs",), "any"),
    "query:solar_panels": (("solar",), "any"),
    "query:ppc": (("ppc",), "any"),
    # -- build_risk_factors terms (retrieval) -----------------------------
    "risk:plumbing": (("plumbing",), "any"),
    "risk:pool": (("pool",), "any"),
    "risk:coastal": (("coastal",), "any"),
    "risk:dogs": (("dogs",), "any"),
    "risk:ppc": (("ppc",), "any"),
    "risk:roof": (("roof_age", "roof_type"), "any"),
    "risk:solar": (("solar",), "any"),
    # -- guaranteed lookups (retrieval) -----------------------------------
    "guarantee:ppc": (("ppc",), "any"),
    "guarantee:pool": (("pool",), "any"),
    "guarantee:solar": (("solar",), "any"),
    "guarantee:roof_shape": (("roof_shape",), "any"),
    "guarantee:roof_life": (("roof_age", "roof_type"), "any"),
    "guarantee:coverage_a": (("dwelling_amount",), "any"),
    # -- post-parse checks and overrides (rules) --------------------------
    "guard:solar_panels": (("solar",), "all"),
    "guard:swimming_pool": (("pool",), "all"),
    "guard:aggressive_breed": (("dogs",), "all"),
    "override:_SAGE_FPC_CARRIERS": (("ppc",), "all"),
    "override:_MERCURY_CARRIERS": (("roof_age", "roof_type"), "all"),
    "override:_SAGE_MARKEL_CARRIERS": (("roof_age", "roof_type"), "all"),
    "override:_SWYFFT_MAX30_CARRIERS": (("roof_age",), "all"),
    "override:_TWICO_CARRIERS": (("roof_age", "roof_type"), "all"),
    "override:_SAGE_ROOFER_STATEMENT_CARRIERS": (("roof_age", "roof_type"), "all"),
    "override:_CENTAURI_DP3_CARRIERS": (("roof_shape", "roof_type"), "all"),
    "check:_enforce_pool_spec_support": (("pool",), "all"),
    "check:_note_solar_roofing_does_not_apply": (("solar",), "all"),
    "check:_apply_location_holds": (("county",), "all"),
    "check:_apply_chubb_hold": (("dwelling_amount",), "all"),
}

# Post-parse functions that run whatever is checked.
CORE_STEPS = {
    "_strip_misattributed_citations": "attribution: a rule must come from the carrier's own guide",
    "_strip_inspection_requests": "Liam 2026-10-01: inspection requirements are never checked",
    "_strip_unchecked_topics": "the selection itself: removes items about unchecked topics",
    "_add_fixed_rows": "GUIDE_UNAVAILABLE / NOT_EVALUATED / UNRECOGNISED rows",
    "_apply_structured_overrides": "a dispatcher; each branch is tagged override:<carrier set>",
    "_strip_contradicted_property_claims": "a dispatcher; each field is tagged guard:<field>",
    "_code_owns_cards": "round 26: a status a rule set shows that rule's reason, whatever is checked",
    "_strip_guide_text_requests": "round 26: a request for guide text is never missing information",
}

# Always-on routing and lookups (not gated; listed so the inventory is whole).
ALWAYS_ON_STEPS = {
    "route:occupancy": "get_carriers_for_occupancy + the HO/DP filter after parsing",
    "route:dwelling_type_house": "House drops the condo (HO6) programs",
    "guarantee:occupancy": "occupancy / trust / LLC lookup (Trust and LLC only)",
    "fact:occupancy_type": "Occupancy Type line",
    "fact:ownership_type": "Ownership Structure line",
    "fact:dwelling_type": "Dwelling Type line (when given)",
    "query:occupancy": "occupancy / ownership query lines",
    "risk:occupancy": "LLC / Trust / tenant risk terms",
}


def normalize(checked_topics):
    """None -> every topic (today's behaviour). Otherwise the frozenset of
    known topic keys given; always-on topics need not be listed."""
    if checked_topics is None:
        return frozenset(TOPIC_KEYS)
    unknown = set(checked_topics) - set(TOPIC_KEYS) - {t.key for t in ALWAYS_ON}
    if unknown:
        raise ValueError(f"unknown topic(s): {sorted(unknown)}")
    return frozenset(k for k in checked_topics if k in TOPIC_KEYS)


def is_partial(checked):
    return set(checked) != set(TOPIC_KEYS)


def step_on(step, checked):
    """Is a gated step switched on for this selection? An untagged step is a
    KeyError -- adding a step without a tag fails loudly, not silently."""
    if step in ALWAYS_ON_STEPS:
        return True
    needed, mode = STEPS[step]
    have = [k in checked for k in needed]
    return all(have) if mode == "all" else any(have)


def unchecked(checked):
    return [t for t in TOPICS if t.key not in checked]


STRIP_RES = {t.key: re.compile(t.strip, re.I) for t in TOPICS}


def item_topics(item):
    """The topic keys whose strip regex matches a missing_info item."""
    return {k for k, rx in STRIP_RES.items() if isinstance(item, str) and rx.search(item)}


def partial_check_line(checked):
    """'Partial check: ...' with the checked topics and the always-on ones."""
    names = [t.label for t in TOPICS if t.key in checked] + [t.short for t in ALWAYS_ON]
    return "Partial check: " + ", ".join(names)
