# Round 38 report (2026-10-11, written at 23:00 CT)

## Is main safe to push?

**Yes, on the zero-API evidence, with two caveats.**

**Fast tier on the final code (8f8b0f4; later commits are docs only),**
sharded four ways by test file, each shard in its own worktree with its
own copy of the store:
- shard 2: 1,227 passed, 0 failed;
- shard 3: 1,255 passed, 0 failed, 1 xfailed;
- shard 4: 1,255 passed, 0 failed, 1 xfailed;
- shard 1: rerun still running at 23:00. On 5596ca3 it had 1,248 passed, 0 failed, 8 xfailed, and its files don't touch what changed since. I'll update this line when it ends

The whole-suite runs:
- bccacc6 (Step 1): 4,432 passed, 0 failed.
- 9b0c4f5 (Step 3): 3 failed, the coverage counts, updated in 3d44949.
- 67053b5: stopped, with 17 failures that came from the harness leak
  fixed in 8f8b0f4. The fixture tests followed by the fallback tests,
  in that order: 50 passed, 1 xfailed.

**Caveats:**
1. **Tier 2 (live baseline) did not run, and live spend was $0.** The
   permission classifier blocked reading the API key. This round did
   not touch prompts, retrieval, ranking or bucket logic; it changed
   map lines and display.
2. **Some verdicts change on purpose** (listed below). The biggest is
   NatGen Custom360 DP3 on LANDLORD.


**Live changes after a push:**
- **Verdicts:**
  - LANDLORD's NatGen Custom360 DP3 goes Not eligible -> Eligible (NCD-150:
    a theft loss is a confirm).
  - A home with 1 water loss: Mercury HO3 Not eligible -> Eligible and
    Travelers HO3 Refer -> Eligible. With 1 theft loss: Mercury Not
    eligible -> Eligible. 55 loss rows decide only on count, type and
    years.
  - A Progressive HO3 / DP3 / HO6 home whose only electrical answer
    against it is "Federal Pacific or Zinsco panel" is no longer Not
    eligible; it gets a confirm (F15).
- **Cards and page:**
  - Held reasons name only what is open, never an entered distance (Step
    1, F14).
  - Confirm items and the top box are worded from the form's answers, and
    an answered topic is never asked again (Step 2).
  - A card doesn't repeat its column's status (Step 5).
  - Foremost's coastal decline reads plainly (Step 4).
  - Code-decided cards keep their deciding row and quote (F01).
  - Progressive HO6's row IDs no longer show (F08).
  - A landlord check's placement panel says it rests on homeowners sales
    (Step 6).
- **No new Railway variable.**
- I did not push.

## Steps 1-6

1. **Held reasons (bccacc6).** A reason names only what is still open, and
   the 5-mile rule only when the station distance is blank. On LANDLORD the
   three SageSure DP3 cards now ask for the hydrant and the table's
   visibility / alarm / access conditions, not the distance. Grid tested:
   distance blank / 4 / 7 × hydrant Yes / No / Unknown.
2. **Confirm items match the form (1fd172b).** Each topic records its form
   fields. An answered topic is worded from the answer, or dropped. The top
   box uses the reworded lines. 200 tests cover every topic × every answer
   for the nine topics.
3. **Loss rows (9b0c4f5).** NCD-150 declines only non-remediated losses,
   so a loss now gives a confirm. All 113 LOSS_HISTORY rows were audited
   and 55 changed (list below). Verdicts:
   - LANDLORD: NatGen Custom360 DP3 Not eligible -> Eligible.
   - LANDLORD with 1 water loss: no change.
   - A Harris home with 1 water loss: Mercury HO3 Not eligible ->
     Eligible; Travelers HO3 Refer -> Eligible.
   - The same home with 1 theft loss: Mercury HO3 Not eligible ->
     Eligible.
4. **Foremost coastal (447db86).** The decision is made in code (FOD-055,
   county in the 28-county list), not by the model. Harris is on the list.
   The guide is clear: p.20 "The following counties are entirely
   restricted", and the exception covers Choice Home, HOA, TDP1 and DF6,
   not TDP-3. So the decline stays. Its reason no longer says "appears to
   be", and the row is now RULE. The verdict follows the county, never
   Tier 1/2; Katy is also outside TWIA's area.
5. **Duplicate Insufficient header (03549d2).** No summary list or empty
   card renders above the section. The repeat was each open card's bold
   "**Insufficient information** —" first line. A card no longer repeats
   its column's status.
6. **Placement panel (64fe93c).** The tables are homeowners only: LOB HOME,
   no HO4/HO6, no tenant-occupied homes. That is 14,398 policies through
   2026-10, and 0 DP policies by construction. A Tenant / Vacant check now
   says "Based on our homeowners placements; we don't have enough landlord
   history yet." There is no DP count in any local file: the HawkSoft mix
   report lists DFIRE as "Not counted". Whether we have ~300 DP policies
   in 36 months needs a counts-only pass at the next monthly refresh.

### Step 2: LANDLORD before -> after (zero API)

