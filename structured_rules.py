"""
Structured (non-LLM) eligibility rules for tables that are static and
tabular, extracted once from the source PDFs and evaluated with plain code
instead of asking the model to re-derive the table from prose on every
call. See CLAUDE.md and the "Experiment B / structured extraction" scoping
work for why this exists: for genuinely tabular rules, this gets much
closer to 100% deterministic than any prompt fix can, because there is no
LLM reasoning step left in the path at all.

Not yet wired into check_eligibility() / eligibility_check.py -- these are
verified building blocks, callable standalone and covered by their own
deterministic tests in verification/test_eligibility_matrix.py.
"""


def sage_family_fpc_eligibility(ppc, distance_miles=None, hydrant_feet=None, carrier=None):
    """Fire Protection Class (FPC) eligibility table shared by all six
    related Sage-family documents: Auros, Occidental, Wilshire, Trium,
    SURE, and SafePort. Verified against each carrier's own raw extracted
    text individually (not assumed from Auros alone) -- Trium/SURE/SafePort
    additionally tag each row with an A/B/C classification label used
    elsewhere in their own documents for a separate Coverage-A/TIV cap (out
    of scope here), but the underlying FPC/distance/hydrant eligibility
    logic below is identical across all six.

    The six rows, sorted by driving distance to the fire station first,
    then by FPC range (this is the order the source table actually keys
    on -- an earlier read of Auros's garbled table-to-text extraction
    mis-keyed on FPC first, which made one row look like it contradicted
    another; it doesn't, once distance is the first key):

      1. Any FPC,  <=5mi,  hydrant <=1,000ft        -> ELIGIBLE, no conditions       ("A")
      2. FPC 1-3,  <=5mi,  hydrant >1,000ft/none     -> ELIGIBLE if 3 conditions      ("B")
      3. FPC 1-3,  >5mi,   hydrant irrelevant        -> ELIGIBLE if same 3 conditions ("C")
      4. FPC 4-10, <=5mi,  hydrant >1,000ft/none     -> ELIGIBLE if same 3 conditions ("B")
      5. FPC 4-8,  >5mi,   hydrant irrelevant        -> ELIGIBLE if 3 conditions + 4 more ("C")
      6. FPC 9+,   >5mi,   hydrant irrelevant        -> INELIGIBLE                    ("C")

    NOTE -- Occidental is a REAL, CONFIRMED exception, not an extraction
    artifact: row 5's fourth extra condition, "no rental exposures
    allowed," is present in Auros, Wilshire, Trium, SURE, and SafePort's
    text but genuinely absent from Occidental's own document (confirmed
    directly against Occidental's source text, not assumed). Pass
    carrier="occidental" (or any string containing "occidental",
    case-insensitive) to get Occidental's 3-condition version of row 5;
    every other carrier (including carrier=None, the default) gets the
    4-condition version.

    The current customer intake form (see profiles.py) only collects a
    single PPC/FPC value -- no driving-distance-to-station or
    hydrant-distance field exists yet. distance_miles / hydrant_feet
    default to None (unknown) to reflect that; the function still returns
    a correct verdict where the table allows one regardless of the missing
    fields (true for FPC 1-8 under every row), and INSUFFICIENT_INFORMATION
    only where the table's outcome genuinely depends on the missing value
    (true only for FPC 9-10, where eligibility depends on distance).

    Returns (status, reasons) where status is one of "ELIGIBLE",
    "INELIGIBLE", "INSUFFICIENT_INFORMATION" and reasons is a list of
    human-readable strings (empty when the verdict is unconditional).
    """
    try:
        fpc = int(ppc)
    except (TypeError, ValueError):
        return "INSUFFICIENT_INFORMATION", [f"FPC/PPC value {ppc!r} is not a recognized number 1-10."]

    is_occidental = bool(carrier) and "occidental" in carrier.lower()

    conditions_b = (
        "visible from the main public road, has a central-station fire alarm, and is "
        "accessible by fire-fighting equipment year-round with a minimum 10-foot roadway width"
    )
    if is_occidental:
        # Occidental's row 5 genuinely lacks "no rental exposures allowed"
        # -- confirmed against its own source text, not a dropped bullet.
        conditions_high_fpc_extra = (
            "home under 25 years old, primary occupancy only, and no prior fire losses"
        )
    else:
        conditions_high_fpc_extra = (
            "home under 25 years old, primary occupancy only, no rental exposure, "
            "and no prior fire losses"
        )

    if distance_miles is not None and distance_miles <= 5:
        if hydrant_feet is not None and hydrant_feet <= 1000:
            return "ELIGIBLE", []  # row 1
        if 1 <= fpc <= 10:
            return "ELIGIBLE", [
                f"Eligible only if the property is {conditions_b} "
                f"(hydrant beyond 1,000ft or absent)."
            ]  # rows 2 & 4
        return "INSUFFICIENT_INFORMATION", [f"FPC {fpc} is outside this table's 1-10 range."]

    if distance_miles is not None and distance_miles > 5:
        if 1 <= fpc <= 3:
            return "ELIGIBLE", [f"Eligible only if the property is {conditions_b}."]  # row 3
        if 4 <= fpc <= 8:
            return "ELIGIBLE", [
                f"Eligible only if the property is {conditions_b}, and {conditions_high_fpc_extra}."
            ]  # row 5
        if fpc >= 9:
            return "INELIGIBLE", [
                "FPC 9 or greater with driving distance to the fire station greater than "
                "5 miles is ineligible."
            ]  # row 6
        return "INSUFFICIENT_INFORMATION", [f"FPC {fpc} is outside this table's 1-10 range."]

    # distance to fire station not provided by the current intake form
    if 1 <= fpc <= 8:
        return "ELIGIBLE", [
            "FPC 1-8 is eligible regardless of driving distance to the fire station or hydrant "
            "proximity -- every row in the table for this FPC range resolves to eligible. The "
            "exact conditions to confirm (if any) depend on that distance, which was not provided."
        ]
    if fpc >= 9:
        return "INSUFFICIENT_INFORMATION", [
            "FPC 9 or greater is eligible if driving distance to the fire station is 5 miles or "
            "less, and ineligible if greater than 5 miles -- that distance was not provided."
        ]
    return "INSUFFICIENT_INFORMATION", [f"FPC {fpc} is outside this table's 1-10 range."]


