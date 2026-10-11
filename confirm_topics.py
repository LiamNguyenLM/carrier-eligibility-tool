"""Round 37 step 1 (Liam, 2026-10-10): what an agent should confirm, in plain words.

Each card used to end with "Also confirm" and a dump of row IDs by workbook topic ("ACREAGE: ALL-157, ...").
Now every confirm row -- a rule the form does not ask (NONE), a standard condition (CONDITION_STANDARD), a row
left open only by a blank field (NOTE), and the model path's "Confirm (...)" items -- is put under a topic from
TOPICS below (topic key -> a plain question), one item per topic per card:

  - at most CARD_MAX items show; the rest sit under "+N more";
  - order: the strongest consequence among the topic's rows first (declines, then refers, then conditions, then
    the rest), upkeep-only topics last, then the topics with more rows;
  - the wording is the topic's question; where a number (or, for a blank field, a named place) decides it, the
    item adds the guide's own rule for its strongest such row, so no limit is invented;
  - the row IDs go on a collapsed "Rule IDs" line.

top_box() counts the topics across the Eligible and Refer cards: the questions to ask the client once.
"""
import functools
import re

CARD_MAX = 6
TOP_MAX = 8
EFFECT_RANK = {"DECLINES": 0, "REFERS_TO_UW": 1, "CONDITION": 2}

