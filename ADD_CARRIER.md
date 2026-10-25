# Adding a carrier (runbook)

Round 39, 2026-10-15; updated in round 43 (2026-10-24) for the Cloudflare version, which has no in-app upload: a
guide goes in through the repo, and the last steps rebuild the manifest, re-export the parity golden file, run parity,
and push. Follow it step by step to add one carrier guide (written for a person or an agent with no
memory of earlier rounds). Each step says what to run and what "done" looks like. Paths are relative to the repo root;
`<key>` is a short lower-case name for the carrier (e.g. `hartford`), `<PRE>` its 3-letter row prefix (e.g. `HAR`).

The first time through was The Hartford HO3 (round 39): its files are the worked example at every step.

## 0. Before you start

- Work on a branch: `git checkout -b add-<key>` (never on main; Liam merges and pushes, and a push deploys).
- Never open, print or copy `.env` or any API key; never set `ANTHROPIC_API_KEY` (see CLAUDE.md, "API keys").
- Know what CFIG writes with this carrier: the forms (HO3 / DP3 / HO6), the occupancies, and any CFIG experience
  that is not in the guide (that goes in `rules_data/cfig_knowledge.csv`, step 4e). Ask Liam if you do not know.
- Pick `<PRE>`: three capital letters no table uses yet
  (`python -c "import rules_evaluator as r; print(sorted({k[:3] for k in r._rules()}))"`).

## 1. Add the guide to the store (in the repo; there is no upload in the web version)

