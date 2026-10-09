"""The three OPTIONAL intake fields (Liam, 2026-09-30): County, Dwelling
amount (Coverage A), Dwelling type. Blank always means UNKNOWN -- none of them
has a default that could be mistaken for an answer, and a blank field adds
nothing to the eligibility prompt (see eligibility_check._optional_fact_lines).

Kept out of app.py so the parsing and the county data are testable without a
Streamlit session.
"""
import csv
import os
import re

TEXAS_COUNTIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "texas_counties.csv")

DWELLING_TYPES = ("", "House", "Townhome", "Condo")

# Round 29 step 1 (Liam, 2026-10-08): every field the intake form collects
# (app.py's property_details keys), with the words a missing_info item uses
# for it. hold_guard.py keeps any hold on these: they are on the form, so a
# blank one is the agent's to fill in, never "not asked".
FORM_FIELDS = {
    "year_built": (r"year built", r"home age", r"age of (the )?(home|dwelling|house)", r"built (in|before|after)"),
    "roof_age": (r"roof age", r"age of (the )?roof", r"roof[- ]age"),
    "roof_type": (r"roof (type|material|covering)", r"3-tab", r"architectural", r"shingle", r"metal roof",
                  r"tile roof", r"wood shake", r"\broof\b"),
    "roof_shape": (r"roof shape", r"flat roof", r"\bgable\b", r"\bhip\b"),
    "construction_type": (r"construction type", r"\bframe\b", r"\bmasonry\b", r"manufactured", r"mobile home"),
    "plumbing_type": (r"plumbing", r"galvani[sz]ed", r"polybutylene", r"\bpex\b", r"\bcopper\b"),
    "occupancy_type": (r"occupan", r"owner[- ]occupied", r"tenant", r"vacan", r"seasonal", r"secondary"),
    "ownership_type": (r"ownership", r"\btrust\b", r"\bllc\b", r"owned by"),
    "coastal_tier": (r"coastal", r"\bcoast\b", r"\bgulf\b", r"shoreline", r"\bbay\b", r"hurricane", r"wind ?pool",
                     r"\btwia\b", r"\btier\b"),
    "swimming_pool": (r"\bpool\b", r"\bspa\b", r"hot tub"),
    "pool_accessories": (r"diving board", r"\bslide\b"),
    "pool_fence_4ft": (r"\bfence\b", r"enclosure", r"pool cage", r"\bbarrier\b"),
    "pool_gate_locking": (r"\bgate\b", r"self[- ]latching", r"self[- ]locking", r"lockable"),
    "has_dogs": (r"\bdogs?\b", r"\bcanine\b"),
    "dog_breeds": (r"\bbreed\b", r"pit ?bull", r"rottweil", r"\bmix of\b"),
    "solar_panels": (r"\bsolar\b",),
    "ppc": (r"\bppc\b", r"protection class", r"\bfpc\b"),
    "fire_station_miles": (r"fire station", r"station distance", r"miles to (the )?(nearest |responding )?fire"),
    "hydrant_1000ft": (r"hydrant",),
    "zip": (r"\bzip\b",),
    "county": (r"\bcounty\b", r"territory", r"south texas", r"east texas"),
    "dwelling_amount": (r"coverage a\b", r"dwelling (amount|limit|coverage)", r"cov\.? a\b"),
    "dwelling_type": (r"dwelling type", r"\bcondo", r"townhome", r"townhouse", r"unit[- ]owner", r"single[- ]family"),
    # Round 30 step 1 (Liam, 2026-10-08): asked only for a Seasonal / Secondary Home.
    "primary_home_carrier": (r"(insures?|writes?|written|insured)\b.{0,40}\bprimary",
                             r"primary\b.{0,40}\b(insur|written|writes)", r"primary (home|residence|dwelling) carrier"),
    "primary_home_miles": (r"(distance|miles)\b.{0,30}\bprimary", r"primary\b.{0,30}\b(distance|miles)"),
}