# key: (plain question, text patterns (any matches), upkeep only). The first key whose patterns match wins, so
# the narrower topics come first. A row no pattern matches takes its workbook topic (CATEGORY_TOPIC), else
# "other".
TOPICS = {
    "binding": ("Any storm, evacuation or other binding restriction in effect for the area right now?",
                (r"\bbinding (is |may be )?suspended", r"\bbinding restriction", r"\bevacuation",
                 r"\bweather (watch|warning)", r"\bearthquake", r"\bmay not be bound while",
                 r"\bbinding authority"), False),
    "county": ("Which county, and where in it? (some guides exclude named counties or areas)",
               (r"\bcount(y|ies)\b", r"\bterritor", r"\bhwy 146\b"), False),
    "coverage_a": ("Coverage A (dwelling) amount within this guide's range?",
                   (r"\bcoverage a\b", r"\bdwelling (limit|amount|coverage)", r"\breplacement cost\b",
                    r"\binsur\w* to value\b", r"\bitv\b", r"\binsured value"), False),
    "other_coverages": ("Other coverage amounts (Coverage B-F, contents) as the guide requires?",
                        (r"\bcoverage [b-f]\b", r"\bpersonal property\b", r"\bcontents\b", r"\bdeductible",
                         r"\bactual cash value"), False),
    "insurance_score": ("Insurance score / credit acceptable?", (r"\binsurance[- ]score", r"\bcredit\b"), False),
    "prior_insurance": ("Prior insurance: any lapse, cancellation or non-renewal?",
                        (r"\bcancel", r"\bnon-?renew", r"\blapse", r"\bprior (insurance|coverage|carrier|policy)",
                         r"\bcontinuous (prior )?(insurance|coverage)", r"\bno prior coverage", r"\bdeclined\b",
                         r"\brescind", r"\bvoided\b"), False),
    "losses": ("Any losses or claims in the last 5 years? (how many, what type, when)",
               (r"\blosse?s?\b", r"\bclaims?\b", r"\bact of nature\b"), False),
    "flood": ("In a flood zone, or near the water?", (r"\bflood", r"\bwave wash"), False),
    "applicant": ("Applicant: any fraud, arson or felony history, foreclosure or bankruptcy?",
                  (r"\bfraud", r"\barson", r"\bfelon", r"\bconvict", r"\bforeclos", r"\bbankrupt",
                   r"\bmisrepresent", r"\bmoral hazard", r"\bpublic eye", r"\blegal capacity"), False),
    "mortgages": ("Mortgages: how many (HELOCs count), and none past due?",
                  (r"\bmortgage", r"\bheloc", r"\blienholder"), False),
    "electrical": ("Electrical: breakers (no fuses), no Federal Pacific / Zinsco panel, no knob-and-tube or aluminum "
                   "wiring?", (r"\bwiring\b", r"\bknob", r"\baluminum\b", r"\bfuses?\b", r"\bbreakers?\b",
                               r"(?<!solar )(?<!metal )\bpanels?\b", r"\bamps?\b",
                               r"\belectric(al)? (service|system|panel)"), False),
    "water_heater": ("Water heater in good condition and within its usable life?", (r"\bwater heater",), True),
    "heating": ("Heating and cooling: central and thermostatic, no wood stove, space heater or kerosene as main "
                "heat?", (r"\bheat", r"\bfurnace", r"\bstoves?\b", r"\bboiler", r"\bfireplace", r"\bkerosene",
                          r"\bhvac", r"\bburners?\b", r"\bchimney", r"\bcooling", r"\bswamp cooler"), False),
    "plumbing": ("Plumbing: material and condition as the guide requires (no polybutylene, no leaks)?",
                 (r"\bplumb", r"\bpolybutyl", r"\bgalvaniz", r"\bpipes?\b", r"\bpiping",
                  r"\bwater (supply|line|shut)"), False),
    "under_construction": ("Not under construction or major renovation?",
                           (r"\bunder construction", r"\bcourse of construction", r"\bbeing built",
                            r"\bmajor (renovation|remodel)", r"\bundergoing", r"\bplanning major",
                            r"\bextensive renovation"), False),
    "updates": ("Systems updated as the guide requires (roof, wiring, plumbing, heating)?",
                (r"\bupdat", r"\brenovat", r"\bremodel", r"\breplaced within"), False),
    "roof": ("Roof in good condition, no visible damage, one layer, enough life left?",
             (r"\broofs?\b", r"\bshingles?\b", r"\boverlay"), False),
    "construction": ("Construction: nothing unusual (log, dome, EIFS / synthetic stucco, asbestos, metal building, "
                     "mobile or modular)?",
                     (r"\blog\b", r"\bdomes?\b", r"\bgeodesic", r"\beifs\b", r"\bdefs\b", r"\bdryvit", r"\bstucco", r"\basbestos",
                      r"\bunconventional", r"\bmetal building", r"\bmodular", r"\bmobile", r"\bmanufactured",
                      r"\bsiding", r"\bconstruction\b", r"\bcantilever", r"\bover water", r"\bcombustible",
                      r"\bfloating home", r"\bboat house"), False),
    "foundation": ("Foundation: no settling or cracks, not on stilts or piers, no sinkhole history?",
                   (r"\bfoundation", r"\bpiers?\b", r"\bstilts?\b", r"\bsettling\b", r"\bsinkhole", r"\bcrawl ?space",
                    r"\bslab\b"), False),
    "ownership": ("Owned by individuals (not an LLC, corporation, trust or estate) and titled to the applicant?",
                  (r"\bllc\b", r"\bcorporat", r"\btrusts?\b", r"\bestates?\b", r"\bdeed", r"\btitled?\b",
                   r"\bnamed insured", r"\bowners?\b(?!-occupied)", r"\bgovernmental"), False),
    "occupancy": ("Occupancy: no short-term rental, roomers, students or vacancy?",
                  (r"\brent", r"\btenant", r"\broomer", r"\bboarder", r"\bstudent", r"\bshort[- ]term",
                   r"\boccup", r"\bvacan", r"\bunoccupied", r"\bseasonal", r"\bhome sharing", r"\bfraternit",
                   r"\bsororit", r"\bcollege"), False),
    "business": ("Any business, farming or daycare on the premises?",
                 # ("new business" is the guides' word for a new policy, not a business on the premises)
                 (r"(?<!new )(?<!name of a )\bbusiness", r"\bdaycare", r"\bday care", r"\bcommercial",
                  r"\bfarm(?! animals)", r"\bnon-habitational",
                  r"\bprivate residential", r"\bresidential purpose", r"\billegal", r"\bspeculation"), False),
    "dwelling_type": ("Building details: number of units, townhome firewalls, single building?",
                      (r"\bunits?\b", r"\bfire ?walls?\b", r"\bfire division", r"\btownho", r"\bduplex",
                       r"\bsingle building", r"\bfamil(y|ies) dwelling", r"\bstories\b", r"\bsquare f",
                       r"\b\d\+? family"), False),
    "pool": ("Pool or spa details: fence, gate, diving board, slide?",
             (r"\bpool", r"\bdiving", r"\bslide", r"\bspa\b", r"\bhot tub"), False),
    "liability_hazards": ("Trampoline, skate ramp, play equipment or other hazards on the property?",
                          (r"\btrampoline", r"\bskate", r"\bplayground", r"\bzip ?line", r"\bswing",
                           r"\bpond", r"\blake", r"\bdock"), False),
    "animals": ("Any livestock or exotic animals, or a dog with a bite history?",
                (r"\banimal", r"\blivestock", r"\bhorse", r"\bexotic", r"\bbite", r"\bvicious", r"\bdogs?\b"), False),
    "acreage": ("Lot size within the guide's acreage limit?", (r"\bacre", r"\blot size"), False),
    "wildfire": ("Any brush, wildfire or hillside exposure?",
                 (r"\bbrush", r"\bwildfire", r"\bwildland", r"\bhillside", r"\bslope", r"\blandslide",
                  r"\bfireline"), False),
    # round 37 follow-up: the protection-class rows (station, hydrant, and the visibility / alarm / access
    # conditions of the higher-risk rows) had landed under "site", "alarms" or "losses"
    "fire_protection": ("Fire protection: station distance and hydrant, and where the guide asks, visible from the "
                        "road, central alarm and year-round access?",
                        (r"\bprotection class", r"\bfpc\b", r"\bppc\b", r"\bfire stations?\b", r"\bhydrants?\b",
                         r"\bfire department"), False),
    "site": ("Site and access: paved road, year-round fire and emergency access, stable ground?",
             (r"\bpaved road", r"\baccessib", r"\baccess\b", r"\blandfill", r"\bunstable", r"\bemergency",
              r"\bjurisdiction", r"\bislands?\b", r"\bfire protection service"), False),
    "alarms": ("Alarms or sprinklers where the guide requires them?", (r"\balarm", r"\bsprinkler"), False),
    "solar": ("Solar panels: how and where installed?", (r"\bsolar",), False),
    "historic": ("A historic or registered home?", (r"\bhistoric",), False),
    "upkeep": ("Home and yard kept up: no existing damage, debris, trip hazards or dead trees?",
               # ("water damage claims / losses" are losses, not upkeep)
               (r"\bdamage(?!\s+(claims?|losses?|remediation))", r"\bgood condition", r"\bdisrepair", r"\bdeteriorat", r"\bpoor condition",
                r"\bmaintenance", r"\bmaintained", r"\bdebris", r"\btrip\b", r"\bfall hazard", r"\btrees?\b",
                r"\bhand ?rail", r"\bunrepaired", r"\bpeeling", r"\bappliances", r"\brailings?\b", r"\bporch",
                r"\bdecks?\b", r"\bbalcon", r"\bburglar bars", r"\blimbs", r"\bdoorways?", r"\bsmoke detector",
                r"\bin need of repair", r"\bgutters", r"\bwindows", r"\btanks?\b",
                r"\bpride of ownership"), True),
}
CATEGORY_TOPIC = {
    "LOSS_HISTORY": "losses", "ELECTRICAL": "electrical", "OTHER_SYSTEMS": "heating", "PLUMBING": "plumbing",
    "CONSTRUCTION": "construction", "FOUNDATION": "foundation", "DWELLING_TYPE": "dwelling_type",
    "OCCUPANCY": "occupancy", "OWNERSHIP": "ownership", "POOL": "pool", "LIABILITY_HAZARDS": "liability_hazards",
    "ANIMALS": "animals", "ACREAGE": "acreage", "FLOOD": "flood", "SOLAR": "solar", "LOCATION": "site",
    "DWELLING_LIMITS": "coverage_a", "ROOF_ELIG": "roof", "ROOF_SETTLEMENT": "roof",
}
OTHER_LABEL = "Other rules in this guide"
_RX = {k: re.compile("|".join(p), re.I) for k, (_, p, _) in TOPICS.items()}
# Phrases that decide the topic before any word count does (checked in order).
_FIRST = (
    (re.compile(r"\bpride of ownership\b", re.I), "upkeep"),
    (re.compile(r"\bin the name of\b|\btitled in\b", re.I), "ownership"),
    # "X roofs are / on / with ..." -- the roof is the subject even when its material words come first
    (re.compile(r"\broofs?\s+(are|is|must|of|on|with|over|older|under|that|in)\b", re.I), "roof"),
)
_HAS_NUMBER = re.compile(r"\d")
_DOLLARS = re.compile(r"\$\s?\d")
_COUNTED = re.compile(r"\b(\d+ or more|more than \d+|at most \d+|no more than \d+|fewer than \d+|any)\b", re.I)


