# Rule field map (round 24 Part 2, 2026-10-02; v3 in round 25, 2026-10-04; v5 in round 28, 2026-10-07)

`rule_field_map.csv` has one line per **deciding** row of
`carrier_rules_pilot_v5.csv` (pilot workbook version 5), i.e. rows whose
Tool handling is EVALUATE or EVALUATE_CURE_IS_INSPECTION. There are 541 such
rows. It is built by `build_rule_field_map.py`, where every non-NONE line is
written by hand. The evaluator that reads it is `rules_evaluator.py` at the
repo root.

IGNORE_INSPECTION and NOT_ELIGIBILITY rows are never mapped and never sent
to the model. `verification/test_rules_evaluator.py` fails if a deciding row
has no line, or if an ignored row has one.

**v3 changes** (round 24's flags, applied in the workbook):
- PRO-018 and SWY-018 are now INFO_ONLY, so they are no longer deciding rows.
- ALL-067 is now IGNORE_INSPECTION.
- PRO-038 is now a CONDITION on replaced plumbing. Its map line is NONE: the
  form does not ask whether the plumbing was replaced as a required update,
  so it is an "Also confirm" note.

**Liam's decisions, 2026-10-03:**
1. A row left open only because Coverage A or County is blank is a NOTE
   (the rule is shown, "confirm"), never a hold. The Sage county hold and
   the CHUBB Coverage A hold are separate pipeline checks and still fire.
2. CONDITION_STANDARD rows (54: roof in good condition, no debris, pool
   maintained, handrails...) are "Also confirm" notes, never a hold.

## Columns

| Column | Meaning |
|---|---|
| `row_id` | the workbook's Rule ID |
| `field` | the property_details key(s) that decide the row, `;`-separated, or `NONE` (the form has no field for it) |
| `test` | must be TRUE for the row to PASS. AMBIGUOUS rows give two readings separated by `\|\|` |
| `gate` | when the row applies (`always` if it always does) |
| `outcome_if_fail` | the row's effect (DECLINES / REFERS_TO_UW / CONDITION / UNKNOWN), or `NOTE` for EVALUATE_CURE_IS_INSPECTION rows |
| `open_fact` | the fact the form never asks, when the gate is a form field but the test is not |
| `map_note` | why: assumptions, ambiguities, cures |

## Grammar

```
expr       := or_expr
or_expr    := and_expr ("or" and_expr)*
and_expr   := atom ("and" atom)*
atom       := "always" | "not" atom | "(" or_expr ")" | FACT(<text>) | comparison
comparison := name ("==" | "!=" | "<" | "<=" | ">" | ">=") value
            | name ("in" | "not in") "{" v1, v2, ... "}"
            | name "between" lo "and" hi        (inclusive)
test       := expr ("||" expr)?                  (two readings: AMBIGUOUS)
```

The logic has three values: true, false and unknown.
- **Unknown values:** a blank optional field (County, Dwelling amount, ZIP,
  Dwelling type), PPC "N/A", plumbing "Unknown" or "Other", an unticked pool
  box (unchecked means unknown, never "no"), and `FACT(...)`.
- **Combining:** `and` is false if any part is false; `or` is true if any
  part is true; otherwise either is unknown.

Derived names:
- `home_age` = this year − `year_built`.
- `ppc_num`: the PPC number, with 8A/8B as 8 and 10W as 10.
- `sage_territory`: IN or OUT from `structured_rules.sage_county_in_territory`
  (round 19).

Each row gets one outcome:

| Outcome | When |
|---|---|
| SKIP | a topic the row needs is unchecked (round 21) |
| N/A | the gate is false |
| PASS | every reading is true. With an unknown gate, a test that passes still passes |
| FAIL | every reading is false and the gate is true |
| OPEN | any reading is unknown, the readings disagree (AMBIGUOUS), or the gate is unknown and the test does not pass |
| NOTE | an EVALUATE_CURE_IS_INSPECTION row that is FAIL or OPEN (its cure is an inspection, round 24 Part 1), or a row open only because Coverage A / County is blank (decision 1): reported, never a hold |
| NONE | the field is NONE: not decided by code |

**Carrier verdict:** any FAIL with effect DECLINES gives INELIGIBLE (flaws =
the number of such FAILs). Otherwise a FAIL REFERS_TO_UW gives REFER; then a
FAIL CONDITION gives REFER, with the condition named. Otherwise any OPEN
gives INSUFFICIENT_INFORMATION, with the open facts listed. Otherwise
ELIGIBLE. A FAIL whose effect is UNKNOWN counts as OPEN.

Every reason cites the row id, PDF page and quote. Those citations come from
the workbook, not from the model, so the pipeline's quote guard does not
apply to them. (23 rows FAIL the workbook's own app-text quote check for
documented reasons: Chubb / Sage tables stored as separate runs, and the
Swyfft ligatures of DD-5.)

## Guide words mapped to the form's options

| Guide word(s) | Form option(s) | How it is mapped |
|---|---|---|
| wood shingle, wood shake | Roof Type = Wood Shake | decided |
| slate | Roof Type = Slate | decided |
| tin, corrugated metal, copper (roof) | Roof Type = Metal | **AMBIGUOUS**: Metal may be steel |
| built-up tar and gravel, rubber membrane, rolled roofing | Roof Type = Flat/Built-Up | **AMBIGUOUS** |
| flat roof | Roof Shape = Flat, or Roof Type = Flat/Built-Up | decided; the material is a FACT |
| poured (reinforced) concrete flat roof | — | FACT (OPEN) |
| T-lock, asbestos, dome, green roof | — | NONE (not form options) |
| 3-tab vs architectural | Composition Shingle / Architectural Shingle | not used by a deciding row here; the Sage statement rows are inspections (Part 1) |
| galvanized, polybutylene | Plumbing = Galvanized / Polybutylene | decided |
| PEX installed before 2011 | Plumbing = PEX | decided if Year Built ≥ 2011 (original plumbing); otherwise **AMBIGUOUS** |
| cast iron, lead (plumbing) | — | not a form option (Unknown / Other are unknown) |
| copper tubing or PVC required | Plumbing = Copper / PVC (and PEX, read with PRO-039) | decided |
| mobile, manufactured | Construction = Manufactured/Mobile | decided; modular / kit / prefab are not options |
| single-family, townhouse unit, condominium | Dwelling Type = House / Townhome / Condo | decided |
| primary residence, owner-occupied | Occupancy = Owner Occupied | decided |
| seasonal / secondary | Occupancy = Seasonal or Secondary Home | decided |
| vacant / unoccupied | Occupancy = Vacant | decided |
| rental, tenant | Occupancy = Tenant Occupied | decided |
| LLC, business, corporation | Ownership = LLC | decided |
| trust | Ownership = Trust | decided; **AMBIGUOUS** where the guide bars a corporate or land trust (MER-005, PRO-012) |
| a listed dog breed | Aggressive Breed = Yes | **AMBIGUOUS** (the form's list is not the carrier's). "No" is read as PASS, although Allied, Mercury and Progressive list breeds the form's help text omits (e.g. Great Dane, Husky, Malamute, Bull Mastiff) |
| bite history, number of dogs | — | FACT, gated on Dogs = Yes |
| solar roof system / solar tiles / Tesla solar roof | Solar Panels = Yes | **AMBIGUOUS** (mounted panels vs an integrated roof) |
| protection class | PPC | decided; the FPC table rows need hydrant / station distance (FACT) |
| Coverage A amounts | Dwelling amount | decided; blank is unknown (OPEN) |
| county lists, 31 degrees N | County | decided; blank is unknown (OPEN) |
| Mercury's coastal ZIP lists | ZIP (not given in these profiles) | OPEN when the County is in the Tier II list |
| Chubb territories (Harris 1A/1B/1C/1E, 8-10) | — | FACT: the guide gives no ZIP or county split |
| within 1/2 mile / 1,000 ft of the coast, extreme hazard, base flood elevation | Coastal Tier = Tier 1 (the form says "within 1 mile of Gulf or bay waters") | gate only; the distance is a FACT |
| "roof older than 15 years" in a remaining-life rule | Roof Age | **assumption:** no covering on the form ends its life before 20 years, so a roof under 15 years cannot be within 5 years of its end (ALL-034, PRO-022). At 15 or more the rule is OPEN |

## Coverage

Deciding rows by how the map decides them (`python experiments/map_coverage.py`):

| Carrier | decided by a form field | gated-but-open | AMBIGUOUS | NONE | total |
|---|---|---|---|---|---|
| Allied Trust HO3 | 19 | 16 | 8 | 104 | 147 |
| Chubb HO | 6 | 8 | 0 | 58 | 72 |
| Mercury HO3 | 15 | 5 | 4 | 57 | 81 |
| Progressive HO3 | 8 | 9 | 4 | 75 | 96 |
| Sage Auros HO3 | 15 | 14 | 1 | 75 | 105 |
| Swyfft Benchmark (Admitted) HO3 | 9 | 2 | 2 | 27 | 40 |
| **all** | **72** | **54** | **19** | **396** | **541** |

(v3. The topic table below is round 24's v2 count, within one row of v3 per topic.)

| Topic | decided | gated-but-open | AMBIGUOUS | NONE |
|---|---|---|---|---|
| OTHER | 0 | 0 | 0 | 79 |
| OCCUPANCY | 17 | 8 | 0 | 30 |
| LOSS_HISTORY | 0 | 1 | 0 | 52 |
| LOCATION | 6 | 9 | 0 | 34 |
| ROOF_ELIG | 6 | 7 | 3 | 17 |
| DWELLING_LIMITS | 14 | 0 | 0 | 17 |
| CONSTRUCTION | 0 | 0 | 0 | 27 |
| OTHER_SYSTEMS | 0 | 1 | 0 | 23 |
| ANIMALS | 0 | 7 | 7 | 10 |
| DWELLING_TYPE | 7 | 2 | 0 | 12 |
| LIABILITY_HAZARDS | 0 | 0 | 0 | 18 |
| ELECTRICAL | 0 | 3 | 0 | 14 |
| OWNERSHIP | 6 | 1 | 2 | 7 |
| POOL | 8 | 1 | 0 | 6 |
| PROTECTION_CLASS | 2 | 7 | 0 | 6 |
| ACREAGE | 0 | 0 | 0 | 15 |
| PLUMBING | 6 | 0 | 4 | 1 |
| FOUNDATION | 0 | 0 | 0 | 10 |
| HOME_AGE | 0 | 6 | 0 | 3 |
| FLOOD | 0 | 1 | 0 | 7 |
| PRODUCT_STATUS | 1 | 0 | 0 | 7 |
| SOLAR | 0 | 0 | 3 | 0 |
| INSPECTIONS | 0 | 0 | 0 | 2 |
| ROOF_SETTLEMENT | 0 | 0 | 0 | 1 |

**396 of 541 deciding rows (73%) need facts the form never collects:** loss
history, wiring, heating, foundation, acreage, liability hazards, siding and
"other". Only 73 (13%) are decided outright by a form field.

## Values checked against the quotes

`map_coverage.py` lists every deciding row whose numeric Value does not
appear in its own quote: 35 rows. None of them turned out to be a wrong
number:
- Most follow the workbook's MAX convention: "3 or more claims in 3 years
  ineligible" is stored as MAX 2. Examples: ALL-142..152, CHU-062..074,
  MER-087..091, PRO-094.
- Some quotes write the number another way ("½ mile" for 0.5: ALL-118,
  MER-061, PRO-087).
- Some quotes are a fragment that leaves the number in the neighbouring
  text: ALL-029 (76 years), ALL-167, ALL-192, ALL-213, SAG-004, SAG-055 (4
  ft), CHU-101, CHU-104, MER-068 / MER-069 (the ZIP lists), PRO-058,
  PRO-111.

## Rows that look wrong (listed only; the workbook is not edited)

Round 24's list (PRO-018, SWY-018, PRO-038, ALL-067) was applied in v3.
Round 25 additions, if any, are in handoff.md.

## The Sage batch (round 27 step 5, 2026-10-06; Liam's decision 4)

`sage_batch_field_map.csv` has one line for each of the 564 deciding rows of
`carrier_rules_sage_batch_v1.csv` (SURE HO-3, SafePort HO-3, Wilshire HO3,
Trium Lloyd's HO3/HO5, Markel HO3 and Vave HO3; 1,033 rows, **not yet
reviewed**). `build_sage_batch_map.py` builds it with the same grammar. The
four guides that share the Auros layout share most of their lines (`sister()`
in the builder). The app reads none of it unless both
ELIGIBILITY_RULES_PILOT and ELIGIBILITY_RULES_SAGE_BATCH are "1".
`verification/test_sage_batch_rules.py` covers it.

| Carrier | decided by a form field | gated-but-open | AMBIGUOUS | same rule as another row | NONE | total |
|---|---|---|---|---|---|---|
| Sage SURE HO-3 | 18 | 18 | 1 | 3 | 77 | 117 |
| Sage SafePort HO-3 | 18 | 20 | 1 | 3 | 78 | 120 |
| Sage Wilshire HO3 | 13 | 11 | 0 | 2 | 69 | 95 |
| Sage Trium Lloyd's HO3/HO5 | 17 | 14 | 1 | 4 | 77 | 113 |
| Sage Markel HO3 | 4 | 1 | 0 | 1 | 55 | 61 |
| Sage Vave HO3 | 9 | 7 | 0 | 2 | 40 | 58 |
| **all** | **79** | **71** | **3** | **15** | **396** | **564** |

"Same rule as another row": the test is `always` and the note names the row
that decides it, so one fact fails one row. Examples: a 3-months-unoccupied
row next to the Vacant row; the East Texas county list next to the territory
row; a second mobile-home row; Vave's five LLC criteria under VAV-015.

**Choices that differ from the Auros lines:**
- **"Dwellings must be owner occupied"** lists primary AND seasonal or
  secondary residences beneath it, so the test is `occupancy_type != Tenant
  Occupied`. Vacant is decided by the guide's vacancy row.
- **Territory:** the south-of-31 / East Texas row tests `sage_territory == IN
  or county == Nueces`, and the guide's own Nueces row decides Nueces, so a
  Nueces home fails one row, not two. Trium's territory has no Nueces
  exception, so Trium has no Nueces row and Nueces passes.
- **Coverage A:** the TIV limits are NONE (TIV is not asked). The SURE and
  SafePort cap of $2,000,000 for FPC B or C risks is gated on the station
  distance and hydrant.
- **Coastal:** Wilshire's and Trium's Extreme Hazard rows are COVERAGE_ONLY
  (eligible with a deductible), so they are not deciding rows. Trium keeps
  one deciding coastal row: barrier islands without road access (TRI-100,
  gated on Tier 1).
- **The FPC table rows** are the Auros lines (SAG-073..078) on each guide's
  own row ids. Agreement with round 27 step 2's `sage_fpc_with_distance`:
  - Owner Occupied: every case of PPC 1-10 x 3 or 7 miles x hydrant
    Yes / No / Unknown x home age 16 or 36 agrees.
  - A known Seasonal or Tenant home in the seven-condition rows does not
    agree: the rows REFER it ("Primary occupancy only" fails, as SAG-075
    does), while step 2 holds it. This is a strict xfail.

**Auros lines found here, fixed in round 28 step 1 (pilot v4/v5, 2026-10-07):**
- **SAG-001** tested `occupancy_type == Owner Occupied`, which fails a seasonal
  or secondary home the guide accepts. It now tests `!= Tenant Occupied` (v4).
- **Vacant** failed SAG-001, SAG-002 and SAG-005. Now only SAG-005 fails;
  SAG-002 is "same rule as SAG-005".
- **SAG-081 / SAG-083** shared one test, so an out-of-territory county failed
  twice, and the round 19 county hold added a third flaw. Now:
  - SAG-081 tests `sage_territory == IN or county == Nueces`;
  - SAG-082 decides Nueces;
  - SAG-083 is "same rule as SAG-081";
  - the county hold leaves a known county to the territory row on every
    rules-table carrier.
- **v5 rows:** SAG-032 is now REFERS_TO_UW (the outcome is taken from the
  row's Effect). SAG-048 is a cure-is-inspection row; its line stays NONE,
  so it is an "Also confirm" note.

## Boundary tests (round 28 step 2, 2026-10-07)

`verification/test_map_boundaries.py` tests every map line with a numeric or
ordered test, in both maps: 93 lines. Each is tested just inside, just outside
and at the boundary written in its **plain rule** (never the Check type column).
A guard fails if a numeric line has no case.

**Wrong, and fixed:**
- **The seven-condition FPC rows:** SAG-078, SUR-116/117, SFP-124/125,
  WIL-121/122/123, TRI-019/020/035.
  - The gate `ppc 4-10 and (no hydrant or over 5 miles)` also took PPC 9-10
    over 5 miles. That is row C 9+ (declined by the FPC 9+ row), never
    these rows.
  - The gate is now `(ppc 4-8 and (no hydrant or over 5 miles)) or (ppc 9-10
    and no hydrant and 5 miles or less)`. A PPC 4-8 home with no hydrant
    still applies with the distance blank.
- **ALL-112** ("Protection classes 1-9 are eligible") failed class 10. That
  declined the new home in a protected subdivision that ALL-113's exception
  allows. Class 10 is now ALL-113's alone.

**Kept, with a note:** MER-078 and MER-081 are limits on Coverage A and C
combined. Coverage C is not asked, so A alone is tested: A over the limit
fails for certain, while A under it passes without knowing C.

**No numeric map test to check:** these numbers are inside FACT(...) lines
or NONE lines (the form does not ask them). Nothing here can carry a wrong
boundary until a form field exists:
- the metal roof gauge (SAG-033 and the batch's metal-roof rows, FACT);
- months unoccupied (SAG-002 and the batch's 3-months rows, "same rule as"
  the Vacant row);
- Vave's 20 rental weeks (NONE);
- loss counts (NONE);
- the shoreline distances (SUR-163, SFP-172 and the like, FACT).
