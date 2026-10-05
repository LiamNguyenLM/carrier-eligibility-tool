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
