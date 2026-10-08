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
      - (Corrected 2026-10-02: the Allied HO3 guide in this repo has NO
        roofer's-letter rule; its roof rule is that a roof with "less than
        5 years of useful life expectancy" is ineligible.) Nothing in code
        handles Travelers' Roof
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
  - **The ZIP pick is shown** (display only). Under the ZIP box: "ZIP 77002
    -> Harris County (100% of the ZIP)".
    - Under 80% it adds "This ZIP spans more than one county."
    - For the 62 ZIPs whose counties give different Sage results (round 21
      Step 7) a warning adds: "This ZIP spans counties with different Sage
      results. Select the County directly to be sure."
    - A county picked by hand replaces these lines with the "set by hand"
      line.
    - None of it reaches the prompt: the prompt for a ZIP is byte-identical
      to the same county typed by hand (tested for a clean, an under-80%
      and a flip ZIP).
    - The round 21 "Checked as ... (from ZIP ...)" caption was replaced; its
      two tests were updated deliberately.

- **2026-10-02 — Round 24 (Liam).**
  - **A roofer's letter or a plumber's statement counts as an inspection,
    so the tool does not check it.** This covers every signed statement or
    certificate of the same kind: electrician, HVAC, roof certification,
    the Roof Condition Form. It also covers a rule whose CURE is such a
    document, which must never become a hold or a decline.
    - **SYSTEM_INSTRUCTIONS:** the inspection sentence now names roofer's
      letters / Roof Condition Forms, plumber's / electrician's / HVAC
      contractor's signed statements and roof certifications, "including
      where such a document is what cures a rule". Round 20's "keep roofer
      letters" clause is gone.
    - **Strip:** `_LETTER_RE` wins over the KEEP list.
      - On the 6,883 recorded Sonnet items it now catches 428 (round 20:
        20). The 412 new ones are 393 Sage sub-type / roofer-statement
        items, 10 Travelers roof questionnaire / "roofer documentation"
        items and 9 Sage DP-3 furnace items cured by an HVAC contractor's
        attestation.
      - No false hits by reading. Markel's "signed no known loss letter"
        (prior insurance, not an inspection) is NOT caught, and a test
        holds it.
      - It would flip 18 of 1,978 recorded Insufficient records to
        ELIGIBLE: SURE DP-3 x6, SafePort DP-3 x5, Travelers x6, Markel x1.
    - **Where the code keys on "roofer" now:**
      - `structured_rules.sage_roofer_statement_required` is unchanged: it
        still computes the age line (over 15 for 3-tab, over 25 for
        architectural).
      - The `_SAGE_ROOFER_STATEMENT_CARRIERS` branch of
        `_apply_structured_overrides` is now **note only** in both cases.
        - REQUIRED: "Roof is over the guide's age line; the guide asks for
          a roofer's statement on its Roof Condition Form (not checked)."
        - Sub-type unknown: both readings, plus the same "(not checked)"
          sentence.
        - It no longer adds the "Roof shingle sub-type" or "Roofer's
          statement attesting ..." items, and no longer calls
          `_hold_for_unresolved_topic` (the sub-type now decides nothing).
      - `_INSPECTION_KEEP_RE` no longer protects "roofer", "certif" or
        "letter"; `_LETTER_RE` holds them instead.
      - Nothing else keys on "roofer".
    - **Measured, one real Luna run before and after** (STANDARD + House,
      roof 27, Architectural Shingle):
      - Before: Allied and the five Sage HO carriers carried a "Roofer's
        statement confirming good roof condition" item; Travelers carried
        a roofer questionnaire item.
      - After: Luna still wrote "Roof condition statement from a roofer
        ..." for the five Sage carriers. That phrasing (from / by / signed
        by a roofer, plumber, ...) and "roofer questionnaire" were added
        to `_LETTER_RE`; both runs replayed with the final code leave no
        roofer or statement item.
      - The Sage carriers stay Insufficient on their other items (FPC 9
        distance, pool), each with the "(not checked)" note.
      - Other carriers moved both ways between the two runs (Mercury,
        Orion, Vave to Insufficient; Swyfft Surplus and Topa to Eligible;
        Foremost not evaluated), with none of it on roof letters. One run
        each is an observation, not a rate.
    - **Correction to round 20:** the Allied HO3 guide in this repo has no
      roofer's-letter rule. Its roof rule is that a roof with "less than 5
      years of useful life expectancy" is ineligible.