# Round 30 step 1 (Liam, 2026-10-08, decision 1): "Primary home insured with", shown only for a
# Seasonal / Secondary Home. One choice per insurer, in the carrier list's order (the list is the
# program names sorted, so an insurer's programs sit together); Sage's insurers stay separate.
# label -> the program-name prefixes it covers. Every expected program maps to exactly one label
# (test_primary_home_fields.py), so a new carrier cannot be left out silently.
PRIMARY_HOME_CARRIERS = {
    "ARI": ("ARI_",), "Allied Trust": ("Allied_Trust",), "Chubb": ("CHUBB_",), "Centauri": ("Centauri_",),
    "Foremost": ("Foremost_",), "HOAIC": ("HOAIC_",), "Liberty Mutual / Safeco": ("Liberty_Mutual_",),
    "Mercury": ("Mercury_",), "National General": ("NatGen_",), "Orion180": ("Orion_",),
    "Progressive": ("Progressive_",), "Sage: Auros": ("Sage_-_Auros",), "Sage: Markel": ("Sage_-_Markel",),
    "Sage: Occidental": ("Sage_-_Occidental",), "Sage: SURE": ("Sage_-_SURE",),
    "Sage: SafePort": ("Sage_-_SafePort",), "Sage: Trium": ("Sage_-_Trium",), "Sage: Vave": ("Sage_-_Vave",),
    "Sage: Wilshire": ("Sage_-_Wilshire",), "Steadily": ("Steadily_",), "Swyfft": ("Swyfft_",),
    "TWICO": ("TWICO_",), "Travelers": ("Travelers_",),
}
OTHER_CARRIER, UNKNOWN_CARRIER = "Other carrier", "Unknown"
PRIMARY_HOME_CHOICES = ("",) + tuple(PRIMARY_HOME_CARRIERS) + (OTHER_CARRIER, UNKNOWN_CARRIER)
OWNERS_OTHER_HOMES = ("Seasonal", "Secondary Home")


def primary_home_label(program):
    """The "Primary home insured with" choice that covers a program name, or None."""
    hits = [label for label, prefixes in PRIMARY_HOME_CARRIERS.items() if program.startswith(prefixes)]
    return hits[0] if len(hits) == 1 else None


def primary_home_carrier(value):
    """A stated choice ("Chubb", "Other carrier"), or None for blank / Unknown / anything else."""
    v = str(value or "").strip()
    return v if v in PRIMARY_HOME_CARRIERS or v == OTHER_CARRIER else None


def parse_primary_home_miles(value):
    """Miles from the primary home, or None when blank or unreadable (read as the station distance)."""
    return parse_station_miles(value)


def _load_counties():
    with open(TEXAS_COUNTIES_FILE, encoding="utf-8") as fh:
        rows = csv.DictReader(line for line in fh if not line.startswith("#"))
        return {r["county"]: float(r["max_latitude"]) for r in rows}


# {county name: northernmost latitude, degrees N}. See texas_counties.csv for
# the source (U.S. Census Bureau 2023 cartographic boundaries) and date.
COUNTY_MAX_LATITUDE = _load_counties()
TEXAS_COUNTIES = sorted(COUNTY_MAX_LATITUDE)


# ---------------------------------------------------------------------------
# ZIP -> County (round 21, Liam 2026-10-02). The table lives in code; the model
# never sees it or the ZIP -- only "County: <name>", and only when the County
# topic is checked. Built by build_zip_county.py; its header names the source,
# the build date and the share definition.
# ---------------------------------------------------------------------------
ZIP_COUNTIES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zip_counties.csv")
# Texas's USPS ZIP ranges: 733xx (Austin IRS / state), 750xx-799xx, 885xx (El Paso).
TEXAS_ZIP_RANGES = ((73301, 73399), (75000, 79999), (88500, 88599))


def _load_zip_counties():
    table, header = {}, []
    with open(ZIP_COUNTIES_FILE, encoding="utf-8") as fh:
        lines = list(fh)
    header = [l[1:].strip() for l in lines if l.startswith("#")]
    for r in csv.DictReader(l for l in lines if not l.startswith("#")):
        table.setdefault(r["zip"], []).append((r["county"], float(r["share"])))
    return table, header


ZIP_COUNTIES, ZIP_TABLE_HEADER = _load_zip_counties()


