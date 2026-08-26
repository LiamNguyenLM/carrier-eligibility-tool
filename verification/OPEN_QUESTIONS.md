# Open Questions — unresolved findings, deliberately NOT closed

Findings that are real, reproduced-as-reported by a human, but whose root
cause is not established. Each one stays here until it either recurs (which
is the strongest evidence for whichever hypothesis is right) or is
positively explained. Do not delete an entry just because a later round
didn't see it — that is exactly the reasoning that lost the round 13 Swyfft
"regression" a week of confusion.

---

## OQ-1 — Fabricated solar panels on a DP3 run (round 14, OPEN)

**Status:** unexplained. A deterministic backstop is shipped, so production
is protected regardless, but the mechanism is not known.

### What was observed (once, by hand)

Manual DP3 audit, 2026-08-25. Profile: PPC 8A, Coastal Tier 2, Tenant
Occupied, built 1982, roof 25yr Composition Shingle, Masonry Veneer, Copper,
Flat roof, No Pool, **Solar Panels: No**.

In ONE execution, 7 of ~12 carriers reasoned from solar panels being
present — Foremost DP3, Sage-Markel DP3, NatGen Premier OneChoice DP3,
NatGen Custom360 DP3, Progressive DP3, Sage-Occidental DP3, Steadily DP3.
NatGen Premier OneChoice DP3 was marked **INELIGIBLE solely on it**: "The
carrier's flat exclusion of solar panels makes this property ineligible
regardless of other factors."

Live commit at the time: `4421414`. Railway deployment id
`44709a48-f9d3-409d-b78e-634bb919707f`.

### What was ruled OUT

| Hypothesis | Verdict | Evidence |
|---|---|---|
| Intake serialization bug | **Ruled out** | `app.py` maps the toggle correctly (`"Yes" if solar_panels else "No"`); the built prompt reads `Solar Panels: No`. |
| Carrier documents supplying it | **Ruled out** | Only 2 "solar" occurrences reach the DP3 prompt, both ARI's *fuel-source* rule ("Kerosene, coal, wood or solar as a source of fuel"). |
| A version gap (audit ran different code) | **Ruled out** | `SYSTEM_INSTRUCTIONS` is byte-identical between `15b141d` and `4421414`. |
| Stale prompt surviving a deploy via Streamlit cache | **Ruled out from code** | The three `@st.cache_resource` functions cache the embedding model, the Chroma store and the retriever. None holds prompt text. `SYSTEM_INSTRUCTIONS` is a module-level constant re-evaluated on import, so any process — new or surviving — serves its own commit's text, and that text is identical across both candidate commits. |
| Reproducible at a per-carrier rate | **Ruled out** | 12-run sweep of the exact profile on the exact code: **0 solar mentions across 151 carrier-records**. Not even neutral ones. |

### What is still OPEN

1. **Deploy timing.** Whether the audit landed between "push" and "actually
   serving" for deployment `44709a48-...`, i.e. hit a half-updated state.
   *Not checkable from this environment* — no Railway CLI, no railway config
   files, no `RAILWAY_*` env vars. Someone with Railway console access
   should compare the deployment's build-finished / started-serving
   timestamps against the audit time. Note the prompt-staleness half of this
   is already ruled out above, so this only matters for some other
   difference between the two builds.

2. **Execution-scoped bleed** — currently the best-supported hypothesis.

### Why bleed is the leading hypothesis

`check_eligibility()` makes **ONE** `client.messages.create` call containing
every carrier, and asks for a single JSON array covering all of them. The
model therefore generates carriers sequentially in one completion, attending
to its own earlier output. Cross-carrier bleed inside that shared context is
not speculative here — this project has documented it twice already: the ARI
HOA+/HOB age-cap citation bleed and the Sage "Classification A/B/C" bleed.

The decisive evidence is which carriers were hit:

```
 #  carrier                                    audit-affected   solar chunks in its OWN doc
 1  ARI_(HOA+)                                        -              1
 2  ARI_(HOB)                                         -              1
 4  Centauri_-_DP3                                    -              0
 5  Foremost_DP3_and_HO3                            YES              4
 8  NatGen_Custom360_DP3                            YES              0   <-- no solar text at all
 9  NatGen_Premier_OneChoice_DP3                    YES              1
10  Progressive_DP3                                 YES              1
11  Sage_-_Markel_DP3                               YES              0   <-- no solar text at all
12  Sage_-_Occidental_DP3                           YES              0   <-- no solar text at all
18  Steadily_DP3                                    YES              2
```

