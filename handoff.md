# Carrier Eligibility Tool — Handoff Notes

Written for a fresh Claude Code session picking this up. Read this before making changes — several of these fixes were built specifically in response to real bugs found by two rounds of an external accuracy audit, and re-reverting them will reintroduce known problems.

## What this project is

A Streamlit RAG app for an independent Texas insurance agency (CFIG). Takes a customer property profile, checks it against ~40 carrier underwriting PDFs, returns per-carrier eligibility (ELIGIBLE / INELIGIBLE / REFER (one issue) / INSUFFICIENT_INFORMATION) with citations. Stack: Streamlit + LangChain + ChromaDB (pinned to **1.5.9** — do not let this drift, see below) + FastEmbed (bge-small) + Claude Sonnet. Deployed on Railway.

## Files and what each does

- `app.py` — Streamlit UI, login, tabs
- `pdf_extraction.py` — table-aware PDF extraction (pdfplumber) + `chunk_documents()`, the atomic/row-split table chunking logic
- `upload_carrier.py` — in-app single-carrier upload (Manage Carriers tab)
- `load_docs.py` — bulk local rebuild script, run this + reseed process when carrier PDFs change
- `eligibility_check.py` — the core RAG query + prompt + Claude API call
- `shared_resources.py` — Chroma/embeddings singletons
- `compare_extraction.py` — local diff tool, old (PyPDFLoader) vs new (pdfplumber) extraction on a given PDF
- `verification/test_eligibility_matrix.py` — runs 12 property-profile test cases through `check_eligibility()` directly
- `verification/verify_citations.py` — automated hallucination check: verifies every citation string actually appears in the source PDF
- `verification/diagnose_carrier.py` — shows exactly what gets retrieved for one carrier + whether `is_eligibility_content()` filtered any of it out. Use this before assuming a carrier's wrong result needs a new audit round.
- `seed_db.sh` + `Procfile` — Railway startup: seeds the persistent volume from `carrier_docs_db_seed/` (committed to git, de-LFS'd) on first boot only
- `.gitattributes` — forces LF line endings on `.sh` files (Windows/Linux container gotcha), explicitly NOT using LFS for the seed database (see git history — LFS caused real pain, was deliberately removed)

## Fixes already applied (don't re-break these)

1. **pdfplumber table-aware extraction** replacing PyPDFLoader — tables render as Markdown grids instead of flattened word-soup.
2. **Row-group table chunking** (`chunk_documents()` in `pdf_extraction.py`) — tables over ~1800 chars split by row group (header repeated in each piece), never mid-row. Small tables stay atomic. This was a second-generation fix; the first version (keep ALL tables atomic regardless of size) caused a different problem — oversized tables risked exceeding the embedding model's effective window.
3. **Anthropic prompt caching** — static instructions moved to a `system` block with `cache_control`. Caveat: may be under Anthropic's minimum cacheable token threshold at its current size — verify via the `Cache: read=... created=...` print statement in the logs.
4. **chromadb pinned to 1.5.9** in `requirements.txt` — matches the local dev environment. An unpinned install on Railway previously pulled a different version and crashed with `AttributeError: 'RustBindingsAPI' object has no attribute 'bindings'`.
5. **Home age computed in Python**, not left to the model to infer — was previously off by one year (model assumed the wrong current year).
6. **Foremost DP3/HO3 combined-name bug** — a carrier whose filename bundles two programs (e.g. `Foremost_DP3_and_HO3_-_07.01.2026.pdf`) was being wrongly excluded entirely for owner-occupied customers by a naive `"DP3" in name` check. Fixed in two places: the pre-filter (`get_carriers_for_occupancy`, using the reliable raw metadata name) AND the post-JSON filter (which needed a *second*, different fix — the model's own restated carrier name can drop a token from an ambiguous combined name, so that filter now trusts a fuzzy match against known combined-program carriers before applying the DP3/HO3 heuristic).
7. **Carrier safety net** — carriers that exist in the database and pass the occupancy filter, but get zero retrieved chunks, are now explicitly listed in the prompt so the model reports `INSUFFICIENT_INFORMATION` instead of silently omitting them entirely.
8. **PPC/Protection-Class risk-factor retrieval trigger** — added because PPC had *zero* dedicated retrieval boost despite being flagged across two audit rounds as the highest-value miss (SafePort, Trium, Auros, Occidental, SURE, Wilshire, Swyfft Lloyd's all either fabricated a rule or silently dropped the PPC question).
9. **`temperature=0`** on the Claude API call — added because apparent "regressions" between audit rounds (NatGen Premier OneChoice, TWICO) couldn't be reliably distinguished from ordinary sampling variance without it.

## Known unresolved issues — pick up here

- **Allied Trust HO3** returns "only a table header" despite having 117 real chunks in the database. Not a missing-carrier problem — a live retrieval-relevance mystery. Run `verification/diagnose_carrier.py` against it before guessing further.
- **Swyfft docs (all 4: Benchmark Admitted/Surplus, Lloyds Surplus, Topa Surplus)** — every table in every one of these fails to row-split ("could not be usefully row-split"). Also throws `Could not get FontBBox from font descriptor` pdfplumber warnings. Likely a dense one-page "quick reference card" layout where pdfplumber detects very few actual rows. Not yet root-caused with the actual PDF content in hand.
- **Cross-contamination bug**: Sage Occidental cited a sentence that only exists in a different carrier's PDF. Likely an LLM attribution error from cramming ~24 carriers into one combined prompt/response, not a retrieval or metadata bug (no evidence found of an ingestion-side mixup). Possible real fix: split eligibility checks into smaller per-carrier-group API calls — real cost/latency trade-off, wanted to discuss before building.
- **Centauri HO3** — scanned/image PDF, 0 pages/chunks extracted (pdfplumber can't OCR). Needs either an OCR preprocessing step or manual re-typing as an eligibility-notes text file. Not fixed, by design (needs a decision, not a quick patch).
- **PPC fix (#8 above) not yet verified against a real audit round** — was built and unit-tested in isolation, but the actual end-to-end effect on Swyfft Lloyd's / the Sage family hasn't been confirmed with real data yet.

## Product decisions (dated)

- **2026-09-28 — The occupancy/ownership guarantee runs for Trust and LLC
  properties only (Liam).**
  - **Why.** Across the round-17 verdict diff (main 72e34db vs the guarantee,
    4 profiles × 3 runs) it made no individual-owner verdict better. It made
    three worse in 3 of 3 runs: ALT CHUBB, ALT HOAIC and COASTAL ARI (HOA+).
    CHUBB's was caused directly by the guarantee, which pulled in its
    "VIII. Tiering Guidelines" section. It also cost about 2 cents a check
    (+5.2K–6.6K input tokens).
  - **The trade.** Individual owners give up 19 better citations, for zero
    extra cost and zero new regressions.
  - **Verified.** Their captured request is byte-identical to 72e34db's on
    STANDARD, ALT, COASTAL_PPC4 and OWNERSHIP_BASE.
  - **Also given up.** CHUBB's clause 2 no longer reaches their prompt, so
    main's rate of inventing a dwelling type (3 of 20 runs) returns for
    them. It is tracked as an xfail.
  - **Next.** The guarantee is switched on for second homes after the Luna
    cutover, and the tier/pricing-section exclusion stays in place for
    Trust and LLC.

- **2026-09-29 — Ship a PROTOTYPE on gpt-6-luna, both surfaces, for internal
  testing only (Liam). Jonathan has not cleared this for agents.**
  - **What changed.** `eligibility_check.ELIGIBILITY_MODEL` and
    `chat.CHAT_MODEL` both default to `gpt-6-luna` now (previously
    `claude-sonnet-4-5`). Each model call goes through one dispatch function
    (`_complete()`), so reverting either surface to Sonnet is one env var.
  - **The chat tab's confidentiality GATE is removed** (Liam's decision,
    carried over from the earlier Luna plan). It used to skip a golden test
    case when `CHAT_MODEL` was a third-party provider and the case would
    send a guide that restricts its own redistribution.
    `guides.confidentiality_markings()` / `is_confidential()` stay, as a
    fact about the documents, not a runtime block. **The 17 of 40 guides
    that carry a marking, and so now go to a non-Anthropic provider by
    default:** CHUBB_HO, Foremost_DP3_and_HO3, Progressive_HO3,
    Progressive_HO6, and the whole Sage family (Auros, Markel HO3/DP3,
    Occidental HO3/DP3, SURE HO3/DP3, SafePort HO3/DP3, Trium, Vave
    HO3/DP3, Wilshire). Full markings, per program, are one call:
    `guides.confidentiality_markings(program)` in a Python shell, or
    `guides.unmarked_programs()` for the 23 that carry none.
  - **Not done this round (see "Open work" below): the Step 2 baseline
    tier, Step 3's quote-in-own-guide guard and Vave fix, and the full
    Luna-vs-Sonnet comparison with a measured noise floor.** The suite
    itself is pinned to Sonnet regardless of these defaults
    (`verification/conftest.py`), so its numbers are unaffected; only a
    real deployment or an explicit env-var override exercises Luna.
  - **Smoke test, not a sweep:** one pipeline run each on STANDARD and
    OWNERSHIP_BASE/LLC, one chat-tab question. See the report for this
    round for the result.

- **2026-09-30 — Round 19 (Liam).** A live check put five Sage carriers and
  CHUBB under Eligible when their guides say the form can't answer yet.
  - **Three OPTIONAL intake fields: County, Dwelling amount (Coverage A),
    Dwelling type.** Blank always means unknown.
    - With all three blank, the prompt is byte-identical to 31abddc's on
      STANDARD, ALT, COASTAL_PPC4 and OWNERSHIP_BASE.
    - A filled field goes into PROPERTY DETAILS as a stated fact.
    - House routes the HO6 condo programs out. Townhome and Condo change no
      routing.
    - A filled Dwelling amount adds one Coverage A limit chunk per carrier
      (cap 1). Measured with count_tokens: +3.3K tokens (+8.4%) on STANDARD
      and +4.2K (+14.2%) on OWNERSHIP_BASE -- only when filled.
    - The county list and each county's northernmost latitude live in
      `texas_counties.csv` (Census 2023 boundaries). Parsing lives in
      `intake_fields.py`.
  - **Sage address rule: a Sage carrier with no County is
    INSUFFICIENT_INFORMATION, not "Eligible with a warning".**
    - **Which guides.** Auros, SURE HO-3, SafePort HO-3 and Wilshire say:
      "South Texas (a county entirely south of 31 degrees North) except
      Nueces county, or Bell, Falls, Robertson, Leon, Madison, Houston,
      Trinity and Polk". Trium has the same rule with **no Nueces
      exception**. The SURE/SafePort/Occidental DP3 guides carry it too.
      Markel and Vave only require Texas, and are untouched.
    - **How it's decided.** Carrier identity plus the County field, never
      the model's wording.
      - In territory: the model's verdict stands.
      - Outside: INELIGIBLE, quoting the guide's own sentence.
      - "Entirely south of 31 degrees" comes from each county's northernmost
        latitude, since the guide names only the eight East Texas counties.
    - **The cause was our code:** the Sage FPC upgrade turns INSUFFICIENT
      into ELIGIBLE without asking whether anything else is open. Recorded
      Sonnet runs show the same thing: 131 of 140 ELIGIBLE records for these
      five carriers, across 48 runs, were flipped by the upgrade.
    - **Not done:** dropping the "moot" fire-distance, visibility, alarm and
      access items. Rows 2-5 of the Sage FPC table attach those conditions
      depending on the distance and hydrant facts, so they are not moot.
      The FPC upgrade's own "ELIGIBLE regardless" glosses over the same
      conditions; that is open.
    - **Baselines changed deliberately:**
      `TestBaselineAltProfile.test_sage_family_ppc1_is_eligible_not_insufficient`
      and `test_sage_family_ppc1_pass_rate`. Both now accept a County-only
      hold, not an FPC one. Occidental was dropped from both: it has been a
      wrong-guide row since 2026-09-29, so it was passing without testing
      anything.
  - **CHUBB Coverage A hold.** With Dwelling amount blank, CHUBB's
    ELIGIBLE or REFER becomes INSUFFICIENT_INFORMATION, with Coverage A
    named. With it filled, the model's verdict stands, plus a note of what
    the guide says for that amount.
    - **What a CHUBB verdict needs** (sections I-III and VIII):
      - Coverage A. For a primary house, the Preferred Tier has a
        "Minimum: $1,000,000"; the Standard Tier reads "Subject to
        pre-approval*", and "Coverage will not be declined solely based on
        the minimum of value of the property".
      - Wildfire classification: 24-50 is "unacceptable in any Tier".
      - Flood Zone: A is "subject to pre-approval"; V is acceptable only
        for tenants and condos on the 3rd floor or higher.
      - Three-year loss history: any loss history "will require
        underwriter approval".
      - The county region: the tier tables differ for Dallas/Fort Worth
        and the Northern counties vs Harris County.
    - **Open for Liam:** below $1,000,000 the guide reads like REFER, but
      that is not built. This round only adds the note.
    - **Test changed deliberately:** round 17's
      `test_chubb_is_not_insufficient_on_guide_silence_alone` xfail is now
      the baseline
      `test_chubb_without_coverage_a_is_insufficient_and_says_why`. Its
      premise ("tiers only set pricing") was incomplete.
  - **Luna with enforced output structure: ON by default.**
    `ELIGIBILITY_STRUCTURED` (unset or 1 = on; 0 = off) sends a strict
    json_schema: `{"carriers": [...]}`, every field required, status an
    enum of the four, flaw_count an integer.
    - gpt-6-luna accepts it together with `reasoning_effort`.
    - **The pass test:** 10 of 10 real checks (5 on Liam's PPC-3 profile, 5
      on STANDARD) had a valid status and an integer flaw_count on every
      record. Unstructured calls the same day: 3 of 8 had no status at all.
    - Each check took 41-49 s and cost $0.003-0.006.
    - The schema does not prevent omissions: Foremost was left out in 3 of
      10, and Progressive HO6 in 1. No duplicates.
    - **Luna vs Sonnet, same commit** (Sonnet run twice per profile):
      - Sonnet disagreed with itself on 5 carriers (Liam's profile) and 12
        (STANDARD).
      - Where Sonnet agreed with itself, Luna's majority differed on 4
        carriers per profile: Foremost, Progressive HO6, Vave and TWICO;
        and Mercury, Progressive HO6, TWICO and Travelers. In most of
        these Luna is the more conservative.
      - The Step 2 and 3 holds make the six held carriers identical on both
        models. Without them, CHUBB on Liam's profile would have been a
        real difference: Luna raw ELIGIBLE 4 of 5, Sonnet INSUFFICIENT 2
        of 2.
    - **Dwelling type, one Luna call each:**
      - Condo: Progressive HO6 goes to ELIGIBLE (INSUFFICIENT 5 of 5 when
        blank), and several HO3s move to INSUFFICIENT.
      - Townhome: Progressive HO6 stays INSUFFICIENT.
      - One call each is an observation, not a rate.

- **2026-10-01 — Round 20 (Liam).**
  - **CHUBB below $1,000,000 Coverage A is REFER.** With Dwelling amount
    filled and below $1,000,000, a CHUBB ELIGIBLE becomes REFER (flaw 0).
    The rule keys on carrier identity and the parsed amount. The note quotes
    the guide: "Subject to pre-approval*" and "Coverage will not be declined
    solely based on the minimum of value of the property." Both quotes pass
    the chat tab's quote check.
    - INELIGIBLE, REFER and an INSUFFICIENT_INFORMATION open for another fact
      are untouched.
    - $1,000,000 and up: the model's verdict stands, with the existing note.
      Blank still means INSUFFICIENT.
    - Parsing (unchanged from round 19): "$950,000" and "950000" are 950,000
      (REFER). "1,000,000" is exactly 1,000,000 (not below). Cents round, so
      "$999,999.50" rounds to 1,000,000.

  - **Pool fence and gate checkboxes.** Two boxes, shown only for "Above
    Ground - Fenced" or "In Ground - Fenced": "Fence confirmed 4 ft or
    higher" and "Gate confirmed self-closing / locking". UNCHECKED MEANS
    UNKNOWN. There is no 6 ft box (declined).
    - With both unticked, the prompt is byte-identical to 7519a6b on
      STANDARD, ALT, COASTAL_PPC4, OWNERSHIP_BASE and a fenced-pool ALT.
    - A ticked box enters PROPERTY DETAILS as a stated fact.
    - Each box's widget key includes the pool answer, so changing that
      answer starts the boxes unticked again. A tick is also ignored unless
      the pool answer is a fenced one.
    - **Fence box:** settles the height for a carrier only when every height
      it states is 4 ft or less (from `pool_specs`).
    - **ARI (HOA+) and ARI (HOB) state 6 ft:** "Pools secured by a 6' high
      fence with locked or self locking gates are acceptable". The 4 ft box
      does not settle them.
    - **Gate box:** settled per carrier by `_POOL_GATE_RULE`, which has each
      guide's verbatim phrase. It settles the gate for carriers that accept a
      locking / locked / lockable gate (Allied, Centauri DP3, NatGen Premier,
      Progressive, Markel, Steadily, ARI). It also settles the Sage family,
      which accepts "combination or padlocked gate or self-locking or
      self-latching mechanism".
    - **NOT settled, for Liam to decide:**
      - Foremost: "a self-locking gate".
      - NatGen Custom360 DP3: "Pools are fenced in with self-locking gate".
      - Swyfft x4: "self-latching gate".
      - A locking gate does not establish either mechanism. Should the box
        count, or should it be split into two boxes?
    - **Travelers' "locking"** in `pool_specs` comes from a "retractable
      locking ladder", not a gate. It was already in `pool_specs` before; the
      box does not settle it.
    - Orion, Allied, Progressive and Centauri accept an approved alternate
      enclosure. Nothing here makes any carrier ineligible.
    - **Measured, one Luna run each on STANDARD (In Ground - Fenced):**

      | | Insufficient | carriers with any pool item in missing_info | output tokens |
      |---|---|---|---|
      | Unticked | 20 | 18 | 5,904 |
      | Both ticked | 12 | 9 | 5,777 |

      The 9 left are ARI x2 (6 ft), Foremost, Swyfft x4 and Travelers (gate
      not settled), and one Markel slide question. One run each is an
      observation, not a rate.

  - **Inspection requirements are not checked.** IGNORED: a requirement
    that an inspection, photos, survey, 4-point or wind-mitigation report be
    obtained or submitted. KEPT: every rule about the property itself, even
    when an inspection verifies it, and roofer letters / roof certifications
    (Liam has not decided on those). There are three layers, plus a caption
    near the results: "Inspection requirements are not checked."
    1. One paragraph in SYSTEM_INSTRUCTIONS.
    2. `_strip_inspection_requests` removes missing_info items that ask for
       an inspection or photos and do not also name a property fact, and
       counts them (stdout "INSPECTION STRIP").
       - KEEP wins: Centauri DP3's "4-point inspection confirming all
         updates ... in past 20 years", NatGen's "photos showing completely
         renovated kitchens", Sage SURE/SafePort's furnace items and
         Markel's Coverage A items stay.
       - **On the 3,895 recorded Sonnet records:** my keyword set finds 96
         inspection-flavoured items (55 distinct). I could not reproduce
         the 113 in the round 20 prompt. The strip catches 20, including 7
         "pictures" items outside that set, with no false hits by reading:
         NatGen photo/picture requests x15, Travelers "Roof Condition
         Questionnaire and photos" x4, TWICO "pass the required inspection
         within 30 days" x1. The other 83 are kept as property rules.
    3. An INSUFFICIENT_INFORMATION left with nothing open by layer 2 becomes
       ELIGIBLE, noted "(inspection requirements are not checked)". It
       never touches INELIGIBLE or REFER. It runs before the County and
       CHUBB holds, so those still apply.
       - **Would flip 0 of the 1,978 recorded Insufficient records**: each
         one with a stripped item had something else open.
       - The round 20 estimate of about 17 matches stripping roofer letters
         too (16: SURE DP-3 x6, SafePort DP-3 x5, Travelers x4, Markel x1).
    - **Luna, 2 runs before vs 2 after the instruction:**
      - STANDARD: Insufficient 19/17 -> 17/16. Changed: Travelers (before
        INSUFFICIENT once, with "photos" in its items; after ELIGIBLE
        twice). Noise: HOAIC, Orion, TWICO.
      - Liam's profile: Insufficient 13/10 -> 10/19. No before-record had
        an inspection item, so all 10 movements are noise. The 19-run held
        carriers on generic "criteria not in the excerpts" items.
      - Two runs per side cannot tell an effect from variance.
    - **Where the code treats roofer statements specially (for Liam):**
      - `structured_rules.sage_roofer_statement_required` (thresholds: over
        15 years for 3-tab, over 25 for architectural).
      - `_SAGE_ROOFER_STATEMENT_CARRIERS` (nine Sage guides) in
        `_apply_structured_overrides`, with three outcomes:
        - sub-type unknown: a "Roof shingle sub-type" missing_info item plus
          `_hold_for_unresolved_topic`;
        - REQUIRED: a "Roofer's statement attesting the roof is in good
          condition" item;
        - otherwise: a "No roofer's statement required" note.
      - Nothing in code handles Allied's roofer letter or Travelers' Roof
        Condition Questionnaire; those come from the model only. No code
        keys on "inspection" apart from the new strip.

- **2026-10-02 — Round 21 (Liam).**
  - **Gate box, one strict box.** The label is now "Gate confirmed
    self-latching AND can be locked". Ticking it settles every guide's gate
    wording: locking / locked / lockable (Allied, Progressive, NatGen
    Premier, Centauri DP3, Steadily, ARI, Markel's "Lockable gate"),
    self-locking (Foremost, NatGen Custom360), self-latching (Swyfft x4), and
    Sage's "combination or padlocked gate or self-locking or self-latching
    mechanism".
    - Unticked still means unknown.
    - Travelers stays unsettled: its "locking" is a ladder.
    - ARI's 6 ft height stays open.
    - With both boxes unticked, the prompt is byte-identical to 6362dac on
      STANDARD, ALT, COASTAL_PPC4, OWNERSHIP_BASE and fenced-ALT.
  - **Per-input checkboxes ("Check this").** UNCHECKED means not
    considered at all, so ELIGIBLE means "no problem found on what was
    checked". `topics.py` is the registry of 13 topics plus 3 always-on
    ones (Occupancy, Ownership, Dwelling type); the full inventory is in
    verification/TOPICS_INVENTORY.md.
    - `check_eligibility(..., checked_topics=None)`: None means everything,
      and Select All gives a prompt byte-identical to before (STANDARD, ALT,
      COASTAL_PPC4, OWNERSHIP_BASE).
    - **Partial selection:**
      - PROPERTY DETAILS lists only the checked topics' facts plus the
        always-on ones.
      - Unchecked topics' guaranteed lookups, query lines and risk terms are
        skipped.
      - A PARTIAL CHECK instruction names the unchecked topics. It goes in
        the user message, so the system prompt never changes.
      - Every rule runs only when all its topics are checked.
    - **Rules needing two topics** (Mercury, Markel, TWICO, Sage roofer's
      statement: roof age AND roof type; Centauri flat roof: roof shape AND
      roof type) are skipped unless both are checked. With only Roof age
      ticked, Swyfft's 30-year maximum still runs. The roof
      life-expectancy chunks (age-by-type tables) still reach the model, so
      it may answer "depends on roof type"; an item that also matches roof
      age is kept.
    - **The strip:** a missing_info item that matches an UNCHECKED topic's
      keywords and no checked topic's is removed. A record left with
      nothing open becomes ELIGIBLE "(unchecked topics were not
      considered)". It never touches INELIGIBLE or REFER.
      - Keyword false hits, from samples of 15 recorded items per topic: 0
        for PPC, pool, roof shape and Coverage A; roof type 2/15 (roof
        condition items naming shingles).
      - Plumbing was 11/15 (update / renovation rules for older homes)
        before it was narrowed to the material.
      - "Acreage of the property" matched home age; fixed.
      - There are no dog items in the recorded data.
      - On the recorded data, a roof age + home age + solar selection
        strips 5,305 of 6,883 items and frees 1,112 of 1,978 Insufficient
        records (round 20's inspection strip freed 0). Those are full-check
        outputs replayed, so this is an upper bound, not a forecast.
    - The model can still cite a rule about an unchecked topic (the
      "leak"). It is not hidden; see the round 21 Step 4 measurement.
  - **The form** (round 21 step 3): a "Check this" box per topic, ticked
    automatically when its input moves off the default. Select All and
    Clear; Dwelling type is required. Partial mode shows "Partial check:
    ..." and, under Eligible, "No problem found on the checked items."
  - **Measured, real gpt-6-luna, STANDARD** (round 21 step 4). Partial =
    roof age + home age + solar, plus the always-on three:

    | Run | Input tokens (cached) | Output | Wall clock | Cost | Eligible / One issue / Insufficient / Not eligible |
    |---|---|---|---|---|---|
    | All checked | 34,093 (0) | 6,030 | 53.7 s | $0.0064 | 2 / 2 / 21 / 0 |
    | Partial 1 | 19,435 (5,343) | 4,565 | 47.0 s | $0.0037 | 19 / 1 / 5 / 0 |
    | Partial 2 | 19,435 (19,432) | 4,771 | 61.2 s | $0.0026 | 19 / 1 / 5 / 0 |

    Plus 4 GUIDE_UNAVAILABLE rows each.
    - **Leak:** model records whose reasons or citations mention an
      unchecked topic: 6 of 25 (partial 1) and 5 of 25 (partial 2).
      - All were ELIGIBLE records: roof-age reasoning that names the
        shingle types in an age-by-type rule (Foremost, Mercury, Sage
        x3, Orion, TWICO), and HOAIC saying its PPC condition does not
        apply.
      - No INELIGIBLE or REFER rested on an unchecked topic, and no
        missing_info item about one survived the strip.
      - Twice Orion and TWICO said their roof table "cannot be evaluated
        without considering roof type, which is expressly outside this
        partial check", and stayed ELIGIBLE.
    - The 5 Insufficient in the partial runs held on roof life (ARI x2,
      Allied, Progressive HO3: "5 years of remaining useful life"), on the
      HO6 condo question (STANDARD has no Dwelling type), on Liberty
      Mutual's generic "criteria" item and on Travelers' roof timeframes.
  - **ZIP to County table** (round 21 step 5). Built from **source B**,
    the Census 2020 ZCTA-to-county file, because HUD_API_TOKEN was not set.
    - Share = AREALAND_PART / AREALAND_ZCTA5_20 (the share of the ZCTA's
      land in each county).
    - The table is `zip_counties.csv`, built by `build_zip_county.py`,
      which supports HUD (`hud`) and Census (`census`); its header names
      the source, the build date and the share. No network call at
      runtime.
    - Size: 1,992 Texas ZIPs (2,893 rows). 685 span more than one county,
      and all 254 counties appear.
    - Three border ZCTAs (73949, 73960, 88430) sit outside Texas's ZIP
      ranges. Their Texas land is under half of the ZCTA for 73949, 79837
      and 88430.
    - **The pick:** largest share, ties alphabetical, never random. The
      real table has no exact tie. Determinism is tested over 1,000 lookups
      and in a fresh interpreter.
    - **Unresolved:** a Texas-range ZIP with no ZCTA (PO-box-only and
      unique ZIPs: 77001, 78711, 73301, 88510 ...) gives a blank County and
      a one-line message. A non-Texas ZIP (90210) does the same.
    - How many USPS ZIPs HUD would add cannot be told from the ranges:
      Texas's ranges hold about 5,000 numbers, the table has 1,989 of
      them, and the missing USPS ZIPs are mostly PO-box / unique ZIPs. HUD
      (Liam's token) would close that gap and switch the share to
      residential addresses. To rebuild: `HUD_API_TOKEN=... python
      build_zip_county.py hud`.
  - **ZIP box** (round 21 step 6), next to County.
    - A valid ZIP sets County to the picked county and ticks the County box.
    - One line under the box always says what was used: "Checked as Harris
      County (from ZIP 77002)." or "ZIP 76801 spans Brown (95%), Coleman
      (3%) and Mills (2%). Checked as Brown; change the county below if you
      know it."
    - A manual county pick wins until the ZIP changes; changing the ZIP
      re-derives the county.
    - The ZIP never reaches the prompt. A ZIP gives the same prompt as the
      same county typed by hand (tested, zero API). With County unchecked
      the ZIP does nothing: no Sage hold, no decline.
  - **How often the ZIP pick matters** (round 21 step 7; Census table,
    land share; `verification/analyze_zip_county_disagreement.py`).
    - **685 of 1,992 Texas ZIPs (34%) span more than one county.** The top
      county's share for those: 95%+ in 147, 80-95% in 226, 60-80% in 218,
      under 60% in 94.
    - **217 ZIPs (10.9% of all) have counties that DISAGREE on at least one
      county-keyed rule**; in 96 of those the top county holds under 80% of
      the land. By rule:
      - Chubb region tables: 108
      - Sage territory: 62 (Trium variant 58)
      - NatGen Custom360 coastal zones: 57
      - Foremost Choice Homeowners restricted counties: 53
      - Foremost TDP1/TDP3 owner-occupied restricted counties: 47
      - Foremost coastal restricted counties: 34
      - Progressive Hidalgo/Webb: 4
    - **Only the Sage rule is decided by code today: 62 ZIPs (3.1%) can
      flip Sage IN/OUT** depending on the pick. In 29 of them the top
      county holds under 80% of the land, and in 10 under 60% (e.g. 75855
      Leon 58% / Freestone 42%). The other rules are applied by the model
      from the county it is told.
    - No hold or warning was added; that is Liam's decision.
    - **Guides that list ZIPs themselves** (read-only):
      - Mercury's coastal table is keyed by county AND ZIP (78 ZIP-like
        numbers, "Refer all to Underwriting", $1,000,000 Coverage A max).
      - NatGen Custom360 puts Harris in Coastal Zone 1 only for ZIPs 77571
        and 77586 (east of Highway 146).
      - Chubb's "Territory 1A in Harris County" has NO ZIP list in the
        guide, and Harris is split between regions by territory
        (01A/B/C/E coastal, 01D south). So neither a county nor a ZIP from
        our table settles Chubb in Harris.
      - ARI and Allied only reserve the right to close ZIPs; the Sage
        guides only say "Zip codes may be added" for sinkholes.
    - **How each guide defines "coastal":**
      - By named counties, which a county settles (Harris is the
        exception: split by territory, Highway 146 or ZIP): Chubb,
        Centauri DP3, Foremost, HOAIC, Mercury, NatGen Premier and
        Custom360, and the Sage family.
      - By distance from the coast, which a county cannot settle: Orion,
        Swyfft Lloyds, and Progressive's wind rules.
      - By Hurricane Underwriting Classification, which a county cannot
        settle: Travelers.
      - By tier name only, with no definition in the guide: ARI, Steadily.
  - **ZIP end to end** (round 21 step 8). Real gpt-6-luna, STANDARD plus
    Dwelling type House, everything checked, County set from the ZIP.
    - **75201 (Dallas):** all five Sage HO carriers INELIGIBLE, citing the
      guide's location sentence ("Property must be located in: South Texas
      ... or ... Bell, Falls, Robertson, Leon, Madison, Houston, Trinity,
      and Polk.").
    - **77002 (Harris):** the round 19 County hold cleared, as expected
      (Harris is entirely south of 31 N, so IN). **But Luna then declined
      Auros and Trium itself**, writing "Harris County is not ... within
      the stated South Texas definition". That is wrong.
      - SURE, SafePort and Wilshire wrote the same reason. They ended
        INSUFFICIENT only because the FPC 9 distance hold downgraded them.
      - Round 19's rule lets the model's verdict stand when the county is
        IN, so a wrong location decline reaches the agent. **Open, for
        Liam.** Options:
        (a) State the territory as a fact in the prompt, e.g. "County:
            Harris (entirely south of 31 degrees N)", when the County topic
            is checked.
        (b) A deterministic correction: when the county is IN and an
            INELIGIBLE rests only on location, re-hold or upgrade it.
        (c) Both.
    - Input tokens: 33,283 for each run (the second run 27,940 + 5,343
      cached). The prompt is byte-identical to the same county typed by
      hand (zero-API test), so the tokens match by construction.
    - Cost $0.0061 + $0.0059.

- **2026-10-02 — Round 22 (Liam).**
  - **Sage location: state the territory, and undo a wrong location
    decline.** Why: in round 21 Step 8, real Luna declined Sage Auros and
    Trium for Harris ("not South Texas"), although Harris is entirely south
    of 31 N.
    - **Layer 1, prompt.** With County filled and checked, one computed line
      follows the County line in PROPERTY DETAILS (the prompt is shared):
      "Territory (computed): Harris County is inside this guide's territory
      -- South Texas (entirely south of 31 N) -- for <the prompt's Sage
      carriers with the rule>". The path for the eight named counties is
      "named East Texas county".
      - Outside counties get no line; code already declines them with the
        guide's quote.
      - Nueces lists only Trium, which has no Nueces exception.
      - County blank: byte-identical to 0db52e4 on STANDARD, ALT,
        COASTAL_PPC4 and OWNERSHIP_BASE, both with no selection and with a
        partial selection.
      - Growth with County filled: +117 input tokens on the full STANDARD
        prompt (33,283 -> 33,400, +0.35%); +109 to +121 on a Sage-only
        prompt.
    - **Layer 2, code** (`_undo_location_decline`). It needs all of: a
      carrier with the rule, County inside (from the county table, never
      the model's words), status INELIGIBLE, and a reason matching
      south texas / 31 / territory / county / location.
      - Those reasons and the matching citations are removed. The location
        rule counts as one flaw.
      - If other flaws remain, INELIGIBLE stands with the rest. If none
        remain, the status becomes REFER (never ELIGIBLE), with the note
        "The county is inside this guide's territory. The model declined on
        location only; re-run to confirm."
      - It logs LOCATION DECLINE CORRECTED. ELIGIBLE, REFER and
        INSUFFICIENT are untouched, and so are Markel and Vave.
      - **The keyword set:** on real Luna it caught the 5 wrong Harris
        reasons and the 4 (correct) Nueces ones, and 0 of 13 other Sage
        decline reasons. On recorded Sonnet it caught 0 of 83 reasons in
        43 Sage declines, all occupancy-based, so no false hit.
    - **Measured, real Luna, Liam's profile + House, Sage HO only:** Harris,
      Bexar, Hidalgo, Bell and Polk (inside) and Nueces (outside), plus 2
      full STANDARD + Harris runs, before (main) and after.
      - Wrong location declines: 0 of 40 inside records before and 0 of 40
        after. Layer 2 caught 0 after Layer 1. Nueces stayed INELIGIBLE x4
        (Trium ELIGIBLE) both times.
      - The only observed failure is the round 21 run (1 of 3 full Harris
        runs at that prompt, 5 of 5 Sage records). Replayed through the new
        code, its two final declines (Auros, Trium) become REFER; it is
        kept as a regression fixture.
      - The wrong decline is occasional, so 8 runs per side cannot show a
        rate.

## Open work, in priority order (updated 2026-10-02)

0. **RESOLVED 2026-09-30: the "omission with no NOT_EVALUATED row"
   finding.** A record whose status is missing or unrecognised used to count
   as covering its carrier by NAME, so its carrier vanished with no row.
   The live bug the same day was 23 Luna records with no status at all.
   Fixed in 31abddc: such a record is now its own "Could Not Be Checked"
   row. Round 19 turned on enforced structure for Luna, which gave 10 of 10
   runs a valid status on every record. Omissions still happen: Foremost
   was left out in 3 of 10 runs, but each now gets a NOT_EVALUATED row.
   Duplicates (earlier: Vave, Wilshire twice): none in round 19's 10 runs.
   No policy is decided for them.

**Round 21, not done (2026-10-02):**
- **A hold or warning for ZIPs whose counties disagree** waits for Liam and
  the round 21 Step 7 number: 217 ZIPs on any county rule, 62 on the Sage
  rule the code decides.
- **Luna's wrong Sage location decline for Harris** (round 21 Step 8). The
  options are above.
- **Coastal tier from ZIP; roof sub-type and fire-station / hydrant
  fields.**
- **Roofer letters:** still undecided whether they count as inspections.
  Kept.
- **HUD-USPS crosswalk:** the table is the Census ZCTA fallback (land
  share, no PO-box ZIPs). Liam creates the HUD token, then run
  `python build_zip_county.py hud`.
- **Tier 2 baseline:** none ran in rounds 19, 20 or 21.
- **NEW: silence in the retrieved text treated as missing information.**
  - Recorded Sonnet: 57 of 1,978 Insufficient records (2.9%) hold ONLY on
    generic items ("criteria not in the excerpts", "table not included in
    the retrieved excerpts").
  - Luna runs: 0-2 per run (the most was 2 of 19, in round 20's
    10-vs-19 run).
  - Counted with a narrow pattern, so it is a lower bound. Nothing has
    changed yet; it is worth its own round.

**Round 20, not done (2026-10-01):**
- **ZIP code:** Liam and Jonathan are still discussing it. Not built.
- **Per-input checkboxes ("test only these inputs") and Select All:**
  waiting on Liam's answers. They will touch:
  - every place a property fact reaches the prompt: the PROPERTY DETAILS
    block, `_optional_fact_lines`, `_pool_fact_lines`, and the risk-factor
    query terms built from the intake;
  - the retrieval guarantees: PPC, pool, solar, roof, occupancy,
    trust/LLC and Coverage A;
  - every deterministic hold and override: Sage county, CHUBB Coverage A
    and below-$1M REFER, the Sage FPC upgrade, Sage roofer statement,
    TWICO sub-type, Centauri flat roof, the pool spec checks, the solar
    note and the OQ-1 intake-contradiction guard.
- **Roof sub-type and fire-station / hydrant fields.** Roof is 17% of
  Insufficient on its own; fire distance appears in 28% of Insufficient
  records.
- **Coastal tier definitions.**
- **6 ft fence box:** declined. ARI (HOA+)/(HOB) state 6 ft, so they stay
  open.
- **Gate wording:** DECIDED 2026-10-02 (round 21): there is one strict box,
  "Gate confirmed self-latching AND can be locked", and it settles every
  wording family.
- **Roofer letters / roof certifications:** do they count as inspection
  requirements? Today they are kept.

**Round 19, not done (Liam, 2026-09-30):**
- **Allied Trust's card reads as if the roof failed.** Its ¾-of-life rule
  only decides replacement cost vs actual cash value; eligibility needs 5+
  years of life left. This is a prompt wording fix, so it needs a Tier 2
  baseline.
- **Travelers lands in Insufficient over a paperwork item:** the
  Renovations Section, required for homes 25+ years old.
- **Sage FPC upgrade glosses over its own conditions.** It says "ELIGIBLE
  regardless of driving distance", but rows 2-5 of the table attach
  conditions (visibility from the road, central-station alarm, year-round
  access) that depend on the distance and hydrant facts.
- **CHUBB below $1,000,000 Coverage A:** DECIDED and built 2026-10-01
  (round 20): it is REFER.
- **Other guides with COUNTY rules.** Listed here, not built:
  - Foremost: a "Restricted Areas -- Coastal" list of counties that are
    "entirely restricted", including Aransas, Bee, Brazoria, Cameron,
    Chambers, Fort Bend, Harris, Hardin, Jim Wells, Kenedy, Montgomery,
    Nueces, Victoria and Wharton. There are exceptions for some programs,
    and only TWIA-served areas are accepted.
  - CHUBB: tier tables differ by region (Dallas/Fort Worth, Collin and the
    Northern counties; Austin, San Antonio and surrounding, East and South;
    Harris County territories). No wind coverage in a First Tier County or
    Harris Territory 1A.
  - Progressive HO3/HO6/DP3: "We are not accepting new business in Hidalgo
    or Webb county". Wind-pool-zone homes are written ex-wind.
  - Mercury: coastal county/ZIP table (Tier I/II counties, "Refer all to
    Underwriting", a $1,000,000 Coverage A maximum, deductibles) and an
    inland-counties table.
  - ARI HOB: homes where TWIA wind coverage is available (Tier 1 counties,
    Harris east of Highway 146) are ineligible.
  - NatGen Premier and Custom360: Tier 1 coastal counties need a signed
    windstorm exclusion; Custom360 has coastal zones.
  - HOAIC: Tier 1/Tier 2 county lists, for deductibles only.
  - Centauri DP3: listed coastal counties are ineligible for wind coverage.
  - Travelers: NO county list. Its coastal rules key on a Hurricane
    Underwriting Classification (Extreme is ineligible; High 2 "Refer all to
    Underwriting"), which is a different fact.
  - Orion: "All counties within Texas are eligible". Allied Trust reserves
    the right to restrict counties, with no list.
  - Liberty Mutual, Swyfft and TWICO: no county mentions.
- Still open from earlier: the Step 3 quote guard and Vave "Exclusion";
  compact output; second homes; pool and fire-distance fields; the Step 2
  baseline tier; the full Luna-vs-Sonnet comparison beyond what round 19
  measured.

1. **What's unvalidated on Luna.** Every Tier 2 baseline in this suite (the
   pipeline's and the chat tab's) was measured against Sonnet's output, not
   Luna's. On the pipeline side specifically, four model-text consumers can
   change a verdict by keying on the model's own wording:
   `_strip_contradicted_property_claims` (the OQ-1 guard),
   `_drop_manufactured_pool_questions`, `_hold_for_unresolved_topic`, and
   the Sage FPC upgrade in `_apply_structured_overrides`. None of these has
   been checked against how Luna phrases the same facts.
2. **Step 3:** the quote-in-own-guide guard (the ARI (HOA+)/(HOB)
   cross-citation xfail) and Vave's roof-age predicate fix (needs
   "Exclusion" as well as "excluded").
3. **The full Luna-vs-Sonnet comparison, with a noise floor.** Run Sonnet
   twice as two independent sets on the same commit before comparing either
   to Luna — Allied Trust/Trust went 0/3 → 3/3 REFER on byte-identical
   input in this round's own re-run, so a 3-of-3 "consistent" result is
   provisional until it is checked against Sonnet's own variance.
4. **Compact output** (verification/COMPACT_OUTPUT_INVENTORY.md, on the
   compact-output branch) — measurement done, format not built.
5. **Second homes:** route Seasonal/Secondary Home to HO and DP carriers,
   let each guide's own occupancy rule decide, turn the occupancy guarantee
   on for those two occupancies.
6. **The intake fields:** pool fence height, self-latching gate, miles to
   fire station, feet to hydrant (all optional).
7. **Allied Trust trust-to-REFER** (0/3 or 3/3 across recorded runs, not
   yet a stable fix) and **CHUBB's insufficiency on guide silence** (its
   guide has no PPC/roof-age/pool rule at all; SYSTEM_INSTRUCTIONS says
   silence is unrestricted, and the model does not always follow that).

## Updating carrier guides in production

Uploads happen in the app on Liam's computer, and **they never reach
production by themselves**. Railway's database is a persistent volume, seeded
from the committed `carrier_docs_db_seed/`. `seed_db.sh` only copies the seed
into an EMPTY volume, or when `FORCE_RESEED=1` is set.

The DD-1, DD-2 and DD-4 re-uploads and the Centauri HO3 fix
(`verification/DATA_DEFECTS.md`) all follow this path:

1. **Upload locally, AND replace the file in `carrier_eligibility_pdfs/`.**
   In the local app's Manage Carriers tab, remove the bad record and upload
   the correct PDF under the same carrier name. Then also copy the correct
   PDF into `carrier_eligibility_pdfs/` under the same filename, replacing
   the wrong one there. **Both steps are required** -- the Manage Carriers
   upload writes only to the vector store; it does not save the PDF
   anywhere, and `carrier_eligibility_pdfs/` is the folder `load_docs.py`
   reads to rebuild the WHOLE database from scratch. Fix only the store and
   a later full rebuild (see "The rebuild/deploy sequence" below) silently
   re-ingests the wrong guide, undoing the fix with no error anywhere. If
   the carrier is NEW, add its name to `expected_programs.txt`.
2. **Rebuild the seed and commit it.**
   ```powershell
   Remove-Item -Recurse -Force carrier_docs_db_seed
   Copy-Item -Recurse carrier_docs_db carrier_docs_db_seed
   git add -f carrier_docs_db_seed
   git add expected_programs.txt
   git commit -m "Re-upload <carrier>"
   git push origin main
   ```
3. **Deploy once with `FORCE_RESEED=1`.** Set it in Railway and redeploy.
   Check the logs for `Forced reseed complete`. Then check that the
   Database Fingerprint in the live Manage Carriers tab matches the local
   one exactly: carriers, chunks, and both hashes.
4. **Unset `FORCE_RESEED`** straight away.

> **Warning.** `FORCE_RESEED=1` WIPES the live database and replaces it with
> the seed. Anything uploaded in the live app and not in the committed seed
> is lost, on that deploy and on EVERY later deploy while the variable stays
> set. As of 2026-09-29 there have been no live uploads, so a reseed loses
> nothing.

The **Database Fingerprint** panel is also the way to tell whether production
holds an older seed at all. The seed was rebuilt four times on 08-15
(b7242d0 through a87535c). Local values on 2026-09-29, identical for
`carrier_docs_db` and the committed seed: 40 carriers, 2,491 chunks,
documents `3e45426347c356dd`, metadata `e35264910096fc15`. If the live panel
differs, deploy once with `FORCE_RESEED=1` as in step 3.

A fixed guide clears its "Could Not Be Checked" warning row on its own.
Presence and defects are read from the database; `expected_programs.txt`
only lists what should be there.

## The rebuild/deploy sequence (a full re-index: needed after a change to how PDFs become chunks -- pdf_extraction.py, load_docs.py, or the chunking in upload_carrier.py)

```powershell
python load_docs.py
Remove-Item -Recurse -Force carrier_docs_db_seed
Copy-Item -Recurse carrier_docs_db carrier_docs_db_seed
Get-ChildItem carrier_docs_db_seed -Recurse | Select-Object FullName, Length   # verify sizes are real, not tiny stubs
git add -f carrier_docs_db_seed
git add <whatever .py files changed>
git status   # confirm seed files show as staged before continuing
git commit -m "..."
git push origin main
```
Then in Railway: set `FORCE_RESEED=1` → redeploy → confirm `Forced reseed complete` in logs with a multi-MB `chroma.sqlite3` → confirm Manage Carriers tab is correct → **remove `FORCE_RESEED`** (leaving it set wipes future in-app uploads on every deploy).

## Verification test profile used across both audit rounds

PPC 9, non-coastal, owner-occupied, individual owner, built 2009, 10-yr composition shingle roof, frame/PVC, in-ground fenced pool, no accessories, no dogs, no solar. Keep using this exact profile for round 3 so results are comparable to rounds 1 and 2.