# ---------------------------------------------------------------------------
# Roof-age tables. Scoped per the "structured extraction for genuinely
# tabular rules" investigation -- roof age has been a repeat source of
# errors since round 1. Checked each of the 7 candidate carriers' actual
# extracted text individually before writing any code; they turned out to
# be far less uniform than the Sage FPC family, so this is NOT one shared
# function -- see the per-carrier docstrings below.
#
# TWICO_HO3's roof-material table (see twico_roof_settlement below) IS
# extractable -- an earlier pass wrongly concluded the material column was
# unrecoverable; it was supplied directly and is not blank. NOT wired into
# check_eligibility() yet, though: TWICO's table distinguishes 3-tab from
# architectural composition shingle with different bands, and the current
# intake form's single "Composition Shingle" field can't tell them apart
# (see that function's own INSUFFICIENT_INFORMATION branch). Held out of
# production until intake collects that distinction, or the function's
# ambiguity handling is otherwise judged sufficient.
# ---------------------------------------------------------------------------

_MERCURY_UNCONDITIONALLY_INELIGIBLE_ROOFS = {
    "asbestos shingle", "asbestos shingles", "tin", "t-lock shingle", "t-lock shingles",
    "wood shake", "wood shakes", "wood shingle", "wood shingles",
}


def mercury_roof_eligibility(roof_type, roof_age):
    """Mercury HO3, page 1. A handful of materials are ineligible
    regardless of age. Slate/tile/metal roofs require the "Roof Surfacing"
    Loss Settlement Payment Schedule endorsement (H0499 TX, windstorm/hail
    -- RCV becomes ACV) beyond 20 years; every other roof type requires the
    same endorsement beyond 10 years. "Older than 10/20 years" is exclusive
    of the boundary value itself -- this matches the existing
    test_mercury_roof_exactly_10_years_gets_rcv_not_endorsement baseline
    test. Requiring the endorsement is not an ineligibility (coverage
    still binds, just on ACV terms), so the status name reflects that
    rather than reusing plain ELIGIBLE/INELIGIBLE."""
    rt = roof_type.strip().lower()
    if rt in _MERCURY_UNCONDITIONALLY_INELIGIBLE_ROOFS:
        return "INELIGIBLE", [f"{roof_type} is an ineligible roof material regardless of age."]

    is_slate_tile_metal = any(k in rt for k in ("slate", "tile", "metal"))
    threshold = 20 if is_slate_tile_metal else 10
    if roof_age > threshold:
        return "ELIGIBLE_REQUIRES_ENDORSEMENT", [
            f"Roof age {roof_age} exceeds {threshold} years -- the Roof Surfacing Loss "
            f"Settlement Payment Schedule (H0499 TX) endorsement is required (ACV, not RCV)."
        ]
    return "ELIGIBLE", []


