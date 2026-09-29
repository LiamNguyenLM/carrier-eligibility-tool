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

## Updating carrier guides in production

Uploads happen in the app on Liam's computer, and **they never reach
production by themselves**. Railway's database is a persistent volume, seeded
from the committed `carrier_docs_db_seed/`. `seed_db.sh` only copies the seed
into an EMPTY volume, or when `FORCE_RESEED=1` is set.

The DD-1, DD-2 and DD-4 re-uploads and the Centauri HO3 fix
(`verification/DATA_DEFECTS.md`) all follow this path:

1. **Upload locally.** In the local app's Manage Carriers tab, remove the bad
   record and upload the correct PDF under the same carrier name. If the
   carrier is NEW, add its name to `expected_programs.txt`.
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