**Three of the seven affected carriers have ZERO solar text in their own
documents.** They cannot have derived "solar panels are present" from
retrieval. It had to come from shared context. Meanwhile ARI (HOA+/HOB) DO
carry solar text and were NOT affected — and they are generated first.
Affected positions form a contiguous block (8–12) plus 5 and 18, with
Foremost (position 5, the richest solar text at 4 chunks) a plausible
origin.

### Why 0/151 and 7/12 are NOT actually contradictory

They conflict only under a per-carrier model. Under a per-execution model
they are entirely compatible:

```
MODEL A -- independent per-carrier rate p
  audit 7/12 implies p ~ 0.58
  P(0 of 151 carrier-records | p=0.58) = 3.9e-58     <- irreconcilable

MODEL B -- per-EXECUTION contamination event, rate q
  P(0 of 12 runs | q=0.05) = 54%
  P(0 of 12 runs | q=0.10) = 28%
  P(0 of 12 runs | q=0.20) =  7%
  95% upper bound given 0/12:  q <= 22%
```

Any per-execution rate up to ~22% is consistent with seeing zero in 12 runs
while still producing the audit's one contaminated run. So the sweep does
**not** refute the report; it bounds how often it happens.

### What ships regardless

`_strip_contradicted_property_claims()` in `eligibility_check.py` — a
deterministic backstop that removes claims contradicting the intake and
undoes any adverse verdict resting solely on one. It is mechanically
decidable (the intake value is known), so it corrects this failure shape
whatever the cause. Covers solar, pool and aggressive breed.

The prompt defect found along the way is fixed too, and was real on its own
terms: the cached system block asserted `The customer's "Solar Panels: Yes"
in PROPERTY DETAILS ...` on every call regardless of intake. It is now a
two-branch conditional. **It is not established to be the cause** — do not
let a later reader assume it was.

### Round 15: the isolation experiment ran, and was UNDERPOWERED

Both arms, identical code, same profile, same 18-carrier detection surface:

```
COMBINED (shared context)   :  0/20 executions contaminated
ISOLATED (one call/carrier) :  0/20 executions contaminated   (360 isolated calls)
```

**This does not support the bleed hypothesis, and must not be read as
though it does.** The arm that is *supposed* to be susceptible produced
nothing either, so 0/20 vs 0/20 cannot distinguish anything. A clean
isolated arm is exactly what a clean combined arm would also produce.

Pooling every combined-mode execution on round 14+ code (20 here + the
12-run post-fix DP3 sweep) gives **0/32**, which bounds the per-execution
rate at **q <= 8.9%** (95%). What it would take to see even one contaminated
combined execution with 95% probability:

```
  q = 8.9%  ->  ~32 executions      (already done, saw none -- so q is likely well below)
  q = 5.0%  ->  ~58 executions
  q = 2.0%  ->  ~148 executions
  q = 1.0%  ->  ~298 executions
```

At ~2 min per combined execution that is 5-10 hours of API time for a
result that, if null, still would not prove absence. **Reproduction by
sampling is not a viable route to closing OQ-1.** Stop spending on it.

Also worth recording: across all of these runs the model said *nothing at
all* about solar on this profile -- not even neutral mentions. So there is
no graded signal to measure either; an ablation design (compare runs with
and without the solar-rich carrier present, and watch whether zero-solar
carriers drift) has nothing to work with on this profile. That route is
closed too.

### The route that IS open: instrument the guard

`_strip_contradicted_property_claims()` fires *exactly* when this failure
occurs, and round 15 made it print to stdout:

```
INTAKE CONTRADICTION [OQ-1]: carrier=... field='solar_panels' intake_value='No' removed=1 status_was='INELIGIBLE'
```

That lands in the Railway logs, so a recurrence is now detectable without
anyone noticing a note in the UI. **If that line ever appears in
production, capture the full raw response** -- the affected carrier list and
whether it forms a forward-contiguous block is the bleed signature, and one
real occurrence is worth more than another 300 sampled runs.

### What would settle it

- **If it recurs**: capture the FULL raw response, not a summary, and note
  whether the affected carriers again form a forward-contiguous block and
  again include carriers with no solar text of their own. That is the
  bleed signature.
- ~~Split the completion with `carrier_subset=`~~ -- **done in round 15,
  underpowered, see above.** Still the right test if a way is found to make
  contamination occur on demand; it just cannot be run against a <=8.9%
  spontaneous rate at feasible n.
- ~~A large sweep~~ -- **not viable**, see the power table above.
- **The live guard log is now the primary detector.** One instrumented
  recurrence beats any amount of further sampling.

### One recurrence kills the theory

If contamination is ever observed in ISOLATED mode, the bleed hypothesis is
wrong or incomplete and OQ-1 goes back to fully unexplained -- regardless of
how many clean isolated runs preceded it. Round 15's 0/20 isolated buys no
credit against that.
