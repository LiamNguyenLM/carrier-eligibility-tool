# Topic inventory (round 21, 2026-10-02)

This is every place a property fact reaches the model or a deterministic
rule, with the topic that switches it. The source of truth is `topics.py`
(`STEPS`, `CORE_STEPS`, `ALWAYS_ON_STEPS`). `TestTopicRegistry` fails the
build if a guaranteed lookup, an override branch, or a post-parse check is
added without a tag.

**Mode.** A step marked **all** is a rule: it runs only when every listed
topic is checked (Liam: a rule needing an unchecked topic is skipped). A
step marked **any** is retrieval: it runs when any listed topic is checked,
because it only puts guide text in front of the model.

## PROPERTY DETAILS lines (`_property_details_text`)

| Line | Topic |
|---|---|
| State: TX | always |
| Year Built, Home Age | home_age |
| Roof Age | roof_age |
| Roof Type | roof_type |
| Roof Shape | roof_shape |
| Construction Type | construction |
| Plumbing Type | plumbing |
| Occupancy Type | always (occupancy) |
| Ownership Structure | always (ownership) |
| Coastal Tier | coastal |
| Swimming Pool, Pool Accessories, Pool Fence Height, Pool Gate | pool |
| Dogs on Premises, Aggressive Breed Dogs | dogs |
| Solar Panels | solar |
| PPC Number | ppc |
| County | county |
| Dwelling Amount (Coverage A) | dwelling_amount |
| Dwelling Type | always (dwelling_type) |

## Retrieval

| Step | What it does | Topic(s) | Mode |
|---|---|---|---|
| `build_retrieval_query` | one line per fact: year built/home age, roof age, roof type, roof shape, construction, plumbing, coastal, pool and accessories, dogs and breed, solar, PPC | that fact's topic | any |
| `build_retrieval_query` | occupancy / ownership lines | always | – |
| `build_risk_factors` | galvanized/polybutylene plumbing | plumbing | any |
| `build_risk_factors` | unfenced pool; diving board/slide; pool type | pool | any |
| `build_risk_factors` | coastal tier wind pool zone | coastal | any |
| `build_risk_factors` | aggressive breed | dogs | any |
| `build_risk_factors` | PPC fire district | ppc | any |
| `build_risk_factors` | "<roof type> roof <age> years old" (an unchecked part is dropped) | roof_age, roof_type | any |
| `build_risk_factors` | solar panels roof | solar | any |
| `build_risk_factors` | LLC / Trust / tenant terms | always | – |
| `guarantee:ppc` | PPC guaranteed lookup (2/carrier) | ppc | any |
| `guarantee:pool` | pool lookup (3/carrier), which also builds `pool_specs` | pool | any |
| `guarantee:solar` | solar lookup (2/carrier), which also builds `solar_classes` | solar | any |
| `guarantee:roof_shape` | restricted roof shape lookup (2/carrier) | roof_shape | any |
| `guarantee:roof_life` | roof life-expectancy lookup (3/carrier) | roof_age, roof_type | any |
| `guarantee:occupancy` | occupancy / Trust / LLC lookup (Trust and LLC only) | always | – |
| `guarantee:coverage_a` | Coverage A limit lookup (1/carrier, only when an amount is filled) | dwelling_amount | any |
| per-carrier similarity search | the main query above | (its lines are gated) | – |

## Routing (always on)

| Step | Topic |
|---|---|
| `get_carriers_for_occupancy` and the HO/DP filter after parsing | occupancy |
| House drops the condo (HO6) programs | dwelling_type |

## Post-parse checks and overrides

| Step | What it does | Topic(s) | Mode |
|---|---|---|---|
| `_strip_contradicted_property_claims` `guard:solar_panels` | removes "has solar" claims when the intake says No | solar | all |
| `guard:swimming_pool` | removes "has a pool" claims when the intake says No Pool | pool | all |
| `guard:aggressive_breed` | removes "has an aggressive breed" claims when the intake says No | dogs | all |
| `_strip_misattributed_citations` | removes another carrier's citations | core | – |
| `override:_SAGE_FPC_CARRIERS` | Sage FPC table: ELIGIBLE upgrade, or fire-station distance item plus `_hold_for_unresolved_topic("fpc")` | ppc | all |
| `override:_MERCURY_CARRIERS` | Mercury roof age x type table | roof_age, roof_type | all |
| `override:_SAGE_MARKEL_CARRIERS` | Markel roof exclusion form | roof_age, roof_type | all |
| `override:_SWYFFT_MAX30_CARRIERS` | Swyfft 30-year roof maximum | roof_age | all |
| `override:_TWICO_CARRIERS` | TWICO settlement table, 3-tab vs architectural sub-type, `_hold_for_unresolved_topic("roof")` | roof_age, roof_type | all |
| `override:_SAGE_ROOFER_STATEMENT_CARRIERS` | Sage roofer's statement (sub-type / required / not required), `_hold_for_unresolved_topic("roof")` | roof_age, roof_type | all |
| `override:_CENTAURI_DP3_CARRIERS` | Centauri flat roof unless poured concrete | roof_shape, roof_type | all |
| `check:_enforce_pool_spec_support` | pool spec item, the Round 20 boxes, `_drop_manufactured_pool_questions` | pool | all |
| `check:_note_solar_roofing_does_not_apply` | mounted panels vs integrated solar roofing note | solar | all |
| `_strip_inspection_requests` | Round 20 inspection strip | core | – |
| `_strip_unchecked_topics` | the selection strip (Step 2e) | core | – |
| `check:_apply_location_holds` | Sage county hold / out-of-territory INELIGIBLE | county | all |
| `check:_apply_chubb_hold` | CHUBB Coverage A hold and under-$1M REFER | dwelling_amount | all |
| `_add_fixed_rows` | GUIDE_UNAVAILABLE / NOT_EVALUATED / UNRECOGNISED rows | core | – |

## Rules that need two topics

Liam's rule is that unchecked means not considered, so these run only when
both topics are checked: Mercury, Markel, TWICO and the Sage roofer's
statement (roof age and roof type), and Centauri flat roof (roof shape and
roof type).

**How that reads for an agent who ticks Roof age but not Roof type:**
- Only Swyfft's 30-year maximum still runs deterministically.
- The prompt states the roof age and says roof type is not being checked.
- The guaranteed roof life-expectancy chunks still reach the model. Most of
  those are age-by-type tables, so the model may answer "depends on roof
  type".
- The selection strip removes a missing_info item that only matches
  roof-type words. It keeps an item that also matches roof-age words, such
  as "roof type needed to apply the age table for a 10-year-old roof",
  because roof age is checked.
- So a roof-age-only check can still come back INSUFFICIENT asking for the
  roof type. That is the honest reading of an age-by-type table. Step 4
  measures how often it happens.
