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


def _load_counties():
    with open(TEXAS_COUNTIES_FILE, encoding="utf-8") as fh:
        rows = csv.DictReader(line for line in fh if not line.startswith("#"))
        return {r["county"]: float(r["max_latitude"]) for r in rows}


# {county name: northernmost latitude, degrees N}. See texas_counties.csv for
# the source (U.S. Census Bureau 2023 cartographic boundaries) and date.
COUNTY_MAX_LATITUDE = _load_counties()
TEXAS_COUNTIES = sorted(COUNTY_MAX_LATITUDE)


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


def normalize_dwelling_type(value):
    return value if value in DWELLING_TYPES else ""