def parse_zip(value):
    """(five-digit ZIP, None) or (None, one-line message). Spaces are
    stripped; ZIP+4 uses its first five digits; blank is (None, None)."""
    text = re.sub(r"\s+", "", str(value or ""))
    if not text:
        return None, None
    m = re.fullmatch(r"(\d{5})(?:-?\d{4})?", text)
    if not m:
        return None, "A ZIP is five digits (ZIP+4 is fine); this one was not used."
    return m.group(1), None


def is_texas_zip_range(zip5):
    n = int(zip5)
    return any(lo <= n <= hi for lo, hi in TEXAS_ZIP_RANGES)


def counties_for_zip(zip5):
    """[(county, share)] largest share first, ties alphabetical -- the same
    order every time, in every process."""
    return sorted(ZIP_COUNTIES.get(zip5, ()), key=lambda cs: (-cs[1], cs[0]))


def county_for_zip(value):
    """The county a ZIP is checked as. Returns (county or "", message).
    One county: that county. Several: the largest share, tie alphabetical,
    never random. Unknown or non-Texas: "" (unknown) and a line saying so."""
    zip5, err = parse_zip(value)
    if err or zip5 is None:
        return "", err
    found = counties_for_zip(zip5)
    if not found:
        if is_texas_zip_range(zip5):
            return "", (f"ZIP {zip5} is not in the ZIP-to-county table (PO-box-only and some "
                        "special ZIPs are missing), so County is left blank.")
        return "", f"ZIP {zip5} is not a Texas ZIP, so County is left blank."
    county = found[0][0]
    if len(found) == 1:
        return county, f"Checked as {county} County (from ZIP {zip5})."
    named = [f"{c} ({s:.0%})" for c, s in found]
    parts = named[0] + " and " + named[1] if len(named) == 2 else ", ".join(named[:-1]) + " and " + named[-1]
    return county, (f"ZIP {zip5} spans {parts}. Checked as {county}; change the county "
                    "below if you know it.")


def zip_spans_sage_split(zip5):
    """True when the ZIP's counties disagree on the Sage ADDRESS rule (either
    variant: with the Nueces exception, or Trium's without), so the pick can
    flip a Sage verdict. Round 21 step 7 counted 62 such ZIPs."""
    from structured_rules import sage_county_in_territory
    counties = [c for c, _ in counties_for_zip(zip5)]
    return len(counties) > 1 and any(
        len({sage_county_in_territory(c, COUNTY_MAX_LATITUDE, excl) for c in counties}) > 1
        for excl in (True, False))


def zip_pick_lines(value):
    """Display only (round 22, Liam 2026-10-02) -- never reaches the prompt.
    (caption, warning) for a ZIP that resolves; (None, None) otherwise.
      caption  "ZIP 77002 -> Harris County (100% of the ZIP)", plus "This ZIP
               spans more than one county." when the share is under 80%
      warning  for a ZIP whose counties give different Sage results"""
    zip5, _ = parse_zip(value)
    found = counties_for_zip(zip5) if zip5 else []
    if not found:
        return None, None
    county, share = found[0]
    caption = f"ZIP {zip5} -> {county} County ({share:.0%} of the ZIP)"
    if share < 0.80:
        caption += ". This ZIP spans more than one county."
    warning = ("This ZIP spans counties with different Sage results. Select the County "
               "directly to be sure.") if zip_spans_sage_split(zip5) else None
    return caption, warning


def normalize_county(value):
    """The canonical county name, or "" for blank/unknown. Accepts any case
    and a trailing " County"; anything not one of Texas's 254 is "" -- an
    unrecognised county is unknown, never a guess."""
    if not value or not isinstance(value, str):
        return ""
    v = re.sub(r"\s+county$", "", value.strip(), flags=re.I).strip()
    for name in TEXAS_COUNTIES:
        if name.lower() == v.lower():
            return name
    return ""