Top box:
- before: "Owned by individuals (not an LLC, corporation, trust or estate)
  and titled to the applicant? — asked by 6 of 7 carriers"
- after: "LLC: titled to the LLC, and the LLC only holds rental property (no
  other business)? — asked by 7 of 8 carriers"

The other seven lines are unchanged. 8 carriers are Eligible / Refer now,
because NatGen Custom360 is Eligible after Step 3.

Steadily (DP3) card:

| before | after |
|---|---|
| Any losses or claims in the last 5 years? (how many, what type, when) | Loss entered: 1 theft (2022). Confirm it was paid and fully repaired, and there are no open claims. |
| Roof in good condition, no visible damage, one layer, enough life left? | Roof in good condition, no visible damage, one layer? |
| Occupancy: no short-term rental, roomers, students or vacancy? | Tenant occupied: a long-term lease (no short-term rental, roomers or students)? |
| Owned by individuals (not an LLC, corporation, trust or estate) and titled to the applicant? | LLC: titled to the LLC, and the LLC only holds rental property (no other business)? |
| Plumbing: material and condition as the guide requires (no polybutylene, no leaks)? | Plumbing (PVC entered): in good condition, no leaks? |

Electrical stays as it was: LANDLORD left that question blank.

### Step 3: the 55 rows changed

ALL-146 ALL-147 ALL-151 ARA-065 ARA-066 ARA-067 ARB-068 ARB-069 ARB-070
CDP-099 CDP-100 CDP-102 CHO-031 CHU-063 CHU-073 FDP-084 FOD-035 FOD-036
FOR-106 FOR-107 FOR-121 MER-087 MER-088 MKL-104 NCD-145 NCD-146 NCD-150
ODP-126 SAG-112 SBS-050 SDP-063 SFP-088 SFP-089 SLL-071 STD-141 STD-142
STD-143 STD-144 STD-145 STD-146 STD-154 STD-155 STD-156 STO-053 SUR-083
SUR-084 TRI-129 TRI-130 TRV-012 TRV-063 TRV-066 VAV-090 VDP-052 WIL-089
WIL-090

The other 58 LOSS_HISTORY rows were already right (count, type and years
only, or already a confirm), per the four readers and review.py.

## Step 7: the self-audit (18:30-23:00, zero API)

**Profiles run:** 3,040+ (still running at 23:00), over five batches (seeds 0-599, 1000-1980,
5000-5778, 9000-9366 and 12000+), with 0 crashes. Each profile runs the
real pipeline (rules pilot + three batches + placement) with a fake model.
Checks 2-4 compared something on 92-100% of profiles. Each of the eleven
checks is shown a page it must reject (test_fuzz_fixtures).

**Spend: $0.** The live sample (7c) did not run: the permission classifier
blocked reading the API key in the worktree .env (F04). I did not work
around it.

**Second readers:** five hours, 50 random Not eligible / Refer verdicts read against the guide PDFs. 46
supported, 2 wrong (F06, F18), 2 unclear (F11; Progressive HO3's bundled membrane answer, in F17).

**Findings by class** (verification/fuzz/findings.jsonl, F01-F19):

| class | fixed | for Liam |
|---|---|---|
| display / wording | F01, F08, F14 | F12 |
| map line | F15 (changes verdicts) | — |
| verdict | — | F06, F10, F11, F13, F17, F18, F19 |
| citation / missing confirm | — | F07, F16 |
| hold logic | — | F09 |
| harness false positive | F02, F03, F05 | — |
| blocked | — | F04 (live sample) |

Fixed (each with a fixture or a test):
- **F01:** a code-decided card lost its deciding row and quote. 70 of the
  first 284 profiles hit it (TWICO, Mercury, Swyfft, Centauri).
- **F08:** Progressive HO6's PH6-NNN row IDs showed raw on cards (20% of
  profiles).
- **F14:** a held reason asked for an entered station distance when the
  PPC was the open fact (4 Sage fire tables).
- **F15:** Progressive HO3 / DP3 / HO6 declined on the combined "Federal
  Pacific or Zinsco panel" answer, though they name Federal Pacific only.
  That answer is now a confirm. **Verdict change.**

**For Liam** (unfixed; each needs a decision):
1. **F10 (flat roof, CDP-023 / PDP-099).** Round 14's code check declines
   a flat roof with a shingle, tile or metal covering. Round 35's map line
   makes it a confirm. Centauri therefore declines with no row or quote,
   and Progressive DP3 confirms the same answers. Which reading? (The fix
   was tried and reverted; strict xfails pin it.)
2. **F18 (Chubb CHU-012).** A Hip roof with a built-up covering is
   declined as "flat": the shared FLAT gate treats built-up or membrane as
   flat whatever the shape. Should the shape answer win?
3. **F06 (Centauri DP3 CDP-053).** An unfenced pool refers, but the guide
   lists unprotected pools as Ineligible. CONDITION rows that say
   "ineligible" (also FOR-062, SLL-007, VDP-042) show "refers to
   underwriting: ... ineligible".