@functools.lru_cache(maxsize=None)
def topic_hits(text):
    """[(position, table order, key)] of every topic whose words occur in the text, first occurrence first."""
    hits = []
    for i, (key, rx) in enumerate(_RX.items()):
        m = rx.search(text or "")
        if m:
            hits.append((m.start(), i, key))
    return sorted(hits)


def label(key):
    return TOPICS[key][0] if key in TOPICS else OTHER_LABEL


@functools.lru_cache(maxsize=None)
def topic_of(text, category=""):
    """The topic key for a rule (or a model's confirm item), from its words; the workbook topic decides when no
    words match; "other" when neither does. Cached: the same rule texts come back on every check (round 37
    step 5: the page took 1-2.5 s to build on Liam's profile, most of it here).

    Round 37 follow-up (Liam, 2026-10-11): the topic is the one whose words come FIRST in the rule -- its subject
    -- not the first topic in TOPICS whose words occur anywhere ("For a building under construction ..., Coverage
    A over $1 million is ineligible" is a construction rule; "Homes of unconventional construction ... Solar
    panels are handled ..." is not an electrical one). _FIRST phrases decide before that."""
    for rx, key in _FIRST:
        if rx.search(text or ""):
            return key
    hits = topic_hits(text)
    return hits[0][2] if hits else CATEGORY_TOPIC.get(category or "", "other")