- **2026-10-04 — Round 25 (Liam's decisions dated 2026-10-03).**
  - **1. Blank Coverage A or blank County:** the rules table shows the
    carrier's rule as a NOTE ("... ; confirm"), never a hold. The two
    holds that already exist stay: Sage's county rule (round 19) and
    CHUBB's Coverage A rule (rounds 19-20).
  - **2. Condition standards** (Tool handling CONDITION_STANDARD: roof in
    good condition, no debris, pool maintained, handrails) are notes, never
    a hold, like inspections.
  - **3. The C2 pilot** covers Allied Trust HO3, Sage Auros HO3, CHUBB HO,
    Mercury HO3, Progressive HO3 and Swyfft Benchmark (Admitted) HO3.
    Every other carrier stays on today's pipeline. It runs behind
    ELIGIBILITY_RULES_PILOT, default OFF. **Do not set it on Railway**;
    Liam decides after the round 25 measurement.
  - **Rules data in the repo:** `rules_data/carrier_rules_pilot_v3.csv` (pilot
    workbook v3, which applies round 24's four flags: PRO-018 and SWY-018
    INFO_ONLY, PRO-038 a CONDITION on replaced plumbing, ALL-067
    IGNORE_INSPECTION). Also `rules_data/rule_field_map.csv` (541 lines,
    145 hand-mapped) and `rules_data/RULE_FIELD_MAP.md`. The evaluator is
    `rules_evaluator.py`. The .xlsx stays untracked, and rows are edited in
    the workbook, never in the CSV.
  - **The switch (step 3):** ELIGIBILITY_RULES_PILOT=1. ON, the six carriers
    leave retrieval and the main call. Code decides them from the form. One
    parallel Luna call sees only the rows code left open. Citations
    ("[ROW] p.N: quote") are attached by code. OFF sends byte-identical
    prompts to bb0e983 on STANDARD, ALT, COASTAL_PPC4 and OWNERSHIP_BASE,
    with and without a partial check.
  - **Two guards came out of the first measurement:**
    1. A pilot-call verdict on a row that is open only because the form
       lacks a fact is held as INSUFFICIENT, listing the facts. Luna said
       REFER, then ELIGIBLE, on the same open pool-fence rows. REFER or
       INELIGIBLE stands only on a row the model can decide (readings
       disagree, or the effect is UNKNOWN).
    2. The pool-spec guards skip pilot carriers. They only know retrieved
       carriers, so "not retrieved" read as "no fence spec" and flipped
       Allied and Swyfft to ELIGIBLE.
  - **Sage Auros with the pilot ON** (FPC upgrade off; SAG-072..080
    decide):
    - STANDARD (PPC 9) is open on SAG-077 ("FPC is 9 or greater, and
      driving distance to fire station is greater than 5 miles" -> ineligible)
      and SAG-075 (FPC 4-10, hydrant over 1,000 ft -> conditions).
    - LIAM and CLEAN (PPC 3, 2) are open on SAG-073 and SAG-074 (FPC 1-3;
      no close hydrant, or station over 5 miles -> visible from the road,
      central-station alarm, year-round access).
    - All three are INSUFFICIENT on station and hydrant distance. The
      upgrade made CLEAN and OLD ELIGIBLE.
  - **Measurement (step 4, Luna, 8 profiles x 2 runs x ON/OFF,
    `verification/measure_rules_pilot.py`):**
    - Per check: ON $0.0034 and 54.9 s; OFF $0.0039 and 78.3 s.
    - The six: ON gave the same status in both runs in 48/48 cells. OFF:
      42/48; its flips are generic "excerpt incomplete" holds and one
      omission.
    - Real ON differences:
      - Galvanized declines OFF missed: Allied ALL-057 on OLD; Swyfft
        SWY-026 on OLD, where OFF gave ELIGIBLE both runs.
      - CHUBB REFER under $1M (CHU-056, Liam 2026-10-01) on CLEAN, where OFF
        held on generic items.
      - Mercury and Progressive ELIGIBLE on CLEAN, where OFF held on generic
        items and a "PEX year" question for a 2015 house.
      - Sage Auros as above.
      - The Tier 2 profiles have no dwelling type, which the live form
        always asks. Their extra ON holds (MER-078/081, PRO-017, CHU-056/059)
        all clear with House.
    - CLEAN false holds: ON 4-7 carriers, OFF 13-16.
  - **OPEN, found by the measurement:**
    - Other carriers move with the pilot ON: 96/336 carrier-runs differ ON
      vs OFF, against 28/168 OFF vs OFF. Their own prompt text is
      unchanged; only the six's sections are gone.
    - Luna answers under display names more often with the pilot ON
      ("SageSure Markel", "Orion180"). Names that fail to resolve become
      NOT_EVALUATED rows: 24 in 16 ON runs, 16 in 16 OFF runs.
      "Swyfft - Benchmark" resolves to (Admitted) although Luna meant
      (Surplus). A fixed carrier enum in the output schema would end this,
      but it would change OFF too.
    - Non-pilot carriers holding on blank Coverage A alone (OFF, Luna): 2
      of 10 runs on blank-Coverage-A profiles, both Liberty Mutual on
      STANDARD.
  - **Not this round:** setting the pilot var on Railway (Liam); the DD-5
    re-seed; extending the table to the other 34 guides; whether the
    pipeline should stop holding on blank Coverage A for non-pilot carriers.

- **2026-10-05 — Round 26 (Liam's decisions dated 2026-10-05).** Liam pushed
  main at 27870a0. Source: his live check on Railway, kept as the LIVE
  profile (verification/profiles.py: PPC 3, Owner Occupied, Individual, built
  2007, No Pool, PVC, Solar Yes, ZIP 75094 -> Collin, House; everything
  else unchecked).
  - **A. Buckets:** the middle column is "Refer to Underwriting" and holds
    REFER only. Every INELIGIBLE goes to "Not Eligible", whatever its
    flaw_count. On LIVE, four Sage carriers declined on the territory showed
    under "One Issue" (flaw_count 1) while Trium, with the same reason, showed
    under "Not Eligible" (flaw_count 2).
  - **B.** Two optional fields: "Distance to fire station (miles)" and
    "Hydrant within 1,000 ft" (Yes / No / Unknown).
  - **C.** Cards must be much more compact.
  - **D.** Condition standards ("in good / proper working condition", "well
    maintained", "meets building codes", "no debris") are notes, never a
    hold, in the WHOLE tool -- like inspections. (2026-10-03 applied this
    to the pilot only.)
  - **Step 2:** a status set by a rule shows that rule's reason (with the
    guide sentence) as the card's only reason. The model's words move to
    `diagnostics`; a decline lists no missing items.
  - **Step 3 (compact cards):**
    - Prompt and schema: reasons at most 2 (20 words, deciding facts only),
      citations at most 2 (quote only), missing_info as noun phrases, notes
      at most 1 sentence. `maxItems` is enforced by Luna's strict mode.
    - Card (cards.py): **status** — one-sentence verdict, then "Missing:",
      then everything else under a collapsed Details. An Eligible card reads
      "No issue on: <checked facts>".
    - Measured on Luna, 2 runs each, before -> after:
      - LIVE: output tokens 4,374 -> 3,252; wall 41.9 -> 30.0 s.
      - STANDARD: output tokens 6,484 -> 3,146; wall 60.3 -> 35.8 s.
    - One status change held in both runs: Travelers on LIVE went
      Insufficient -> Eligible. Its rule is "unprotected ground mounted
      solar panels", and the prompt defines Solar Panels: Yes as panels
      mounted on the roof; the old hold asked for the mount location.
  - **Step 4 (citation guard):** a citation must be a quote and nothing
    else, from the carrier's own guide.
    - The old guard judged only the label, so "ARI_(HOA+): <HOB's age
      rule>" passed.
    - Now a citation with no quote marks or with commentary is removed (a
      note, no status change).
    - A quote found only in another program's guide counts as that
      program's citation.
    - Replay over the round's runs: 226 citations, 0 removed.
  - **Step 5 (stitching):** 600 of 1,810 prose chunks start mid-sentence.
    - Each gets the end of the previous chunk, up to 300 characters.
    - A missing item that asks for guide text never holds a carrier (97 of
      2,879 recorded items).
  - **Step 6 (condition standards, D):** prompt sentence + strip + flip.
    - Caught 110 of 9,104 recorded items, 3 false hits fixed.
    - 25 recorded Insufficient records would become Eligible.
    - Orion on LIVE no longer holds.
  - **Step 7:** Could Not Be Checked rows have no empty bullets. There is no
    real double render (AppTest); Liam's copy showed Streamlit's stale
    elements during a re-check. Results now live in one st.empty()
    placeholder that a new check replaces at once.
  - **Step 11:** the form says "Only checked items are considered.
    Inspections and the condition of the home are not checked."
  - **Step 12 (Tier 2 baseline, Luna, pilot OFF):**
    - First run, on 8ec2f21: 24 passed, 5 failed, 10 xfailed, 5 xpassed;
      90 calls, $0.13 ($0.17 in round 25). Fixes in dee8e4c.
    - Re-run on dee8e4c: 26 passed, 3 failed, 9 xfailed, 6 xpassed; 90
      calls, $0.13.
      - Progressive solar, single run: Luna's rate. The 3-run test passed
        at 1/3. Left red, as in round 25.
      - Swyfft trust/LLC: OPEN since round 25, also on origin.
      - Allied 14-year roof: the test's premise was wrong. The guide's ¾
        rule is "to qualify for replacement cost coverage", not
        eligibility. A chunk boundary hid that until step 5's stitching.
        Corrected; 3/3 on Luna.
    - LIVE, 2 runs, pilot OFF and ON: 26 of 27 carriers are the same in
      all four runs; Travelers was Insufficient once (OFF). Not Eligible:
      Sage Auros/SURE/SafePort/Wilshire/Trium (territory), NatGen Premier
      (closed), TWICO (open item).
  - **OPEN after round 26:**
    - TWICO on LIVE is INELIGIBLE (4/4 Luna runs) on "...or not meeting
      building codes. This includes solar panels." Liam's reading is a
      building-code rule. Not hardcoded; tracked by a baseline xfail.
    - The Sage FPC override says Eligible at 7 miles where SAG-074's
      conditions are open (step 10).
    - NatGen Premier DP3, Foremost's condo/tenant forms and the catastrophe
      moratoriums await Liam (step 9 list).
    - Swyfft Benchmark trust/LLC declines (round 25, also on origin).
  - **Step 8 (carrier enum; pilot ON vs OFF):**
    - The strict schema's "carrier" is an enum of the call's own program
      names; ELIGIBILITY_CARRIER_ENUM=0 turns it off.
    - Round 25 profiles, 2 runs each, Luna:
      - Unresolved display names: pilot ON 50 -> 0; pilot OFF 0 -> 0.
      - NOT_EVALUATED rows, pilot ON: 6 -> 2.
      - NOT_EVALUATED rows, pilot OFF: 7 -> 8. These are real omissions,
        which an enum cannot stop.
    - The Tier 2 profiles now carry Dwelling type House (dated).
    - Other carriers, pilot ON vs OFF (enum on, this round's prompt):
      - 5 of 168 carrier-profile cells change in both runs; OFF vs OFF
        differs in 22. Round 25 was 96/336 vs 28/168.
      - 19 cells where both ON runs agree and differ from an OFF run,
        judged against the guides: ON right 16, OFF right 3.
      - ON's misses: Markel's pool rule twice (a liability-coverage
        condition treated as a hold) and Travelers' "Renovations Section
        must be completed" (application paperwork).
  - **Step 9 (closed programs):**
    - NatGen Premier OneChoice HO3 is a fixed INELIGIBLE row, sent to no
      model: "Closed to new business (guide, p.3): "Homeowners policies are
      not eligible for new business effective 11/30/2023."" The quote is
      re-checked against the stored guide on every check, so a new upload
      without it clears the row. It does not count as a usable answer.
    - **For Liam to decide** (found by searching all 40 guides):
      - NatGen Premier OneChoice DP3, p.3: "Dwelling fire policies are not
        eligible for new business effective 11/30/2023." The same closure
        for the DP3 program; not decided by code, since only the HO3 program
        was named.
      - Foremost, pp.2-34: the Condominium Homeowners, Condominium Landlord
        and Tenant forms are marked "(Existing Business Only, No New
        Business)". Sub-forms; the Foremost Choice HO3 itself is open.
      - Temporary catastrophe suspensions, not closures:
        - NatGen Custom360 p.19 ("New Business Moratorium ... may invoke a
          moratorium on new business");
        - CHUBB p.6 ("Underwriting Binding Suspensions for Hurricane,
          Wildfire, Tornado ...");
        - Mercury p.5 ("authority will remain suspended until an
          announcement is made");
        - NatGen Premier HO3/DP3 p.3 ("Binding authority for new business
          ... will be suspended in areas that may be affected by a tropical
          storm").
      - Rules, not closures: Progressive HO3/HO6/DP3, "We are not accepting
        new business in Hidalgo or Webb county."
  - **Step 10 (station distance and hydrant fields, decision B):**
    - The fields are optional, part of the PPC topic. Blank / Unknown is
      unknown and leaves the prompt byte-identical to step 9 on STANDARD,
      ALT, COASTAL_PPC4, OWNERSHIP_BASE and LIVE.
    - The rules table maps them in SAG-073 to SAG-078. No other row's open
      fact is station or hydrant distance; SAG-072 (eligible) is ALLOWS,
      and SAG-079/080 are NONE.
    - The Sage FPC override passes both into sage_family_fpc_eligibility:
      - FPC 9+ over 5 miles is now a code decline;
      - "fire station" and "hydrant" joined its keyword set;
      - missing items the form now answers are dropped when it upgrades.
    - Measured on LIVE + Bexar, Luna, 2 runs each:
      - With the pilot ON, Sage Auros is Insufficient on SAG-073/074 when
        blank, Eligible by code at 3 mi / hydrant Yes, and Insufficient on
        SAG-074's conditions at 7 mi / No.
      - SURE, SafePort, Wilshire and Trium (the override) are Eligible in
        all three.
      - **OPEN for Liam:** at 7 miles the override still says Eligible
        ("eligible only if visible from the road, central alarm, year-round
        access"), where the rows say those conditions are open. This is the
        same override-vs-rows question as round 19.

- **2026-10-06 — Round 27 (Liam's decisions dated 2026-10-06).** Built on
  3deb3bb (round 26, not yet pushed when the round started).
  - **1. TWICO and solar:** standard mounted solar panels count as
    code-compliant, so they do NOT make a TWICO home ineligible.
  - **2. Sage FPC with a known distance:** over 5 miles, the old Sage FPC
    upgrade must no longer say ELIGIBLE; hold on the guide's conditions, as
    Sage Auros does on the rules table. Blank distance behaves as before.
  - **3.** The rules pilot goes live on Railway; Liam sets
    ELIGIBILITY_RULES_PILOT.
  - **4.** The rules table is extended to the Sage batch (SURE HO-3,
    SafePort HO-3, Wilshire HO3, Trium Lloyd's HO3/HO5, Markel HO3, Vave
    HO3). It ships behind its OWN switch (ELIGIBILITY_RULES_SAGE_BATCH),
    OFF, until Claude has reviewed the rows. Never set on Railway without
    Liam.
  - **Step 1 (TWICO solar):** _apply_twico_solar_decision.
    - Fires on TWICO_HO3 + Solar = Yes + a flaw resting on the sentence
      "... or not meeting building codes. This includes solar panels." (a
      citation quoting it, or a reason in its words).
    - It removes that flaw: the status becomes ELIGIBLE (code-decided) when
      nothing else is wrong; otherwise the remaining flaws stand. The card
      carries the note.
    - Real Luna, LIVE, pilot ON: the rule fired in 2 of 3 runs (Luna did
      not decline TWICO in the third); TWICO was Eligible in all 3.
  - **Step 2 (Sage FPC with a stated distance):**
    - The upgrade covers Auros, Wilshire, Trium, SURE and SafePort
      (Occidental is a wrong-guide row).
    - All five FPC tables carry every Auros clause, checked clause by clause.
      Only the labels differ: Trium, SURE and SafePort say "FPC
      classification" and tag rows A/B/C ("the suffix value that is applied
      to the FPC values that are used in rating"); SURE and SafePort cap
      Coverage A at $2,000,000 for B/C risks.
    - Page layout, all five: FPC 4-10 within 5 miles without a hydrant
      shares its merged cell, and so all SEVEN conditions, with FPC 4-8 over
      5 miles. The round 11 code gave it three; corrected.
    - With the distance stated (structured_rules.sage_fpc_with_distance):
      - row A -> the old upgrade, as before;
      - FPC 9+ over 5 miles -> declined;
      - an unknown hydrant within 5 miles -> hold on the hydrant only;
      - every "eligible only if" row -> hold, listing the conditions as noun
        phrases in the guide's words (home age and owner occupancy evaluated
        when known);
      - a known failed condition (home 25+) -> REFER, as the rules table
        treats a failed condition row.
    - A blank distance gives output identical to 3deb3bb: 60 replays
      (STANDARD, ALT, LIVE, LIVE+Bexar, STANDARD+Bexar x 4 model answers x
      3 blank forms).
    - Real Luna, LIVE + Bexar, pilot ON:
      - 3 mi / Yes: all five Eligible.
      - 3 mi / No: all five held on row B (Auros on SAG-073).
      - 7 mi / No: all five held on row C (Auros on SAG-074).
  - **Step 3:** the Database Fingerprint panel (Manage Carriers) shows
    "Rules pilot: ON (6 carriers)" or "Rules pilot: OFF".
    - **ELIGIBILITY_RULES_PILOT must be exactly "1"** to turn it on; "true",
      "yes", " 1" or anything else is OFF.
    - The app reads it at start, so redeploy after changing it.
  - **Step 4 (Sage batch extraction):** written to
    pilot_structured_rules/Carrier_Rules_Sage_Batch_v1.xlsx and
    _rules.csv. Both are untracked, like v3, until Claude reviews the rows.
    - 1,033 rows; IDs SUR-, SFP-, WIL-, TRI-, MKL- and VAV-NNN. The sheets
      and columns match v3.
    - Each guide was extracted in its own pass per EXTRACTION_SPEC_v2. The
      parent ran the checks on every row:
      - quote in PDF text: 0 FAILs;
      - lint: 0;
      - quote in app stored text: 18 FAILs, each a split or interleaved
        stored chunk, with the reason in the row.
    - The scripts and the agent brief are in
      pilot_structured_rules/sage_batch_tools/.
    - How the four sister guides compare with Auros, word for word:
      - **Roof ages:** identical in all four (15-year 3-tab, 25-year
        architectural, roofer's statement).
      - **FPC table:** every clause is the same in all four (see Step 2).
      - **Territory:** identical, except that Trium drops "except Nueces
        county". Trium mentions Nueces only for a foundation-coverage
        exclusion.
      - **Coastal:** SURE is identical. The others differ:
        - SafePort raises the deductibles: Very High is 5% (Auros: 3% or
          higher); High and Moderate are 3% (Auros: 2%).
        - Wilshire has the same deductibles as SafePort. Its Extreme Hazard
          locations are "eligible with a 5% Wind and Hail Deductible, or
          Coastal – 5% Hurricane Deductible and a 1.5% AOP Deductible"
          (Auros: "Ineligible.").
        - Trium makes Extreme Hazard eligible with a 1.5% Wind and Hail
          Deductible, plus "Exception: Coastal – Risks located on any barrier
          island are only eligible if the island is accessible to the
          mainland by a roadway". It uses 1.5% in every tier and drops the
          trees-between-the-rows note.
    - Markel and Vave do not follow the Auros layout:
      - Markel: PPC 1-10 allowed, no county or coastal rule; roof age is
        coverage-only (Roof Exclusion form); LLCs and trusts are allowed.
      - Vave: no referrals; roof is RCV/ACV/excluded by age (coverage-only);
        no county or FPC table; LLCs are allowed on five criteria.
  - **Step 5 (Sage batch map):** files in rules_data:
    - carrier_rules_sage_batch_v1.csv: a copy of the step 4 rules CSV with a
      source header (the .xlsx stays untracked);
    - build_sage_batch_map.py, which writes sage_batch_field_map.csv.
    - 564 deciding rows: 79 decided by a form field, 71 gated-but-open,
      3 AMBIGUOUS, 15 the same rule as another row, 396 NONE. The per-carrier
      table and the choices that differ from Auros are in RULE_FIELD_MAP.md.
    - verification/test_sage_batch_rules.py covers the data and the lines.
      Its FPC rows agree with step 2's sage_fpc_with_distance in all 120
      owner-occupied cases. A known Seasonal or Tenant home in the
      seven-condition rows is REFER on the rows but held by step 2 (strict
      xfail).
    - **Found in Auros's pilot lines** (pilot ON today; listed, not changed,
      because step 6 must keep batch-OFF byte-identical):
      - SAG-001 declines a seasonal or secondary Auros home, which the guide
        accepts. This changes a verdict: it is the first thing to fix after
        this round.
      - Vacant gives three flaws (SAG-001, -002, -005).
      - A county outside the territory gives two flaws (SAG-081, -083), and
        the county hold adds a third.
      - All three are strict xfails in test_rules_evaluator.py.
  - **Step 6 (the Sage batch switch):** ELIGIBILITY_RULES_SAGE_BATCH.
    - **It must be exactly "1", and it only takes effect when
      ELIGIBILITY_RULES_PILOT is "1".** Default OFF. Do not set it on Railway
      until Claude has reviewed the rows.
    - With it ON, the six batch carriers move to the rules table like the
      pilot six. The Fingerprint panel line reads "Rules pilot: ON (6
      carriers) + Sage batch ON (6 more)".
    - OFF is byte-identical to step 3. Checked over 30 replays (10 profiles x
      3 model answers; every prompt and result): pilot OFF (batch unset or
      "1"), and pilot ON (batch unset, "0" or "true").
    - ON, with a fixed model: no carrier outside the batch changes.
    - The Step 2 FPC logic and the Round 19 county hold, on a batch carrier:
      - The FPC upgrade is skipped (fpc_skip), so the batch's FPC rows decide.
        They agree with sage_fpc_with_distance for every owner-occupied case
        (step 5).
      - The county hold leaves a known county to the evaluator's territory
        row, so the card shows that row once (one flaw).
      - A blank county is still held by the county hold, with one County
        item. The rows' "blank County" notes are dropped from also_confirm.
      - Auros, a pilot carrier, keeps round 25's path.
  - **Step 7 (real Luna, pilot ON, batch OFF vs ON, 2 runs each, 37f22b4):**
    - Batch ON cuts prompt tokens (input + cached) by 19-26% and wall time
      by 2-8 s. Cost is roughly flat ($0.0017-0.0037 per check; caching
      dominates).
    - **Every Sage-batch difference, and which side is right:**
      - **Blank station distance, PPC 1-3** (LIVE+Bexar, CLEAN): SURE,
        SafePort, Wilshire and Trium are Eligible OFF, Insufficient ON.
        - ON follows the guide: row A needs a hydrant and a station within
          5 miles, so the row is unknown. It is also what Auros does on the
          pilot.
        - OFF is the old upgrade that decision 2 kept for a blank distance.
        - **Liam's call:** the two paths now disagree on purpose.
      - **OLD** (PPC 6, home 56, distance blank): the four are Eligible OFF,
        Insufficient ON. ON is right: rows B/C need a home under 25.
        Wilshire OFF even said "any value is eligible" (model error).
      - **Markel, OLD and CLEAN:** OFF declined both runs on "$500,000
        minimum". That is the HO5 minimum (MKL-080); the HO3 minimum is
        $100,000 (MKL-079). Model error OFF; ON is right.
      - **Vave, OLD:** ON declines on VAV-047 ("Homes with galvanized,
        steel, iron, or polybutylene plumbing are ineligible."; OLD has
        galvanized). Both OFF runs said Eligible: model error OFF.
      - **Trium, LIVE (Collin):** 2 flaws OFF, 1 flaw ON. OFF: the model
        declined on location and the county hold added a second flaw for
        the same county (code bug on the OFF path). ON: TRI-093 only.
      - Noise only: Wilshire CLEAN OFF Eligible/Refer; Markel STRESS OFF
        Eligible/Insufficient; Vave STRESS OFF NOT_EVALUATED (omitted).
    - **Other carriers:** their prompt sections are byte-identical OFF and
      ON. Yet verdicts outside OFF's range: 0, 1, 0, 4, 3, 4 per profile
      (OFF-vs-OFF noise: 0, 1, 1, 3, 2, 1). Same-evidence drift from a
      smaller prompt. Consistent 2/2 flips:
      - HOAIC STRESS: Refer -> Eligible. Wrong: Coverage A $900k needs
        underwriting approval.
      - Swyfft Lloyds STRESS: Insufficient -> Ineligible. Right: "ISO
        Protection Class 9 or 10" is listed.
      - Travelers STRESS: Insufficient -> Eligible. Defensible: the PPC 9
        rule is for secondary / seasonal homes.
      - HOAIC OLD: Insufficient -> Eligible. ARI HOB CLEAN: Eligible ->
        Insufficient.
    - **Rows that look wrong** (not edited; for Claude's review):
      - MKL-120: "Lapses in coverage up to 90 days are allowed." is stored
        as RULE / DECLINES. It is an allowance (a lapse over 90 days is
        what declines).
      - SUR-048 / SFP-048: the guide's EIFS sentence ("Although excluded,
        we still will decline homes unless used as trim or minimal portion
        of siding.") repeated under Screened or Tent-Like Enclosures, stored
        as UNCLEAR / DECLINES. Map line NONE.

- **2026-10-07 — Round 28 (Liam's decisions dated 2026-10-07).** Built on
  329e183 (rounds 26-27 still unpushed; origin 27870a0).
  - **1. Sage batch, blank fire-station distance: follow the guide.** SURE,
    SafePort, Wilshire and Trium hold on the fire-protection question when
    the distance is blank (unless PPC alone settles it), like Sage Auros.
  - **2. Measure Claude Haiku 5.5 against Luna** (measurement only; the
    production model stays Luna).
  - New data from Claude (untracked, pilot_structured_rules/): pilot v5,
    and Sage batch v2 (Claude's review of v1, 103 changes).
  - **Step 1 (Auros on the live pilot):** pilot v5 is loaded
    (rules_data/carrier_rules_pilot_v5.csv); only SAG-001, SAG-032 and
    SAG-048 differ from v3.
    - Map lines:
      - SAG-001 = not Tenant Occupied (an owner's seasonal or secondary
        home passes);
      - SAG-002 and SAG-083 are "same rule as" SAG-005 and SAG-081;
      - SAG-081 leaves Nueces to SAG-082.
    - The county hold leaves a known county to the territory row on every
      rules-table carrier. An out-of-territory Auros card was 3 flaws with 1
      reason; it is now 1 flaw and 1 reason. Vacant is 1 flaw.
    - **Found:** _fits_occupancy sends every occupancy except Owner Occupied
      to DP programs only. So a Seasonal / Secondary home never reaches Sage
      Auros or any HO3, and the SAG-001 decline was never reachable in the
      app. What was live: the 3-flaw out-of-territory card. Routing is
      Liam's call (strict xfail).
    - Pilot OFF is byte-identical to 329e183 (30 replays). Pilot ON changes
      only Auros.

  - **Step 2 (boundary tests):** verification/test_map_boundaries.py covers
    all 93 numeric map lines, at the boundary written in each plain rule.
    Fixed:
    - The seven-condition FPC gate (11 lines) took PPC 9-10 over 5 miles; no
      verdict changed, because the FPC 9+ row declines first.
    - ALL-112 declined a PPC 10 home that ALL-113's exception allows: a
      verdict change, Ineligible -> Insufficient for a new home.
    The details are in RULE_FIELD_MAP.md.

  - **Step 3 (Sage batch v2):** rules_data/carrier_rules_sage_batch_v2.csv
    replaces v1. 69 rows differ; 21 stop deciding (543 deciding rows).
    Map line changes, old -> new:
    - **Territory:**
      - SUR-003 / SFP-003 / WIL-003 / TRI-094: `always` -> `county in {the
        8}`, gated `south_of_31 == False` (v2's Applies when).
      - SUR-001 / SFP-001 / WIL-001 / TRI-093: `sage_territory == IN or
        county == Nueces` -> `always`, "same rule as" the East Texas and
        Nueces rows.
      - Result: one flaw per county. A new derived fact, south_of_31.
    - **Flat roof** (SUR-148 / SFP-154 / WIL-152 / TRI-040): DECLINES ->
      REFERS_TO_UW (same test).
    - **Furnace** (SUR-141 / SFP-147 / WIL-146 / TRI-058): NONE [CONDITION]
      -> NONE [NOTE] (the cure is the HVAC statement).
    - **Vave:** VAV-001 `not Tenant Occupied` -> not deciding (program
      description). VAV-007 `always` -> `not Tenant Occupied` (the whole
      home rented long-term).
    - **No longer deciding** (were NONE): SUR-048, SFP-048 (screened
      enclosure no longer declines), SUR-124/125/146, SFP-132/133,
      WIL-129/150/178, TRI-102/162, MKL-004/060/103/120/121,
      VAV-109/122/124.
    - **Text changed, line unchanged:** SUR-013 / SFP-013 / WIL-013 /
      TRI-002 (already "not Tenant Occupied" since round 27); the trust
      exceptions on SUR/SFP/WIL-006/007 and TRI-021/022 (their lines test
      LLC or are NONE); MKL-076/077 (>10 acres; acreage not asked: NONE);
      SFP-053 (NONE).
    - **Decision 1:** with the batch ON, a blank distance holds all four
      sister carriers' FPC rows for every PPC 1-10 and every hydrant answer
      (tested). PPC never settles a Sage row alone, because every class has
      an eligible row A.
    - **Not changed:** with the batch OFF, the old Step 2 FPC upgrade still
      runs for a blank distance, as it still does for Auros with the pilot
      OFF.

  - **Step 4 (re-measure the Sage batch, real Luna, pilot ON, batch OFF -> ON,
    2 runs each, on 5d600c9):** Round 27's six profiles, plus SEASONAL,
    SECONDARY and TRUST (County Bexar).
    - Wall times are inflated by fast tiers running in parallel. Prompt
      tokens fall 10-30% with the batch ON.
    - **Every Sage difference; the ON side is right in each:**
      - **Blank distance:** SURE, SafePort, Wilshire and Trium go Eligible
        -> Insufficient on LIVE+Bexar, CLEAN, OLD and TRUST. This is
        decision 1. OLD also needs a home under 25 on rows B/C. TRUST also
        needs SUR-020/021 (family-held, one trust).
      - **Trium, Collin:** 2 flaws -> 1. OFF, the county hold adds a flaw
        to the model's own location decline; it still does.
      - **Markel:** OLD and CLEAN Ineligible -> Eligible. OFF applied the
        HO5 $500k minimum; MKL-079 sets $100k for HO3. STRESS Insufficient
        -> Eligible: OFF held on the pool fence, but MKL-053/054 make that a
        pool exclusion (coverage only).
      - **Vave:** OLD Eligible / Insufficient -> Ineligible on VAV-047
        (galvanized). TRUST Insufficient -> Eligible: VAV-014 reads Owner
        Occupied + Trust as occupied by the trust's people, as SAG-019 does.
        That is an assumption, since the form does not name the occupant.
    - **SEASONAL / SECONDARY:** no batch carrier appears ON or OFF. They are
      HO3s, and the occupancy routing sends these homes to DP programs only
      (step 1 xfail).
    - **Other carriers:** results outside the OFF range per profile were 1,
      0, 1, 2, 0, 1, 2, 2, 0. That is within the OFF-vs-OFF noise (0-4).
    - **Rows still thought wrong:** none among the measured differences.
      The VAV-014 occupant assumption (shared with SAG-019) is for Liam and
      Claude to confirm.
    - **Ready to switch on:** yes, on these runs.

  - **Step 5 (Anthropic path, production-equal, measurement only):** for
    Claude 5-generation models (claude-haiku-5-5). Older Claude models keep
    their exact call, and ELIGIBILITY_MODEL still defaults to gpt-6-luna.
    - **Structured output** (output_config.format) uses the production
      schema, carrier enum included. What Haiku 5.5 rejects, measured
      2026-10-07:
      - `maxItems` ("For 'array' type, property 'maxItems' is not
        supported", 400). It is dropped, and _trim_to_two cuts reasons and
        citations to 2, counting each trim (usage "trimmed_lists").
      - `temperature` ("`temperature` is deprecated for this model", 400).
        It is not sent.
      - The enum is enforced: a carrier outside it was refused.
    - **Caching:** cache_control on the system prompt. max_tokens gets
      +4,000 because thinking counts against it (as Luna's reasoning does).
    - **Effort:** ELIGIBILITY_EFFORT (unset = the model's default, medium)
      goes to output_config.effort.
    - The rules pilot's side call uses the same model (_complete_named).
    - Measurement: verification/measure_models.py.

  - **Step 6 (Haiku 5.5 vs Luna, measurement only; pilot ON, batch ON; 8
    profiles x 3 runs each, on e827e18).** The configs are interleaved, so
    the parallel fast tiers slow all three equally.

    | | Haiku medium | Haiku low | Luna |
    |---|---|---|---|
    | wall s per check | 47.0 | 36.8 | 38.2 |
    | cost $ per check (cached) | 0.0083 | 0.0060 | 0.0023 |
    | input / cached / cache-write / output tokens | 17.4k / 12.8k / 7.0k / 11.1k | 17.4k / 19.8k / 0 / 8.2k | 2.7k / 19.5k / 0 / 3.6k |
    | calls parsed, valid status on every record | 48/48 | 48/48 | 48/48 |
    | names outside the enum | 0 | 0 | 0 |
    | carriers omitted (NOT_EVALUATED) | 0 | 4 | 2 |
    | lists cut to two (no maxItems) | 6 | 7 | 0 (schema) |
    | same verdict in all 3 runs | 163/192 (85%) | 158/192 (82%) | 175/192 (91%) |
    | CLEAN model holds per run (+5 rules-table holds, same for all) | 9, 9, 9 | 7, 9, 10 | 3, 3, 2 |
    | Tier 2 baseline (pilot + batch ON) | 15 pass / 7 fail | 15 / 7 (+1 xpass) | 15 / 7 |

    - **Cost assumptions.** Haiku's cache prices are not on its page: read
      $0.01 and write $0.125 per M are ASSUMED (Anthropic's usual 0.1x /
      1.25x). Most of Haiku's extra cost is output, i.e. thinking.
    - **Tier 2:** the same 7 tests fail on all three, all from the
      configuration:
      - Auros / Wilshire PPC 1 is held on the distance (decision 1; the test
        assumes pilot OFF);
      - Progressive / Allied solar and the Allied 14-year roof are decided
        by code, so there is no model text;
      - Swyfft Benchmark Surplus trust/LLC is open since round 25.
      Haiku low also XPASSes the TWICO circuit-panel test.
    - **OLD declines caught:**
      - Pilot carriers, decided by code: all three configs are Ineligible
        on Allied ALL-057, Swyfft SWY-026, Vave VAV-047, Progressive and
        Mercury.
      - Non-pilot galvanized rules: no model applies them, because the
        rule is not retrieved for ARI HOA+ / HOB, Swyfft Benchmark / Topa /
        Lloyds Surplus, TWICO or Travelers (pilot OFF as well). This is a
        verdict-changing retrieval miss; strict xfails in
        test_plumbing_retrieval.py.
    - **Disagreements in every run:** 17 pairs (Haiku medium) and 8 (Haiku
      low), always Haiku Insufficient vs Luna Eligible.
      - The carriers: Liberty Mutual (brush / wind hazard area), Orion
        (acreage, commercial exposure), Swyfft Benchmark / Lloyds Surplus
        (loss history), Travelers (heating; ground-mounted solar is a
        liability exclusion), Foremost (wiring / amperage).
      - Each Haiku hold is on a fact the form never asks. Luna is right by
        the project's rule for such facts ("confirm", never a hold, as the
        rules table's NONE rows). The system prompt's literal text (missing
        facts -> missing_info) allows Haiku's reading.
    - The default model was not switched.

- **2026-10-08 — Round 29 (Liam's decisions dated 2026-10-08).** Built on
  d0332f0 (rounds 26-28 unpushed; origin 27870a0). Railway today: pilot ON,
  Sage batch OFF, model Luna.
  - **1. Model:** fix false holds in code, re-test Haiku 5.5 against Luna,
    and report against the gate (step 3). The default in code stays
    gpt-6-luna. If Haiku passes, Liam switches by setting ELIGIBILITY_MODEL
    on Railway; nothing else should be needed.
  - **2. Seasonal and Secondary Home** (owner's homes) are routed to HO3
    programs as well as DP programs, and each guide's occupancy rows decide.
    Tenant Occupied and Vacant stay DP-only.
  - **Step 1 (hold guard, hold_guard.py):** runs after every code rule and
    before _code_owns_cards. It classifies the missing_info items of each
    INSUFFICIENT card:
    - (a) a form field (intake_fields.FORM_FIELDS, 23 fields): kept;
    - (b) written by code (any item not in the model's own list, snapshotted
      right after parsing, plus prefix patterns): kept;
    - (c) a fact the form does not collect (hold_guard.NOT_ASKED: 25 facts,
      110 patterns): moved to a "Confirm (not asked by the form; never a
      hold): ..." note;
    - anything unclassified, and items asking for guide text: kept.
    - All items (c) -> ELIGIBLE, decided by code; some (c) -> only those
      move.
    - Never touched: INELIGIBLE / REFER cards, rules-table cards, holds
      made by code, cards citing a row.
    - Replayed over round 28 step 6's records, it releases 107/165 held
      cards on Haiku medium, 86/142 on Haiku low and 24/62 on Luna.
    - Top (c) items: roof remaining useful life 36, brush / wind hazard
      area 32, heating / cooling system 30 (plus variants), commercial
      exposure 17, number of mortgages 14, prior liability / fire loss 12,
      plumbing update date 11.

  - **Step 2 (omitted carriers):** _retry_omitted. A carrier the main or
    pilot reply left out gets ONE more call, for just the missing carriers:
    the same prompt and schema, the carrier enum narrowed to them, and a
    closing line naming them. The records are merged into the reply. A
    carrier still missing keeps the NOT_EVALUATED card ("No answer came back
    for this carrier in this check -- run the check again"). The retry's
    usage is recorded as main_retry / pilot_retry.

  - **Step 5 (store fixes):**
    - **a. Centauri HO3:** the OCR text is committed as
      ocr_text/Centauri_-_HO3_-_05.01.2026.txt. pdf_extraction.load_guide_documents
      is the one entry point for load_docs.py and uploads: it uses
      ocr_text/<pdf name>.txt when a PDF has no text layer. No Tesseract
      dependency. The source is recorded in data_defects.ALTERNATE_TEXT_SOURCES.
      Chunks: 0 -> 45.
    - **b. Centauri DP3:** Word list labels sit 2 pt above the body text and
      were interleaved by the default line clustering. The guide is now read
      in content-stream order (FLOW_ORDER_FILES). Chunks: 38 -> 40.
      - The overlap signature over all 41 PDFs also finds Travelers HO3. That
        is a different cause (a large watermark); listed in DATA_DEFECTS.md
        (DD-6), not changed.
    - **c.** reindex_program.py re-ingests one program in place, and the seed
      was copied from the result. All other 39 programs are identical in ids,
      text, metadata and embeddings (compared per program).
    - **d. App quote check over Carrier_Rules_Remaining_Batch_v1_rules.csv:**
      - before: 1,501 pass, 26 fail (15 Centauri DP3), 88 Centauri HO3 with no
        text;
      - after: 1,602 pass, 13 fail (2 Centauri DP3: CDP-085 / CDP-086,
        table text), 0 no text.
    - DD-3 is fixed. The tests that assumed Centauri HO3 had no text are
      updated, with dated notes.
    - **Refresh a local store from the new seed:**
      `rm -rf carrier_docs_db && cp -r carrier_docs_db_seed carrier_docs_db`.
      On Railway it needs FORCE_RESEED=1 once (seed_db.sh), then remove it.

  - **Step 4 (occupancy routing, decision 2):**
    - _fits_occupancy and the post-parse HO/DP filter send Seasonal and
      Secondary Home to HO3 programs as well as DP programs. HO6 (condo) is
      unchanged; Tenant Occupied and Vacant stay DP-only.
    - The system prompt's two occupancy lines now name Tenant Occupied /
      Vacant, and say a Seasonal / Secondary Home is the owner's own home,
      with each HO3 guide's occupancy rules deciding. **This is a
      system-prompt change for every check.**
    - Seasonal and Secondary homes get one more retrieval term, for the
      guides' seasonal rows.
    - The round 28 routing xfail now passes: a seasonal Auros home reaches
      Auros and is not declined on SAG-001.
    - Replay vs the parent commit (13 profiles x 3 model answers), pilot
      OFF and ON: 33/39 identical. The 6 that differ are Seasonal and
      Secondary, where 26 HO3-side carriers now appear and none are removed.
      Tenant, Vacant and every Owner Occupied case are byte-identical.

  - **Step 7 (HO3 batch, 11 guides, behind ELIGIBILITY_RULES_HO3_BATCH):**
    - Data and map:
      - rules_data/carrier_rules_ho3_batch_v1.csv (964 rows) and
        build_ho3_batch_map.py -> ho3_batch_field_map.csv (615 deciding rows:
        102 decided, 61 gated-but-open, 14 AMBIGUOUS, 18 same-rule, 420 NONE);
      - RULE_FIELD_MAP.md has the section.
    - **The batch hook is a registry** (rules_evaluator.BATCHES plus
      eligibility_check.RULES_BATCH_SWITCHES). A further batch is one entry
      and one switch line.
      - A per-carrier occupancy scope picks a two-program guide's rows:
        Foremost's FOR rows apply to owner's homes only.
      - The panel shows "+ HO3 batch ON (11 more)".
    - **Switch:** exactly "1", only with the pilot on, default OFF.
    - **Tests:**
      - verification/test_ho3_batch_rules.py;
      - boundary cases for all 60 numeric HO3 lines, in
        test_map_boundaries.py.
      - The boundary cases found one wrong first draft: with an unknown PPC,
        "within 5 miles" came out OPEN, not FAIL. Hence station_miles_iso.
    - **Galvanized, batch ON:** code declines the seven carriers on their own
      galvanized row.
    - **Galvanized, batch OFF:** a guaranteed plumbing-material lookup
      (guarantee:plumbing) now brings each carrier's galvanized /
      polybutylene chunks into the prompt when the form names the material.
      The seven round 28 strict xfails pass, and none remain.
    - **Replay vs the parent, HO3 switch OFF, pilot OFF and ON:** 36/39
      identical. The OLD (galvanized) prompt differs, from the plumbing
      lookup. Under fixed answers the results are identical.

  - **Step 3 (Haiku 5.5 vs Luna, re-measured on f12b5b6 = steps 1-2):** pilot
    ON, Sage batch ON, 8 profiles x 3 runs per config, configs interleaved
    (the fast tiers ran alongside, slowing all three equally). Tier 2: pilot +
    Sage batch ON, once per config.

    | | Haiku medium | Haiku low | Luna |
    |---|---|---|---|
    | wall s per check | 38.1 | 28.5 | 23.1 |
    | cost $ per check | 0.0080 | 0.0071 | 0.0025 |
    | same verdict in all 3 runs | 173/192 (90%) | 176/192 (92%) | 172/192 (90%) |
    | CLEAN holds per run | 7, 6, 6 | 7, 6, 7 | 6, 8, 7 |
    | holds removed by the guard | 95 (4.0 / check) | 75 (3.1) | 22 (0.9) |
    | carriers omitted -> after the retry | 2 -> 0 | 1 -> 0 | 1 -> 0 |
    | OLD declines caught (galvanized carriers, 3 runs) | 18 | 18 | 18 |
    | Tier 2 failures | the same 7 | 6 (a subset: Allied solar passed) | 7 |

    - **Gate, Haiku low vs Luna:**
      - same verdict: 92% vs 90% (needs >= 88%): pass;
      - CLEAN holds per run: 6.7 vs 7.0: pass;
      - omitted after the retry: 0: pass;
      - Tier 2: no new failures: pass;
      - OLD declines: 18 vs 18: pass;
      - wall: 28.5 s vs 1.25 x 23.1 = 28.9 s: pass, by 0.4 s (1.23x). The
        thinnest margin.
    - Haiku medium fails on wall time (1.65x).
    - Cost is not a gate item: Haiku low costs 2.8x Luna per check.
    - **The one carrier where they disagree in every run is TWICO.**
      - CLEAN: Haiku is right. A 3-year architectural roof is in the RCV band
        under every row of TWICO's roof table. Luna held on the table's missing
        material labels.
      - ALT: Luna is right. A 14-year roof changes only ACV vs RCV, never
        eligibility, and central A/C / heat is a confirm. Haiku held on the
        roof sub-type.
    - **Haiku passes the gate at low: set ELIGIBILITY_MODEL=claude-haiku-5-5
      and ELIGIBILITY_EFFORT=low.** Liam's call: wall time is within 2% of the
      limit, and cost is 2.8x.
  - **Step 4, real runs (Luna, Bexar, pilot + Sage + HO3 batch ON, 2 runs):**
    all 26 HO3-side carriers now answer for a Seasonal / Secondary home.
    - Seasonal, r1: 8 ELIGIBLE, 3 REFER, 13 INSUFFICIENT, 1 closed (NatGen
      Premier), 2 wrong guide. Secondary is the same, except Centauri HO3
      INELIGIBLE (model: "owner-occupied only").
    - The REFERs are the guides' own rows: ARA-030, ARB-025, LIB-066.
    - The ELIGIBLEs:
      - rules table, none fails: Foremost, HOAIC, Orion, Markel, Vave, Topa,
        Travelers;
      - model: Centauri HO3.
    - Every INSUFFICIENT names the guide's secondary-home condition on a fact
      the form does not ask: same carrier writes the primary (Chubb, Mercury,
      TWICO), property checks while away (Auros, SURE, SafePort, Trium,
      Wilshire), distance from the primary (Swyfft Admitted / Surplus),
      country of the primary (Lloyd's), rental exposure (Progressive,
      Allied).
    - These are rules-table holds (or model holds citing them), so the hold
      guard does not touch them. **Seasonal / Secondary checks are now
      dominated by these.** A form question ("does the same carrier insure
      the primary home?") would settle most of them. That is Liam's call.

  - **Step 7, measured (Luna, pilot + Sage ON, HO3 batch OFF -> ON, 9
    profiles x 2):** wall 30.1 -> 23.6 s; cost $0.0031 -> $0.0019.
    - **ON is right (per the guide):**
      - CLEAN TWICO and Travelers: ELIGIBLE (OFF held on garbled roof tables);
      - LIVE ARI HOB: ELIGIBLE (OFF held on "9 months occupancy");
      - LIVE / STRESS Foremost: FOR-078 county (+ FOR-006 Coverage A);
      - OLD Foremost: FOR-036 galvanized;
      - 7 mi: ARA-014, ARB-012, ORI-098 (more than 5 miles from a station);
      - Seasonal / Secondary Liberty HO3: REFER on LIB-066;
      - STRESS: ARI HOA+ REFER (ARA-078 over $700k), ARI HOB ARB-040 (over 20
        years), HOAIC HOA-008 (PPC 8-10, over 3 years);
      - TRUST Swyfft Benchmark Surplus: REFER on SBS-054 (OFF declined; the
        round 25 Tier 2 failure);
      - TRUST ARI: ELIGIBLE.
    - **ON holds by design on a fact the form does not ask** (gated-but-open
      rows): Liberty HO3 wiring (LIB-033, OLD and STRESS); TWICO primary with
      TWICO (Seasonal) and trustee name (Trust); Travelers trust activity;
      Lloyd's country of primary; TWICO plumbing update (STRESS).
    - **Rows still wrong:** ARA-049 / ARB-046 ("exposed water lines must be
      copper or PVC"). For a PEX home the AMBIGUOUS line lets the model hold
      on "are the lines exposed", a fact the form does not ask (CLEAN, ARI
      HOA+, both runs). It should be NONE (confirm). Not changed this round.

  - **Step 8 (remaining batch, 15 guides, behind ELIGIBILITY_RULES_DP_BATCH):**
    - rules_data/carrier_rules_remaining_v1.csv (1,655 rows) and
      build_remaining_batch_map.py -> remaining_batch_field_map.csv: 990
      deciding rows (109 decided, 56 gated-but-open, 13 AMBIGUOUS, 40
      same-rule, 772 NONE).
    - The readings and the wrong-looking rows (SDP-012/013, FOD-005, PH6-078,
      CDP-094, STD-045) are in RULE_FIELD_MAP.md.
    - Registry: BATCHES["dp"], 14 carriers. NatGen Premier DP3 is closed: it
      is in CLOSED_PROGRAMS (a live change, for every check that reaches it).
      Panel: "+ DP batch ON (14 more)".
    - **Foremost DP vs HO:** one guide and one carrier name, so the occupancy
      decides.
      - FOD rows apply to Tenant / Vacant checks; FOR rows to owner's homes.
      - The FOR rows the guide marks "All use types (shared ...)" also apply to
        the DP check (BATCHES["dp"]["shares"]), except FOR-012 / 074 / 076,
        which FOD decides.
    - **PH6 (condo):** HO6 programs are routed for Owner Occupied only, and
      dropped when the dwelling type is House. The guide also writes tenant
      and seasonal units, which the app never routes to it (a routing gap,
      not changed).
    - **Tests:**
      - test_remaining_batch_boundaries.py: 109 cases;
      - test_remaining_batch_rules.py: tenant passes every DP occupancy line;
        owner's homes fail only the landlord-only guides; liability-only rows
        are NONE; registry, switch, panel; the pipeline.
    - **Measured (Luna, pilot + Sage + HO3 ON, DP OFF -> ON, 6 profiles x 2):**
      wall 25.9 -> 19.1 s; cost $0.0020 -> $0.0013.
      - The first ON runs found four map errors, fixed in the follow-up commit
        (0b6a321) and re-run:
        - CDP-069 written "X || FACT" ("||" is two readings, not "or"), which
          held every Centauri DP3 check;
        - Seasonal AMBIGUOUS on LDP-001 / NCD-047 flipped I / ? between runs;
        - STD-073 galvanized was AMBIGUOUS;
        - Foremost's shared rules were missing, so a galvanized rental came
          back ELIGIBLE.
      - **ON is right (after the follow-up):**
        - VACANT: CDP-066 / PDP-030 / VDP-026 decline; Markel / SURE /
          SafePort REFER on their own vacancy rows.
        - OLD+Tenant: Liberty DP3 LDP-049, Foremost FOR-036, Steadily STD-073
          decline galvanized.
        - SEASONAL: Liberty DP3 / NatGen C360 decline (landlord-only); HOAIC
          DP ELIGIBLE.
        - CONDO: PH6 ELIGIBLE (OFF held on months occupied).
      - **ON holds by design:**
        - SURE / SafePort / Occidental FPC rows with a blank distance (decision
          2026-10-07; Tenant+LLC, OLD+Tenant);
        - FOD-018 LLC business on premises;
        - NCD-051 vacant occupied within 60 days;
        - STD-092 solar share of the roof;
        - Centauri HO3 on Seasonal (CHO-013 AMBIGUOUS).
      - **Doubtful:** a Vacant Foremost DP check declines on FOD-005
        ("TDP-3 has no vacant use; write TDP-1"). This was inferred from the
        guide's silence. Liam to confirm.

  - **Step 6 (record only):** data_defects.WRONG_FILE_EVIDENCE has the size,
    sha256 and page 1 of Liberty_Mutual_HO6 (= the HO3 guide),
    NatGen_Custom360_HO3 (= the DP3 landlord guide) and Sage_-_Occidental_HO3
    (a DP3 guide). Files are kept. Today a profile that reaches one gets a
    GUIDE_UNAVAILABLE card: "The guide on file is the wrong document -- check
    with the carrier directly."

  - **Step 9 (Tier 2's seven):**
    - **Three code fixes (verdicts were right; notes were lost):**
      - rules_evaluator.coverage_notes adds Progressive HO3's PRO-067 solar
        wind/hail exclusion and Allied's ALL-045 replacement-cost limit;
      - the [Solar check] note now also covers rules-table carriers.
    - **One dated baseline update:** Auros / Wilshire PPC 1, held on the FPC
      1-3 B/C conditions with no distance (decision 2026-10-07).
    - **No change:** Swyfft Benchmark Surplus trust/LLC and Progressive HO6
      trust are decided by SBS-054 / PH6-027 once their batches are on.
    - **Tier 2, once on Luna after step 9 (3b5847d; pilot + Sage + HO3 + DP
      batch ON): 22 passed, 0 failed, 7 xfailed, 7 xpassed.** With today's
      Railway values (batches OFF), Swyfft Benchmark Surplus trust/LLC and
      Progressive HO6 trust still fail.

  - **Replays, DP batch OFF vs the parent (74e2a46 -> 0b6a321, pilot + Sage
    ON, 13 profiles x 3 fixed answers):** 27/39 byte-identical. The 12 that
    differ are the Tenant / Vacant / Seasonal / Secondary cases, and only by
    NatGen Premier DP3: it is now the closed card and has left the prompt.

  - **Fast tiers (fast_at2.sh, each commit's own seed):**
    - 07f160b (step 5), 2bfb48d (step 4), 27b2363 (step 7): 1 failure each,
      all the same test (Centauri HO3 is now in the enum). The test is updated
      in 74e2a46.
    - 0b6a321 (step 8 + follow-up): 1 failure (the NatGen Premier DP3 closure
      test). Updated in 6b8ae91.
    - 6b8ae91 (round 29 head): 1,857 passed, 0 failed, 1 skipped, 9 xfailed.

- **2026-10-08 — Round 30 (Liam's decisions dated 2026-10-08).** Built on
  3e0bfd3. Live configuration after the round 29 push, as Liam sets it:
  pilot ON, Sage + HO3 + DP batches ON, model Luna (FORCE_RESEED=1 once).
  Liam plans to switch to Haiku 5.5 low a few days later (step 6 tests it).
  - **1. Seasonal and Secondary Home profiles get two new form questions**
    (step 1), so the largest groups of round 29 holds can be decided.
  - **2. Project rule, applied to the rules table too:** a fact the form never
    asks is a "Confirm:" note, never a hold (step 2).
  - **3. Foremost vacant dwelling (FOD-005) is a note, not a decline:**
    Foremost writes vacant dwellings on TDP-1 (step 3).
  - **4. Condo units that are tenant-occupied or seasonal go to Progressive
    HO6 as well;** its rows decide (step 4).
  - **Step 1 (primary-home questions):**
    - Shown only for Seasonal / Secondary Home:
      - "Primary home insured with": one choice per insurer, in the carrier
        list's order (Sage's insurers separate), plus "Other carrier" and
        "Unknown";
      - "Distance to the primary home (miles)".
    - Absent from property_details otherwise. Stated in the prompt only when
      answered. Replay vs 3e0bfd3 (13 profiles x 3 answers, switches off and
      on): 78/78 byte-identical, blank Seasonal / Secondary included.
    - **Rows they settle.** None of these guides extends the rule to an
      affiliate or group, so only the carrier's own choice passes.
      - CHU-004 / 045: "Applicable to residences where Chubb writes the
        primary residence". CHU-046 also still needs the $25,000 non-CAT
        premium fact.
      - MER-003: "...and Mercury does not insure the primary dwelling".
      - ARA-029: "...unless ARI insures the primary home".
      - TWI-005: "Secondary must have an associated primary written in Twico".
      - TRV-039: PC 9/10, "and we do not write the primary dwelling".
      - SWY-007 / SBS-027: "less than 50 miles from the primary residence"
        (50 passes).
    - **Not settled:**
      - SLL-043 (country of the primary home);
      - ARB-025 / ARB-039 (both REFER, so a non-ARI primary still refers; the
        data has no decline row);
      - CHU-005 (tenant risks; the question is not shown);
      - NPD-010 (closed).
    - Blank / Unknown leaves the row open on a form field, which still holds
      (step 2's class a).
    - Tests: verification/test_primary_home_fields.py (32), and boundary
      cases for the 50-mile lines.

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

**Round 22, not done (2026-10-02):**
- **The "not in the excerpts" hold.** 57 of 1,978 recorded Insufficient
  records (2.9%) hold only on such items; Luna 0-2 per run. It waits for
  the structured-rules test.
- **Chubb Harris Territory 1A has no ZIP list** in the guide, and Harris is
  split between regions by territory. Neither the county nor the ZIP
  settles it: a known gap.
- **Roofer letters as inspections:** DECIDED 2026-10-02 (round 24): they are inspections, not checked.
- **The Sage wrong location decline** is guarded but occasional: 1 of 11
  real runs so far, 0 of 8 in round 22. A rate needs more runs.

**Round 21, not done (2026-10-02):**
- **A hold or warning for ZIPs whose counties disagree** waits for Liam and
  the round 21 Step 7 number: 217 ZIPs on any county rule, 62 on the Sage
  rule the code decides.
- **Luna's wrong Sage location decline for Harris** (round 21 Step 8). The
  options are above.
- **Coastal tier from ZIP; roof sub-type and fire-station / hydrant
  fields.**
- **Roofer letters:** DECIDED 2026-10-02 (round 24): inspections, not checked.
- **HUD-USPS crosswalk:** the table is the Census ZCTA fallback (land
  share, no PO-box ZIPs). Liam creates the HUD token, then run
  `python build_zip_county.py hud`.
- **Tier 2 baseline:** none ran in rounds 19, 20 or 21. **Ran 2026-10-04
  (round 25 step 1) on main bb0e983 with Luna**: 19 passed, 10 failed,
  8 xfailed, 6 xpassed; 82 calls, $0.17, 41.5 min. Controls on origin
  463e290 (Luna, same database) separate the causes. User prompts for
  ALT, Trust and LLC are byte-identical on both. The only prompt
  difference is the round 20/24 inspection sentence.
  - 7 chat golden cases: a NameError. The merge eefc9cd dropped
    `_assert_rate`, so this was already broken on origin. Restored. Re-run
    at 3 runs each: 6 of 7 at 100%.
  - The 7th, Sage Auros pool, failed on the correct answer "not a decline of
    the home" because the regex ignored "not". It now ignores negated
    mentions, with a fast test for both phrasings, and passes 3/3.
  - Sage Occidental pool fence: an expected change. Liam's 2026-09-28/29
    decision (c49aa2b) made it a fixed GUIDE_UNAVAILABLE row. The test now
    asserts that row, and passes 3/3.
  - **OPEN, Luna rate, not a regression:** Progressive HO3 names solar on
    ALT in 4/12 runs on main and 2/6 on origin. Sonnet measured 16/16 in
    round 12. Retrieval still delivers the clause: a page 12 chunk that
    starts mid-list, with no heading. Progressive's ALT verdict also varies
    (7 Eligible, 4 Insufficient, 1 Ineligible in 12 runs).
  - **OPEN, Luna, already on origin:** in the Trust/LLC verdict test,
    Swyfft Benchmark (Admitted) and (Surplus) DECLINE a trust. Their guide
    lists it under "Check with us first" (stored as "␀rst", DD-5).
    - Extra Trust runs: origin declined 6/6, main 5/6.
    - Lloyds and Topa mostly REFER on both commits.
    - Progressive HO6 holds on "not a condo unit" and is left out in 2/6 on
      both commits.
    - Sage Auros is now INSUFFICIENT on a blank county, from round 19's
      county hold (expected); origin gave ELIGIBLE.
    - The test stays red. Nothing was loosened.
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
- **Roofer letters / roof certifications:** DECIDED 2026-10-02 (round 24): inspections, not checked.

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