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

## Open work, in priority order (2026-09-29)

0. **Smoke test finding, not yet root-caused: the NOT_EVALUATED safety net
   may not catch every way Luna drops a carrier.** Two back-to-back real
   Luna runs of OWNERSHIP_BASE/LLC (no code change between them):
   - Run 1: 25 model records for 23 distinct carriers -- Sage SURE HO-3 and
     Sage SafePort HO-3 absent, and **no NOT_EVALUATED row appeared for
     either**, which `_add_fixed_rows`'s coverage check should have caught
     (any `relevant_carrier` not in the resolved set of `kept` carriers gets
     one). Not yet explained: whether some other pair of carriers was
     silently DUPLICATED in that run's raw JSON (consuming 2 slots invisibly
     because the resolver's `covered` set collapses duplicates), which would
     explain the record count without a code bug, or whether the coverage
     check itself has a gap this smoke test wasn't built to catch.
   - Run 2 (same profile, same code): all 26 usable carriers present, but
     Sage Vave HO3 and Sage Wilshire HO3 EACH appear twice (30 total
     records for 26 distinct carriers) -- no omission this time.
   - Both runs' JSON parsed without error; this is a completeness issue, not
     a parseability one. Before this prototype goes past internal testing,
     capture a failing run's raw JSON (not just the post-parse `results`)
     and confirm whether `_add_fixed_rows` is actually blind to duplicate-
     masking-an-omission, or whether run 1's specific raw output had some
     other shape. Zero-API once a raw sample is in hand -- reuse the replay
     harness in verification/test_eligibility_matrix.py.

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