# roof_type keyword (checked in priority order below) -> (rcv_max_inclusive, acv_max_inclusive).
# age <= rcv_max -> RCV; rcv_max < age <= acv_max -> ACV; age > acv_max -> EXCLUDED.
_TWICO_ROOF_BANDS = {
    "architectural": (15, 25),
    "3-tab": (10, 20),
    "3 tab": (10, 20),
    "standing-seam": (20, 35),
    "standing seam": (20, 35),
    "tile": (25, 45),
    "concrete": (25, 45),
    "clay": (25, 45),
}
_TWICO_UNCONDITIONALLY_INELIGIBLE_KEYWORDS = ("corrugated", "asbestos", "wood", "slate")

# CHANGED (round 13): the asphalt-shingle family names, all of which refer
# to the SAME roofing category per the ROOFING MATERIAL TERMINOLOGY rule in
# eligibility_check.SYSTEM_INSTRUCTIONS. Previously only the literal word
# "composition" was recognized, so "Composite Shingle" and "asphalt
# shingle" fell through to the generic "not found in this table" branch --
# TWICO's table plainly covers them, and the sub-type ambiguity that makes
# this carrier's outcome undecidable applies to them identically. Exactly
# the failure mode CLAUDE.md calls out: a fix that only works for the one
# phrasing that happened to appear in the bug report.
_TWICO_ASPHALT_FAMILY_KEYWORDS = ("composition", "composite", "asphalt")

# Sub-type qualifiers that DO resolve the ambiguity, so a roof type naming
# one of these is decidable and must not be treated as ambiguous.
_TWICO_SUBTYPE_QUALIFIERS = ("architectural", "3-tab", "3 tab")


def twico_roof_subtype_is_ambiguous(roof_type):
    """True when roof_type names the asphalt-shingle family without saying
    WHICH sub-type -- the one case TWICO's table genuinely cannot resolve.

    Single source of truth, deliberately: eligibility_check.py's structured
    override needs the exact same test to decide whether to hold a verdict
    for confirmation, and an independent copy of "is this composition
    shingle?" in the two files is precisely how the two would drift.
    """
    rt = roof_type.strip().lower()
    if any(q in rt for q in _TWICO_SUBTYPE_QUALIFIERS):
        return False
    return any(k in rt for k in _TWICO_ASPHALT_FAMILY_KEYWORDS)


def twico_roof_settlement(roof_type, roof_age):
    """TWICO HO3, page 2 roof settlement table:

        Material                          RCV     ACV       Excluded
        Composition (3-tab)                0-10    11-20     21+
        Composition (Architectural)        0-15    16-25     26+
        Metal (Standing-Seam)              0-20    21-35     36+
        Tile (Concrete/Clay)               0-25    26-45     46+
        Wood, Slate, or Metal Shingle      Ineligible at any age
        Asbestos                          Ineligible at any age
        Corrugated Metal                  Ineligible at any age

    NOT wired into check_eligibility() yet -- see the module docstring.
    Reason: the current intake form's "roof_type" field only ever contains
    the generic value "Composition Shingle", with no way to know whether
    that means 3-tab (RCV<=10/ACV 11-20/Excluded 21+) or architectural
    (RCV<=15/ACV 16-25/Excluded 26+). A 14-year-old roof is ACV-with-limits
    under one and full RCV under the other -- guessing either way would be
    confidently wrong in the same direction on every single call, which is
    worse than the LLM's occasional inconsistency this is meant to replace.
    The generic "composition shingle, no subtype given" case below
    deliberately returns INSUFFICIENT_INFORMATION rather than picking one."""
    rt = roof_type.strip().lower()

    if "metal" in rt and "shingle" in rt and "standing" not in rt:
        return "INELIGIBLE", ["Metal shingle roofing is ineligible regardless of age."]
    if any(k in rt for k in _TWICO_UNCONDITIONALLY_INELIGIBLE_KEYWORDS):
        return "INELIGIBLE", [f"{roof_type} is an ineligible roof material regardless of age."]

    bands = next((v for k, v in _TWICO_ROOF_BANDS.items() if k in rt), None)
    if bands is None:
        if twico_roof_subtype_is_ambiguous(roof_type):
            return "INSUFFICIENT_INFORMATION", [
                "TWICO distinguishes 3-tab composition shingle (RCV<=10yr/ACV 11-20yr/"
                "Excluded 21+yr) from architectural composition shingle (RCV<=15yr/ACV "
                "16-25yr/Excluded 26+yr) -- roof subtype was not provided, and this table's "
                "outcome genuinely depends on which one it is."
            ]
        return "INSUFFICIENT_INFORMATION", [f"Roof type {roof_type!r} not found in TWICO's roof settlement table."]

    rcv_max, acv_max = bands
    if roof_age <= rcv_max:
        return "RCV", []
    if roof_age <= acv_max:
        return "ACV", [f"Roof age {roof_age} falls in the {rcv_max + 1}-{acv_max} year ACV band."]
    return "EXCLUDED", [f"Roof age {roof_age} exceeds {acv_max} years -- roof coverage is excluded."]