def _decides_often(r):
    """Sort key for the rule an item quotes: one that decides most often first -- no dollar amount (the form never
    asks one), a rule wholly about this topic, a count ("2 or more", "any") -- then the strongest effect."""
    t = r["rule"]
    return (bool(_DOLLARS.search(t)), len(topic_hits(t)) > 1, not _COUNTED.search(t),
            EFFECT_RANK.get(r.get("effect"), 3))


# ---------------------------------------------------------------- one card

_CONFIRM_NOTE = re.compile(r"Confirm \((?:not asked by the form|left blank on the form)[^)]*\): (.+?)\.(?=\s|$)")


def card_rows(rec):
    """Every confirm row of one card as dicts {row, category, effect, rule, kind}: the rules table's
    confirm_items, and the model path's "Confirm (...)" note items."""
    rows = [dict(r) for r in rec.get("confirm_items") or []]
    for m in _CONFIRM_NOTE.finditer(rec.get("notes") or ""):
        for item in m.group(1).split("; "):
            if item.strip():
                rows.append({"row": "", "category": "", "effect": "", "rule": item.strip(), "kind": "model"})
    return rows


def _short(rule, n=120):
    first = re.split(r";\s", rule.strip())[0].rstrip(".")
    return first if len(first) <= n else first[:n].rsplit(" ", 1)[0] + "…"


def card_items(rec):
    """[{key, text, effect, rows, count}] for one card, in display order (all of them; the card shows CARD_MAX)."""
    groups = {}
    for r in card_rows(rec):
        key = topic_of(r["rule"], r.get("category"))
        groups.setdefault(key, []).append(r)
    items = []
    for key, rules in groups.items():
        ranked = sorted(rules, key=lambda r: EFFECT_RANK.get(r.get("effect"), 3))
        text = label(key)
        # a number (or, for a blank-field note, the named places) decides it: keep the guide's own rule
        # (round 37 follow-up: of those, the one that decides most often)
        candidates = [r for r in ranked if _HAS_NUMBER.search(r["rule"]) or r.get("kind") == "blank"]
        decisive = min(candidates, key=_decides_often) if candidates else None
        if key == "other":
            text = f"{OTHER_LABEL}: " + "; ".join(_short(r["rule"], 80) for r in ranked[:2]) + (
                f" (+{len(ranked) - 2} more)" if len(ranked) > 2 else "")
        elif decisive is not None:
            text = f"{text} — guide: {_short(decisive['rule'])}"
        items.append({"key": key, "text": text, "effect": ranked[0].get("effect") or "",
                      "rows": sorted({r.get("row") for r in rules if r.get("row")}), "count": len(rules)})

    def order(it):
        upkeep = TOPICS.get(it["key"], ("", (), False))[2]
        return (it["key"] == "other", upkeep, EFFECT_RANK.get(it["effect"], 3), -it["count"], it["key"])
    return sorted(items, key=order)


def card_list(rec):
    """(shown, more, rule_ids): what the card prints under "Before you quote, confirm:"."""
    items = card_items(rec)
    ids = sorted({rid for it in items for rid in it["rows"]})
    return items[:CARD_MAX], items[CARD_MAX:], ids


# ---------------------------------------------------------------- the results page

def top_box(results):
    """[(label, count, of)] -- the topics at least half of the Eligible and Refer cards ask, most common first,
    at most TOP_MAX. "of" is the number of Eligible and Refer cards."""
    cards = [r for r in results if r.get("status") in ("ELIGIBLE", "REFER")]
    if not cards:
        return []
    counts = {}
    for r in cards:
        for key in {it["key"] for it in card_items(r)} - {"other"}:
            counts[key] = counts.get(key, 0) + 1
    of = len(cards)
    common = [(k, n) for k, n in counts.items() if 2 * n >= of]
    common.sort(key=lambda kn: (-kn[1], list(TOPICS).index(kn[0])))
    return [(TOPICS[k][0], n, of) for k, n in common[:TOP_MAX]]