4. **F17 (bundled answers, as F15).** "Corporation / partnership" fails
   MER-005, which names no partnership. "Metal: corrugated / exposed-
   fastener / tin / aluminum panels" fails PRO-024, which names tin and
   corrugated only.
5. **F13 / F19 (estate and trust ownership).** Sage Trium / Wilshire read
   an estate as "non-individual". Progressive declines a business trust
   where its guide refers trusts.
6. **F11 (Liberty HO3).** p.8 rules the card never raises: "wind hazard
   area" (undefined), an estate owner, and Coverage A over $1M at PC10.
7. **F12 (wording, 5 of 40 verdicts).** A decline's reason is the rule
   and never names the answer that fails it (e.g. Wheeler County, Estate,
   wood shake).
8. **F07 (Chubb citation, 3 repros).** CHU-004 always cites p.10 (DFW /
   Northern). Cameron, Montgomery and Duval use the p.11 / p.12 tables
   (county lists on p.14). The fix needs the county threaded into the
   citation.
9. **F09.** hold_guard.ROW_ID doesn't know PH6-NNN; it decides holds.
10. **F16.** Confirms the cards could add: HOAIC's 50-year updates,
    Swyfft's loss type, Liberty's trust rule, NatGen Premier's citation
    page.
11. **F04.** Allow, or run yourself, a live sample: `verification/fuzz`
    has no live mode yet; landlord.py --live is the existing route.
12. **Step 3 judgment calls** (from the loss audit):
    - VAV-089/090 treat wind/hail as CAT;
    - ARI "All Other Losses" vs Act of Nature (ARA-066/067, ARB-069/070
      confirm on wind/hail);
    - CHU-073's 3-year table is now confirm-only;
    - FOR-121 "loss severity".

**Map lines never reached / never failing:** all 832 deciding lines were
reached. 233-283 decline/refer lines never failed in a batch. Most carry a
FACT() escape by design (they give confirms). 18 have no FACT:
- dead lines: FOR-087 is never evaluated on a vacant home; ALL-112 is
  PPC 1-10;
- generator gaps: Coverage A caps of $4-5M (PDP-007, SDP-069, FDP-093,
  SUR-090, SFP-095), as the generator tops out at $3M;
- cure rows (TRV-046, roof over 25 years: a questionnaire, so a note);
- pool-fence lines that need a fenced in-ground pool with an unticked
  4-ft box (SUR-061, SFP-060, TRI-068).

**Slowest checks** (six profiles, alone): answer-no-hold median 12.3 s
(max 34.6 s), unticked = blank 11.7 s, determinism 5.2 s, one pipeline
run 3.5 s, monotonic 2.6 s; the page checks run in under 0.1 s. Under
load a profile took a median of 25-53 s, and 1,200-1,300 s at worst while
the fast tiers and test runs shared the CPU.

## Commits (a1289fc..HEAD, not pushed)

```
bccacc6 Round 38 step 1: held reasons name only what is still open
9b0c4f5 Round 38 step 3: loss rows decide only on what the form can settle
447db86 Round 38 step 4: Foremost TDP-3 coastal decline in plain words
03549d2 Round 38 step 5: a card does not repeat its column's status
64fe93c Round 38 step 6: the placement panel says it rests on homeowners sales
1fd172b Round 38 step 2: confirm items are worded from the form's answers
654291a Round 38 step 7: the randomized self-audit harness (verification/fuzz/)
9c31e94 Round 38 step 7 fix F01: a code-decided card keeps the table's deciding row
c9da05e Round 38 step 7: checkpoint 1 in handoff.md; the runner records which checks compared
f552c79 Round 38 step 5 follow-up: dated expectation update in test_readable_reasons
7327341 Round 38 step 7 fix F08: Progressive HO6's PH6 row IDs are hidden from agents
3d44949 Round 38 step 3 follow-up: dated coverage-count updates
237dfe4 Round 38 step 7 fix F10: a flat roof is poured concrete only as "Other"
0cc8857 Round 38 step 7: check 11 (held reasons never ask for an answered field); hour-2 findings
4f4151f Round 38 step 7: checkpoint 2 in handoff.md (docs only; Tier 2 not run)
67053b5 Round 38 step 7 fix F14: a held reason names the open PPC, not an entered distance
ccc0e18 Round 38 step 7 fix F15: Progressive's Federal Pacific rows confirm on the combined panel answer
87d3f01 Round 38 step 7: checkpoint 3 in handoff.md; F14 reaches four Sage fire tables (docs only; Tier 2 not run)
5596ca3 Round 38 step 7: F17 (Mercury MER-005 and the bundled Corporation / partnership answer) for Liam (docs only; Tier 2 not run)
d157deb Round 38 step 7: revert F10's map lines; the flat-roof question goes to Liam
8f8b0f4 Round 38 step 7: the self-audit harness no longer configures itself on import
83d678d Round 38 step 7: checkpoint 4 in handoff.md (docs only; Tier 2 not run)
<this report and the final checkpoint>
```