def parse_dwelling_amount(value):
    """Coverage A in whole dollars, or None for blank/unparseable.

    Accepts "450000", "450,000", "$450,000", "$450,000.00", "450k", "1.2m".
    Anything else -- words, a negative, zero -- is None (unknown), so a typo
    never turns into a stated fact."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    text = str(value).strip().lower().replace(",", "").replace("$", "").replace(" ", "")
    if not text:
        return None
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(k|m)?", text)
    if not m:
        return None
    amount = float(m.group(1)) * {"k": 1_000, "m": 1_000_000}.get(m.group(2) or "", 1)
    return int(round(amount)) if amount > 0 else None


# Round 20 (Liam, 2026-10-01): the two pool checkboxes exist only for these
# answers. Unchecked means UNKNOWN, never "no".
FENCED_POOL_VALUES = ("Above Ground - Fenced", "In Ground - Fenced")


def pool_box(property_details, key):
    """True only when the pool answer is a fenced one AND the box was ticked.
    Anything else -- no pool, unfenced, a stale tick left over from an
    earlier pool answer, a truthy string -- is unknown."""
    return (property_details.get("swimming_pool") in FENCED_POOL_VALUES
            and property_details.get(key) is True)


# Round 26 (Liam, 2026-10-05, decision B): two optional PPC-topic fields.
# Blank / Unknown is UNKNOWN -- never "no", never 0 miles.
HYDRANT_CHOICES = ("Unknown", "Yes", "No")


def parse_station_miles(value):
    """Driving distance to the responding fire station in miles, or None when
    blank or unreadable. "3", "3.5", "3 miles", " 7mi " all read."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else None
    m = re.match(r"\s*(\d+(?:\.\d+)?)", str(value))
    return float(m.group(1)) if m else None


def hydrant_answer(value):
    """"Yes" / "No" for a stated answer, None for Unknown or blank."""
    v = str(value or "").strip().capitalize()
    return v if v in ("Yes", "No") else None


def normalize_dwelling_type(value):
    return value if value in DWELLING_TYPES else ""


# ---------------------------------------------------------------------------
# Round 35 step 3a (Liam, 2026-10-09, decision 1): "Breed(s) on the property", asked when Dogs = Yes. The
# union of every carrier's banned and specified breeds (the four rules tables plus the guides' own lists:
# Sage's "Specified Dog Breeds", Travelers p1, Allied p7). Picking a breed means the dog is that breed or a
# mix of it. No option holds a comma (the map grammar splits sets on commas).
DOG_BREEDS = (
    "Akita", "Alaskan Malamute", "American Bull Terrier", "American Bulldog", "American Bully",
    "American Staffordshire Terrier", "Beauceron", "Belgian Malinois", "Boxer", "Bull Terrier", "Bullmastiff",
    "Cane Corso", "Caucasian Ovcharka (Caucasian Mountain Dog)", "Chow Chow", "Doberman Pinscher",
    "Dogo Argentino", "German Shepherd", "Giant Schnauzer", "Great Dane", "Husky (other than Siberian)",
    "Mastiff", "Neapolitan Mastiff", "Pit Bull (American Pit Bull Terrier)", "Presa Canario",
    "Rhodesian Ridgeback", "Rottweiler", "Siberian Husky", "St. Bernard", "Staffordshire Bull Terrier",
    "Trained guard / attack / police / military dog", "Wolf hybrid or wild dog")
DOG_NONE, DOG_UNSURE = "None of these", "Not sure"
DOG_CHOICES = DOG_BREEDS + (DOG_NONE, DOG_UNSURE)


def dog_breeds(pd):
    """The breeds on the property as the rules read them:
    - None: no answer (blank, "Not sure", or only the old aggressive-breed toggle) -- unknown, so it holds;
    - frozenset(): "None of these";
    - the frozenset of picked breeds otherwise.
    With no dogs the field is never read (the rows are gated on Dogs = Yes)."""
    picked = pd.get("dog_breeds")
    if picked in (None, "", []):
        return None                     # the old toggle (aggressive_breed) never says which breed: unknown
    if isinstance(picked, str):
        picked = [x.strip() for x in picked.split(";") if x.strip()]
    picked = [x for x in picked if x]
    if not picked or DOG_UNSURE in picked:
        return None
    return frozenset(x for x in picked if x in DOG_BREEDS)


def aggressive_breed_answer(pd):
    """The old Yes / No / Unknown answer, derived for the code that still reads it (the prompt line with no
    dogs, the contradiction guard, the card's first line). An old saved profile keeps its own value."""
    if pd.get("has_dogs") != "Yes":
        return "No"
    if "dog_breeds" not in pd:
        return pd.get("aggressive_breed") or "Unknown"
    b = dog_breeds(pd)
    return "Unknown" if b is None else ("Yes" if b else "No")