# roof_type substring (lowercased, checked via `in`) -> (rcv_max_exclusive, acv_max_exclusive)
# age < rcv_max_exclusive -> RCV; rcv_max_exclusive <= age <= acv_max_exclusive -> ACV;
# age > acv_max_exclusive -> EXCLUDED. Verified against Swyfft Lloyds (Surplus) HO3's own
# table text directly -- this one carrier's table was the only one of the seven checked
# that extracted cleanly with material names intact.
SWYFFT_LLOYDS_ROOF_BANDS = {
    "asphalt shingle": (15, 25),
    "light metal panel": (15, 25),
    "built-up roof": (15, 25),
    "single ply membrane": (15, 25),
    "hurricane rated shingle": (20, 25),
    "wooden shingle": (20, 25),
    "standing seam metal": (35, 40),
    "clay": (35, 40),
    "concrete tile": (35, 40),
    "slate": (35, 40),
}


def swyfft_lloyds_roof_settlement(roof_type, roof_age):
    """Swyfft Lloyds (Surplus) HO3, page 1 roof settlement table -- the
    cleanest of the seven candidate roof-age tables checked, with roof
    material names intact in the extracted text (unlike TWICO's version of
    the same kind of table). Returns "RCV", "ACV", or "EXCLUDED" (this
    carrier's table describes loss-settlement basis, not a hard eligibility
    yes/no)."""
    rt = roof_type.strip().lower()
    bands = next((v for k, v in SWYFFT_LLOYDS_ROOF_BANDS.items() if k in rt), None)
    if bands is None:
        return "INSUFFICIENT_INFORMATION", [
            f"Roof type {roof_type!r} was not found in Swyfft Lloyds's roof settlement table."
        ]
    rcv_max, acv_max = bands
    if roof_age < rcv_max:
        return "RCV", []
    if roof_age <= acv_max:
        return "ACV", [f"Roof age {roof_age} falls in the {rcv_max}-{acv_max} year ACV band for this roof type."]
    return "EXCLUDED", [f"Roof age {roof_age} exceeds {acv_max} years -- roof coverage is excluded for this roof type."]


def sage_markel_roof_exclusion(roof_type, roof_age):
    """Sage - Markel HO3, page 6. The Roof Exclusion form applies past 25
    years for any roof type other than slate/tile/metal, and past 40 years
    for slate/tile/metal. Sage Markel ALSO reserves underwriting discretion
    to move any roof (regardless of age) to ACV or exclusion if it's found
    "patched, damaged, worn, or otherwise posing additional hazards" --
    that clause is a judgment call on physical condition, not a lookup, and
    is deliberately NOT covered by this deterministic age check. Note:
    unlike its six Sage-family siblings, Markel's own text states
    "Protection Classes 1-10 are eligible (No limitations based on
    Protection Class)" -- the FPC table above must never be applied to
    Markel."""
    rt = roof_type.strip().lower()
    is_slate_tile_metal = any(k in rt for k in ("slate", "tile", "metal"))
    threshold = 40 if is_slate_tile_metal else 25
    if roof_age > threshold:
        return "ROOF_EXCLUDED", [
            f"Roof age {roof_age} exceeds {threshold} years -- the Roof Exclusion form applies. "
            f"(Underwriting may also apply this at any age for a roof found patched, damaged, "
            f"worn, or otherwise hazardous -- not evaluated by this check.)"
        ]
    return "ROOF_COVERED", []


def swyfft_max_roof_age_30(roof_age):
    """Applies to Swyfft Benchmark (Admitted), Swyfft Benchmark (Surplus),
    and Swyfft Topa (Surplus) HO3 -- all three state only "Max roof age is
    30 years. Other age restrictions depend on roof type and property
    location," with no further per-material table anywhere in the
    retrievable document text (confirmed via a full-document 'roof'
    keyword scan, not just the eligibility-content-filtered subset). The
    type/location-dependent restrictions the source text refers to are NOT
    extractable from what this tool has ingested for these three carriers
    -- this function only implements the one hard number that IS stated.
    Flag for a human check against the source PDFs before treating this as
    the complete rule."""
    if roof_age > 30:
        return "INELIGIBLE", [f"Roof age {roof_age} exceeds the 30-year maximum."]
    return "ELIGIBLE", []