1. Name the PDF `Name_FORM_-_MM.DD.YYYY.pdf` (the form token -- HO3, DP3, HO6 -- routes it by occupancy; the date is
   the guide's date, checked on the PDF) and put it in `carrier_eligibility_pdfs/`.
2. Index it into a fresh copy of the seed, which the tests and the manifest read (step 7):
   ```
   python reindex_program.py ./carrier_docs_db <file>.pdf
   ```
3. Its display name goes in `display_names.DISPLAY` (step 4c). A homeowners form that also writes a rental needs
   `RENTAL_HO3_OCCUPANCIES` (step 4d) -- the occupancies the Manage Carriers upload used to store.

Until it has a rules table the web version shows it under **Could Not Be Checked**: "No rules table yet for this
guide, so it is not checked here -- read the guide before quoting." (no model call). Railway, while it still runs,
reads it from the guide with the model as before (a guide-only card).

## 2. Prepare the guide's text

```
python rules_data/add_carrier/prepare_guide.py <guide.pdf> pilot_structured_rules/<key>/
```
This writes `reading_order.txt` (the text exactly as the app stores it, with hidden text dropped and section
headings kept), `layout.txt` (the columns), `page_N.png` (each page) and `guide.txt` (pages, date, hidden characters
dropped). If "hidden characters dropped" is large, open page 1's PNG and check nothing visible went missing.
(The Hartford: 1,166 dropped, all of it an auto guide hidden on page 1.)

## 3. Extract the rules (two agents), then check the quotes

**3a. Extract.** Start a fresh agent. Its task is `pilot_structured_rules/specs/EXTRACT_TASK.md`, with these changes:
- Point it at `specs/SPEC_v1.md`, then `specs/EXTRACTION_SPEC_v2.md` (v2 wins where they differ).
- Give it `pilot_structured_rules/<key>/reading_order.txt` and `layout.txt`, and the page PNGs.
- Output: `pilot_structured_rules/<key>/rows.json`.
- Replace "Context for THIS batch" with this carrier's context:
  - the forms and occupancies CFIG writes;
  - any program inside the guide that has its own table (the Hartford's RPP+);
  - "rules under a heading apply only within that heading" (the Hartford's High Value Homes rows apply at $1.5M+
    only).

The agent must not see another carrier's table for this guide.

**3b. Review.** Start a second, fresh agent with `specs/REVIEW_TASK.md`. Give it:
- the rows, as `rows_review.csv`;
- the same text files;
- the page PNGs, which are the source of truth: "read every page image before judging".

Its findings go to `findings.json`. Apply every HIGH and MED finding the page images support; note LOW ones in the
row's review note. If the reviewer and the extractor disagree on a heading or action column, read the PNG yourself.
The Hartford's p.3 action column sits one line below its bullets.

**3c. Quote check.**
```
python rules_data/add_carrier/quote_check.py pilot_structured_rules/<key>/rows.json pilot_structured_rules/<key>/ \
    <PRE> "<Carrier name> <FORM>" <Program_file_name>.pdf rules_data/carrier_rules_<key>_v1.csv
```
Every FAIL it prints needs fixing (a wrong quote) or a reason in "Quote check note". Done when it prints
`quote FAILs without a note: 0`.

## 4. Wire it into the app

Copy the worked example and change it; never edit another carrier's lines.

- **a. Map lines.** Copy `rules_data/build_hartford_map.py` to `build_<key>_map.py` and run it to write
  `<key>_field_map.csv`. Every row whose Tool handling is EVALUATE gets a line. Liam, 2026-10-14: none is left to
  the model or to the Also-confirm list.
  - A form field decides it when the form asks the fact (grammar: `rules_data/RULE_FIELD_MAP.md`).
  - Otherwise it is a confirm: `FACT(<the fact, in words an agent can ask>)`.
  - A rule for one occupancy only gets a gate (`occupancy_type == Tenant Occupied`). A general row that a
    program-specific row replaces is gated off it.
  - Two rows on the same fact: one decides, the other is `always` with the note "decided by <row>".
  - Never let a blank PPC, County or Coverage A hold a carrier on a fact it only gates (the Hartford's stove row).
- **b. Register.** In `engine/rules_evaluator.py`, add `<KEY>_RULES_CSV` / `<KEY>_MAP_CSV`, `<KEY>_CARRIERS = {"<table
  carrier name>": "<program name>"}` and a `BATCHES` entry. In `engine/pipeline.py` (`RULES_BATCH_SWITCHES`), ride an
  existing flag (`RULES_HO3_BATCH` for a homeowners program, `RULES_DP_BATCH` for dwelling fire), so no new Railway
  variable is needed.
- **c. Names and lists.**
  - `engine/display_names.py` DISPLAY (and `OCCUPANCY_NAMES` if one occupancy has its own program name);
  - `engine/intake_fields.py` PRIMARY_HOME_CARRIERS (one choice per insurer, in program-name order);
  - `rules_data/placement/placement_markets.csv` and `pilot_structured_rules/placement/placement_data.py` (MARKETS
    and OTHERS);
  - `expected_programs.txt`.
- **d. Routing.** A homeowners form on a non-owner occupancy (the Hartford's rentals) needs an entry in
  `RENTAL_HO3_OCCUPANCIES` (engine/pipeline.py).
- **e. CFIG knowledge.** A rule CFIG knows that the guide does not state goes in `rules_data/cfig_knowledge.csv` as
  one row (rule + map line). Give it an ID `CFG-NNN`, the carrier's table name, "CFIG experience: ..." wording, and
  who said it and when.
- **f. Notes.** Coverage-only rows the card should state (deductibles, wind exclusions) go in
  `PROGRAM_NOTES` (engine/rules_evaluator.py). Roof-settlement and solar rows show by themselves.
- **g. Hold guard and topics.** Nothing to add for an `XXX-NNN` prefix. `verification/test_topic_audit.py` fails if a
  deciding row has no card topic: add a topic word in `engine/confirm_topics.py`, not an exception.

## 5. Tests, then the fast tier, then one live run

- Copy `verification/test_hartford_boundaries.py` to `test_<key>_boundaries.py`. Give it one passing and one failing
  case for every deciding row (its completeness test enforces this). A row that cannot reach both sides goes in
  `ONE_SIDED`, with the reason.
- Copy the data tests from `verification/test_hartford.py`:
  - source header;
  - one map line per deciding row, and the map file is the builder's;
  - every expression parses;
  - coverage counts;
  - every quote is in the stored text;
  - no hidden text in the stored chunks;
  - routing and names.

  Then write the carrier's own verdict cases: two phrasings for each general rule, as CLAUDE.md says.
- Run the new files, then the whole fast tier, through the guard (never start a second run on the same shards; it
  refuses):
  ```
  sh /c/Users/Intern/carrier/wt/fast/ft.sh <commit> <label>
  ```
  Without the shard setup, run `python -m pytest verification/ -m "not baseline"`. A failure in another carrier's
  test is either a mistake to fix, or a deliberate change that gets a dated expectation update naming the decision.
- Optional, for a large guide: adapt `verification/hartford_deep.py` (its FACTORS) and run 5,000 profiles. Every
  invariant failure is a real bug or a named `xfail`.
- One live run (Haiku 5.5 low, all batches on). Pass the key file path into the child process only:
  ```
  $env:ELIGIBILITY_DOTENV = [Environment]::GetEnvironmentVariable('ELIGIBILITY_DOTENV','User')
  python verification/check_api.py      # API OK: claude-haiku-5-5, ...
  ```
  Then check one ordinary profile and paste the carrier's card into the commit message.

## 6. Review sheet (a person signs it)

```
python rules_data/add_carrier/review_sheet.py <program name> pilot_structured_rules/<key>/REVIEW.md
```
One page: every deciding row (page, effect, how the tool decides it) and the tool's verdict on 25 standard homes,
each with a blank column. Liam or the agency's underwriting contact (Jonathan for the Hartford) marks each line
right, or writes what the carrier really does. Fix what they mark. Their decisions go in `handoff.md`, dated.

## 7. Seed, manifest, golden file, parity, push

1. **Seed.** Copy the store from step 1 to `carrier_docs_db_seed/`. Compare per-carrier hashes before and after: only
   the new carrier may change. `git add -f carrier_docs_db_seed`. Write the new Fingerprint (carriers, chunks,
   documents and metadata hashes) into the commit message.
2. **Manifest** (the store's facts the browser reads; `verification/test_engine_split.py` fails while it is stale):
   ```
   python build_engine_manifest.py
   ```
3. **Re-export the parity golden file** (a new carrier changes the cards on purpose; `test_parity_golden.py` fails
   until the golden is re-exported). About 30 minutes as 8 processes:
   ```
   for i in 0 1 2 3 4 5 6 7; do OMP_NUM_THREADS=2 python verification/parity/export_golden.py export part$i.json.gz --shard $i/8 & done; wait
   python verification/parity/export_golden.py merge new_golden.json.xz part?.json.gz
   python verification/parity/export_golden.py compare verification/parity/golden.json.xz new_golden.json.xz
   ```
   Every difference must be the new carrier (or a change you meant). Then copy `new_golden.json.xz` over
   `verification/parity/golden.json.xz` and commit it with the change, naming the decision.
4. **Parity: the browser's engine against the new golden** (only the bundle, no store; about 2 minutes):
   ```
   for i in 0 1 2 3 4 5 6 7; do python verification/parity/export_golden.py export-engine eng$i.json.gz --shard $i/8 & done; wait
   python verification/parity/export_golden.py merge engine.json.xz eng?.json.gz
   python verification/parity/export_golden.py compare verification/parity/golden.json.xz engine.json.xz   # 0 differences
   ```
5. **Parity: the page in a browser** (Microsoft Edge, headless):
   ```
   npm ci && npm run build
   python verification/parity/export_golden.py inputs verification/parity/golden.json.xz inputs.json
   node web/tests/parity.mjs --profiles inputs.json --out web/tests/out/candidate.json
   python web/tests/candidate_to_golden.py web/tests/out/candidate.json        # 0 difference(s)
   ```
6. **Placement**: a new market goes in `rules_data/placement/placement_markets.csv`. Nothing else to load: the Worker
   rebuilds its placement tables from the CSVs on every deploy (round 44b; DEPLOY_CLOUDFLARE.md, section 3 step 4).
   To check before pushing: `npm run build:placement` prints the row counts, or the CSV line at fault.
7. **Push** (Liam): the push deploys (Workers Builds). The web version needs no `FORCE_RESEED` -- it has no store at
   run time; Railway, while it still runs, does.
- Never open a tracked seed with chromadb directly: opening a store writes to its sqlite file. Tests read
  `carrier_docs_db`.
- One commit per step. Each message says whether Tier 2 ran, and ends with the Co-Authored-By line when an agent
  wrote it.
- Tell Liam: the branch name; whether Railway (while it still runs) needs `FORCE_RESEED`; and any new variable
  (there should be none).

## 8. A new version of a guide

1. Add it under its new dated name (step 1), so both versions are in the store, and run step 2 into
   `pilot_structured_rules/<key>_<date>/`.
2. `quote_check.py` the existing `rows.json` against the new text. Every row whose quote now FAILs is a changed
   rule: re-extract that section (3a) and review it (3b) only. Diff the two `reading_order.txt` files for new
   sections, and extract those too.
3. Save the table as `carrier_rules_<key>_v2.csv` (keep the row IDs of unchanged rows; new rows take the next
   numbers). Rebuild the map, update the tests (dated, naming the guide date), run the fast tier and the review
   sheet.
4. Point `<KEY>_CARRIERS` at the new program name, then remove the old program from the store
   (`python -c "import upload_carrier as u; u.remove_carrier_from_database('<old program>')"` on the local copy) and
   its PDF. Update the seed, the manifest, the golden file and parity (step 7) and `expected_programs.txt`.
