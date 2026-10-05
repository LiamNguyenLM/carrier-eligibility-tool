# Rule field map (round 24 Part 2, 2026-10-02; updated for v3 in round 25, 2026-10-04)

`rule_field_map.csv` has one line per **deciding** row of
`carrier_rules_pilot_v3.csv` (pilot workbook version 3), i.e. rows whose
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
